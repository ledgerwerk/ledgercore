from __future__ import annotations

from pathlib import Path

import pytest

from ledgercore.errors import StorageMigrationError
from ledgercore.migration import (
    DestinationPrecondition,
    Schema3MigrationJournal,
    StorageMigrationHooks,
    StorageMigrationItem,
    StorageMigrationPlan,
    execute_storage_migration,
    fingerprint_storage_directory,
    inspect_storage_migration,
    inspect_storage_migration_destination,
    recover_storage_migration,
)
from ledgercore.overrides import LedgerLocalOverrides
from ledgercore.storage_binding import StorageBinding, write_storage_binding


def _binding(project_uuid: str, mount: str, storage: str) -> StorageBinding:
    return StorageBinding(
        schema_version=1,
        layout_version=3,
        project_uuid=project_uuid,
        project_name=None,
        tool="example",
        mount=mount,
        storage=storage,  # type: ignore[arg-type]
    )


def _plan(tmp_path: Path) -> tuple[StorageMigrationPlan, Path, Path]:
    root = tmp_path / "project"
    (root / ".ledger").mkdir(parents=True)
    source = tmp_path / "source"
    source.mkdir()
    source_binding = _binding("project", "data", "external")
    write_storage_binding(source, source_binding)
    (source / "records.txt").write_text("records\n", encoding="utf-8")
    destination = tmp_path / "destination"
    destination_binding = _binding("project", "data", "user-data")
    plan = StorageMigrationPlan(
        migration_id="recovery-test-0001",
        project_uuid="project",
        items=(
            StorageMigrationItem(
                component="mount",
                tool_name="example",
                mount_name="data",
                source=source,
                destination=destination,
                source_binding=source_binding,
                destination_binding=destination_binding,
                strategy="copy",
                expected_source_fingerprint=fingerprint_storage_directory(source),
                expected_before=DestinationPrecondition("absent"),
            ),
        ),
        config_changes=LedgerLocalOverrides(3, {}),
    )
    return plan, root, source


def test_required_hooks_are_journaled_and_run_in_order(tmp_path: Path) -> None:
    plan, root, source = _plan(tmp_path)
    assert inspect_storage_migration_destination(plan.items[0]).state == "absent"
    events: list[str] = []
    hooks = StorageMigrationHooks(
        quiescence_check=lambda: events.append("quiesce"),
        validate_staged=lambda index: events.append(f"staged:{index}"),
        validate_activated=lambda index: events.append(f"activated:{index}"),
        finalize=lambda: events.append("finalize"),
        requires_staged_validation=True,
        requires_activated_validation=True,
        requires_finalization=True,
    )

    result = execute_storage_migration(plan, project_root=root, hooks=hooks)

    assert result.phase == "complete"
    assert source.exists()
    assert events == ["quiesce", "staged:0", "activated:0", "finalize"]
    journal = inspect_storage_migration(result.journal_path)
    assert isinstance(journal, Schema3MigrationJournal)
    assert journal.schema_version == 3
    assert journal.quiescence_completed is True
    assert journal.staged_validated == (0,)
    assert journal.activated_validated == (0,)
    assert journal.finalized is True
    assert journal.items[0].state == "complete"


def test_missing_required_hook_fails_before_filesystem_mutation(tmp_path: Path) -> None:
    plan, root, source = _plan(tmp_path)
    hooks = StorageMigrationHooks(requires_finalization=True)

    with pytest.raises(StorageMigrationError) as raised:
        execute_storage_migration(plan, project_root=root, hooks=hooks)

    assert raised.value.code == "STORAGE_MIGRATION_HOOK_REQUIRED"
    assert source.exists()
    assert not (root / ".ledger" / "migrations").exists()


def test_failed_finalization_can_be_inspected_and_resumed(tmp_path: Path) -> None:
    plan, root, source = _plan(tmp_path)

    def fail_finalize() -> None:
        raise RuntimeError("operator callback interrupted")

    with pytest.raises(StorageMigrationError) as raised:
        execute_storage_migration(
            plan,
            project_root=root,
            hooks=StorageMigrationHooks(
                finalize=fail_finalize, requires_finalization=True
            ),
        )
    assert raised.value.code == "STORAGE_MIGRATION_HOOK_FAILED"
    journal_path = root / ".ledger" / "migrations" / f"{plan.migration_id}.toml"
    assessment = inspect_storage_migration(journal_path)
    assert isinstance(assessment, Schema3MigrationJournal)
    assert assessment.phase == "failed"
    assert assessment.error is not None

    recovered = recover_storage_migration(
        journal_path,
        policy="resume",
        project_root=root,
        hooks=StorageMigrationHooks(finalize=lambda: None, requires_finalization=True),
    )

    assert recovered.phase == "complete"
    assert source.exists()


def test_explicit_rollback_restores_source_layout_without_touching_source(
    tmp_path: Path,
) -> None:
    plan, root, source = _plan(tmp_path)

    with pytest.raises(StorageMigrationError):
        execute_storage_migration(
            plan,
            project_root=root,
            hooks=StorageMigrationHooks(
                finalize=lambda: (_ for _ in ()).throw(RuntimeError("stop")),
                requires_finalization=True,
            ),
        )

    journal_path = root / ".ledger" / "migrations" / f"{plan.migration_id}.toml"
    rolled_back = recover_storage_migration(
        journal_path, policy="rollback", project_root=root
    )

    assert rolled_back.phase == "rolled-back"
    assert source.exists()
    assert not plan.items[0].destination.exists()
    assert not (root / ".ledger" / "ledger.local.toml").exists()


def test_recovery_dry_run_is_non_mutating(tmp_path: Path) -> None:
    plan, root, _ = _plan(tmp_path)
    with pytest.raises(StorageMigrationError):
        execute_storage_migration(
            plan,
            project_root=root,
            hooks=StorageMigrationHooks(
                finalize=lambda: (_ for _ in ()).throw(RuntimeError("stop")),
                requires_finalization=True,
            ),
        )
    journal_path = root / ".ledger" / "migrations" / f"{plan.migration_id}.toml"
    before = journal_path.read_bytes()
    assessment = recover_storage_migration(
        journal_path, dry_run=True, project_root=root
    )
    assert assessment.recommendation in {"resume", "rollback", "manual-intervention"}
    assert journal_path.read_bytes() == before
