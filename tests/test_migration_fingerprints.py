"""Tests for destination policies, fingerprints, inspection, and plan validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ledgercore.errors import StorageMigrationError
from ledgercore.migration import (
    DestinationPrecondition,
    StorageFingerprint,
    StorageMigrationItem,
    StorageMigrationPlan,
    _prepare_item_paths,
    fingerprint_storage_directory,
    fingerprint_storage_file,
    inspect_storage_migration_destination,
    validate_storage_migration_plan,
)
from ledgercore.storage_binding import (
    StorageBinding,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _binding(
    project_uuid: str = "test-uuid",
    tool: str = "test-tool",
    mount: str = "data",
    storage: str = "project",
) -> StorageBinding:
    return StorageBinding(
        schema_version=1,
        layout_version=3,
        project_uuid=project_uuid,
        project_name=None,
        tool=tool,
        mount=mount,
        storage=storage,
    )


def _file_binding(
    project_uuid: str = "test-uuid",
    tool: str = "test-tool",
) -> StorageBinding:
    return _binding(
        project_uuid=project_uuid, tool=tool, mount="config", storage="project"
    )


def _create_tree(root: Path, structure: dict[str, object]) -> None:
    """Create a directory tree from a nested dict.
    Files are str (content), dirs are dict.
    """
    for name, value in structure.items():
        path = root / name
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            _create_tree(path, value)
        elif isinstance(value, str):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        else:
            raise ValueError(f"unexpected type {type(value)} for {name}")


def _write_marker(directory: Path, binding: StorageBinding) -> None:
    marker = directory / ".ledger-project.toml"
    marker.write_text(
        f"schema_version = 1\n"
        f"layout_version = 3\n"
        f'project_uuid = "{binding.project_uuid}"\n'
        f'tool = "{binding.tool}"\n'
        f'mount = "{binding.mount}"\n'
        f'storage = "{binding.storage}"\n',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Directory fingerprint tests
# ---------------------------------------------------------------------------


class TestDirectoryFingerprint:
    def test_deterministic(self, tmp_path: Path) -> None:
        """Identical trees in different creation orders produce the same digest."""
        tree1 = tmp_path / "tree1"
        tree2 = tmp_path / "tree2"
        tree1.mkdir()
        tree2.mkdir()
        # Create in different order
        _create_tree(tree1, {"b.txt": "hello", "a.txt": "world", "sub": {"c.txt": "!"}})
        _create_tree(tree2, {"a.txt": "world", "sub": {"c.txt": "!"}, "b.txt": "hello"})
        fp1 = fingerprint_storage_directory(tree1)
        fp2 = fingerprint_storage_directory(tree2)
        assert fp1.digest == fp2.digest
        assert fp1.file_count == 3
        assert fp1.total_bytes == fp2.total_bytes

    def test_changes_on_file_content(self, tmp_path: Path) -> None:
        """Modifying file bytes changes the fingerprint."""
        tree = tmp_path / "tree"
        _create_tree(tree, {"file.txt": "hello"})
        fp1 = fingerprint_storage_directory(tree)
        (tree / "file.txt").write_text("goodbye", encoding="utf-8")
        fp2 = fingerprint_storage_directory(tree)
        assert fp1.digest != fp2.digest

    def test_changes_on_relative_path(self, tmp_path: Path) -> None:
        """Renaming a file (same bytes, different path) changes fingerprint."""
        tree = tmp_path / "tree"
        _create_tree(tree, {"original.txt": "hello"})
        fp1 = fingerprint_storage_directory(tree)
        (tree / "original.txt").rename(tree / "renamed.txt")
        fp2 = fingerprint_storage_directory(tree)
        assert fp1.digest != fp2.digest

    def test_rejects_symlink(self, tmp_path: Path) -> None:
        """Symlinks are rejected."""
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "real.txt").write_text("data", encoding="utf-8")
        (tree / "link.txt").symlink_to(tree / "real.txt")
        with pytest.raises(StorageMigrationError, match="symlink"):
            fingerprint_storage_directory(tree)

    def test_rejects_special_file(self, tmp_path: Path) -> None:
        """Non-regular files are rejected (fifo/socket)."""
        tree = tmp_path / "tree"
        tree.mkdir()
        fifo = tree / "special"
        mkfifo = getattr(os, "mkfifo", None)
        if mkfifo is None:
            pytest.skip("mkfifo not supported")
        try:
            mkfifo(str(fifo))
        except OSError:
            pytest.skip("mkfifo not supported")
        with pytest.raises(StorageMigrationError, match="special file"):
            fingerprint_storage_directory(tree)

    def test_ignores_root_binding_marker(self, tmp_path: Path) -> None:
        """Changing .ledger-project.toml does not affect content fingerprint."""
        tree = tmp_path / "tree"
        _create_tree(tree, {"data.txt": "hello"})
        _write_marker(tree, _binding())
        fp1 = fingerprint_storage_directory(tree)
        # Change marker content
        (tree / ".ledger-project.toml").write_text("different marker", encoding="utf-8")
        fp2 = fingerprint_storage_directory(tree)
        assert fp1.digest == fp2.digest

    def test_includes_empty_directories(self, tmp_path: Path) -> None:
        """Empty subdirectories are included in the fingerprint."""
        tree1 = tmp_path / "tree1"
        tree2 = tmp_path / "tree2"
        _create_tree(tree1, {"file.txt": "data"})
        _create_tree(tree2, {"file.txt": "data", "empty_dir": {}})
        fp1 = fingerprint_storage_directory(tree1)
        fp2 = fingerprint_storage_directory(tree2)
        assert fp1.digest != fp2.digest

    def test_nonexistent_raises(self, tmp_path: Path) -> None:
        """Missing directory raises error."""
        with pytest.raises(StorageMigrationError, match="does not exist"):
            fingerprint_storage_directory(tmp_path / "missing")

    def test_file_target_raises(self, tmp_path: Path) -> None:
        """File instead of directory raises error."""
        target = tmp_path / "file"
        target.write_text("data", encoding="utf-8")
        with pytest.raises(StorageMigrationError, match="not a regular directory"):
            fingerprint_storage_directory(target)

    def test_encoded_property(self, tmp_path: Path) -> None:
        """StorageFingerprint.encoded returns algorithm:digest."""
        tree = tmp_path / "tree"
        _create_tree(tree, {"file.txt": "hello"})
        fp = fingerprint_storage_directory(tree)
        assert fp.encoded == f"{fp.algorithm}:{fp.digest}"


# ---------------------------------------------------------------------------
# File fingerprint tests
# ---------------------------------------------------------------------------


class TestFileFingerprint:
    def test_basic(self, tmp_path: Path) -> None:
        """File fingerprint has correct algorithm, file_count, total_bytes."""
        target = tmp_path / "config.toml"
        content = "hello world"
        target.write_text(content, encoding="utf-8")
        fp = fingerprint_storage_file(target)
        assert fp.algorithm == "sha256-file-v1"
        assert fp.file_count == 1
        assert fp.total_bytes == len(content.encode("utf-8"))
        assert fp.digest

    def test_deterministic(self, tmp_path: Path) -> None:
        """Same file produces same fingerprint."""
        target = tmp_path / "file.txt"
        target.write_text("stable", encoding="utf-8")
        fp1 = fingerprint_storage_file(target)
        fp2 = fingerprint_storage_file(target)
        assert fp1.digest == fp2.digest

    def test_changes_on_content(self, tmp_path: Path) -> None:
        """Different content produces different fingerprint."""
        target = tmp_path / "file.txt"
        target.write_text("v1", encoding="utf-8")
        fp1 = fingerprint_storage_file(target)
        target.write_text("v2", encoding="utf-8")
        fp2 = fingerprint_storage_file(target)
        assert fp1.digest != fp2.digest

    def test_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(StorageMigrationError, match="does not exist"):
            fingerprint_storage_file(tmp_path / "missing")

    def test_symlink_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "real.txt"
        target.write_text("data", encoding="utf-8")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        with pytest.raises(StorageMigrationError, match="not a regular file"):
            fingerprint_storage_file(link)


# ---------------------------------------------------------------------------
# Destination inspection tests
# ---------------------------------------------------------------------------


class TestDestinationInspection:
    def test_absent(self, tmp_path: Path) -> None:
        """Missing directory returns 'absent'."""
        result = inspect_storage_migration_destination(
            path=tmp_path / "missing",
            kind="directory",
            expected_binding=_binding(),
        )
        assert result.state == "absent"
        assert result.binding is None

    def test_empty_unbound(self, tmp_path: Path) -> None:
        """Empty directory with no marker returns 'empty-unbound'."""
        dest = tmp_path / "dest"
        dest.mkdir()
        result = inspect_storage_migration_destination(
            path=dest,
            kind="directory",
            expected_binding=_binding(),
        )
        assert result.state == "empty-unbound"

    def test_owned(self, tmp_path: Path) -> None:
        """Correctly bound directory returns 'owned' with fingerprint."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding())
        (dest / "data.txt").write_text("content", encoding="utf-8")
        result = inspect_storage_migration_destination(
            path=dest,
            kind="directory",
            expected_binding=_binding(),
        )
        assert result.state == "owned"
        assert result.binding is not None
        assert result.fingerprint is not None
        assert result.fingerprint.algorithm == "sha256-tree-v1"

    def test_foreign(self, tmp_path: Path) -> None:
        """Wrong binding returns 'foreign'."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding(project_uuid="other-uuid"))
        result = inspect_storage_migration_destination(
            path=dest,
            kind="directory",
            expected_binding=_binding(),
        )
        assert result.state == "foreign"
        assert result.binding is not None

    def test_invalid_symlink(self, tmp_path: Path) -> None:
        """Symlink returns 'invalid'."""
        target = tmp_path / "target"
        target.mkdir()
        dest = tmp_path / "dest"
        dest.symlink_to(target)
        result = inspect_storage_migration_destination(
            path=dest,
            kind="directory",
            expected_binding=_binding(),
        )
        assert result.state == "invalid"

    def test_invalid_no_marker_nonempty(self, tmp_path: Path) -> None:
        """Non-empty directory without marker returns 'invalid'."""
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "orphan.txt").write_text("data", encoding="utf-8")
        result = inspect_storage_migration_destination(
            path=dest,
            kind="directory",
            expected_binding=_binding(),
        )
        assert result.state == "invalid"

    def test_file_absent(self, tmp_path: Path) -> None:
        """Missing config file returns 'absent'."""
        result = inspect_storage_migration_destination(
            path=tmp_path / "config.toml",
            kind="file",
            expected_binding=_file_binding(),
        )
        assert result.state == "absent"

    def test_file_owned(self, tmp_path: Path) -> None:
        """Config file with valid parent binding returns 'owned'."""
        parent = tmp_path / "tool"
        parent.mkdir()
        _write_marker(parent, _file_binding())
        config = parent / "config.toml"
        config.write_text("[settings]\n", encoding="utf-8")
        result = inspect_storage_migration_destination(
            path=config,
            kind="file",
            expected_binding=_file_binding(),
        )
        assert result.state == "owned"
        assert result.fingerprint is not None
        assert result.fingerprint.algorithm == "sha256-file-v1"

    def test_file_foreign(self, tmp_path: Path) -> None:
        """Config file with wrong parent binding returns 'foreign'."""
        parent = tmp_path / "tool"
        parent.mkdir()
        _write_marker(parent, _file_binding(project_uuid="other"))
        config = parent / "config.toml"
        config.write_text("[settings]\n", encoding="utf-8")
        result = inspect_storage_migration_destination(
            path=config,
            kind="file",
            expected_binding=_file_binding(),
        )
        assert result.state == "foreign"


# ---------------------------------------------------------------------------
# Plan validation tests — destination policy matrix
# ---------------------------------------------------------------------------


def _make_plan(
    items: tuple[StorageMigrationItem, ...],
    project_uuid: str = "test-uuid",
) -> StorageMigrationPlan:
    from ledgercore.manifest import LedgerLocalOverrides

    return StorageMigrationPlan(
        migration_id="test-migration-id",
        project_uuid=project_uuid,
        items=items,
        config_changes=LedgerLocalOverrides(3, {}),
        warnings=(),
    )


class TestPlanValidation:
    def test_create_only_absent_ok(self, tmp_path: Path) -> None:
        """create-only + absent destination → create action."""
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=tmp_path / "dest",
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert val.valid
        assert val.items[0].action == "create"

    def test_create_only_empty_unbound_ok(self, tmp_path: Path) -> None:
        """create-only + empty unbound directory → create action."""
        dest = tmp_path / "dest"
        dest.mkdir()
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert val.valid
        assert val.items[0].action == "create"

    def test_create_only_rejects_owned(self, tmp_path: Path) -> None:
        """create-only + owned destination → conflict."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding())
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert val.items[0].action == "conflict"
        assert any("create-only" in e for e in val.errors)

    def test_replace_owned_requires_fingerprint(self, tmp_path: Path) -> None:
        """replace-owned without expected_before → conflict."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding())
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
            destination_policy="replace-owned",
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert val.items[0].action == "conflict"
        assert any("fingerprint" in e for e in val.errors)

    def test_replace_owned_rejects_foreign(self, tmp_path: Path) -> None:
        """replace-owned + foreign binding → conflict."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding(project_uuid="other-uuid"))
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
            destination_policy="replace-owned",
            expected_before=DestinationPrecondition(state="absent"),
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert val.items[0].action == "conflict"
        assert any("foreign" in e for e in val.errors)

    def test_replace_owned_accepts_matching(self, tmp_path: Path) -> None:
        """replace-owned + correct binding + matching fingerprint → replace."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding())
        (dest / "data.txt").write_text("content", encoding="utf-8")
        fp = fingerprint_storage_directory(dest)
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
            destination_policy="replace-owned",
            expected_before=DestinationPrecondition(state="owned", fingerprint=fp),
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert val.valid
        assert val.items[0].action == "replace"

    def test_replace_owned_rejects_changed_dest(self, tmp_path: Path) -> None:
        """replace-owned + fingerprint mismatch → conflict."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding())
        (dest / "data.txt").write_text("v1", encoding="utf-8")
        fp_v1 = fingerprint_storage_directory(dest)
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
            destination_policy="replace-owned",
            expected_before=DestinationPrecondition(state="owned", fingerprint=fp_v1),
        )
        # Mutate destination after fingerprinting
        (dest / "data.txt").write_text("v2", encoding="utf-8")
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert val.items[0].action == "conflict"
        assert any("fingerprint changed" in e for e in val.errors)

    def test_noop_if_exact_accepts_exact(self, tmp_path: Path) -> None:
        """noop-if-exact + exact fingerprint → noop."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding())
        (dest / "data.txt").write_text("content", encoding="utf-8")
        fp = fingerprint_storage_directory(dest)
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
            destination_policy="noop-if-exact",
            expected_target_fingerprint=fp,
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert val.valid
        assert val.items[0].action == "noop"

    def test_noop_if_exact_rejects_different(self, tmp_path: Path) -> None:
        """noop-if-exact + different fingerprint → conflict."""
        dest = tmp_path / "dest"
        dest.mkdir()
        _write_marker(dest, _binding())
        (dest / "data.txt").write_text("content", encoding="utf-8")
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "source",
            destination=dest,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
            destination_policy="noop-if-exact",
            expected_target_fingerprint=StorageFingerprint(
                algorithm="sha256-tree-v1",
                digest="definitelynotmatching",
                file_count=0,
                total_bytes=0,
            ),
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert val.items[0].action == "conflict"

    def test_config_replace_owned_accepts(self, tmp_path: Path) -> None:
        """replace-owned config file with matching fingerprint → replace."""
        parent = tmp_path / "tool"
        parent.mkdir()
        _write_marker(parent, _file_binding())
        config = parent / "config.toml"
        config.write_text("[settings]\n", encoding="utf-8")
        fp = fingerprint_storage_file(config)
        item = StorageMigrationItem(
            component="config",
            tool_name="test-tool",
            mount_name="config",
            source=tmp_path / "new_config.toml",
            destination=config,
            source_binding=_file_binding(),
            destination_binding=_file_binding(),
            strategy="copy",
            destination_policy="replace-owned",
            expected_before=DestinationPrecondition(state="owned", fingerprint=fp),
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert val.valid
        assert val.items[0].action == "replace"

    def test_rebuild_strategy_returns_rebuild(self, tmp_path: Path) -> None:
        """rebuild strategy → rebuild action (even with create-only)."""
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="cache",
            source=tmp_path / "source",
            destination=tmp_path / "dest",
            source_binding=_binding(mount="cache", storage="cache"),
            destination_binding=_binding(mount="cache", storage="cache"),
            strategy="rebuild",
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert val.valid
        assert val.items[0].action == "rebuild"


# ---------------------------------------------------------------------------
# Path overlap tests
# ---------------------------------------------------------------------------


class TestPathOverlap:
    def test_rejects_overlapping_destinations(self, tmp_path: Path) -> None:
        """One item destination inside another → conflict."""
        dest_a = tmp_path / "data"
        dest_b = tmp_path / "data" / "subdir"
        item_a = StorageMigrationItem(
            component="mount",
            tool_name="t",
            mount_name="a",
            source=tmp_path / "src_a",
            destination=dest_a,
            source_binding=_binding(mount="a"),
            destination_binding=_binding(mount="a"),
            strategy="copy",
        )
        item_b = StorageMigrationItem(
            component="mount",
            tool_name="t",
            mount_name="b",
            source=tmp_path / "src_b",
            destination=dest_b,
            source_binding=_binding(mount="b"),
            destination_binding=_binding(mount="b"),
            strategy="copy",
        )
        plan = _make_plan((item_a, item_b))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert any("inside" in e for e in val.errors)

    def test_rejects_same_destination(self, tmp_path: Path) -> None:
        """Two items with same destination → conflict."""
        dest = tmp_path / "dest"
        item_a = StorageMigrationItem(
            component="mount",
            tool_name="t",
            mount_name="a",
            source=tmp_path / "src_a",
            destination=dest,
            source_binding=_binding(mount="a"),
            destination_binding=_binding(mount="a"),
            strategy="copy",
        )
        item_b = StorageMigrationItem(
            component="mount",
            tool_name="t",
            mount_name="b",
            source=tmp_path / "src_b",
            destination=dest,
            source_binding=_binding(mount="b"),
            destination_binding=_binding(mount="b"),
            strategy="copy",
        )
        plan = _make_plan((item_a, item_b))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert any("same destination" in e for e in val.errors)

    def test_rejects_project_root_replacement(self, tmp_path: Path) -> None:
        """Destination equals project root → conflict."""
        item = StorageMigrationItem(
            component="mount",
            tool_name="t",
            mount_name="data",
            source=tmp_path / "src",
            destination=tmp_path,
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert any("project root" in e for e in val.errors)

    def test_rejects_ledger_dir_replacement(self, tmp_path: Path) -> None:
        """Destination equals .ledger → conflict."""
        item = StorageMigrationItem(
            component="mount",
            tool_name="t",
            mount_name="data",
            source=tmp_path / "src",
            destination=tmp_path / ".ledger",
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
        )
        plan = _make_plan((item,))
        val = validate_storage_migration_plan(plan, project_root=tmp_path)
        assert not val.valid
        assert any(".ledger" in e for e in val.errors)


# ---------------------------------------------------------------------------
# MigrationItemPaths tests
# ---------------------------------------------------------------------------


class TestPrepareItemPaths:
    def test_deterministic_naming(self, tmp_path: Path) -> None:
        """Stage and backup paths include migration-id and item-index."""
        dest = tmp_path / "data"
        paths = _prepare_item_paths(dest, "abc123", 0)
        assert "abc123-0" in str(paths.stage)
        assert "abc123-0" in str(paths.backup)
        assert ".data.migrating-" in str(paths.stage)
        assert ".data.backup-" in str(paths.backup)

    def test_different_index_different_paths(self, tmp_path: Path) -> None:
        """Different item indices produce different paths."""
        dest = tmp_path / "data"
        p0 = _prepare_item_paths(dest, "abc", 0)
        p1 = _prepare_item_paths(dest, "abc", 1)
        assert p0.stage != p1.stage
        assert p0.backup != p1.backup


# ---------------------------------------------------------------------------
# Existing behavior preservation
# ---------------------------------------------------------------------------


class TestExistingBehaviorPreserved:
    def test_default_policy_is_create_only(self, tmp_path: Path) -> None:
        """StorageMigrationItem defaults to create-only policy."""
        item = StorageMigrationItem(
            component="mount",
            tool_name="test-tool",
            mount_name="data",
            source=tmp_path / "src",
            destination=tmp_path / "dest",
            source_binding=_binding(),
            destination_binding=_binding(),
            strategy="copy",
        )
        assert item.destination_policy == "create-only"
        assert item.expected_before == DestinationPrecondition(state="absent")
        assert item.expected_source_fingerprint is None
        assert item.destination_kind is None
