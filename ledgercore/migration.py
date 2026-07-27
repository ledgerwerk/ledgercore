"""Explicit, verified Ledgercore storage migration planning and execution."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
    storage_binding_from_mapping,
    storage_binding_to_mapping,
    write_storage_binding,
)
from ledgercore.tomlio import write_ledger_local_config, write_ledger_manifest

MigrationStrategy = Literal["copy", "rebuild", "noop"]
MigrationMode = Literal["copy", "move"]
VerifyMode = Literal["sha256", "size"]
MigrationRecoveryCapability = Literal["completed-only", "manual-intervention"]

_JOURNAL_PHASES = frozenset(
    {"planned", "copying", "verified", "config-switched", "complete", "failed"}
)
_JOURNAL_COMPONENTS = frozenset({"config", "mount"})
_JOURNAL_STRATEGIES = frozenset({"copy", "rebuild", "noop"})


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
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class StorageMigrationResult:
    migration_id: str
    phase: str
    items_completed: int
    source_removed: bool | None
    journal_path: Path


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
    if actual != expected:
        raise StorageMigrationError(
            f"migration source binding mismatch at {marker}: expected "
            f"{expected.project_uuid}/{expected.tool}/{expected.mount}/"
            f"{expected.storage}, got "
            f"{actual.project_uuid}/{actual.tool}/{actual.mount}/{actual.storage}"
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
    if actual != expected:
        raise StorageMigrationError(
            f"migration destination binding mismatch at {marker}: expected "
            f"{expected.project_uuid}/{expected.tool}/{expected.mount}/{expected.storage}"
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
        items.append(
            StorageMigrationItem(
                "mount",
                tool_name,
                mount_name,
                source,
                destination,
                actual,
                destination_binding,
                strategy,
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
        else:
            if not source.is_file() or source.is_symlink():
                raise StorageMigrationError(
                    f"config migration source {source} is not a regular file"
                )
            _validate_destination(destination.parent, destination_binding)
            strategy = "copy"
        items.insert(
            0,
            StorageMigrationItem(
                "config",
                tool_name,
                "config",
                source,
                destination,
                source_binding,
                destination_binding,
                strategy,
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


def execute_storage_migration(  # noqa: C901
    plan: StorageMigrationPlan,
    *,
    mode: MigrationMode = "copy",
    verify: VerifyMode = "sha256",
    quiescence_check: Callable[[], None] | None = None,
    project_root: Path | None = None,
) -> StorageMigrationResult:
    """Execute a previously validated plan with journaled, verified switching."""
    if mode not in {"copy", "move"} or verify not in {"sha256", "size"}:
        raise StorageMigrationError(
            "unsupported migration mode or verification mode",
            code="STORAGE_MIGRATION_INVALID_ARGUMENT",
        )
    if mode == "move":
        raise StorageMigrationError(
            "mode='move' is disabled in Ledgercore 0.5.1 because source cleanup "
            "is not safely recoverable; use mode='copy'",
            code="STORAGE_MIGRATION_MOVE_DISABLED",
        )
    durable = any(
        item.component == "mount" and item.strategy == "copy" for item in plan.items
    )
    if durable and quiescence_check is None:
        raise StorageMigrationError(
            "durable migration requires a downstream quiescence_check"
        )
    root = (project_root or Path.cwd()).resolve(strict=False)
    journal = _journal_path(plan, root)
    completed = 0
    try:
        _write_journal(
            plan,
            journal,
            phase="planned",
            mode=mode,
            verify=verify,
            project_root=root,
            items_completed=0,
            source_removed=False,
        )
        _write_journal(
            plan,
            journal,
            phase="copying",
            mode=mode,
            verify=verify,
            project_root=root,
            items_completed=0,
            source_removed=False,
        )
        for item in plan.items:
            if item.strategy == "noop":
                completed += 1
                continue
            if quiescence_check is not None:
                quiescence_check()
            if item.strategy == "rebuild":
                destination = item.destination
                _validate_destination(destination, item.destination_binding)
                if destination.exists() and any(destination.iterdir()):
                    actual = read_storage_binding(destination / ".ledger-project.toml")
                    if actual == item.destination_binding:
                        completed += 1
                        continue
                destination.mkdir(parents=True, exist_ok=True)
                write_storage_binding(destination, item.destination_binding)
            elif item.component == "config":
                if item.destination.exists():
                    raise StorageMigrationError(
                        "config migration destination already exists: "
                        f"{item.destination}"
                    )
                temporary = item.destination.with_name(
                    f".{item.destination.name}.migrating-{plan.migration_id}"
                )
                _copy_file(item.source, temporary)
                temporary.replace(item.destination)
                write_storage_binding(item.destination.parent, item.destination_binding)
            else:
                _validate_destination(item.destination, item.destination_binding)
                temporary, staging_root = _staging_path(
                    item.source, item.destination, plan.migration_id
                )
                if staging_root is not None:
                    if staging_root.exists():
                        shutil.rmtree(staging_root)
                    staging_root.mkdir(parents=True, exist_ok=False)
                elif temporary.exists():
                    shutil.rmtree(temporary)
                _copy_tree(item.source, temporary)
                write_storage_binding(temporary, item.destination_binding)
                _verify(item.source, temporary, verify)
                if item.destination.exists():
                    if any(item.destination.iterdir()):
                        raise StorageMigrationError(
                            "migration destination became non-empty: "
                            f"{item.destination}"
                        )
                    item.destination.rmdir()
                temporary.replace(item.destination)
                if staging_root is not None:
                    staging_root.rmdir()
            completed += 1
            _write_journal(
                plan,
                journal,
                phase="copying",
                mode=mode,
                verify=verify,
                project_root=root,
                items_completed=completed,
                source_removed=False,
            )
        _write_journal(
            plan,
            journal,
            phase="verified",
            mode=mode,
            verify=verify,
            project_root=root,
            items_completed=completed,
            source_removed=False,
        )
        if quiescence_check is not None:
            quiescence_check()
        if isinstance(plan.config_changes, LedgerLocalOverrides):
            write_ledger_local_config(
                root / ".ledger" / "ledger.local.toml",
                plan.config_changes,
                delete_if_empty=True,
            )
        else:
            write_ledger_manifest(root / ".ledger" / "ledger.toml", plan.config_changes)
        _write_journal(
            plan,
            journal,
            phase="config-switched",
            mode=mode,
            verify=verify,
            project_root=root,
            items_completed=completed,
            source_removed=False,
        )
        _write_journal(
            plan,
            journal,
            phase="complete",
            mode=mode,
            verify=verify,
            project_root=root,
            items_completed=completed,
            source_removed=False,
        )
        return StorageMigrationResult(
            plan.migration_id, "complete", completed, False, journal
        )
    except Exception as exc:
        try:
            _write_journal(
                plan,
                journal,
                phase="failed",
                mode=mode,
                verify=verify,
                project_root=root,
                items_completed=completed,
                source_removed=False,
                error=str(exc),
            )
        except Exception:
            pass
        if isinstance(exc, StorageMigrationError):
            raise
        raise StorageMigrationError(
            f"storage migration {plan.migration_id} failed: {exc}"
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
    if isinstance(items_completed_raw, bool) or not isinstance(items_completed_raw, int):
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


def inspect_storage_migration(journal_path: Path) -> StorageMigrationJournal:
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


def recover_storage_migration(
    journal_path: Path,
) -> StorageMigrationResult:
    """Return completed journal result or refuse incomplete recovery."""
    journal = inspect_storage_migration(journal_path)
    if journal.phase == "complete":
        return StorageMigrationResult(
            journal.migration_id,
            journal.phase,
            journal.items_completed
            if journal.items_completed is not None
            else len(journal.items),
            journal.source_removed,
            journal_path,
        )
    raise StorageMigrationError(
        f"migration journal {journal_path} is in phase {journal.phase}; "
        "Ledgercore 0.5.1 can inspect this journal but cannot "
        "safely resume it automatically",
        code="STORAGE_MIGRATION_MANUAL_INTERVENTION_REQUIRED",
    )


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


__all__ = [
    "MigrationRecoveryCapability",
    "StorageMigrationItem",
    "StorageMigrationJournal",
    "StorageMigrationJournalItem",
    "StorageMigrationPlan",
    "StorageMigrationResult",
    "execute_storage_migration",
    "inspect_storage_migration",
    "plan_schema_v2_to_v3",
    "plan_storage_migration",
    "recover_storage_migration",
]
