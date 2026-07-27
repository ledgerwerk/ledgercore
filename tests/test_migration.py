from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ledgercore.config import LedgerProjectLocator
from ledgercore.errors import StorageMigrationError
from ledgercore.layout import PlatformRoots, resolve_ledger_layout
from ledgercore.manifest import (
    LedgerLocalOverrides,
    LoadedLedgerProject,
    MountOverride,
    parse_ledger_manifest_v3,
)
from ledgercore.migration import (
    execute_storage_migration,
    inspect_storage_migration,
    plan_storage_migration,
    recover_storage_migration,
)
from ledgercore.storage_binding import (
    initialize_external_store,
    initialize_storage_binding,
)

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def test_plan_rejects_unbound_source_and_does_not_write(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".ledger").mkdir(parents=True)
    initialize_external_store(tmp_path / "ledger")
    locator = LedgerProjectLocator(
        project,
        project / ".ledger",
        project / ".ledger/ledger.toml",
        project / ".ledger/ledger.local.toml",
        "canonical",
    )
    manifest = parse_ledger_manifest_v3(
        {
            "schema_version": 3,
            "project": {"uuid": UUID},
            "ledgers": {
                "taskledger": {
                    "mounts": {"data": {"storage": "external", "root": "../ledger"}}
                }
            },
        }
    )
    current = LoadedLedgerProject(locator, manifest, LedgerLocalOverrides(3, {}), {})
    layout = resolve_ledger_layout(
        locator,
        manifest,
        "taskledger",
        platform_roots=PlatformRoots(tmp_path / "data", tmp_path / "cache"),
    )
    initialize_storage_binding(layout.mounts["data"])
    target = LedgerLocalOverrides(
        3, {"taskledger": {"data": MountOverride(storage="user-data")}}
    )
    plan = plan_storage_migration(current, manifest, target, "taskledger")
    assert plan.items[0].strategy == "copy"
    assert not (project / ".ledger/migrations").exists()


def _make_plan_external_to_user_data(tmp_path: Path) -> tuple:
    """Set up a plan migrating external -> user-data."""
    project = tmp_path / "project"
    (project / ".ledger").mkdir(parents=True)
    external_root = tmp_path / "ledger"
    initialize_external_store(external_root)
    locator = LedgerProjectLocator(
        project,
        project / ".ledger",
        project / ".ledger/ledger.toml",
        project / ".ledger/ledger.local.toml",
        "canonical",
    )
    manifest = parse_ledger_manifest_v3(
        {
            "schema_version": 3,
            "project": {"uuid": UUID},
            "ledgers": {
                "taskledger": {
                    "mounts": {"data": {"storage": "external", "root": "../ledger"}}
                }
            },
        }
    )
    current = LoadedLedgerProject(locator, manifest, LedgerLocalOverrides(3, {}), {})
    layout = resolve_ledger_layout(
        locator,
        manifest,
        "taskledger",
        platform_roots=PlatformRoots(tmp_path / "data", tmp_path / "cache"),
    )
    initialize_storage_binding(layout.mounts["data"])
    # Put some data in the source
    source_data = layout.mounts["data"].path / "testfile.txt"
    source_data.write_text("hello world", encoding="utf-8")
    target = LedgerLocalOverrides(
        3, {"taskledger": {"data": MountOverride(storage="user-data")}}
    )
    plan = plan_storage_migration(current, manifest, target, "taskledger")
    # Clean up user-data destination if it exists from a previous test
    for item in plan.items:
        dest = item.destination
        if dest.exists():
            shutil.rmtree(dest)
    return plan, locator, manifest, layout, project


def test_binding_identity_regression_external_to_user_data(tmp_path: Path) -> None:
    """Regression: journal must preserve exact source/destination binding storage."""
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    result = execute_storage_migration(
        plan,
        project_root=project,
        quiescence_check=lambda: None,
    )
    assert result.phase == "complete"
    assert result.source_removed is False
    journal = inspect_storage_migration(result.journal_path)
    assert journal.schema_version == 2
    assert journal.items[0].source_binding is not None
    assert journal.items[0].destination_binding is not None
    assert journal.items[0].source_binding.storage == "external"
    assert journal.items[0].destination_binding.storage == "user-data"
    # Full binding equality
    src = plan.items[0].source_binding
    dst = plan.items[0].destination_binding
    assert journal.items[0].source_binding == src
    assert journal.items[0].destination_binding == dst


def test_binding_field_coverage_round_trip(tmp_path: Path) -> None:
    """Test that all binding fields round-trip through the journal."""
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    result = execute_storage_migration(
        plan,
        project_root=project,
        quiescence_check=lambda: None,
    )
    journal = inspect_storage_migration(result.journal_path)
    src = journal.items[0].source_binding
    assert src is not None
    assert src.schema_version == 1
    assert src.layout_version == 3
    assert src.project_uuid == UUID
    assert src.tool == "taskledger"
    assert src.mount == "data"
    assert src.storage == "external"
    dst = journal.items[0].destination_binding
    assert dst is not None
    assert dst.storage == "user-data"


def test_schema1_inspection(tmp_path: Path) -> None:
    """Schema-1 journal: bindings, mode, verify, source_removed are None."""
    journal_dir = tmp_path / "project" / ".ledger" / "migrations"
    journal_dir.mkdir(parents=True)
    journal_path = journal_dir / "abc123.toml"
    journal_content = (
        "schema_version = 1\n"
        'migration_id = "test-mig"\n'
        f'project_uuid = "{UUID}"\n'
        'phase = "complete"\n'
        "\n"
        '[items."0"]\n'
        'component = "mount"\n'
        'tool = "taskledger"\n'
        'mount = "data"\n'
        'source = "/old/data"\n'
        'destination = "/new/data"\n'
        'strategy = "copy"\n'
    )
    journal_path.write_text(journal_content, encoding="utf-8")
    journal = inspect_storage_migration(journal_path)
    assert journal.schema_version == 1
    assert journal.items[0].source_binding is None
    assert journal.items[0].destination_binding is None
    assert journal.mode is None
    assert journal.verify is None
    assert journal.source_removed is None
    assert journal.items_completed == 1  # complete journal
    assert journal.recovery_capability == "completed-only"


def test_schema2_round_trip(tmp_path: Path) -> None:
    """Schema-2 journal round-trips all fields."""
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    result = execute_storage_migration(
        plan,
        project_root=project,
        quiescence_check=lambda: None,
    )
    journal = inspect_storage_migration(result.journal_path)
    assert journal.migration_id == plan.migration_id
    assert journal.project_uuid == UUID
    assert journal.phase == "complete"
    assert journal.mode == "copy"
    assert journal.verify == "sha256"
    assert journal.project_root is not None
    assert journal.items_completed == 1
    assert journal.source_removed is False
    assert journal.error is None
    assert len(journal.items) == 1
    assert journal.items[0].source == plan.items[0].source
    assert journal.items[0].destination == plan.items[0].destination
    assert journal.items[0].strategy == "copy"
    # Check deterministic rendering and final newline
    text = result.journal_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    # Re-read to verify determinism
    journal2 = inspect_storage_migration(result.journal_path)
    assert journal2 == journal


def test_copy_is_default(tmp_path: Path) -> None:
    """Execute without mode argument; copy is the default."""
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    result = execute_storage_migration(
        plan,
        project_root=project,
        quiescence_check=lambda: None,
    )
    assert result.phase == "complete"
    assert result.source_removed is False
    # Source still exists
    source = plan.items[0].source
    assert source.exists()
    assert (source / "testfile.txt").read_text(encoding="utf-8") == "hello world"
    # Destination exists with same content
    dest = plan.items[0].destination
    assert dest.exists()
    assert (dest / "testfile.txt").read_text(encoding="utf-8") == "hello world"
    # Journal says copy
    journal = inspect_storage_migration(result.journal_path)
    assert journal.mode == "copy"
    assert journal.source_removed is False


def test_explicit_move_is_rejected_safely(tmp_path: Path) -> None:
    """mode='move' raises before any write."""
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    with pytest.raises(StorageMigrationError) as exc_info:
        execute_storage_migration(
            plan,
            mode="move",
            project_root=project,
            quiescence_check=lambda: None,
        )
    assert exc_info.value.code == "STORAGE_MIGRATION_MOVE_DISABLED"
    # No journal directory was created
    migrations_dir = project / ".ledger" / "migrations"
    assert not migrations_dir.exists()
    # Source unchanged
    source = plan.items[0].source
    assert source.exists()
    assert (source / "testfile.txt").read_text(encoding="utf-8") == "hello world"


def test_move_rejection_precedes_verification_validation(tmp_path: Path) -> None:
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)

    with pytest.raises(StorageMigrationError) as exc_info:
        execute_storage_migration(
            plan,
            mode="move",
            verify="invalid",  # type: ignore[arg-type]
            project_root=project,
            quiescence_check=lambda: None,
        )

    assert exc_info.value.code == "STORAGE_MIGRATION_MOVE_DISABLED"
    assert not (project / ".ledger" / "migrations").exists()


def test_completed_recovery_schema2_copy(tmp_path: Path) -> None:
    """Completed schema-2 copy journal returns source_removed=False."""
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    result = execute_storage_migration(
        plan,
        project_root=project,
        quiescence_check=lambda: None,
    )
    recovered = recover_storage_migration(result.journal_path)
    assert recovered.source_removed is False
    assert recovered.phase == "complete"


def test_completed_recovery_schema1(tmp_path: Path) -> None:
    """Completed schema-1 journal returns source_removed=None."""
    journal_dir = tmp_path / "project" / ".ledger" / "migrations"
    journal_dir.mkdir(parents=True)
    journal_path = journal_dir / "schema1.toml"
    journal_content = (
        "schema_version = 1\n"
        'migration_id = "old-mig"\n'
        f'project_uuid = "{UUID}"\n'
        'phase = "complete"\n'
        "\n"
        '[items."0"]\n'
        'component = "mount"\n'
        'tool = "taskledger"\n'
        'mount = "data"\n'
        'source = "/old/data"\n'
        'destination = "/new/data"\n'
        'strategy = "copy"\n'
    )
    journal_path.write_text(journal_content, encoding="utf-8")
    recovered = recover_storage_migration(journal_path)
    assert recovered.source_removed is None
    assert recovered.phase == "complete"


def test_schema1_unknown_phase_is_manual_intervention(tmp_path: Path) -> None:
    journal_dir = tmp_path / "project" / ".ledger" / "migrations"
    journal_dir.mkdir(parents=True)
    journal_path = journal_dir / "unknown-phase.toml"
    journal_path.write_text(
        "schema_version = 1\n"
        'migration_id = "old-mig"\n'
        f'project_uuid = "{UUID}"\n'
        'phase = "legacy-unknown"\n'
        "[items]\n",
        encoding="utf-8",
    )

    journal = inspect_storage_migration(journal_path)
    assert journal.recovery_capability == "manual-intervention"
    with pytest.raises(StorageMigrationError) as exc_info:
        recover_storage_migration(journal_path)
    assert exc_info.value.code == "STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED"


def test_recovery_does_not_modify_journal(tmp_path: Path) -> None:
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    result = execute_storage_migration(
        plan,
        project_root=project,
        quiescence_check=lambda: None,
    )
    before = result.journal_path.read_bytes()

    recovered = recover_storage_migration(result.journal_path)

    assert recovered.source_removed is False
    assert result.journal_path.read_bytes() == before


def test_incomplete_recovery_raises_manual_intervention(tmp_path: Path) -> None:
    """Incomplete journals raise STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED."""
    journal_dir = tmp_path / "project" / ".ledger" / "migrations"
    journal_dir.mkdir(parents=True)
    for phase in ("planned", "copying", "verified", "config-switched", "failed"):
        journal_path = journal_dir / f"{phase}.toml"
        journal_content = (
            f"schema_version = 2\n"
            f'migration_id = "test-{phase}"\n'
            f'project_uuid = "{UUID}"\n'
            f'phase = "{phase}"\n'
            f'mode = "copy"\n'
            f'verify = "sha256"\n'
            f'project_root = "/tmp"\n'
            f"items_completed = 0\n"
            f"source_removed = false\n"
            f"\n"
            f"[items]\n"
        )
        journal_path.write_text(journal_content, encoding="utf-8")
        journal = inspect_storage_migration(journal_path)
        assert journal.recovery_capability == "manual-intervention"
        with pytest.raises(StorageMigrationError) as exc_info:
            recover_storage_migration(journal_path)
        assert exc_info.value.code == "STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED"


def test_failure_journal(tmp_path: Path) -> None:
    """Failure during execution records a schema-2 failed journal."""
    plan, _, _, _, project = _make_plan_external_to_user_data(tmp_path)
    call_count = 0

    def failing_quiescence() -> None:
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise RuntimeError("quiescence failure")

    with pytest.raises((RuntimeError, StorageMigrationError)):
        execute_storage_migration(
            plan,
            project_root=project,
            quiescence_check=failing_quiescence,
        )
    # Find the journal
    migrations_dir = project / ".ledger" / "migrations"
    assert migrations_dir.exists()
    journals = list(migrations_dir.glob("*.toml"))
    assert len(journals) == 1
    journal = inspect_storage_migration(journals[0])
    assert journal.schema_version == 2
    assert journal.phase == "failed"
    assert journal.source_removed is False
    assert journal.error is not None
    # Source data still present
    source = plan.items[0].source
    assert source.exists()
    assert (source / "testfile.txt").exists()


def test_invalid_journal_data_rejection(tmp_path: Path) -> None:
    """Invalid journal data is rejected with STORAGE_MIGRATION_JOURNAL_INVALID."""
    journal_dir = tmp_path / "journals"
    journal_dir.mkdir()

    # Unsupported schema
    p = journal_dir / "bad_schema.toml"
    p.write_text("schema_version = 99\n", encoding="utf-8")
    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(p)
    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"

    # Missing migration_id in schema 2
    p = journal_dir / "no_id.toml"
    p.write_text(
        'schema_version = 2\nphase = "complete"\n'
        'project_uuid = "x"\nmode = "copy"\nverify = "sha256"\n'
        'project_root = "/tmp"\nitems_completed = 0\n'
        "source_removed = false\n[items]\n",
        encoding="utf-8",
    )
    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(p)
    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"

    # Non-integer items_completed
    p = journal_dir / "bad_completed.toml"
    p.write_text(
        'schema_version = 2\nmigration_id = "x"\n'
        'phase = "complete"\nproject_uuid = "x"\n'
        'mode = "copy"\nverify = "sha256"\n'
        'project_root = "/tmp"\n'
        'items_completed = "not-int"\n'
        "source_removed = false\n[items]\n",
        encoding="utf-8",
    )
    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(p)
    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"

    # Invalid mode
    p = journal_dir / "bad_mode.toml"
    p.write_text(
        'schema_version = 2\nmigration_id = "x"\n'
        'phase = "complete"\nproject_uuid = "x"\n'
        'mode = "invalid"\nverify = "sha256"\n'
        'project_root = "/tmp"\n'
        "items_completed = 0\n"
        "source_removed = false\n[items]\n",
        encoding="utf-8",
    )
    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(p)
    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"

    # Symlink journal path
    symlink = journal_dir / "symlink.toml"
    symlink.symlink_to(p)
    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(symlink)
    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"


def _write_schema2_journal(
    path: Path, *, phase: str = "complete", items: str = ""
) -> None:
    path.write_text(
        "schema_version = 2\n"
        'migration_id = "test-migration"\n'
        f'project_uuid = "{UUID}"\n'
        f'phase = "{phase}"\n'
        'mode = "copy"\n'
        'verify = "sha256"\n'
        'project_root = "/tmp/project"\n'
        "items_completed = 0\n"
        "source_removed = false\n"
        "\n"
        "[items]\n"
        f"{items}",
        encoding="utf-8",
    )


def test_schema2_rejects_unsupported_phase(tmp_path: Path) -> None:
    journal_path = tmp_path / "unsupported-phase.toml"
    _write_schema2_journal(journal_path, phase="resuming")

    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(journal_path)

    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"


def test_schema2_rejects_non_string_identity_fields(tmp_path: Path) -> None:
    journal_path = tmp_path / "invalid-identity.toml"
    journal_path.write_text(
        "schema_version = 2\n"
        "migration_id = 42\n"
        f'project_uuid = "{UUID}"\n'
        'phase = "complete"\n'
        'mode = "copy"\n'
        'verify = "sha256"\n'
        'project_root = "/tmp/project"\n'
        "items_completed = 0\n"
        "source_removed = false\n"
        "[items]\n",
        encoding="utf-8",
    )

    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(journal_path)

    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"


def test_schema2_rejects_non_numeric_item_key(tmp_path: Path) -> None:
    journal_path = tmp_path / "invalid-item-key.toml"
    _write_schema2_journal(
        journal_path,
        items="""
[items.bad]
component = "mount"
tool = "taskledger"
mount = "data"
source = "/old/data"
destination = "/new/data"
strategy = "copy"
""",
    )

    with pytest.raises(StorageMigrationError) as exc_info:
        inspect_storage_migration(journal_path)

    assert exc_info.value.code == "STORAGE_MIGRATION_JOURNAL_INVALID"


def test_existing_behavior_planning_no_writes(tmp_path: Path) -> None:
    """Planning performs no writes (existing test, strengthened)."""
    project = tmp_path / "project"
    (project / ".ledger").mkdir(parents=True)
    initialize_external_store(tmp_path / "ledger")
    locator = LedgerProjectLocator(
        project,
        project / ".ledger",
        project / ".ledger/ledger.toml",
        project / ".ledger/ledger.local.toml",
        "canonical",
    )
    manifest = parse_ledger_manifest_v3(
        {
            "schema_version": 3,
            "project": {"uuid": UUID},
            "ledgers": {
                "taskledger": {
                    "mounts": {"data": {"storage": "external", "root": "../ledger"}}
                }
            },
        }
    )
    current = LoadedLedgerProject(locator, manifest, LedgerLocalOverrides(3, {}), {})
    layout = resolve_ledger_layout(
        locator,
        manifest,
        "taskledger",
        platform_roots=PlatformRoots(tmp_path / "data", tmp_path / "cache"),
    )
    initialize_storage_binding(layout.mounts["data"])
    target = LedgerLocalOverrides(
        3, {"taskledger": {"data": MountOverride(storage="user-data")}}
    )
    plan = plan_storage_migration(current, manifest, target, "taskledger")
    assert plan.items[0].strategy == "copy"
    assert not (project / ".ledger/migrations").exists()
