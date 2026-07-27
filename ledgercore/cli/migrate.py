"""Framework-neutral migration protocol.

Memoryledger registers domain handlers. Ledgercore owns the lifecycle
vocabulary and shared storage migration adapter, not the domain
transformations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


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
