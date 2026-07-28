"""Explicit, verified Ledgercore storage migration planning and execution."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, cast

from tomlkit import dumps, parse, table

from ledgercore.atomic import atomic_write_text
from ledgercore.errors import StorageBindingError, StorageMigrationError
from ledgercore.layout import resolve_ledger_layout
from ledgercore.manifest import (
    LedgerLocalOverrides,
    LedgerProjectManifest,
    LoadedLedgerProject,
)
from ledgercore.storage_binding import (
    StorageBinding,
    read_storage_binding,
    storage_binding_diff,
    storage_binding_from_mapping,
    storage_binding_to_mapping,
    storage_bindings_match,
    write_storage_binding,
)
from ledgercore.time import utc_now_iso
from ledgercore.tomlio import (
    render_ledger_local_config,
    render_ledger_manifest,
)

MigrationStrategy = Literal["copy", "rebuild", "noop"]
MigrationMode = Literal["copy", "move"]
VerifyMode = Literal["sha256", "size"]
MigrationRecoveryCapability = Literal["completed-only", "manual-intervention"]

DestinationPolicy = Literal["create-only", "replace-owned", "noop-if-exact"]
DestinationKind = Literal["directory", "file"]

# Schema-3 top-level migration phases
MigrationPhase = Literal[
    "planned",
    "staging",
    "staged",
    "activating",
    "items-activated",
    "config-switching",
    "config-switched",
    "post-verifying",
    "committed",
    "cleaning-up",
    "complete",
    "rolling-back",
    "rolled-back",
    "failed",
]

# Schema-3 per-item states
MigrationItemState = Literal[
    "pending",
    "staging",
    "staged",
    "stage-verified",
    "backup-intent",
    "backup-created",
    "activation-intent",
    "activated",
    "post-verified",
    "rollback-intent",
    "rolled-back",
    "cleanup-pending",
    "complete",
]

# Legacy schema-2 phases (kept for backward compatibility)
_JOURNAL_PHASES = frozenset(
    {"planned", "copying", "verified", "config-switched", "complete", "failed"}
)
_JOURNAL_COMPONENTS = frozenset({"config", "mount"})
_JOURNAL_STRATEGIES = frozenset({"copy", "rebuild", "noop"})
_DESTINATION_POLICIES = frozenset({"create-only", "replace-owned", "noop-if-exact"})

# Schema-3 valid phase transitions
_PHASE_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"staging", "failed", "rolling-back"},
    "staging": {"staged", "failed", "rolling-back"},
    "staged": {"activating", "failed", "rolling-back"},
    "activating": {"items-activated", "failed", "rolling-back"},
    "items-activated": {"config-switching", "failed", "rolling-back"},
    "config-switching": {"config-switched", "failed", "rolling-back"},
    "config-switched": {"post-verifying", "failed", "rolling-back"},
    "post-verifying": {"committed", "failed", "rolling-back"},
    "committed": {"cleaning-up", "complete", "failed"},
    "cleaning-up": {"complete", "failed"},
    "complete": set(),
    "rolling-back": {"rolled-back", "failed"},
    "rolled-back": set(),
    "failed": {"staging", "activating", "config-switching", "rolling-back"},
}

# Schema-3 valid item state transitions
_ITEM_STATE_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"staging", "rollback-intent", "cleanup-pending", "complete"},
    "staging": {"staged", "rollback-intent"},
    "staged": {"stage-verified", "rollback-intent"},
    "stage-verified": {"backup-intent", "activation-intent", "rollback-intent"},
    "backup-intent": {"backup-created", "rollback-intent"},
    "backup-created": {"activation-intent", "rollback-intent"},
    "activation-intent": {"activated", "rollback-intent"},
    "activated": {"post-verified", "rollback-intent"},
    "post-verified": {"rollback-intent", "cleanup-pending"},
    "rollback-intent": {"rolled-back", "cleanup-pending"},
    "rolled-back": {"cleanup-pending"},
    "cleanup-pending": {"complete"},
    "complete": set(),
}


def _journal_invalid(message: str) -> StorageMigrationError:
    return StorageMigrationError(message, code="STORAGE_MIGRATION_JOURNAL_INVALID")


def _journal_string(
    document: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> str:
    value = document.get(field)
    if isinstance(value, bool) or not isinstance(value, str) or not value:
        raise _journal_invalid(f"{context} requires non-empty string {field}")
    return value


def _journal_item(
    row: Mapping[str, object],
    *,
    item_id: str,
    context: str,
    require_bindings: bool,
) -> StorageMigrationJournalItem:
    component = _journal_string(row, "component", context=context)
    if component not in _JOURNAL_COMPONENTS:
        raise _journal_invalid(f"{context} has invalid component {component!r}")
    tool_name = _journal_string(row, "tool", context=context)
    mount_name = _journal_string(row, "mount", context=context)
    source_text = _journal_string(row, "source", context=context)
    destination_text = _journal_string(row, "destination", context=context)
    strategy = _journal_string(row, "strategy", context=context)
    if strategy not in _JOURNAL_STRATEGIES:
        raise _journal_invalid(f"{context} has invalid strategy {strategy!r}")
    source_binding: StorageBinding | None = None
    destination_binding: StorageBinding | None = None
    if require_bindings:
        source_raw = row.get("source_binding")
        destination_raw = row.get("destination_binding")
        if not isinstance(source_raw, Mapping):
            raise _journal_invalid(f"{context} is missing source_binding")
        if not isinstance(destination_raw, Mapping):
            raise _journal_invalid(f"{context} is missing destination_binding")
        try:
            source_binding = storage_binding_from_mapping(
                source_raw, source=f"{context} source_binding"
            )
            destination_binding = storage_binding_from_mapping(
                destination_raw, source=f"{context} destination_binding"
            )
        except StorageBindingError as exc:
            raise _journal_invalid(f"{context} has invalid binding: {exc}") from exc
    return StorageMigrationJournalItem(
        item_id=item_id,
        component=cast(Literal["config", "mount"], component),
        tool_name=tool_name,
        mount_name=mount_name,
        source=Path(source_text),
        destination=Path(destination_text),
        strategy=cast(MigrationStrategy, strategy),
        source_binding=source_binding,
        destination_binding=destination_binding,
    )


@dataclass(frozen=True, slots=True)
class StorageFingerprint:
    algorithm: Literal["sha256-tree-v1", "sha256-file-v1"]
    digest: str
    file_count: int
    total_bytes: int

    @property
    def encoded(self) -> str:
        """Return a portable encoded representation: 'algorithm:digest'."""
        return f"{self.algorithm}:{self.digest}"

    def to_mapping(self) -> dict[str, object]:
        """Return the stable journal representation of this fingerprint."""
        return {
            "algorithm": self.algorithm,
            "digest": self.digest,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> StorageFingerprint:
        """Parse a fingerprint and reject malformed journal values."""
        algorithm = value.get("algorithm")
        digest = value.get("digest")
        file_count = value.get("file_count")
        total_bytes = value.get("total_bytes")
        if (
            algorithm not in {"sha256-tree-v1", "sha256-file-v1"}
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or isinstance(file_count, bool)
            or not isinstance(file_count, int)
            or file_count < 0
            or isinstance(total_bytes, bool)
            or not isinstance(total_bytes, int)
            or total_bytes < 0
        ):
            raise StorageMigrationError(
                "invalid storage fingerprint",
                code="STORAGE_MIGRATION_JOURNAL_INVALID",
            )
        return cls(cast(Any, algorithm), digest, file_count, total_bytes)


@dataclass(frozen=True, slots=True)
class StorageFingerprintEntry:
    relative_path: str
    kind: Literal["file", "directory"]
    sha256: str | None
    size: int | None


def _inventory_storage_directory(
    path: Path,
    *,
    ignored_relative_paths: frozenset[str] = frozenset({".ledger-project.toml"}),
) -> tuple[StorageFingerprintEntry, ...]:
    """Build a diagnostic inventory of a directory tree.

    Returns entries in POSIX-relative lexical order. Rejects symlinks
    and special files. Ignores the root .ledger-project.toml marker.
    """
    if not path.exists():
        raise StorageMigrationError(f"fingerprint target {path} does not exist")
    if path.is_symlink() or not path.is_dir():
        raise StorageMigrationError(
            f"fingerprint target {path} is not a regular directory"
        )
    entries: list[StorageFingerprintEntry] = []
    _walk_directory_for_inventory(path, path, entries, ignored_relative_paths)
    return tuple(entries)


def _walk_directory_for_inventory(
    root: Path,
    current: Path,
    entries: list[StorageFingerprintEntry],
    ignored_relative_paths: frozenset[str],
) -> None:
    """Recursively walk and collect directory/file entries."""
    children: list[Path] = []
    for child in current.iterdir():
        children.append(child)
    # POSIX-relative lexical order (case-sensitive)
    children.sort(key=lambda p: p.name)
    for child in children:
        rel = child.relative_to(root).as_posix()
        if current == root and child.name in ignored_relative_paths:
            continue
        if child.is_symlink():
            raise StorageMigrationError(f"fingerprint refuses symlink {child}")
        if child.is_dir():
            entries.append(
                StorageFingerprintEntry(
                    relative_path=rel,
                    kind="directory",
                    sha256=None,
                    size=None,
                )
            )
            _walk_directory_for_inventory(root, child, entries, ignored_relative_paths)
        elif child.is_file():
            raw = child.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            entries.append(
                StorageFingerprintEntry(
                    relative_path=rel,
                    kind="file",
                    sha256=digest,
                    size=len(raw),
                )
            )
        else:
            raise StorageMigrationError(f"fingerprint refuses special file {child}")


def fingerprint_storage_directory(
    path: Path,
    *,
    algorithm: str = "sha256",
    ignored_relative_paths: frozenset[str] = frozenset({".ledger-project.toml"}),
) -> StorageFingerprint:
    """Compute a deterministic sha256-tree-v1 fingerprint of a directory.

    The canonical stream encodes:
        D\\0<relative_path>\\0 for directories
        F\\0<relative_path>\\0<size>\\0<sha256>\\0 for files

    Paths are in POSIX relative form. Entries are sorted in POSIX-relative
    lexical order. Symlinks and special files are rejected.
    """
    if algorithm != "sha256":
        raise StorageMigrationError(
            f"unsupported fingerprint algorithm {algorithm!r}",
            code="STORAGE_MIGRATION_INVALID_ARGUMENT",
        )
    entries = _inventory_storage_directory(
        path, ignored_relative_paths=ignored_relative_paths
    )
    hasher = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for entry in entries:
        if entry.kind == "directory":
            hasher.update(f"D\0{entry.relative_path}\0".encode())
        else:
            assert entry.sha256 is not None
            assert entry.size is not None
            hasher.update(
                f"F\0{entry.relative_path}\0{entry.size}\0{entry.sha256}\0".encode()
            )
            file_count += 1
            total_bytes += entry.size
    return StorageFingerprint(
        algorithm="sha256-tree-v1",
        digest=hasher.hexdigest(),
        file_count=file_count,
        total_bytes=total_bytes,
    )


def fingerprint_storage_file(
    path: Path, *, algorithm: str = "sha256"
) -> StorageFingerprint:
    """Compute a deterministic sha256-file-v1 fingerprint of a regular file.

    The canonical representation is path-independent:
        F\\0<size>\\0<content-sha256>
    """
    if algorithm != "sha256":
        raise StorageMigrationError(
            f"unsupported fingerprint algorithm {algorithm!r}",
            code="STORAGE_MIGRATION_INVALID_ARGUMENT",
        )
    if not path.exists():
        raise StorageMigrationError(f"fingerprint target {path} does not exist")
    if path.is_symlink() or not path.is_file():
        raise StorageMigrationError(f"fingerprint target {path} is not a regular file")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    hasher = hashlib.sha256()
    hasher.update(f"F\\0{len(raw)}\\0{digest}".encode())
    return StorageFingerprint(
        algorithm="sha256-file-v1",
        digest=hasher.hexdigest(),
        file_count=1,
        total_bytes=len(raw),
    )


DestinationState = Literal["absent", "empty-unbound", "owned", "foreign", "invalid"]


@dataclass(frozen=True, slots=True)
class StorageDestinationInspection:
    state: DestinationState
    path: Path
    kind: DestinationKind
    binding: StorageBinding | None
    fingerprint: StorageFingerprint | None
    error: str | None = None


def inspect_storage_migration_destination(
    item: StorageMigrationItem | None = None,
    *,
    path: Path | None = None,
    kind: DestinationKind | None = None,
    expected_binding: StorageBinding | None = None,
    project_root: Path | None = None,
) -> StorageDestinationInspection:
    """Inspect a migration destination and classify its current state.

    For directories:
        - missing: absent
        - symlink or non-directory: invalid
        - empty and no marker: empty-unbound
        - nonempty without marker: invalid
        - marker mismatch: foreign
        - marker match: owned

    For config files:
        - inspect the parent directory binding and file type.
    """
    if item is not None:
        if path is not None or kind is not None or expected_binding is not None:
            raise StorageMigrationError(
                "destination inspection item conflicts with explicit arguments",
                code="STORAGE_MIGRATION_INVALID_ARGUMENT",
            )
        path = item.destination
        kind = item.destination_kind or (
            "file" if item.component == "config" else "directory"
        )
        expected_binding = item.destination_binding
    if path is None or kind is None or expected_binding is None:
        raise StorageMigrationError(
            "destination inspection requires an item or path, kind, and binding",
            code="STORAGE_MIGRATION_INVALID_ARGUMENT",
        )
    if project_root is not None and not path.is_absolute():
        path = project_root / path
    if kind == "file":
        return _inspect_config_destination(path, expected_binding)
    return _inspect_directory_destination(path, expected_binding)


def _inspect_directory_destination(
    path: Path,
    expected_binding: StorageBinding,
) -> StorageDestinationInspection:
    """Classify a directory destination."""
    if not path.exists():
        return StorageDestinationInspection(
            state="absent",
            path=path,
            kind="directory",
            binding=None,
            fingerprint=None,
        )
    if path.is_symlink() or not path.is_dir():
        return StorageDestinationInspection(
            state="invalid",
            path=path,
            kind="directory",
            binding=None,
            fingerprint=None,
            error=f"{path} is not a regular directory",
        )
    marker = path / ".ledger-project.toml"
    if not any(path.iterdir()):
        return StorageDestinationInspection(
            state="empty-unbound",
            path=path,
            kind="directory",
            binding=None,
            fingerprint=None,
        )
    if not marker.is_file() or marker.is_symlink():
        return StorageDestinationInspection(
            state="invalid",
            path=path,
            kind="directory",
            binding=None,
            fingerprint=None,
            error=f"{path} is non-empty and has no valid binding marker",
        )
    try:
        actual = read_storage_binding(marker)
    except StorageBindingError as exc:
        return StorageDestinationInspection(
            state="invalid",
            path=path,
            kind="directory",
            binding=None,
            fingerprint=None,
            error=str(exc),
        )
    if not storage_bindings_match(actual, expected_binding):
        return StorageDestinationInspection(
            state="foreign",
            path=path,
            kind="directory",
            binding=actual,
            fingerprint=None,
        )
    # Owned — compute fingerprint of content (excluding marker)
    try:
        fp = fingerprint_storage_directory(path)
    except StorageMigrationError as exc:
        return StorageDestinationInspection(
            state="invalid",
            path=path,
            kind="directory",
            binding=actual,
            fingerprint=None,
            error=f"fingerprint failed: {exc}",
        )
    return StorageDestinationInspection(
        state="owned",
        path=path,
        kind="directory",
        binding=actual,
        fingerprint=fp,
    )


def _inspect_config_destination(
    path: Path,
    expected_binding: StorageBinding,
) -> StorageDestinationInspection:
    """Classify a config file destination.

    Inspects parent binding even when file is absent.
    """
    parent = path.parent
    marker = parent / ".ledger-project.toml"

    # Check parent binding first, even if file is absent
    parent_binding: StorageBinding | None = None
    if marker.is_file() and not marker.is_symlink():
        try:
            parent_binding = read_storage_binding(marker)
        except StorageBindingError:
            parent_binding = None

    if not path.exists():
        if parent_binding is None:
            # No parent marker or invalid marker
            if marker.exists():
                return StorageDestinationInspection(
                    state="invalid",
                    path=path,
                    kind="file",
                    binding=None,
                    fingerprint=None,
                    error=f"parent {parent} has invalid binding marker",
                )
            return StorageDestinationInspection(
                state="absent",
                path=path,
                kind="file",
                binding=None,
                fingerprint=None,
            )
        if storage_bindings_match(parent_binding, expected_binding):
            return StorageDestinationInspection(
                state="absent",
                path=path,
                kind="file",
                binding=parent_binding,
                fingerprint=None,
            )
        return StorageDestinationInspection(
            state="foreign",
            path=path,
            kind="file",
            binding=parent_binding,
            fingerprint=None,
        )
    if path.is_symlink() or not path.is_file():
        return StorageDestinationInspection(
            state="invalid",
            path=path,
            kind="file",
            binding=None,
            fingerprint=None,
            error=f"{path} is not a regular file",
        )
    # For existing file, use already-resolved parent binding
    if parent_binding is None:
        return StorageDestinationInspection(
            state="invalid",
            path=path,
            kind="file",
            binding=None,
            fingerprint=None,
            error=f"parent {parent} has no valid binding marker",
        )
    if not storage_bindings_match(parent_binding, expected_binding):
        return StorageDestinationInspection(
            state="foreign",
            path=path,
            kind="file",
            binding=parent_binding,
            fingerprint=None,
        )
    try:
        fp = fingerprint_storage_file(path)
    except StorageMigrationError as exc:
        return StorageDestinationInspection(
            state="invalid",
            path=path,
            kind="file",
            binding=parent_binding,
            fingerprint=None,
            error=f"fingerprint failed: {exc}",
        )
    return StorageDestinationInspection(
        state="owned",
        path=path,
        kind="file",
        binding=parent_binding,
        fingerprint=fp,
    )


@dataclass(frozen=True, slots=True)
class DestinationPrecondition:
    """Expected state of a migration destination before activation."""

    state: Literal["absent", "empty-unbound", "owned"]
    fingerprint: StorageFingerprint | None = None


@dataclass(frozen=True)
class StorageMigrationItem:
    component: Literal["config", "mount"]
    tool_name: str
    mount_name: str
    source: Path
    destination: Path
    source_binding: StorageBinding
    destination_binding: StorageBinding
    strategy: MigrationStrategy
    destination_policy: DestinationPolicy = "create-only"
    expected_source_fingerprint: StorageFingerprint | None = None
    expected_before: DestinationPrecondition = DestinationPrecondition(state="absent")
    expected_target_fingerprint: StorageFingerprint | None = None
    destination_kind: DestinationKind | None = None


@dataclass(frozen=True)
class StorageMigrationJournalItem:
    item_id: str
    component: Literal["config", "mount"]
    tool_name: str
    mount_name: str
    source: Path
    destination: Path
    strategy: MigrationStrategy
    source_binding: StorageBinding | None = None
    destination_binding: StorageBinding | None = None


@dataclass(frozen=True)
class StorageMigrationPlan:
    migration_id: str
    project_uuid: str
    items: tuple[StorageMigrationItem, ...]
    config_changes: LedgerLocalOverrides | LedgerProjectManifest
    warnings: tuple[str, ...] = ()
    schema_version: int = 3
    project_root: Path | None = None
    config_switch_metadata: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class StorageMigrationItemValidation:
    item_index: int
    component: str
    mount_name: str
    policy: DestinationPolicy
    source_fingerprint: StorageFingerprint | None
    destination_fingerprint: StorageFingerprint | None
    action: Literal["noop", "create", "replace", "rebuild", "conflict"]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StorageMigrationPlanValidation:
    valid: bool
    items: tuple[StorageMigrationItemValidation, ...]
    errors: tuple[str, ...]
    structural_errors: tuple[str, ...] = ()
    source_precondition_errors: tuple[str, ...] = ()
    destination_precondition_errors: tuple[str, ...] = ()
    collisions: tuple[str, ...] = ()
    unsupported_strategies: tuple[str, ...] = ()
    filesystem_errors: tuple[str, ...] = ()
    no_op: bool = False


@dataclass(frozen=True)
class StorageMigrationResult:
    migration_id: str
    phase: str
    items_completed: int
    source_removed: bool | None
    journal_path: Path
    item_outcomes: tuple[Mapping[str, object], ...] = ()
    fingerprints: tuple[StorageFingerprint, ...] = ()
    config_switched: bool = False
    cleanup_complete: bool = False
    error_code: str | None = None
    recommendation: str | None = None


@dataclass(frozen=True)
class StorageMigrationJournal:
    migration_id: str
    phase: str
    project_uuid: str
    journal_path: Path
    items: tuple[StorageMigrationJournalItem, ...]
    error: str | None = None
    schema_version: int = 1
    mode: MigrationMode | None = None
    verify: VerifyMode | None = None
    project_root: Path | None = None
    items_completed: int | None = None
    source_removed: bool | None = None
    recovery_capability: MigrationRecoveryCapability = "manual-intervention"


@dataclass(frozen=True, slots=True)
class Schema3ItemJournalState:
    """Per-item journal state for schema-3 migrations."""

    item_index: int
    component: Literal["config", "mount"]
    tool_name: str
    mount_name: str
    source: Path
    destination: Path
    strategy: MigrationStrategy
    destination_policy: DestinationPolicy
    source_binding: StorageBinding | None = None
    destination_binding: StorageBinding | None = None
    expected_before_state: DestinationState | None = None
    state: MigrationItemState = "pending"
    source_fingerprint: StorageFingerprint | None = None
    expected_before_fingerprint: StorageFingerprint | None = None
    expected_target_fingerprint: StorageFingerprint | None = None
    staged_fingerprint: StorageFingerprint | None = None
    activated_fingerprint: StorageFingerprint | None = None
    stage_path: Path | None = None
    backup_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Schema3ConfigSwitchState:
    """Config switch state for schema-3 migrations."""

    kind: Literal["manifest", "local-overrides"]
    destination: Path
    state: Literal["pending", "staged", "activated", "rolled-back"] = "pending"
    expected_before_fingerprint: StorageFingerprint | None = None
    target_fingerprint: StorageFingerprint | None = None
    backup_path: Path | None = None
    error: str | None = None
    intent_written: bool = False
    applied: bool = False
    verified: bool = False
    previous_content: str | None = None
    target_content: str | None = None


@dataclass(frozen=True, slots=True)
class Schema3MigrationJournal:
    """Schema-3 migration journal."""

    migration_id: str
    project_uuid: str
    phase: MigrationPhase = "planned"
    mode: MigrationMode = "copy"
    verify: VerifyMode = "sha256"
    project_root: Path | None = None
    items: tuple[Schema3ItemJournalState, ...] = ()
    config_switches: tuple[Schema3ConfigSwitchState, ...] = ()
    error: str | None = None
    requires_staged_validation: bool = False
    requires_activated_validation: bool = False
    requires_finalization: bool = False
    cleanup_warnings: tuple[str, ...] = ()
    plan_digest: str | None = None
    lock_identity: Mapping[str, object] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    config_switch_state: Mapping[str, object] | None = None
    manual_intervention_reason: str | None = None
    quiescence_completed: bool = False
    staged_validated: tuple[int, ...] = ()
    activated_validated: tuple[int, ...] = ()
    finalized: bool = False

    @property
    def schema_version(self) -> int:
        return 3

    @property
    def items_completed(self) -> int:
        return sum(item.state == "complete" for item in self.items)

    @property
    def source_removed(self) -> bool:
        return False

    @property
    def recovery_capability(self) -> MigrationRecoveryCapability:
        if self.phase == "complete":
            return "completed-only"
        return "manual-intervention"


@dataclass(frozen=True, slots=True)
class RecoveryAssessment:
    """Non-mutating assessment of a schema-3 journal and its filesystem."""

    migration_id: str
    journal_path: Path
    phase: str
    item_states: tuple[MigrationItemState, ...]
    owned_paths: tuple[Path, ...]
    blockers: tuple[str, ...] = ()
    recommendation: Literal["resume", "rollback", "complete", "manual-intervention"] = (
        "manual-intervention"
    )
    resumable: bool = False
    rollbackable: bool = False
    complete: bool = False

    @property
    def requires_manual_intervention(self) -> bool:
        return self.recommendation == "manual-intervention"


def _binding(layout: Any, mount_name: str, storage: str) -> StorageBinding:
    return StorageBinding(
        schema_version=1,
        layout_version=3,
        project_uuid=layout.project_uuid,
        project_name=None,
        tool=layout.ledger_name,
        mount=mount_name,
        storage=cast(Literal["project", "external", "user-data", "cache"], storage),
    )


@dataclass(frozen=True, slots=True)
class StorageMigrationHooks:
    """Hooks for migration lifecycle events."""

    quiescence_check: Callable[[], None] | None = None
    validate_staged: Callable[[int], None] | None = None
    validate_activated: Callable[[int], None] | None = None
    finalize: Callable[[], None] | None = None
    requires_staged_validation: bool = False
    requires_activated_validation: bool = False
    requires_finalization: bool = False

    def validate_requirements(self) -> None:
        """Validate required callback presence before filesystem mutation."""
        required = (
            (self.requires_staged_validation, self.validate_staged, "validate_staged"),
            (
                self.requires_activated_validation,
                self.validate_activated,
                "validate_activated",
            ),
            (self.requires_finalization, self.finalize, "finalize"),
        )
        for enabled, callback, name in required:
            if enabled and callback is None:
                raise StorageMigrationError(
                    f"required migration hook {name} is not provided",
                    code="STORAGE_MIGRATION_HOOK_REQUIRED",
                )


def _validate_source(
    path: Path, expected: StorageBinding, *, required: bool
) -> StorageBinding | None:
    if not path.exists():
        if required:
            raise StorageMigrationError(f"migration source {path} is missing")
        return None
    if path.is_symlink() or not path.is_dir():
        raise StorageMigrationError(
            f"migration source {path} is not a regular directory"
        )
    marker = path / ".ledger-project.toml"
    if not marker.is_file() or marker.is_symlink():
        raise StorageMigrationError(
            f"migration source {path} has no regular binding marker"
        )
    try:
        actual = read_storage_binding(marker)
    except StorageBindingError as exc:
        raise StorageMigrationError(
            f"invalid migration source binding {marker}: {exc}"
        ) from exc
    if not storage_bindings_match(actual, expected):
        diff = storage_binding_diff(actual, expected)
        raise StorageMigrationError(
            f"migration source binding mismatch at {marker}: "
            f"differences={diff['differences']}"
        )
    return actual


def _validate_destination(path: Path, expected: StorageBinding) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise StorageMigrationError(
            f"migration destination {path} is not a regular directory"
        )
    marker = path / ".ledger-project.toml"
    if not any(path.iterdir()):
        return
    if not marker.is_file() or marker.is_symlink():
        raise StorageMigrationError(
            f"migration destination {path} is non-empty and unbound"
        )
    actual = read_storage_binding(marker)
    if not storage_bindings_match(actual, expected):
        diff = storage_binding_diff(actual, expected)
        raise StorageMigrationError(
            f"migration destination binding mismatch at {marker}: "
            f"differences={diff['differences']}"
        )


def _file_binding(layout: Any) -> StorageBinding:
    return _binding(layout, "config", "project")


def plan_storage_migration(
    current: LoadedLedgerProject,
    target_manifest: LedgerProjectManifest,
    target_overrides: LedgerLocalOverrides,
    tool_name: str,
    *,
    mounts: tuple[str, ...] | None = None,
    include_config: bool = False,
    cache_strategy: Literal["copy", "rebuild"] = "rebuild",
) -> StorageMigrationPlan:
    """Build a migration plan without creating or changing any filesystem entry."""
    if cache_strategy not in {"copy", "rebuild"}:
        raise StorageMigrationError(f"unsupported cache strategy {cache_strategy!r}")
    current_layout = resolve_ledger_layout(
        current.locator,
        current.manifest,
        tool_name,
        local_overrides=current.local_overrides,
    )
    target_layout = resolve_ledger_layout(
        current.locator,
        target_manifest,
        tool_name,
        local_overrides=target_overrides,
    )
    wanted = set(mounts or target_layout.mounts)
    unknown = wanted - set(current_layout.mounts) - set(target_layout.mounts)
    if unknown:
        raise StorageMigrationError(f"unknown migration mount {sorted(unknown)[0]!r}")
    items: list[StorageMigrationItem] = []
    warnings: list[str] = []
    for mount_name in sorted(wanted):
        if (
            mount_name not in current_layout.mounts
            or mount_name not in target_layout.mounts
        ):
            raise StorageMigrationError(
                f"mount {mount_name!r} must exist in both layouts"
            )
        source_mount = current_layout.mounts[mount_name]
        destination_mount = target_layout.mounts[mount_name]
        source = source_mount.path
        destination = destination_mount.path
        source_binding = _binding(current_layout, mount_name, source_mount.storage)
        destination_binding = _binding(
            target_layout, mount_name, destination_mount.storage
        )
        if source == destination:
            strategy: MigrationStrategy = "noop"
            actual = source_binding
            source_fp = None
        else:
            strategy = (
                "rebuild"
                if destination_mount.storage == "cache" and cache_strategy == "rebuild"
                else "copy"
            )
            actual = (
                _validate_source(source, source_binding, required=strategy == "copy")
                or source_binding
            )
            _validate_destination(destination, destination_binding)
            # Compute source fingerprint for copy strategy
            if strategy == "copy" and source.is_dir():
                source_fp = fingerprint_storage_directory(source)
            else:
                source_fp = None
        items.append(
            StorageMigrationItem(
                component="mount",
                tool_name=tool_name,
                mount_name=mount_name,
                source=source,
                destination=destination,
                source_binding=actual,
                destination_binding=destination_binding,
                strategy=strategy,
                expected_source_fingerprint=source_fp,
            )
        )
    if include_config:
        config_source = current_layout.tool_config_path
        config_destination = target_layout.tool_config_path
        if config_source is None or config_destination is None:
            raise StorageMigrationError("config migration requires both config paths")
        source = config_source
        destination = config_destination
        source_binding = _file_binding(current_layout)
        destination_binding = _file_binding(target_layout)
        if source == destination:
            strategy = "noop"
            source_fp = None
        else:
            if not source.is_file() or source.is_symlink():
                raise StorageMigrationError(
                    f"config migration source {source} is not a regular file"
                )
            _validate_destination(destination.parent, destination_binding)
            strategy = "copy"
            source_fp = fingerprint_storage_file(source)
        items.insert(
            0,
            StorageMigrationItem(
                component="config",
                tool_name=tool_name,
                mount_name="config",
                source=source,
                destination=destination,
                source_binding=source_binding,
                destination_binding=destination_binding,
                strategy=strategy,
                expected_source_fingerprint=source_fp,
            ),
        )
    if any(item.strategy == "rebuild" for item in items):
        warnings.append("cache mounts use rebuild strategy by default")
    return StorageMigrationPlan(
        migration_id=uuid.uuid4().hex,
        project_uuid=target_manifest.project_uuid,
        items=tuple(items),
        config_changes=target_overrides,
        warnings=tuple(warnings),
    )


def _validate_plan_item(
    item: StorageMigrationItem,
    item_index: int,
    project_root: Path,
) -> StorageMigrationItemValidation:
    """Validate a single migration item against its destination policy."""
    errors: list[str] = []
    action: Literal["noop", "create", "replace", "rebuild", "conflict"] = "create"
    dest_fp: StorageFingerprint | None = None

    # Reject project-root and .ledger replacement
    resolved_dest = item.destination.resolve()
    resolved_root = project_root.resolve()
    if resolved_dest == resolved_root:
        errors.append(
            f"item {item_index}: destination {item.destination} is the project root"
        )
        return StorageMigrationItemValidation(
            item_index=item_index,
            component=item.component,
            mount_name=item.mount_name,
            policy=item.destination_policy,
            source_fingerprint=None,
            destination_fingerprint=None,
            action="conflict",
            errors=tuple(errors),
        )
    ledger_dir = resolved_root / ".ledger"
    if resolved_dest == ledger_dir:
        errors.append(
            f"item {item_index}: destination "
            f"{item.destination} is the .ledger directory"
        )
        return StorageMigrationItemValidation(
            item_index=item_index,
            component=item.component,
            mount_name=item.mount_name,
            policy=item.destination_policy,
            source_fingerprint=None,
            destination_fingerprint=None,
            action="conflict",
            errors=tuple(errors),
        )

    inspection = inspect_storage_migration_destination(
        path=item.destination,
        kind=item.destination_kind
        or ("file" if item.component == "config" else "directory"),
        expected_binding=item.destination_binding,
    )
    dest_fp = inspection.fingerprint

    policy = item.destination_policy

    if inspection.state == "foreign":
        errors.append(
            f"item {item_index}: destination is foreign"
            " (bound to different project/tool/mount)"
        )
        action = "conflict"
    elif inspection.state == "invalid":
        errors.append(f"item {item_index}: destination is invalid: {inspection.error}")
        action = "conflict"
    elif policy == "create-only":
        if inspection.state in ("owned",):
            errors.append(
                f"item {item_index}: create-only policy rejects owned destination"
            )
            action = "conflict"
        elif inspection.state == "empty-unbound":
            action = "create"
        elif inspection.state == "absent":
            action = "create"
    elif policy == "replace-owned":
        if (
            item.expected_before.state != "owned"
            or item.expected_before.fingerprint is None
        ):
            errors.append(
                f"item {item_index}: replace-owned requires"
                " expected_before.state='owned' and expected_before.fingerprint"
            )
            action = "conflict"
        elif inspection.state != "owned":
            errors.append(
                f"item {item_index}: replace-owned requires owned destination, "
                f"got {inspection.state}"
            )
            action = "conflict"
        elif (
            dest_fp is not None
            and dest_fp.encoded != item.expected_before.fingerprint.encoded
        ):
            errors.append(
                f"item {item_index}: destination fingerprint changed; "
                f"expected {item.expected_before.fingerprint.encoded}, "
                f"actual {dest_fp.encoded}"
            )
            action = "conflict"
        else:
            action = "replace"
    elif policy == "noop-if-exact":
        if item.expected_target_fingerprint is None:
            errors.append(
                f"item {item_index}: noop-if-exact requires expected_target_fingerprint"
            )
            action = "conflict"
        elif inspection.state == "absent":
            errors.append(
                f"item {item_index}: noop-if-exact requires existing destination"
            )
            action = "conflict"
        elif (
            dest_fp is not None
            and dest_fp.encoded == item.expected_target_fingerprint.encoded
        ):
            action = "noop"
        else:
            errors.append(
                f"item {item_index}: noop-if-exact destination differs from expected"
            )
            action = "conflict"

    # For rebuild strategy, override action
    if item.strategy == "rebuild" and not errors:
        action = "rebuild"

    return StorageMigrationItemValidation(
        item_index=item_index,
        component=item.component,
        mount_name=item.mount_name,
        policy=policy,
        source_fingerprint=None,
        destination_fingerprint=dest_fp,
        action=action,
        errors=tuple(errors),
    )


def _check_path_overlaps(
    items: tuple[StorageMigrationItem, ...],
    project_root: Path,
    migration_id: str,
) -> tuple[str, ...]:
    """Check for path overlaps between items. Returns error messages."""
    errors: list[str] = []
    resolved_root = project_root.resolve()

    # Collect all paths
    destinations: list[tuple[int, Path]] = []
    for i, item in enumerate(items):
        destinations.append((i, item.destination.resolve()))

    # A copy-only migration cannot safely use a source path as, or below,
    # another item's activation target. This also prevents a source from being
    # changed by a sibling activation while it is being copied.
    sources = [(i, item.source.resolve()) for i, item in enumerate(items)]
    for source_index, source in sources:
        for dest_index, destination in destinations:
            if source_index == dest_index and source == destination:
                continue
            if (
                source == destination
                or source.is_relative_to(destination)
                or destination.is_relative_to(source)
            ):
                errors.append(
                    f"item {source_index} source {source} aliases item "
                    f"{dest_index} destination {destination}"
                )

    # Check destination overlaps
    for i, (_, dest_a) in enumerate(destinations):
        for j, (_, dest_b) in enumerate(destinations):
            if i >= j:
                continue
            if dest_a == dest_b:
                errors.append(f"items {i} and {j} have the same destination {dest_a}")
            elif dest_a.is_relative_to(dest_b):
                errors.append(
                    f"item {i} destination {dest_a}"
                    f" is inside item {j} destination {dest_b}"
                )
            elif dest_b.is_relative_to(dest_a):
                errors.append(
                    f"item {j} destination {dest_b}"
                    f" is inside item {i} destination {dest_a}"
                )

    # Check for project-root and .ledger replacement
    # (redundant with per-item check, but belt-and-suspenders)
    for i, item in enumerate(items):
        resolved = item.destination.resolve()
        if resolved == resolved_root:
            errors.append(f"item {i}: destination is the project root")
        if resolved == resolved_root / ".ledger":
            errors.append(f"item {i}: destination is the .ledger directory")

    # Check stage/backup path collisions
    all_generated: list[tuple[str, int, Path]] = []
    for i, item in enumerate(items):
        item_paths = _prepare_item_paths(item.destination, migration_id, i)
        all_generated.append(("stage", i, item_paths.stage.resolve()))
        all_generated.append(("backup", i, item_paths.backup.resolve()))

    for a_idx, (a_kind, a_item, a_path) in enumerate(all_generated):
        for b_kind, b_item, b_path in all_generated[a_idx + 1 :]:
            if a_path == b_path:
                errors.append(
                    f"{a_kind} path for item {a_item} conflicts with"
                    f" {b_kind} path for item {b_item}: {a_path}"
                )
            elif a_path.is_relative_to(b_path) or b_path.is_relative_to(a_path):
                errors.append(
                    f"{a_kind} path for item {a_item} overlaps with"
                    f" {b_kind} path for item {b_item}: {a_path} vs {b_path}"
                )

    return tuple(errors)


def _validate_plan_structure(
    plan: StorageMigrationPlan,
) -> tuple[str, ...]:
    """Validate plan structure before filesystem inspection.

    Returns error messages for structural issues.
    """
    errors: list[str] = []

    # Validate migration_id (must be a valid hex string, no path separators)
    if not plan.migration_id:
        errors.append("migration_id is empty")
    elif "/" in plan.migration_id or "\\" in plan.migration_id:
        errors.append(f"migration_id contains path separators: {plan.migration_id!r}")
    elif len(plan.migration_id) < 8:
        errors.append(f"migration_id is too short: {plan.migration_id!r}")

    # Validate project_uuid
    if not plan.project_uuid:
        errors.append("project_uuid is empty")

    # Validate each item structure
    seen_identities: set[tuple[str, str, str]] = set()
    for i, item in enumerate(plan.items):
        # Validate component
        if item.component not in ("config", "mount"):
            errors.append(f"item {i}: unknown component {item.component!r}")

        # Validate strategy
        if item.strategy not in ("copy", "rebuild", "noop"):
            errors.append(f"item {i}: unknown strategy {item.strategy!r}")

        # Validate destination_policy
        if item.destination_policy not in (
            "create-only",
            "replace-owned",
            "noop-if-exact",
        ):
            errors.append(
                f"item {i}: unknown destination_policy {item.destination_policy!r}"
            )

        # Validate destination_kind if set
        if item.destination_kind is not None and item.destination_kind not in (
            "directory",
            "file",
        ):
            errors.append(
                f"item {i}: unknown destination_kind {item.destination_kind!r}"
            )

        if item.expected_before.state not in {"absent", "empty-unbound", "owned"}:
            errors.append(f"item {i}: invalid expected destination state")
        if (
            item.expected_before.state == "owned"
            and item.expected_before.fingerprint is None
        ):
            errors.append(f"item {i}: owned destination requires a fingerprint")

        # Validate tool_name and mount_name are not empty
        if not item.tool_name:
            errors.append(f"item {i}: tool_name is empty")
        if not item.mount_name:
            errors.append(f"item {i}: mount_name is empty")

        # Check for duplicate identities
        identity = (item.component, item.tool_name, item.mount_name)
        if identity in seen_identities:
            errors.append(f"item {i}: duplicate identity {identity}")
        seen_identities.add(identity)

        # Validate paths are absolute
        if not item.source.is_absolute():
            errors.append(f"item {i}: source path is not absolute: {item.source}")
        if not item.destination.is_absolute():
            errors.append(
                f"item {i}: destination path is not absolute: {item.destination}"
            )

    return tuple(errors)


def validate_storage_migration_plan(
    plan: StorageMigrationPlan,
    *,
    project_root: Path | None = None,
) -> StorageMigrationPlanValidation:
    """Perform side-effect-free validation of a migration plan.

    Validates destination policies, fingerprints, bindings, and path overlaps
    without creating or modifying any filesystem entry.
    """
    root = (project_root or Path.cwd()).resolve(strict=False)
    all_errors: list[str] = []
    item_validations: list[StorageMigrationItemValidation] = []

    # Validate plan structure first (before filesystem inspection)
    structure_errors = _validate_plan_structure(plan)
    all_errors.extend(structure_errors)

    # Validate each item
    for i, item in enumerate(plan.items):
        item_val = _validate_plan_item(item, i, root)
        item_validations.append(item_val)
        all_errors.extend(item_val.errors)

    # Check path overlaps
    overlap_errors = _check_path_overlaps(plan.items, root, plan.migration_id)
    all_errors.extend(overlap_errors)

    return StorageMigrationPlanValidation(
        valid=len(all_errors) == 0,
        items=tuple(item_validations),
        errors=tuple(all_errors),
    )


def _hash_tree(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in sorted(path.rglob("*")):
        if child.name == ".ledger-project.toml":
            continue
        if child.is_symlink():
            raise StorageMigrationError(f"migration refuses symlink {child}")
        if child.is_file():
            digest = hashlib.sha256(child.read_bytes()).hexdigest()
            values[child.relative_to(path).as_posix()] = digest
    return values


def _check_same_filesystem(path_a: Path, path_b: Path) -> bool:
    """Check if two paths are on the same filesystem."""
    try:
        stat_a = path_a.stat()
        stat_b = path_b.stat()
        return stat_a.st_dev == stat_b.st_dev
    except OSError:
        return False


def _validate_same_filesystem(
    destination: Path,
    stage: Path,
    backup: Path,
    item_index: int,
) -> None:
    """Validate that destination, stage, and backup are on the same filesystem.

    Raises StorageMigrationError if cross-filesystem activation would be required.
    """
    dest_parent = destination.parent
    stage_parent = stage.parent
    backup_parent = backup.parent

    if not _check_same_filesystem(dest_parent, stage_parent):
        raise StorageMigrationError(
            f"item {item_index}: stage path {stage} is on a different filesystem"
            f" than destination {destination}",
            code="STORAGE_MIGRATION_CROSS_FILESYSTEM",
        )
    if not _check_same_filesystem(dest_parent, backup_parent):
        raise StorageMigrationError(
            f"item {item_index}: backup path {backup} is on a different filesystem"
            f" than destination {destination}",
            code="STORAGE_MIGRATION_CROSS_FILESYSTEM",
        )


def _durable_rename(source: Path, destination: Path) -> None:
    """Perform a durable rename with directory fsync.

    This ensures the rename is persisted to disk, including the parent directory.
    """
    source.rename(destination)
    # Fsync the parent directory to ensure the rename is durable
    try:
        parent_fd = os.open(str(destination.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        # Best-effort: some filesystems may not support directory fsync
        pass


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for child in source.iterdir():
        if child.name == ".ledger-project.toml":
            continue
        target = destination / child.name
        if child.is_symlink():
            raise StorageMigrationError(f"migration refuses symlink {child}")
        if child.is_dir():
            _copy_tree(child, target)
        elif child.is_file():
            shutil.copy2(child, target)
        else:
            raise StorageMigrationError(f"migration refuses special file {child}")


@dataclass(frozen=True, slots=True)
class MigrationItemPaths:
    stage: Path
    stage_root: Path | None
    backup: Path


def _prepare_item_paths(
    destination: Path,
    migration_id: str,
    item_index: int,
) -> MigrationItemPaths:
    """Derive deterministic stage and backup paths for a migration item.

    Naming convention:
        stage: .<destination-name>.migrating-<migration-id>-<item-index>
        backup: .<destination-name>.backup-<migration-id>-<item-index>
    """
    dest_name = destination.name
    parent = destination.parent
    suffix = f"{migration_id}-{item_index}"
    stage = parent / f".{dest_name}.migrating-{suffix}"
    backup = parent / f".{dest_name}.backup-{suffix}"
    return MigrationItemPaths(stage=stage, stage_root=None, backup=backup)


def _staging_path(
    source: Path, destination: Path, migration_id: str
) -> tuple[Path, Path | None]:
    """Return a staging path that never lives below an ancestor source."""
    if destination != source and destination.is_relative_to(source):
        staging_root = source.parent / f"{source.name}.migrating-{migration_id}"
        return staging_root / destination.relative_to(source), staging_root
    if source != destination and source.is_relative_to(destination):
        raise StorageMigrationError(
            "migration destination is an ancestor of its source; "
            "use an outside staging target"
        )
    return destination.with_name(f".{destination.name}.migrating-{migration_id}"), None


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink() or not source.is_file():
        raise StorageMigrationError(
            f"migration refuses non-regular config source {source}"
        )
    shutil.copy2(source, destination)


def _journal_path(plan: StorageMigrationPlan, project_root: Path) -> Path:
    return project_root / ".ledger" / "migrations" / f"{plan.migration_id}.toml"


def _canonical_value(value: object) -> object:
    """Convert plan values to a deterministic JSON-compatible structure."""
    if isinstance(value, Path):
        return str(value.resolve(strict=False))
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        values = [_canonical_value(item) for item in value]
        if isinstance(value, (set, frozenset)):
            values.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return values
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _canonical_value(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        enum_value = value.value
        if enum_value is not value:
            return _canonical_value(enum_value)
    return value


def storage_migration_plan_digest(plan: StorageMigrationPlan) -> str:
    """Return the stable SHA-256 digest persisted in schema-3 journals."""
    payload = {
        "schema_version": plan.schema_version,
        "migration_id": plan.migration_id,
        "project_uuid": plan.project_uuid,
        "project_root": _canonical_value(plan.project_root),
        "items": _canonical_value(plan.items),
        "config_changes": _canonical_value(plan.config_changes),
        "config_switch_metadata": _canonical_value(plan.config_switch_metadata),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _schema3_item_from_plan(
    item: StorageMigrationItem,
    index: int,
    paths: MigrationItemPaths,
) -> Schema3ItemJournalState:
    return Schema3ItemJournalState(
        item_index=index,
        component=item.component,
        tool_name=item.tool_name,
        mount_name=item.mount_name,
        source=item.source.resolve(strict=False),
        destination=item.destination.resolve(strict=False),
        strategy=item.strategy,
        destination_policy=item.destination_policy,
        source_binding=item.source_binding,
        destination_binding=item.destination_binding,
        expected_before_state=item.expected_before.state,
        source_fingerprint=item.expected_source_fingerprint,
        expected_before_fingerprint=item.expected_before.fingerprint,
        expected_target_fingerprint=item.expected_target_fingerprint,
        stage_path=paths.stage.resolve(strict=False),
        backup_path=paths.backup.resolve(strict=False),
    )


def _schema3_journal_from_plan(
    plan: StorageMigrationPlan,
    *,
    root: Path,
    mode: MigrationMode,
    verify: VerifyMode,
    hooks: StorageMigrationHooks,
) -> Schema3MigrationJournal:
    items = tuple(
        _schema3_item_from_plan(
            item, index, _prepare_item_paths(item.destination, plan.migration_id, index)
        )
        for index, item in enumerate(plan.items)
    )
    now = utc_now_iso()
    return Schema3MigrationJournal(
        migration_id=plan.migration_id,
        project_uuid=plan.project_uuid,
        phase="planned",
        mode=mode,
        verify=verify,
        project_root=root.resolve(strict=False),
        items=items,
        requires_staged_validation=hooks.requires_staged_validation,
        requires_activated_validation=hooks.requires_activated_validation,
        requires_finalization=hooks.requires_finalization,
        plan_digest=storage_migration_plan_digest(plan),
        lock_identity={
            "migration_id": plan.migration_id,
            "owner": "ledgercore",
            "pid": os.getpid(),
        },
        created_at=now,
        updated_at=now,
    )


def _persist_schema3(journal: Schema3MigrationJournal, path: Path) -> None:
    """Persist one complete schema-3 transition atomically and durably."""
    updated = replace(journal, updated_at=utc_now_iso())
    write_schema3_journal(updated, path)


def _transition_phase(
    journal: Schema3MigrationJournal,
    phase: MigrationPhase,
) -> Schema3MigrationJournal:
    if phase == journal.phase:
        return journal
    allowed = _PHASE_TRANSITIONS.get(journal.phase, set())
    if phase not in allowed:
        raise StorageMigrationError(
            f"invalid migration phase transition {journal.phase!r} -> {phase!r}",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        )
    return replace(journal, phase=phase)


def _transition_item(
    journal: Schema3MigrationJournal,
    item_index: int,
    state: MigrationItemState,
    **changes: Any,
) -> Schema3MigrationJournal:
    items = list(journal.items)
    try:
        current = items[item_index]
    except IndexError as exc:
        raise StorageMigrationError(
            f"unknown migration item {item_index}",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        ) from exc
    if state != current.state and state not in _ITEM_STATE_TRANSITIONS.get(
        current.state, set()
    ):
        raise StorageMigrationError(
            f"invalid item {item_index} state transition "
            f"{current.state!r} -> {state!r}",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        )
    items[item_index] = replace(current, state=state, **changes)
    return replace(journal, items=tuple(items))


def _write_journal(
    plan: StorageMigrationPlan,
    path: Path,
    *,
    phase: str,
    mode: MigrationMode,
    verify: VerifyMode,
    project_root: Path,
    items_completed: int,
    source_removed: bool,
    error: str | None = None,
) -> None:
    doc = table()
    doc.add("schema_version", 2)
    doc.add("migration_id", plan.migration_id)
    doc.add("project_uuid", plan.project_uuid)
    doc.add("phase", phase)
    doc.add("mode", mode)
    doc.add("verify", verify)
    doc.add("project_root", str(project_root))
    doc.add("items_completed", items_completed)
    doc.add("source_removed", source_removed)
    if error is not None:
        doc.add("error", error)
    items = table()
    for index, item in enumerate(plan.items):
        row = table()
        row.add("component", item.component)
        row.add("tool", item.tool_name)
        row.add("mount", item.mount_name)
        row.add("source", str(item.source))
        row.add("destination", str(item.destination))
        row.add("strategy", item.strategy)
        src_map = storage_binding_to_mapping(item.source_binding)
        row.add("source_binding", table())
        for k, v in src_map.items():
            row["source_binding"].add(k, v)
        dst_map = storage_binding_to_mapping(item.destination_binding)
        row.add("destination_binding", table())
        for k, v in dst_map.items():
            row["destination_binding"].add(k, v)
        items.add(str(index), row)
    doc.add("items", items)
    text = dumps(doc)
    if not text.endswith("\n"):
        text += "\n"
    atomic_write_text(path, text)


def _fingerprint_to_toml(fp: StorageFingerprint | None) -> dict[str, Any] | None:
    """Convert a StorageFingerprint to a TOML-compatible dict."""
    if fp is None:
        return None
    return {
        "algorithm": fp.algorithm,
        "digest": fp.digest,
        "file_count": fp.file_count,
        "total_bytes": fp.total_bytes,
    }


def _fingerprint_from_toml(data: dict[str, Any] | None) -> StorageFingerprint | None:
    """Parse a StorageFingerprint from a TOML dict."""
    if data is None:
        return None
    try:
        return StorageFingerprint.from_mapping(data)
    except (KeyError, TypeError, StorageMigrationError) as exc:
        raise _journal_invalid("invalid fingerprint record") from exc


def _binding_to_toml(binding: StorageBinding | None) -> Any:
    if binding is None:
        return None
    result = table()
    for key, value in storage_binding_to_mapping(binding).items():
        result.add(key, value)
    return result


def _binding_from_toml(value: object, *, context: str) -> StorageBinding | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _journal_invalid(f"{context} binding must be a table")
    try:
        return storage_binding_from_mapping(value, source=context)
    except StorageBindingError as exc:
        raise _journal_invalid(f"{context} has invalid binding: {exc}") from exc


def _serialize_journal_item(item: Schema3ItemJournalState) -> Any:
    """Serialize a single migration journal item to a TOML table."""
    row = table()
    row.add("item_index", item.item_index)
    row.add("component", item.component)
    row.add("tool_name", item.tool_name)
    row.add("mount_name", item.mount_name)
    row.add("source", str(item.source))
    row.add("destination", str(item.destination))
    row.add("strategy", item.strategy)
    row.add("destination_policy", item.destination_policy)
    row.add("state", item.state)
    if item.source_binding is not None:
        row.add("source_binding", _binding_to_toml(item.source_binding))
    if item.destination_binding is not None:
        row.add("destination_binding", _binding_to_toml(item.destination_binding))
    if item.expected_before_state is not None:
        row.add("expected_before_state", item.expected_before_state)

    if item.source_fingerprint is not None:
        row.add("source_fingerprint", _fingerprint_to_toml(item.source_fingerprint))
    if item.expected_before_fingerprint is not None:
        row.add(
            "expected_before_fingerprint",
            _fingerprint_to_toml(item.expected_before_fingerprint),
        )
    if item.expected_target_fingerprint is not None:
        row.add(
            "expected_target_fingerprint",
            _fingerprint_to_toml(item.expected_target_fingerprint),
        )
    if item.staged_fingerprint is not None:
        row.add("staged_fingerprint", _fingerprint_to_toml(item.staged_fingerprint))
    if item.activated_fingerprint is not None:
        row.add(
            "activated_fingerprint",
            _fingerprint_to_toml(item.activated_fingerprint),
        )
    if item.stage_path is not None:
        row.add("stage_path", str(item.stage_path))
    if item.backup_path is not None:
        row.add("backup_path", str(item.backup_path))
    if item.error is not None:
        row.add("error", item.error)
    return row


def _serialize_config_switch(sw: Schema3ConfigSwitchState) -> Any:
    """Serialize a single config switch to a TOML table."""
    row = table()
    row.add("kind", sw.kind)
    row.add("destination", str(sw.destination))
    row.add("state", sw.state)
    if sw.expected_before_fingerprint is not None:
        row.add(
            "expected_before_fingerprint",
            _fingerprint_to_toml(sw.expected_before_fingerprint),
        )
    if sw.target_fingerprint is not None:
        row.add("target_fingerprint", _fingerprint_to_toml(sw.target_fingerprint))
    if sw.backup_path is not None:
        row.add("backup_path", str(sw.backup_path))
    if sw.error is not None:
        row.add("error", sw.error)
    row.add("intent_written", sw.intent_written)
    row.add("applied", sw.applied)
    row.add("verified", sw.verified)
    if sw.previous_content is not None:
        row.add("previous_content", sw.previous_content)
    if sw.target_content is not None:
        row.add("target_content", sw.target_content)
    return row


def write_schema3_journal(
    journal: Schema3MigrationJournal,
    path: Path,
) -> None:
    """Write a schema-3 migration journal to a TOML file."""
    doc = table()
    doc.add("schema_version", 3)
    doc.add("migration_id", journal.migration_id)
    doc.add("project_uuid", journal.project_uuid)
    doc.add("phase", journal.phase)
    doc.add("mode", journal.mode)
    doc.add("verify", journal.verify)
    if journal.project_root is not None:
        doc.add("project_root", str(journal.project_root))
    if journal.error is not None:
        doc.add("error", journal.error)
    doc.add("requires_staged_validation", journal.requires_staged_validation)
    doc.add("requires_activated_validation", journal.requires_activated_validation)
    doc.add("requires_finalization", journal.requires_finalization)
    doc.add("quiescence_completed", journal.quiescence_completed)
    doc.add("staged_validated", list(journal.staged_validated))
    doc.add("activated_validated", list(journal.activated_validated))
    doc.add("finalized", journal.finalized)
    if journal.plan_digest is not None:
        doc.add("plan_digest", journal.plan_digest)
    if journal.lock_identity:
        lock = table()
        for key, value in journal.lock_identity.items():
            lock.add(key, value)
        doc.add("lock_identity", lock)
    if journal.created_at is not None:
        doc.add("created_at", journal.created_at)
    if journal.updated_at is not None:
        doc.add("updated_at", journal.updated_at)
    if journal.config_switch_state is not None:
        switch_state = table()
        for key, value in journal.config_switch_state.items():
            switch_state.add(key, value)
        doc.add("config_switch_state", switch_state)
    if journal.manual_intervention_reason is not None:
        doc.add("manual_intervention_reason", journal.manual_intervention_reason)
    if journal.cleanup_warnings:
        warnings = table()
        for i, w in enumerate(journal.cleanup_warnings):
            warnings.add(str(i), w)
        doc.add("cleanup_warnings", warnings)

    # Write items
    items = table()
    for item in journal.items:
        items.add(str(item.item_index), _serialize_journal_item(item))
    doc.add("items", items)

    # Write config switches
    if journal.config_switches:
        switches = table()
        for i, sw in enumerate(journal.config_switches):
            switches.add(str(i), _serialize_config_switch(sw))
        doc.add("config_switches", switches)

    text = dumps(doc)
    if not text.endswith("\n"):
        text += "\n"
    atomic_write_text(path, text)


def _parse_schema3_journal(  # noqa: C901
    document: Mapping[str, object],
    journal_path: Path,
) -> Schema3MigrationJournal:
    """Parse a schema-3 migration journal from a TOML document."""
    context = f"schema-3 journal {journal_path}"

    migration_id = _journal_string(document, "migration_id", context=context)
    project_uuid = _journal_string(document, "project_uuid", context=context)
    phase = _journal_string(document, "phase", context=context)
    mode = _journal_string(document, "mode", context=context)
    verify = _journal_string(document, "verify", context=context)
    if mode != "copy":
        raise _journal_invalid(f"{context}: unsupported mode {mode!r}")
    if verify not in {"sha256", "size"}:
        raise _journal_invalid(f"{context}: unsupported verify mode {verify!r}")

    # Validate phase
    valid_phases = set(MigrationPhase.__args__)  # type: ignore[attr-defined]
    if phase not in valid_phases:
        raise _journal_invalid(f"{context}: invalid phase {phase!r}")

    # Parse project_root
    project_root_raw = document.get("project_root")
    project_root = Path(str(project_root_raw)) if project_root_raw is not None else None

    # Parse error
    error = document.get("error")
    if error is not None and not isinstance(error, str):
        raise _journal_invalid(f"{context}: error must be a string")

    # Parse hook requirements
    requires_staged = bool(document.get("requires_staged_validation", False))
    requires_activated = bool(document.get("requires_activated_validation", False))
    requires_final = bool(document.get("requires_finalization", False))
    quiescence_completed = document.get("quiescence_completed", False)
    finalized = document.get("finalized", False)
    if not isinstance(quiescence_completed, bool) or not isinstance(finalized, bool):
        raise _journal_invalid(f"{context}: hook completion flags must be booleans")

    def _hook_indexes(name: str) -> tuple[int, ...]:
        raw = document.get(name, [])
        if not isinstance(raw, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in raw
        ):
            raise _journal_invalid(f"{context}: {name} must be a list of indexes")
        return tuple(raw)

    staged_validated = _hook_indexes("staged_validated")
    activated_validated = _hook_indexes("activated_validated")
    plan_digest = document.get("plan_digest")
    if plan_digest is not None and not isinstance(plan_digest, str):
        raise _journal_invalid(f"{context}: plan_digest must be a string")
    lock_identity_raw = document.get("lock_identity", {})
    if not isinstance(lock_identity_raw, Mapping):
        raise _journal_invalid(f"{context}: lock_identity must be a table")
    created_at = document.get("created_at")
    updated_at = document.get("updated_at")
    if created_at is not None and not isinstance(created_at, str):
        raise _journal_invalid(f"{context}: created_at must be a string")
    if updated_at is not None and not isinstance(updated_at, str):
        raise _journal_invalid(f"{context}: updated_at must be a string")
    config_switch_state_raw = document.get("config_switch_state")
    if config_switch_state_raw is not None and not isinstance(
        config_switch_state_raw, Mapping
    ):
        raise _journal_invalid(f"{context}: config_switch_state must be a table")
    manual_reason = document.get("manual_intervention_reason")
    if manual_reason is not None and not isinstance(manual_reason, str):
        raise _journal_invalid(
            f"{context}: manual_intervention_reason must be a string"
        )

    # Parse cleanup warnings
    cleanup_warnings: list[str] = []
    warnings_raw = document.get("cleanup_warnings")
    if isinstance(warnings_raw, Mapping):
        for i in sorted(warnings_raw.keys(), key=int):
            cleanup_warnings.append(str(warnings_raw[i]))

    # Parse items
    items_raw = document.get("items", {})
    if not isinstance(items_raw, Mapping):
        raise _journal_invalid(f"{context}: items must be a table")

    items: list[Schema3ItemJournalState] = []
    for key in sorted(items_raw.keys(), key=int):
        item_raw = items_raw[key]
        if not isinstance(item_raw, Mapping):
            raise _journal_invalid(f"{context}: item {key} must be a table")

        item_index = int(item_raw["item_index"])
        if item_index != int(key):
            raise _journal_invalid(
                f"{context}: item key {key!r} does not match item_index {item_index}"
            )
        item_state = _journal_string(
            item_raw, "state", context=f"{context} item {item_index}"
        )
        valid_states = set(MigrationItemState.__args__)  # type: ignore[attr-defined]
        if item_state not in valid_states:
            raise _journal_invalid(
                f"{context} item {item_index}: invalid state {item_state!r}"
            )
        expected_before_state = item_raw.get("expected_before_state")
        if expected_before_state is not None and expected_before_state not in {
            "absent",
            "empty-unbound",
            "owned",
        }:
            raise _journal_invalid(
                f"{context} item {item_index}: invalid expected_before_state"
            )
        item_component = _journal_string(
            item_raw, "component", context=f"{context} item {item_index}"
        )
        item_strategy = _journal_string(
            item_raw, "strategy", context=f"{context} item {item_index}"
        )
        item_policy = _journal_string(
            item_raw, "destination_policy", context=f"{context} item {item_index}"
        )
        if item_component not in {"config", "mount"}:
            raise _journal_invalid(f"{context} item {item_index}: invalid component")
        if item_strategy not in _JOURNAL_STRATEGIES:
            raise _journal_invalid(f"{context} item {item_index}: invalid strategy")
        if item_policy not in _DESTINATION_POLICIES:
            raise _journal_invalid(f"{context} item {item_index}: invalid policy")

        items.append(
            Schema3ItemJournalState(
                item_index=item_index,
                component=cast(Literal["config", "mount"], item_component),
                tool_name=_journal_string(
                    item_raw, "tool_name", context=f"{context} item {item_index}"
                ),
                mount_name=_journal_string(
                    item_raw, "mount_name", context=f"{context} item {item_index}"
                ),
                source=Path(
                    _journal_string(
                        item_raw, "source", context=f"{context} item {item_index}"
                    )
                ),
                destination=Path(
                    _journal_string(
                        item_raw, "destination", context=f"{context} item {item_index}"
                    )
                ),
                strategy=cast(MigrationStrategy, item_strategy),
                destination_policy=cast(DestinationPolicy, item_policy),
                state=item_state,  # type: ignore[arg-type]
                source_binding=_binding_from_toml(
                    item_raw.get("source_binding"),
                    context=f"{context} item {item_index} source",
                ),
                destination_binding=_binding_from_toml(
                    item_raw.get("destination_binding"),
                    context=f"{context} item {item_index} destination",
                ),
                expected_before_state=cast(
                    DestinationState | None, expected_before_state
                ),
                source_fingerprint=_fingerprint_from_toml(
                    item_raw.get("source_fingerprint")
                ),
                expected_before_fingerprint=_fingerprint_from_toml(
                    item_raw.get("expected_before_fingerprint")
                ),
                expected_target_fingerprint=_fingerprint_from_toml(
                    item_raw.get("expected_target_fingerprint")
                ),
                staged_fingerprint=_fingerprint_from_toml(
                    item_raw.get("staged_fingerprint")
                ),
                activated_fingerprint=_fingerprint_from_toml(
                    item_raw.get("activated_fingerprint")
                ),
                stage_path=Path(item_raw["stage_path"])
                if "stage_path" in item_raw
                else None,
                backup_path=Path(item_raw["backup_path"])
                if "backup_path" in item_raw
                else None,
                error=item_raw.get("error"),
            )
        )

    # Parse config switches
    config_switches: list[Schema3ConfigSwitchState] = []
    switches_raw = document.get("config_switches", {})
    if isinstance(switches_raw, Mapping):
        for key in sorted(switches_raw.keys(), key=int):
            sw_raw = switches_raw[key]
            if not isinstance(sw_raw, Mapping):
                raise _journal_invalid(
                    f"{context}: config_switch {key} must be a table"
                )
            previous_content = sw_raw.get("previous_content")
            target_content = sw_raw.get("target_content")
            if previous_content is not None and not isinstance(previous_content, str):
                raise _journal_invalid(
                    f"{context}: config_switch {key} previous_content must be text"
                )
            if target_content is not None and not isinstance(target_content, str):
                raise _journal_invalid(
                    f"{context}: config_switch {key} target_content must be text"
                )
            config_switches.append(
                Schema3ConfigSwitchState(
                    kind=_journal_string(
                        sw_raw, "kind", context=f"{context} config_switch {key}"
                    ),  # type: ignore[arg-type]
                    destination=Path(
                        _journal_string(
                            sw_raw,
                            "destination",
                            context=f"{context} config_switch {key}",
                        )
                    ),
                    state=_journal_string(
                        sw_raw, "state", context=f"{context} config_switch {key}"
                    ),  # type: ignore[arg-type]
                    expected_before_fingerprint=_fingerprint_from_toml(
                        sw_raw.get("expected_before_fingerprint")
                    ),
                    target_fingerprint=_fingerprint_from_toml(
                        sw_raw.get("target_fingerprint")
                    ),
                    backup_path=Path(sw_raw["backup_path"])
                    if "backup_path" in sw_raw
                    else None,
                    error=sw_raw.get("error"),
                    intent_written=bool(sw_raw.get("intent_written", False)),
                    applied=bool(sw_raw.get("applied", False)),
                    verified=bool(sw_raw.get("verified", False)),
                    previous_content=previous_content,
                    target_content=target_content,
                )
            )

    return Schema3MigrationJournal(
        migration_id=migration_id,
        project_uuid=project_uuid,
        phase=phase,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        verify=verify,  # type: ignore[arg-type]
        project_root=project_root,
        items=tuple(items),
        config_switches=tuple(config_switches),
        error=error,
        requires_staged_validation=requires_staged,
        requires_activated_validation=requires_activated,
        requires_finalization=requires_final,
        cleanup_warnings=tuple(cleanup_warnings),
        plan_digest=plan_digest,
        lock_identity=dict(lock_identity_raw),
        created_at=created_at,
        updated_at=updated_at,
        config_switch_state=(
            dict(config_switch_state_raw)
            if isinstance(config_switch_state_raw, Mapping)
            else None
        ),
        manual_intervention_reason=manual_reason,
        quiescence_completed=quiescence_completed,
        staged_validated=staged_validated,
        activated_validated=activated_validated,
        finalized=finalized,
    )


def _verify(source: Path, destination: Path, mode: VerifyMode) -> None:
    if mode == "size":
        source_size = sum(
            item.stat().st_size for item in source.rglob("*") if item.is_file()
        )
        destination_size = sum(
            item.stat().st_size for item in destination.rglob("*") if item.is_file()
        )
        if source_size != destination_size:
            raise StorageMigrationError(
                f"migration size verification failed for {destination}"
            )
    elif _hash_tree(source) != _hash_tree(destination):
        raise StorageMigrationError(
            f"migration SHA-256 verification failed for {destination}"
        )


def _migration_fingerprint(path: Path, kind: DestinationKind) -> StorageFingerprint:
    if kind == "file":
        return fingerprint_storage_file(path)
    return fingerprint_storage_directory(path)


def _fingerprint_file_bytes(contents: str) -> StorageFingerprint:
    raw = contents.encode("utf-8")
    content_digest = hashlib.sha256(raw).hexdigest()
    digest = hashlib.sha256(f"F\\0{len(raw)}\\0{content_digest}".encode()).hexdigest()
    return StorageFingerprint("sha256-file-v1", digest, 1, len(raw))


def _render_config_changes(
    changes: LedgerLocalOverrides | LedgerProjectManifest,
) -> tuple[Path, str]:
    if isinstance(changes, LedgerLocalOverrides):
        return Path(".ledger/ledger.local.toml"), render_ledger_local_config(changes)
    return Path(".ledger/ledger.toml"), render_ledger_manifest(changes)


def _call_hook(name: str, callback: Callable[..., Any], *args: object) -> None:
    try:
        callback(*args)
    except Exception as exc:
        raise StorageMigrationError(
            f"migration hook {name} failed: {exc}",
            code="STORAGE_MIGRATION_HOOK_FAILED",
        ) from exc


def _item_kind(item: StorageMigrationItem) -> DestinationKind:
    return item.destination_kind or (
        "file" if item.component == "config" else "directory"
    )


def _validate_execution_preflight(
    plan: StorageMigrationPlan,
    validation: StorageMigrationPlanValidation,
) -> None:
    for index, item in enumerate(plan.items):
        if item.strategy == "noop":
            continue
        kind = _item_kind(item)
        if item.strategy == "copy":
            if not item.source.exists() or item.source.is_symlink():
                raise StorageMigrationError(
                    f"item {index}: source precondition changed at {item.source}",
                    code="STORAGE_MIGRATION_SOURCE_CHANGED",
                )
            actual_source = _migration_fingerprint(item.source, kind)
            expected_source = item.expected_source_fingerprint
            if expected_source is not None and actual_source != expected_source:
                raise StorageMigrationError(
                    f"item {index}: source fingerprint changed at {item.source}",
                    code="STORAGE_MIGRATION_SOURCE_CHANGED",
                )
        inspection = inspect_storage_migration_destination(
            path=item.destination,
            kind=kind,
            expected_binding=item.destination_binding,
        )
        if inspection.state in {"foreign", "invalid"}:
            raise StorageMigrationError(
                f"item {index}: destination {item.destination} is {inspection.state}",
                code=(
                    "STORAGE_MIGRATION_DESTINATION_FOREIGN"
                    if inspection.state == "foreign"
                    else "STORAGE_MIGRATION_UNSAFE_PATH"
                ),
            )
        if item.destination_policy == "create-only" and inspection.state == "owned":
            raise StorageMigrationError(
                f"item {index}: create-only destination already exists at "
                f"{item.destination}",
                code="STORAGE_MIGRATION_DESTINATION_UNEXPECTED",
            )
        if item.destination_policy == "replace-owned":
            if inspection.state != "owned" or item.expected_before.fingerprint is None:
                raise StorageMigrationError(
                    f"item {index}: owned destination precondition failed at "
                    f"{item.destination}",
                    code="STORAGE_MIGRATION_DESTINATION_UNEXPECTED",
                )
            if inspection.fingerprint != item.expected_before.fingerprint:
                raise StorageMigrationError(
                    f"item {index}: destination fingerprint changed at "
                    f"{item.destination}",
                    code="STORAGE_MIGRATION_DESTINATION_CHANGED",
                )
        if item.destination_policy == "noop-if-exact":
            if inspection.fingerprint != item.expected_target_fingerprint:
                raise StorageMigrationError(
                    f"item {index}: destination is not the expected exact target",
                    code="STORAGE_MIGRATION_DESTINATION_UNEXPECTED",
                )
        paths = _prepare_item_paths(item.destination, plan.migration_id, index)
        _validate_same_filesystem(item.destination, paths.stage, paths.backup, index)
        for generated in (paths.stage, paths.backup):
            if generated.exists():
                raise StorageMigrationError(
                    f"item {index}: migration-owned path collision at {generated}",
                    code="STORAGE_MIGRATION_PATH_COLLISION",
                )
    if not validation.valid:
        raise StorageMigrationError(
            f"migration plan is invalid: {'; '.join(validation.errors)}",
            code="STORAGE_MIGRATION_PLAN_INVALID",
        )


def _result_from_schema3(
    journal: Schema3MigrationJournal,
    path: Path,
    *,
    error_code: str | None = None,
    recommendation: str | None = None,
) -> StorageMigrationResult:
    outcomes = tuple(
        {"index": item.item_index, "state": item.state, "error": item.error}
        for item in journal.items
    )
    fingerprints = tuple(
        item.activated_fingerprint
        for item in journal.items
        if item.activated_fingerprint is not None
    )
    return StorageMigrationResult(
        journal.migration_id,
        journal.phase,
        sum(item.state == "complete" for item in journal.items),
        False,
        path,
        outcomes,
        fingerprints,
        any(s.state == "activated" for s in journal.config_switches),
        journal.phase == "complete" and not journal.cleanup_warnings,
        error_code,
        recommendation,
    )


def execute_storage_migration(  # noqa: C901
    plan: StorageMigrationPlan,
    *,
    mode: MigrationMode = "copy",
    verify: VerifyMode = "sha256",
    hooks: StorageMigrationHooks | None = None,
    quiescence_check: Callable[[], None] | None = None,
    project_root: Path | None = None,
) -> StorageMigrationResult:
    """Execute a copy-only migration as a durable schema-3 transaction."""
    if mode == "move":
        raise StorageMigrationError(
            "mode='move' is unsupported; Ledgercore migrations are copy-only",
            code="STORAGE_MIGRATION_MOVE_DISABLED",
        )
    if mode != "copy" or verify not in {"sha256", "size"}:
        raise StorageMigrationError(
            "unsupported migration execution option",
            code="STORAGE_MIGRATION_INVALID_ARGUMENT",
        )
    active_hooks = hooks or StorageMigrationHooks()
    if quiescence_check is not None and active_hooks.quiescence_check is not None:
        if quiescence_check is not active_hooks.quiescence_check:
            raise StorageMigrationError(
                "quiescence_check conflicts with hooks.quiescence_check",
                code="STORAGE_MIGRATION_INVALID_ARGUMENT",
            )
    if quiescence_check is not None:
        active_hooks = replace(active_hooks, quiescence_check=quiescence_check)
    active_hooks.validate_requirements()
    root = (project_root or plan.project_root or Path.cwd()).resolve(strict=False)
    validation = validate_storage_migration_plan(plan, project_root=root)
    _validate_execution_preflight(plan, validation)
    journal_path = _journal_path(plan, root)
    lock = MigrationLock(root, plan.migration_id)
    journal = _schema3_journal_from_plan(
        plan, root=root, mode="copy", verify=verify, hooks=active_hooks
    )
    with lock:
        try:
            _persist_schema3(journal, journal_path)
            if active_hooks.quiescence_check is not None:
                _call_hook("quiescence_check", active_hooks.quiescence_check)
                journal = replace(journal, quiescence_completed=True)
                _persist_schema3(journal, journal_path)
            journal = _transition_phase(journal, "staging")
            _persist_schema3(journal, journal_path)
            for index, item in enumerate(plan.items):
                if item.strategy == "noop":
                    journal = _transition_item(journal, index, "complete")
                    _persist_schema3(journal, journal_path)
                    continue
                paths = _prepare_item_paths(item.destination, plan.migration_id, index)
                journal = _transition_item(journal, index, "staging")
                _persist_schema3(journal, journal_path)
                kind = _item_kind(item)
                if kind == "file":
                    _copy_file(item.source, paths.stage)
                else:
                    _copy_tree(item.source, paths.stage)
                    write_storage_binding(paths.stage, item.destination_binding)
                staged_fp = _migration_fingerprint(paths.stage, kind)
                expected_source = item.expected_source_fingerprint
                if expected_source is not None and staged_fp != expected_source:
                    raise StorageMigrationError(
                        f"item {index}: staged fingerprint does not match source "
                        f"at {item.source}",
                        code="STORAGE_MIGRATION_VERIFICATION_FAILED",
                    )
                journal = _transition_item(
                    journal, index, "staged", staged_fingerprint=staged_fp
                )
                _persist_schema3(journal, journal_path)
                if active_hooks.validate_staged is not None:
                    _call_hook("validate_staged", active_hooks.validate_staged, index)
                    journal = replace(
                        journal,
                        staged_validated=tuple((*journal.staged_validated, index)),
                    )
                    _persist_schema3(journal, journal_path)
                journal = _transition_item(journal, index, "stage-verified")
                _persist_schema3(journal, journal_path)
            journal = _transition_phase(journal, "staged")
            _persist_schema3(journal, journal_path)
            journal = _transition_phase(journal, "activating")
            _persist_schema3(journal, journal_path)
            for index, item in enumerate(plan.items):
                if item.strategy == "noop":
                    continue
                paths = _prepare_item_paths(item.destination, plan.migration_id, index)
                kind = _item_kind(item)
                inspection = inspect_storage_migration_destination(
                    path=item.destination,
                    kind=kind,
                    expected_binding=item.destination_binding,
                )
                if inspection.state == "owned":
                    journal = _transition_item(journal, index, "backup-intent")
                    _persist_schema3(journal, journal_path)
                    _durable_rename(item.destination, paths.backup)
                    journal = _transition_item(journal, index, "backup-created")
                    _persist_schema3(journal, journal_path)
                elif inspection.state not in {"absent", "empty-unbound"}:
                    raise StorageMigrationError(
                        f"item {index}: destination changed before activation",
                        code="STORAGE_MIGRATION_DESTINATION_CHANGED",
                    )
                if inspection.state == "empty-unbound":
                    raise StorageMigrationError(
                        f"item {index}: empty-unbound destination cannot be "
                        "atomically activated",
                        code="STORAGE_MIGRATION_DESTINATION_UNEXPECTED",
                    )
                journal = _transition_item(journal, index, "activation-intent")
                _persist_schema3(journal, journal_path)
                _durable_rename(paths.stage, item.destination)
                activated_fp = _migration_fingerprint(item.destination, kind)
                expected_target = (
                    item.expected_target_fingerprint
                    or journal.items[index].staged_fingerprint
                )
                if expected_target is not None and activated_fp != expected_target:
                    raise StorageMigrationError(
                        f"item {index}: activated fingerprint verification failed "
                        f"at {item.destination}",
                        code="STORAGE_MIGRATION_VERIFICATION_FAILED",
                    )
                journal = _transition_item(
                    journal, index, "activated", activated_fingerprint=activated_fp
                )
                _persist_schema3(journal, journal_path)
                if active_hooks.validate_activated is not None:
                    _call_hook(
                        "validate_activated", active_hooks.validate_activated, index
                    )
                    journal = replace(
                        journal,
                        activated_validated=tuple(
                            (*journal.activated_validated, index)
                        ),
                    )
                    _persist_schema3(journal, journal_path)
                journal = _transition_item(journal, index, "post-verified")
                _persist_schema3(journal, journal_path)
            journal = _transition_phase(journal, "items-activated")
            _persist_schema3(journal, journal_path)
            config_relative, target_content = _render_config_changes(
                plan.config_changes
            )
            config_path = root / config_relative
            previous_content = (
                config_path.read_text(encoding="utf-8")
                if config_path.is_file()
                else None
            )
            config_state = Schema3ConfigSwitchState(
                kind=(
                    "local-overrides"
                    if isinstance(plan.config_changes, LedgerLocalOverrides)
                    else "manifest"
                ),
                destination=config_path,
                expected_before_fingerprint=(
                    fingerprint_storage_file(config_path)
                    if config_path.is_file()
                    else None
                ),
                target_fingerprint=_fingerprint_file_bytes(target_content),
                backup_path=config_path.with_name(
                    f".{config_path.name}.backup-{plan.migration_id}"
                ),
                previous_content=previous_content,
                target_content=target_content,
            )
            journal = _transition_phase(journal, "config-switching")
            journal = replace(journal, config_switches=(config_state,))
            _persist_schema3(journal, journal_path)
            config_state = replace(config_state, intent_written=True, state="staged")
            journal = replace(journal, config_switches=(config_state,))
            _persist_schema3(journal, journal_path)
            atomic_write_text(config_path, target_content)
            config_state = replace(config_state, applied=True, state="activated")
            journal = replace(journal, config_switches=(config_state,))
            _persist_schema3(journal, journal_path)
            if fingerprint_storage_file(config_path) != config_state.target_fingerprint:
                raise StorageMigrationError(
                    f"configuration verification failed at {config_path}",
                    code="STORAGE_MIGRATION_CONFIG_SWITCH_FAILED",
                )
            config_state = replace(config_state, verified=True)
            journal = replace(journal, config_switches=(config_state,))
            journal = _transition_phase(journal, "config-switched")
            _persist_schema3(journal, journal_path)
            journal = _transition_phase(journal, "post-verifying")
            _persist_schema3(journal, journal_path)
            if active_hooks.finalize is not None:
                _call_hook("finalize", active_hooks.finalize)
                journal = replace(journal, finalized=True)
                _persist_schema3(journal, journal_path)
            journal = _transition_phase(journal, "committed")
            _persist_schema3(journal, journal_path)
            journal = _transition_phase(journal, "cleaning-up")
            _persist_schema3(journal, journal_path)
            cleanup_warnings: list[str] = []
            for index, item in enumerate(plan.items):
                paths = _prepare_item_paths(item.destination, plan.migration_id, index)
                if paths.stage.exists():
                    paths.stage.unlink() if paths.stage.is_file() else shutil.rmtree(
                        paths.stage
                    )
                if paths.backup.exists():
                    paths.backup.unlink() if paths.backup.is_file() else shutil.rmtree(
                        paths.backup
                    )
                if item.strategy != "noop":
                    journal = _transition_item(journal, index, "cleanup-pending")
                    journal = _transition_item(journal, index, "complete")
            journal = replace(journal, cleanup_warnings=tuple(cleanup_warnings))
            journal = _transition_phase(journal, "complete")
            _persist_schema3(journal, journal_path)
            return _result_from_schema3(journal, journal_path)
        except Exception as exc:
            error_code = (
                exc.code
                if isinstance(exc, StorageMigrationError)
                else "STORAGE_MIGRATION_RECOVERY_FAILED"
            )
            message = str(exc)[:500]
            failed_items = tuple(
                replace(item, error=message)
                if item.state not in {"complete", "rolled-back"} and item.error is None
                else item
                for item in journal.items
            )
            journal = replace(
                journal, phase="failed", error=message, items=failed_items
            )
            try:
                _persist_schema3(journal, journal_path)
            except Exception:
                pass
            if isinstance(exc, StorageMigrationError):
                raise
            raise StorageMigrationError(
                f"storage migration {plan.migration_id} failed: {exc}",
                code=error_code,
            ) from exc


def _inspect_journal_v1(
    document: Mapping[str, object],
    journal_path: Path,
) -> StorageMigrationJournal:
    """Inspect a schema-1 journal, preserving only known facts."""
    context = f"schema-1 journal {journal_path}"
    migration_id = _journal_string(document, "migration_id", context=context)
    phase = _journal_string(document, "phase", context=context)
    project_uuid = _journal_string(document, "project_uuid", context=context)
    error_raw = document.get("error")
    if error_raw is not None and (
        isinstance(error_raw, bool) or not isinstance(error_raw, str)
    ):
        raise _journal_invalid(f"{context} has non-string error")
    error = error_raw
    items_data = document.get("items", {})
    if not isinstance(items_data, Mapping):
        raise _journal_invalid(f"{context} items must be a TOML table")
    journal_items: list[StorageMigrationJournalItem] = []
    for index, (item_key, row) in enumerate(items_data.items()):
        if not isinstance(row, Mapping):
            raise _journal_invalid(f"{context} item {item_key!r} must be a TOML table")
        journal_items.append(
            _journal_item(
                row,
                item_id=str(item_key) if item_key is not None else str(index),
                context=f"{context} item {item_key!r}",
                require_bindings=False,
            )
        )
    # Schema-1: bindings, mode, verify, project_root are unknown
    items_completed: int | None = None
    if phase == "complete":
        items_completed = len(journal_items)
    recovery_capability: MigrationRecoveryCapability
    if phase == "complete":
        recovery_capability = "completed-only"
    else:
        recovery_capability = "manual-intervention"
    return StorageMigrationJournal(
        migration_id=migration_id,
        phase=phase,
        project_uuid=project_uuid,
        journal_path=journal_path,
        items=tuple(journal_items),
        error=error,
        schema_version=1,
        mode=None,
        verify=None,
        project_root=None,
        items_completed=items_completed,
        source_removed=None,
        recovery_capability=recovery_capability,
    )


def _inspect_journal_v2(
    document: Mapping[str, object],
    journal_path: Path,
) -> StorageMigrationJournal:
    """Strictly inspect a schema-2 journal."""
    context = f"schema-2 journal {journal_path}"
    migration_id = _journal_string(document, "migration_id", context=context)
    phase = _journal_string(document, "phase", context=context)
    if phase not in _JOURNAL_PHASES:
        raise _journal_invalid(f"{context} has invalid phase {phase!r}")
    project_uuid = _journal_string(document, "project_uuid", context=context)
    error_raw = document.get("error")
    if error_raw is not None and (
        isinstance(error_raw, bool) or not isinstance(error_raw, str)
    ):
        raise _journal_invalid(f"{context} has non-string error")
    error = error_raw
    mode_raw = document.get("mode")
    if mode_raw not in ("copy", "move"):
        raise _journal_invalid(f"{context} has invalid mode {mode_raw!r}")
    mode: MigrationMode = mode_raw
    verify_raw = document.get("verify")
    if verify_raw not in ("sha256", "size"):
        raise _journal_invalid(f"{context} has invalid verify {verify_raw!r}")
    verify: VerifyMode = verify_raw
    project_root_raw = document.get("project_root")
    if (
        isinstance(project_root_raw, bool)
        or not isinstance(project_root_raw, str)
        or not project_root_raw
    ):
        raise _journal_invalid(f"{context} requires non-empty string project_root")
    project_root = Path(project_root_raw)
    items_completed_raw = document.get("items_completed")
    if isinstance(items_completed_raw, bool) or not isinstance(
        items_completed_raw, int
    ):
        raise _journal_invalid(
            f"{context} has non-integer items_completed {items_completed_raw!r}"
        )
    source_removed_raw = document.get("source_removed")
    if not isinstance(source_removed_raw, bool):
        raise _journal_invalid(
            f"{context} has non-boolean source_removed {source_removed_raw!r}"
        )
    items_data = document.get("items")
    if not isinstance(items_data, Mapping):
        raise _journal_invalid(f"{context} has non-table items")
    numeric_keys: list[tuple[int, str]] = []
    for key in items_data:
        if not isinstance(key, str) or not key.isdecimal():
            raise _journal_invalid(f"{context} has non-numeric item key {key!r}")
        number = int(key)
        if any(existing == number for existing, _ in numeric_keys):
            raise _journal_invalid(f"{context} has duplicate item key {key!r}")
        numeric_keys.append((number, key))
    journal_items: list[StorageMigrationJournalItem] = []
    for _, key in sorted(numeric_keys):
        row = items_data[key]
        if not isinstance(row, Mapping):
            raise _journal_invalid(f"{context} item {key!r} must be a TOML table")
        journal_items.append(
            _journal_item(
                row,
                item_id=key,
                context=f"{context} item {key}",
                require_bindings=True,
            )
        )
    num_items = len(journal_items)
    if items_completed_raw < 0 or items_completed_raw > num_items:
        raise StorageMigrationError(
            f"schema-2 journal items_completed={items_completed_raw} "
            f"out of range for {num_items} items",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        )
    recovery_capability: MigrationRecoveryCapability
    if phase == "complete":
        recovery_capability = "completed-only"
    else:
        recovery_capability = "manual-intervention"
    return StorageMigrationJournal(
        migration_id=migration_id,
        phase=phase,
        project_uuid=project_uuid,
        journal_path=journal_path,
        items=tuple(journal_items),
        error=error,
        schema_version=2,
        mode=mode,
        verify=verify,
        project_root=project_root,
        items_completed=items_completed_raw,
        source_removed=source_removed_raw,
        recovery_capability=recovery_capability,
    )


def inspect_storage_migration(
    journal_path: Path,
) -> StorageMigrationJournal | Schema3MigrationJournal:
    """Read a migration journal for operator or recovery tooling."""
    if journal_path.is_symlink() or not journal_path.is_file():
        raise StorageMigrationError(
            f"migration journal {journal_path} is missing or is not a regular file",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        )
    try:
        document = parse(journal_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StorageMigrationError(
            f"unable to read migration journal {journal_path}: {exc}",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        ) from exc

    if not isinstance(document, Mapping):
        raise StorageMigrationError(
            f"migration journal {journal_path} is not a TOML table",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        )
    schema_raw = document.get("schema_version")
    if isinstance(schema_raw, bool) or not isinstance(schema_raw, int):
        raise StorageMigrationError(
            f"migration journal {journal_path} has non-integer schema_version",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        )
    try:
        if schema_raw == 1:
            return _inspect_journal_v1(document, journal_path)
        elif schema_raw == 2:
            return _inspect_journal_v2(document, journal_path)
        elif schema_raw == 3:
            journal = _parse_schema3_journal(document, journal_path)
            if journal.plan_digest is not None:
                # A digest is a commitment, not a suggestion; the plan is not
                # available during inspection, so retain it for recovery checks.
                if len(journal.plan_digest) != 64 or any(
                    char not in "0123456789abcdef" for char in journal.plan_digest
                ):
                    raise _journal_invalid(
                        f"schema-3 journal {journal_path}: invalid plan_digest"
                    )
            return journal
        else:
            raise StorageMigrationError(
                f"migration journal {journal_path} has unsupported schema {schema_raw}",
                code="STORAGE_MIGRATION_JOURNAL_INVALID",
            )
    except StorageMigrationError:
        raise
    except Exception as exc:
        raise StorageMigrationError(
            f"unable to inspect migration journal {journal_path}: {exc}",
            code="STORAGE_MIGRATION_JOURNAL_INVALID",
        ) from exc


def assess_storage_migration(
    journal_path: Path,
    *,
    project_root: Path | None = None,
) -> RecoveryAssessment:
    """Return the non-mutating schema-3 recovery assessment for a journal."""
    inspected = inspect_storage_migration(journal_path)
    if not isinstance(inspected, Schema3MigrationJournal):
        recommendation: Literal[
            "resume", "rollback", "complete", "manual-intervention"
        ] = "complete" if inspected.phase == "complete" else "manual-intervention"
        return RecoveryAssessment(
            migration_id=inspected.migration_id,
            journal_path=journal_path,
            phase=inspected.phase,
            item_states=(),
            owned_paths=(),
            blockers=()
            if recommendation == "complete"
            else ("legacy journal is not automatically recoverable",),
            recommendation=recommendation,
            resumable=False,
            rollbackable=False,
            complete=inspected.phase == "complete",
        )
    return _schema3_assessment(inspected, journal_path, project_root=project_root)


def _path_is_owned_directory(path: Path, binding: StorageBinding | None) -> bool:
    if binding is None or not path.is_dir() or path.is_symlink():
        return False
    marker = path / ".ledger-project.toml"
    try:
        return marker.is_file() and storage_bindings_match(
            read_storage_binding(marker), binding
        )
    except StorageBindingError:
        return False


def _schema3_assessment(  # noqa: C901
    journal: Schema3MigrationJournal,
    journal_path: Path,
    *,
    project_root: Path | None = None,
) -> RecoveryAssessment:
    blockers: list[str] = []
    owned: list[Path] = []
    resumable = journal.phase != "complete"
    rollbackable = journal.phase not in {"complete", "rolled-back"}
    states: list[MigrationItemState] = []
    for item in journal.items:
        states.append(item.state)
        kind: DestinationKind = "file" if item.component == "config" else "directory"
        destination_inspection = None
        if item.destination_binding is not None:
            destination_inspection = inspect_storage_migration_destination(
                path=item.destination,
                kind=kind,
                expected_binding=item.destination_binding,
            )
            if destination_inspection.state == "foreign":
                blockers.append(f"foreign destination {item.destination}")
                resumable = False
                rollbackable = False
            elif destination_inspection.state == "owned":
                owned.append(item.destination)
        if item.stage_path is not None and item.stage_path.exists():
            if kind == "directory" and not _path_is_owned_directory(
                item.stage_path, item.destination_binding
            ):
                blockers.append(
                    f"stage ownership cannot be proven at {item.stage_path}"
                )
                resumable = False
                rollbackable = False
            elif kind == "file" and (
                item.stage_path.is_symlink() or not item.stage_path.is_file()
            ):
                blockers.append(f"unsafe stage path {item.stage_path}")
                resumable = False
                rollbackable = False
            else:
                owned.append(item.stage_path)
                try:
                    staged = _migration_fingerprint(item.stage_path, kind)
                    if (
                        item.staged_fingerprint is not None
                        and staged != item.staged_fingerprint
                    ):
                        blockers.append(
                            f"stage fingerprint mismatch at {item.stage_path}"
                        )
                        resumable = False
                        rollbackable = False
                except StorageMigrationError as exc:
                    blockers.append(str(exc))
                    resumable = False
                    rollbackable = False
        elif item.state in {"staged", "stage-verified", "activation-intent"}:
            blockers.append(f"journal-owned stage is missing at {item.stage_path}")
            resumable = False
        if item.backup_path is not None and item.backup_path.exists():
            if kind == "directory" and not _path_is_owned_directory(
                item.backup_path, item.destination_binding
            ):
                blockers.append(
                    f"backup ownership cannot be proven at {item.backup_path}"
                )
                resumable = False
                rollbackable = False
            elif item.backup_path.is_symlink():
                blockers.append(f"unsafe backup path {item.backup_path}")
                resumable = False
                rollbackable = False
            else:
                owned.append(item.backup_path)
        if item.state == "activation-intent" and destination_inspection is not None:
            if (
                destination_inspection.state == "owned"
                and item.activated_fingerprint is None
            ):
                try:
                    if (
                        item.expected_target_fingerprint is not None
                        and destination_inspection.fingerprint
                        != item.expected_target_fingerprint
                    ):
                        blockers.append(
                            f"activation result mismatch at {item.destination}"
                        )
                        resumable = False
                except Exception:
                    resumable = False
        if item.source_fingerprint is not None and item.source.exists():
            try:
                if _migration_fingerprint(item.source, kind) != item.source_fingerprint:
                    blockers.append(f"source changed at {item.source}")
                    resumable = False
            except StorageMigrationError as exc:
                blockers.append(str(exc))
                resumable = False
    if journal.error and journal.phase == "failed" and not blockers:
        # A bounded recorded error is not by itself ambiguity; the filesystem
        # assessment above is authoritative for recovery selection.
        pass
    if journal.phase == "complete":
        recommendation: Literal[
            "resume", "rollback", "complete", "manual-intervention"
        ] = "complete"
    elif blockers:
        recommendation = "manual-intervention"
    elif resumable:
        recommendation = "resume"
    elif rollbackable:
        recommendation = "rollback"
    else:
        recommendation = "manual-intervention"
    return RecoveryAssessment(
        migration_id=journal.migration_id,
        journal_path=journal_path,
        phase=journal.phase,
        item_states=tuple(states),
        owned_paths=tuple(dict.fromkeys(owned)),
        blockers=tuple(blockers),
        recommendation=recommendation,
        resumable=resumable,
        rollbackable=rollbackable,
        complete=journal.phase == "complete",
    )


def _recover_schema3_rollback(
    journal: Schema3MigrationJournal,
    journal_path: Path,
    *,
    root: Path,
) -> StorageMigrationResult:
    assessment = _schema3_assessment(journal, journal_path, project_root=root)
    if assessment.blockers:
        raise StorageMigrationError(
            f"rollback requires manual intervention: {'; '.join(assessment.blockers)}",
            code="STORAGE_MIGRATION_ROLLBACK_CONFLICT",
        )
    journal = replace(journal, phase="rolling-back")
    _persist_schema3(journal, journal_path)
    try:
        for index in reversed(range(len(journal.items))):
            item = journal.items[index]
            if item.destination_binding is None:
                continue
            if item.state == "complete":
                journal = replace(
                    journal,
                    items=tuple(
                        replace(candidate, state="rollback-intent")
                        if candidate.item_index == index
                        else candidate
                        for candidate in journal.items
                    ),
                )
                _persist_schema3(journal, journal_path)
            elif item.state != "rolled-back":
                journal = _transition_item(journal, index, "rollback-intent")
                _persist_schema3(journal, journal_path)
            kind: DestinationKind = (
                "file" if item.component == "config" else "directory"
            )
            if item.destination.exists() and item.destination_binding is not None:
                inspection = inspect_storage_migration_destination(
                    path=item.destination,
                    kind=kind,
                    expected_binding=item.destination_binding,
                )
                if inspection.state == "foreign":
                    raise StorageMigrationError(
                        f"rollback would overwrite foreign destination "
                        f"{item.destination}",
                        code="STORAGE_MIGRATION_ROLLBACK_CONFLICT",
                    )
                if inspection.state == "owned":
                    if kind == "file":
                        item.destination.unlink()
                    else:
                        shutil.rmtree(item.destination)
            if item.backup_path is not None and item.backup_path.exists():
                _durable_rename(item.backup_path, item.destination)
            if item.stage_path is not None and item.stage_path.exists():
                if kind == "file":
                    item.stage_path.unlink()
                else:
                    shutil.rmtree(item.stage_path)
            journal = _transition_item(journal, index, "rolled-back")
            journal = _transition_item(journal, index, "cleanup-pending")
            journal = _transition_item(journal, index, "complete")
            _persist_schema3(journal, journal_path)
        for switch in journal.config_switches:
            if not switch.applied:
                continue
            current = (
                fingerprint_storage_file(switch.destination)
                if switch.destination.is_file()
                else None
            )
            if current != switch.target_fingerprint:
                raise StorageMigrationError(
                    f"configuration changed outside migration at {switch.destination}",
                    code="STORAGE_MIGRATION_ROLLBACK_CONFLICT",
                )
            if switch.previous_content is None:
                switch.destination.unlink(missing_ok=True)
            else:
                atomic_write_text(switch.destination, switch.previous_content)
        journal = replace(journal, phase="rolled-back")
        _persist_schema3(journal, journal_path)
        return _result_from_schema3(journal, journal_path, recommendation="rollback")
    except Exception as exc:
        journal = replace(
            journal,
            phase="failed",
            error=str(exc)[:500],
            manual_intervention_reason="rollback conflict or ownership proof failed",
        )
        try:
            _persist_schema3(journal, journal_path)
        except Exception:
            pass
        if isinstance(exc, StorageMigrationError):
            raise
        raise StorageMigrationError(
            f"rollback failed: {exc}", code="STORAGE_MIGRATION_ROLLBACK_CONFLICT"
        ) from exc


def _recover_schema3_resume(  # noqa: C901
    journal: Schema3MigrationJournal,
    journal_path: Path,
    *,
    root: Path,
    hooks: StorageMigrationHooks,
) -> StorageMigrationResult:
    assessment = _schema3_assessment(journal, journal_path, project_root=root)
    if assessment.blockers:
        raise StorageMigrationError(
            f"resume requires manual intervention: {'; '.join(assessment.blockers)}",
            code="STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED",
        )
    with MigrationLock(root, journal.migration_id):
        try:
            if hooks.quiescence_check is not None and not journal.quiescence_completed:
                _call_hook("quiescence_check", hooks.quiescence_check)
                journal = replace(journal, quiescence_completed=True)
                _persist_schema3(journal, journal_path)
            for index, item in enumerate(journal.items):
                if item.state == "complete":
                    continue
                kind: DestinationKind = (
                    "file" if item.component == "config" else "directory"
                )
                if item.state in {"activated", "post-verified", "cleanup-pending"}:
                    if item.destination_binding is None:
                        raise StorageMigrationError(
                            f"item {index} has no destination binding",
                            code="STORAGE_MIGRATION_JOURNAL_INVALID",
                        )
                    destination = inspect_storage_migration_destination(
                        path=item.destination,
                        kind=kind,
                        expected_binding=item.destination_binding,
                    )
                    if destination.state != "owned":
                        raise StorageMigrationError(
                            f"activated destination cannot be proven at "
                            f"{item.destination}",
                            code="STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED",
                        )
                    if (
                        hooks.validate_activated is not None
                        and index not in journal.activated_validated
                    ):
                        _call_hook(
                            "validate_activated", hooks.validate_activated, index
                        )
                        journal = replace(
                            journal,
                            activated_validated=tuple(
                                (*journal.activated_validated, index)
                            ),
                        )
                        _persist_schema3(journal, journal_path)
                    if journal.items[index].state == "activated":
                        journal = _transition_item(journal, index, "post-verified")
                    if journal.items[index].state == "post-verified":
                        journal = _transition_item(journal, index, "cleanup-pending")
                    if journal.items[index].state == "cleanup-pending":
                        journal = _transition_item(journal, index, "complete")
                    _persist_schema3(journal, journal_path)
                    continue
                if item.stage_path is None:
                    raise StorageMigrationError(
                        f"item {index} has no stage path",
                        code="STORAGE_MIGRATION_JOURNAL_INVALID",
                    )
                if not item.stage_path.exists():
                    if item.source_fingerprint is None or not item.source.exists():
                        raise StorageMigrationError(
                            f"cannot recreate stage for item {index}",
                            code="STORAGE_MIGRATION_SOURCE_CHANGED",
                        )
                    journal = _transition_item(journal, index, "staging")
                    _persist_schema3(journal, journal_path)
                    if kind == "file":
                        _copy_file(item.source, item.stage_path)
                    else:
                        _copy_tree(item.source, item.stage_path)
                        if item.destination_binding is not None:
                            write_storage_binding(
                                item.stage_path, item.destination_binding
                            )
                    staged_fp = _migration_fingerprint(item.stage_path, kind)
                    if staged_fp != item.source_fingerprint:
                        raise StorageMigrationError(
                            f"source changed while recovering item {index}",
                            code="STORAGE_MIGRATION_SOURCE_CHANGED",
                        )
                    journal = _transition_item(
                        journal, index, "staged", staged_fingerprint=staged_fp
                    )
                    _persist_schema3(journal, journal_path)
                    item = journal.items[index]
                if journal.items[index].state in {"staging", "staged"}:
                    stage_path = item.stage_path
                    if stage_path is None:
                        raise StorageMigrationError(
                            f"item {index} has no stage path",
                            code="STORAGE_MIGRATION_JOURNAL_INVALID",
                        )
                    staged_fp = _migration_fingerprint(stage_path, kind)
                    journal = _transition_item(
                        journal, index, "stage-verified", staged_fingerprint=staged_fp
                    )
                    _persist_schema3(journal, journal_path)
                    item = journal.items[index]
                if (
                    hooks.validate_staged is not None
                    and index not in journal.staged_validated
                ):
                    _call_hook("validate_staged", hooks.validate_staged, index)
                    journal = replace(
                        journal,
                        staged_validated=tuple((*journal.staged_validated, index)),
                    )
                    _persist_schema3(journal, journal_path)
                if journal.items[index].state == "stage-verified":
                    destination_binding = item.destination_binding
                    if destination_binding is None:
                        raise StorageMigrationError(
                            f"item {index} has no destination binding",
                            code="STORAGE_MIGRATION_JOURNAL_INVALID",
                        )
                    inspection = inspect_storage_migration_destination(
                        path=item.destination,
                        kind=kind,
                        expected_binding=destination_binding,
                    )
                    if inspection.state == "owned":
                        if item.backup_path is None:
                            raise StorageMigrationError(
                                f"item {index} is missing backup path",
                                code="STORAGE_MIGRATION_JOURNAL_INVALID",
                            )
                        journal = _transition_item(journal, index, "backup-intent")
                        _persist_schema3(journal, journal_path)
                        _durable_rename(item.destination, item.backup_path)
                        journal = _transition_item(journal, index, "backup-created")
                        _persist_schema3(journal, journal_path)
                    elif inspection.state not in {"absent"}:
                        raise StorageMigrationError(
                            f"destination changed during resume at {item.destination}",
                            code="STORAGE_MIGRATION_DESTINATION_CHANGED",
                        )
                    journal = _transition_item(journal, index, "activation-intent")
                    _persist_schema3(journal, journal_path)
                    stage_path = item.stage_path
                    if stage_path is None:
                        raise StorageMigrationError(
                            f"item {index} has no stage path",
                            code="STORAGE_MIGRATION_JOURNAL_INVALID",
                        )
                    _durable_rename(stage_path, item.destination)
                    activated_fp = _migration_fingerprint(item.destination, kind)
                    journal = _transition_item(
                        journal, index, "activated", activated_fingerprint=activated_fp
                    )
                    _persist_schema3(journal, journal_path)
                if (
                    hooks.validate_activated is not None
                    and index not in journal.activated_validated
                ):
                    _call_hook("validate_activated", hooks.validate_activated, index)
                    journal = replace(
                        journal,
                        activated_validated=tuple(
                            (*journal.activated_validated, index)
                        ),
                    )
                    _persist_schema3(journal, journal_path)
                if journal.items[index].state == "activated":
                    journal = _transition_item(journal, index, "post-verified")
                    journal = _transition_item(journal, index, "cleanup-pending")
                    journal = _transition_item(journal, index, "complete")
                    _persist_schema3(journal, journal_path)
            if journal.config_switches:
                switch = journal.config_switches[0]
                if switch.target_content is None:
                    raise StorageMigrationError(
                        "config switch target content is missing",
                        code="STORAGE_MIGRATION_JOURNAL_INVALID",
                    )
                if not switch.verified:
                    if (
                        switch.destination.exists()
                        and switch.target_fingerprint is not None
                    ):
                        current = fingerprint_storage_file(switch.destination)
                        if current != switch.target_fingerprint:
                            if (
                                switch.expected_before_fingerprint is not None
                                and current != switch.expected_before_fingerprint
                            ):
                                raise StorageMigrationError(
                                    f"configuration changed during resume at "
                                    f"{switch.destination}",
                                    code="STORAGE_MIGRATION_CONFIG_SWITCH_FAILED",
                                )
                    atomic_write_text(switch.destination, switch.target_content)
                    switch = replace(
                        switch, applied=True, verified=True, state="activated"
                    )
                    journal = replace(journal, config_switches=(switch,))
                    _persist_schema3(journal, journal_path)
            if hooks.finalize is not None and not journal.finalized:
                _call_hook("finalize", hooks.finalize)
                journal = replace(journal, finalized=True)
                _persist_schema3(journal, journal_path)
            journal = replace(journal, phase="committed")
            _persist_schema3(journal, journal_path)
            journal = replace(journal, phase="cleaning-up")
            _persist_schema3(journal, journal_path)
            for item in journal.items:
                if item.backup_path is not None and item.backup_path.exists():
                    if item.backup_path.is_dir():
                        shutil.rmtree(item.backup_path)
                    else:
                        item.backup_path.unlink()
            journal = replace(journal, phase="complete")
            _persist_schema3(journal, journal_path)
            return _result_from_schema3(journal, journal_path, recommendation="resume")
        except Exception as exc:
            journal = replace(journal, phase="failed", error=str(exc)[:500])
            try:
                _persist_schema3(journal, journal_path)
            except Exception:
                pass
            if isinstance(exc, StorageMigrationError):
                raise
            raise StorageMigrationError(
                f"resume failed: {exc}", code="STORAGE_MIGRATION_RECOVERY_FAILED"
            ) from exc


def recover_storage_migration(
    journal_path: Path,
    *,
    policy: Literal["auto", "resume", "rollback"] = "auto",
    dry_run: bool = False,
    hooks: StorageMigrationHooks | None = None,
    project_root: Path | None = None,
) -> StorageMigrationResult | RecoveryAssessment:
    """Inspect or recover a migration journal under an explicit safety policy."""
    if policy not in {"auto", "resume", "rollback"}:
        raise StorageMigrationError(
            f"unsupported recovery policy {policy!r}",
            code="STORAGE_MIGRATION_INVALID_ARGUMENT",
        )
    journal = inspect_storage_migration(journal_path)
    if isinstance(journal, StorageMigrationJournal):
        if journal.recovery_capability == "completed-only":
            result = StorageMigrationResult(
                journal.migration_id,
                journal.phase,
                journal.items_completed or len(journal.items),
                journal.source_removed,
                journal_path,
            )
            return result
        raise StorageMigrationError(
            f"migration journal {journal_path} requires manual intervention",
            code="STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED",
        )
    assessment = _schema3_assessment(journal, journal_path, project_root=project_root)
    if dry_run:
        return assessment
    if assessment.complete:
        return _result_from_schema3(journal, journal_path, recommendation="complete")
    selected = assessment.recommendation if policy == "auto" else policy
    if (
        selected == "manual-intervention"
        or (selected == "resume" and not assessment.resumable)
        or (selected == "rollback" and not assessment.rollbackable)
    ):
        raise StorageMigrationError(
            "recovery requires manual intervention: "
            f"{'; '.join(assessment.blockers) or 'policy is unsafe'}",
            code="STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED",
        )
    root = (
        project_root or journal.project_root or journal_path.parent.parent.parent
    ).resolve(strict=False)
    active_hooks = hooks or StorageMigrationHooks()
    active_hooks.validate_requirements()
    if selected == "rollback":
        return _recover_schema3_rollback(journal, journal_path, root=root)
    return _recover_schema3_resume(journal, journal_path, root=root, hooks=active_hooks)


def plan_schema_v2_to_v3(loaded: Any) -> Any:
    """Create a conservative schema conversion plan for simple schema-2 layouts."""
    from ledgercore.manifest import LedgerRegistration as V3Registration
    from ledgercore.manifest import MountDefinition

    if loaded.manifest.schema_version != 2:
        raise StorageMigrationError("schema conversion requires a schema-2 manifest")
    ledgers: dict[str, V3Registration] = {}
    for tool_name, registration in loaded.manifest.ledgers.items():
        mounts: dict[str, MountDefinition] = {}
        for mount_name, mount in registration.mounts.items():
            if mount.storage == "repository":
                storage = "project"
                root = None
            elif mount.storage == "cache":
                storage = "cache"
                root = None
            else:
                storage = "external"
                root = "../ledger"
            mounts[mount_name] = MountDefinition(
                mount_name,
                cast(Literal["project", "external", "user-data", "cache"], storage),
                root,
            )
        ledgers[tool_name] = V3Registration(tool_name, mounts)
    return LedgerProjectManifest(
        3, loaded.manifest.project_uuid, loaded.manifest.project_name, ledgers
    )


class MigrationLock:
    """Advisory lock for project migration operations."""

    def __init__(self, project_root: Path, migration_id: str) -> None:
        self._lock_dir = project_root / ".ledger" / "migrations"
        self._lock_file = self._lock_dir / "write.lock"
        self._lock_fd: int | None = None
        self._migration_id = migration_id

    def acquire(self) -> None:
        """Acquire the migration lock."""
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl

            self._lock_fd = os.open(str(self._lock_file), os.O_CREAT | os.O_WRONLY)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write migration_id to lock file for diagnostics
            os.write(self._lock_fd, self._migration_id.encode())
            os.fsync(self._lock_fd)
        except ImportError:
            # Windows: use msvcrt
            import msvcrt

            self._lock_fd = os.open(str(self._lock_file), os.O_CREAT | os.O_WRONLY)
            msvcrt.locking(self._lock_fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError as exc:
            raise StorageMigrationError(
                f"could not acquire migration lock: {exc}",
                code="STORAGE_MIGRATION_LOCKED",
            ) from exc

    def release(self) -> None:
        """Release the migration lock."""
        if self._lock_fd is not None:
            try:
                import fcntl

                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except ImportError:
                pass
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def __enter__(self) -> MigrationLock:
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


__all__ = [
    "MigrationRecoveryCapability",
    "RecoveryAssessment",
    "Schema3ConfigSwitchState",
    "Schema3ItemJournalState",
    "Schema3MigrationJournal",
    "StorageDestinationInspection",
    "StorageFingerprint",
    "StorageFingerprintEntry",
    "StorageMigrationHooks",
    "StorageMigrationItem",
    "StorageMigrationJournal",
    "StorageMigrationJournalItem",
    "StorageMigrationPlan",
    "StorageMigrationPlanValidation",
    "StorageMigrationResult",
    "DestinationPrecondition",
    "DestinationKind",
    "DestinationPolicy",
    "MigrationItemPaths",
    "MigrationItemState",
    "MigrationLock",
    "MigrationPhase",
    "execute_storage_migration",
    "assess_storage_migration",
    "fingerprint_storage_directory",
    "fingerprint_storage_file",
    "inspect_storage_migration",
    "inspect_storage_migration_destination",
    "plan_schema_v2_to_v3",
    "plan_storage_migration",
    "recover_storage_migration",
    "validate_storage_migration_plan",
    "write_schema3_journal",
]
