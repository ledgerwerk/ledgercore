"""Tests for shared ledger configuration conventions."""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgercore.config import (
    LEDGER_CONFIG_FILENAMES,
    LEDGER_LEGACY_SHARED_CONFIGS,
    LEDGER_PROJECT_LOCAL_CONFIG,
    LEDGER_PROJECT_MANIFEST,
    LedgerConfigError,
    LedgerProjectLocator,
    ledger_config_filenames,
    locate_ledger_config,
    locate_ledger_project,
    select_project_config,
    select_tool_config,
)


@pytest.fixture()
def _isolate_path_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent locate_ledger_project from finding configs in ancestor dirs."""
    real_tmp = tmp_path.resolve()
    _orig_is_file = Path.is_file

    def _scoped_is_file(self: Path) -> bool:
        try:
            self.resolve().relative_to(real_tmp)
        except ValueError:
            return False
        return _orig_is_file(self)

    monkeypatch.setattr(Path, "is_file", _scoped_is_file)


def test_default_filenames_prefer_hidden() -> None:
    assert LEDGER_CONFIG_FILENAMES == (".ledger.toml", "ledger.toml")


def test_legacy_shared_filenames_match_default_names() -> None:
    assert LEDGER_LEGACY_SHARED_CONFIGS == LEDGER_CONFIG_FILENAMES


def test_ledger_config_filenames_appends_legacy() -> None:
    assert ledger_config_filenames(".legacy.toml", "legacy.toml") == (
        ".ledger.toml",
        "ledger.toml",
        ".legacy.toml",
        "legacy.toml",
    )


def test_ledger_config_filenames_can_exclude_visible() -> None:
    assert ledger_config_filenames(
        ".legacy.toml",
        include_visible=False,
    ) == (".ledger.toml", ".legacy.toml")


def test_locate_ledger_config_prefers_dot_ledger_toml(tmp_path: Path) -> None:
    visible = tmp_path / "ledger.toml"
    hidden = tmp_path / ".ledger.toml"
    visible.write_text("visible", encoding="utf-8")
    hidden.write_text("hidden", encoding="utf-8")

    result = locate_ledger_config(tmp_path)

    assert result is not None
    assert result.config_path == hidden
    assert result.workspace_root == tmp_path


def test_locate_ledger_config_prefers_canonical_over_legacy(tmp_path: Path) -> None:
    canonical = tmp_path / "ledger.toml"
    legacy = tmp_path / ".legacy.toml"
    canonical.write_text("canonical", encoding="utf-8")
    legacy.write_text("legacy", encoding="utf-8")

    result = locate_ledger_config(
        tmp_path,
        legacy_filenames=(".legacy.toml", "legacy.toml"),
    )

    assert result is not None
    assert result.config_path == canonical


def test_locate_ledger_config_falls_back_to_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / ".legacy.toml"
    legacy.write_text("legacy", encoding="utf-8")

    result = locate_ledger_config(
        tmp_path,
        legacy_filenames=(".legacy.toml", "legacy.toml"),
    )

    assert result is not None
    assert result.config_path == legacy


def test_locate_ledger_config_default_uses_dot_ledger(tmp_path: Path) -> None:
    result = locate_ledger_config(tmp_path, default=True)

    assert result is not None
    assert result.source == "default"
    assert result.config_path == (tmp_path / ".ledger.toml").resolve()


def test_locate_ledger_config_accepts_custom_default_filename(
    tmp_path: Path,
) -> None:
    result = locate_ledger_config(
        tmp_path,
        default=True,
        default_filename="custom.toml",
    )

    assert result is not None
    assert result.config_path == (tmp_path / "custom.toml").resolve()


class TestLocateLedgerProject:
    def test_prefers_canonical_nested_manifest(self, tmp_path: Path) -> None:
        config_root = tmp_path / ".ledger"
        config_root.mkdir()
        manifest = config_root / "ledger.toml"
        manifest.write_text("schema_version = 2\n", encoding="utf-8")
        (tmp_path / ".ledger.toml").write_text("legacy", encoding="utf-8")
        nested = tmp_path / "src" / "pkg"
        nested.mkdir(parents=True)

        result = locate_ledger_project(nested)

        assert result == LedgerProjectLocator(
            project_root=tmp_path.resolve(),
            config_root=config_root.resolve(),
            manifest_path=manifest.resolve(),
            local_config_path=(config_root / "ledger.local.toml").resolve(),
            source="canonical",
        )
        assert not result.is_legacy

    def test_falls_back_to_legacy_shared(self, tmp_path: Path) -> None:
        shared = tmp_path / ".ledger.toml"
        shared.write_text("schema_version = 1\n", encoding="utf-8")

        result = locate_ledger_project(tmp_path)

        assert result is not None
        assert result.project_root == tmp_path.resolve()
        assert result.manifest_path == shared.resolve()
        assert (
            result.local_config_path
            == (tmp_path / LEDGER_PROJECT_LOCAL_CONFIG).resolve()
        )
        assert result.source == "legacy-shared"
        assert result.is_legacy

    def test_falls_back_to_legacy_tool_names(self, tmp_path: Path) -> None:
        tool_config = tmp_path / ".taskledger.toml"
        tool_config.write_text("schema_version = 1\n", encoding="utf-8")

        result = locate_ledger_project(
            tmp_path / "nested",
            legacy_tool_filenames=(".taskledger.toml", "taskledger.toml"),
        )

        assert result is not None
        assert result.manifest_path == tool_config.resolve()
        assert result.source == "legacy-tool"
        assert result.is_legacy

    def test_prefers_nearest_ancestor(self, tmp_path: Path) -> None:
        root_manifest = tmp_path / ".ledger" / "ledger.toml"
        root_manifest.parent.mkdir()
        root_manifest.write_text("schema_version = 2\n", encoding="utf-8")
        nested_project = tmp_path / "sub"
        nested_manifest = nested_project / ".ledger" / "ledger.toml"
        nested_manifest.parent.mkdir(parents=True)
        nested_manifest.write_text("schema_version = 2\n", encoding="utf-8")

        result = locate_ledger_project(nested_project / "pkg" / "module.py")

        assert result is not None
        assert result.project_root == nested_project.resolve()
        assert result.manifest_path == nested_manifest.resolve()

    def test_accepts_existing_file_start(self, tmp_path: Path) -> None:
        manifest = tmp_path / ".ledger" / "ledger.toml"
        manifest.parent.mkdir()
        manifest.write_text("schema_version = 2\n", encoding="utf-8")
        source_file = tmp_path / "src" / "main.py"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("print('x')\n", encoding="utf-8")

        result = locate_ledger_project(source_file)

        assert result is not None
        assert result.project_root == tmp_path.resolve()

    def test_treats_missing_start_as_directory_for_default(
        self, tmp_path: Path, _isolate_path_to_tmp: None
    ) -> None:
        missing = tmp_path / "missing" / "path.py"

        result = locate_ledger_project(missing, default=True)

        assert result is not None
        assert result.source == "default"
        assert result.project_root == missing.resolve()
        assert result.config_root == (missing / ".ledger").resolve()
        assert result.manifest_path == (missing / LEDGER_PROJECT_MANIFEST).resolve()

    def test_returns_none_without_default(
        self, tmp_path: Path, _isolate_path_to_tmp: None
    ) -> None:
        assert locate_ledger_project(tmp_path) is None


def test_select_tool_config() -> None:
    doc = {"tools": {"example": {"config_version": 2}}}

    assert select_tool_config(doc, "example") == {"config_version": 2}


def test_select_tool_config_accepts_custom_table_name() -> None:
    doc = {"extensions": {"example": {"enabled": True}}}

    assert select_tool_config(
        doc,
        "example",
        table_name="extensions",
    ) == {"enabled": True}


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({}, "missing [tools] table"),
        ({"tools": []}, "missing [tools] table"),
        ({"tools": {}}, "missing [tools.example] table"),
        ({"tools": {"example": "invalid"}}, "missing [tools.example] table"),
    ],
)
def test_select_tool_config_rejects_missing_or_invalid_tables(
    document: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(LedgerConfigError) as exc_info:
        select_tool_config(document, "example")
    assert str(exc_info.value) == message


def test_select_project_config_defaults_empty() -> None:
    assert select_project_config({}) == {}


def test_select_project_config() -> None:
    project = {"uuid": "123", "name": "example"}

    assert select_project_config({"project": project}) == project


def test_select_project_config_accepts_custom_table_name() -> None:
    shared = {"name": "example"}

    assert select_project_config({"shared": shared}, table_name="shared") == shared


def test_select_project_config_rejects_non_mapping() -> None:
    with pytest.raises(LedgerConfigError, match=r"\[project\] must be a table"):
        select_project_config({"project": []})
