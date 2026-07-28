"""Framework-neutral migration protocol.

Memoryledger registers domain handlers. Ledgercore owns the lifecycle
vocabulary and shared storage migration adapter, not the domain
transformations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from ledgercore.migration import (
    RecoveryAssessment,
    StorageMigrationHooks,
    StorageMigrationResult,
    assess_storage_migration,
    inspect_storage_migration,
    recover_storage_migration,
)

from .envelope import ErrorEnvelope, SuccessEnvelope
from .errors import CLIError, ExitCode, cli_error_from_exception


@dataclass(frozen=True)
class MigrationCapabilities:
    """Capabilities declared by a migration handler."""

    supports_plan: bool = True
    supports_apply: bool = True
    supports_recover: bool = False
    supports_cleanup: bool = True
    requires_workspace: bool = True
    requires_legacy_state: bool = False


class MigrationHandler(Protocol):
    """Protocol for domain migration handlers."""

    name: str
    summary: str
    capabilities: MigrationCapabilities

    def status(self, root: Path) -> Mapping[str, object]: ...
    def plan(self, root: Path, options: Mapping[str, object]) -> Any: ...
    def apply(
        self, root: Path, plan: Any, dry_run: bool = False
    ) -> Mapping[str, object]: ...
    def recover(self, root: Path, journal: Path) -> Mapping[str, object]: ...
    def cleanup(self, root: Path, dry_run: bool = False) -> Mapping[str, object]: ...


@dataclass
class MigrationPlanLike:
    """Shape expected from a migration plan."""

    migration_name: str
    source_paths: list[str]
    target_paths: list[str]
    details: Mapping[str, object]


@dataclass(frozen=True)
class MigrationCommandResponse:
    """Framework-neutral response used by unified CLI adapters."""

    exit_code: ExitCode
    payload: Mapping[str, object]
    envelope: SuccessEnvelope | ErrorEnvelope
    human: str

    @property
    def ok(self) -> bool:
        return self.exit_code == ExitCode.SUCCESS

    def as_mapping(self) -> dict[str, object]:
        result = self.envelope.as_mapping()
        result["exit_code"] = int(self.exit_code)
        return result

    def to_json(self) -> str:
        return self.envelope.to_json()

    def __str__(self) -> str:
        return self.human


def _payload(value: StorageMigrationResult | RecoveryAssessment) -> dict[str, object]:
    if isinstance(value, RecoveryAssessment):
        return {
            "migration_id": value.migration_id,
            "journal_path": str(value.journal_path),
            "phase": value.phase,
            "item_states": list(value.item_states),
            "owned_paths": [str(path) for path in value.owned_paths],
            "blockers": list(value.blockers),
            "recommended_action": value.recommendation,
            "resumable": value.resumable,
            "rollbackable": value.rollbackable,
            "complete": value.complete,
        }
    return {
        "migration_id": value.migration_id,
        "journal_path": str(value.journal_path),
        "phase": value.phase,
        "items_completed": value.items_completed,
        "source_removed": value.source_removed,
        "config_switched": value.config_switched,
        "cleanup_complete": value.cleanup_complete,
        "item_outcomes": list(value.item_outcomes),
        "error_code": value.error_code,
        "recommendation": value.recommendation,
    }


def _human(command: str, payload: Mapping[str, object]) -> str:
    lines = [
        f"ledgercore {command}",
        f"journal: {payload.get('journal_path', '')}",
        f"phase: {payload.get('phase', '')}",
    ]
    recommendation = payload.get("recommended_action", payload.get("recommendation"))
    if recommendation:
        lines.append(f"recommended action: {recommendation}")
    blockers = payload.get("blockers")
    if isinstance(blockers, (list, tuple)) and blockers:
        lines.append("blockers: " + "; ".join(str(blocker) for blocker in blockers))
    return "\n".join(lines)


def _error_response(command: str, exc: Exception) -> MigrationCommandResponse:
    error: CLIError = cli_error_from_exception(exc)
    payload = {
        "code": error.code,
        "message": error.message,
        "details": dict(error.details),
        "remediation": list(error.remediation),
    }
    envelope = ErrorEnvelope(
        tool="ledgercore",
        command=command,
        error=payload,
    )
    return MigrationCommandResponse(
        error.exit_code,
        payload,
        envelope,
        f"ledgercore {command}: {error.code}: {error.message}",
    )


def inspect_migration(
    journal: Path,
    *,
    output: Literal["human", "json"] = "human",
) -> MigrationCommandResponse:
    """Implement ``ledgercore migrate inspect --journal PATH``."""
    try:
        inspected = inspect_storage_migration(journal)
        if isinstance(inspected, RecoveryAssessment):
            payload = _payload(inspected)
        elif inspected.schema_version == 3:
            payload = _payload(assess_storage_migration(journal))
        else:
            payload = {
                "migration_id": inspected.migration_id,
                "journal_path": str(journal),
                "phase": inspected.phase,
                "schema_version": inspected.schema_version,
                "recommended_action": inspected.recovery_capability,
                "items_completed": inspected.items_completed,
            }
        envelope = SuccessEnvelope(
            tool="ledgercore",
            command="migrate.inspect",
            result=payload,
        )
        response = MigrationCommandResponse(
            ExitCode.SUCCESS, payload, envelope, _human("migrate inspect", payload)
        )
        return response
    except Exception as exc:
        return _error_response("migrate.inspect", exc)


def recover_migration(
    journal: Path,
    *,
    policy: Literal["auto", "resume", "rollback"] = "auto",
    dry_run: bool = False,
    reason: str | None = None,
    hooks: StorageMigrationHooks | None = None,
    project_root: Path | None = None,
) -> MigrationCommandResponse:
    """Implement ``ledgercore migrate recover`` with stable output models."""
    del reason  # Operator audit integration may persist it in its own receipt.
    try:
        recovered = recover_storage_migration(
            journal,
            policy=policy,
            dry_run=dry_run,
            hooks=hooks,
            project_root=project_root,
        )
        payload = _payload(recovered)
        command = "migrate recover"
        envelope = SuccessEnvelope(
            tool="ledgercore",
            command="migrate.recover",
            result=payload,
        )
        return MigrationCommandResponse(
            ExitCode.SUCCESS, payload, envelope, _human(command, payload)
        )
    except Exception as exc:
        return _error_response("migrate.recover", exc)


migrate_inspect = inspect_migration
migrate_recover = recover_migration
