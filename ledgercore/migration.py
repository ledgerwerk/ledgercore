"""Explicit, verified Ledgercore storage migration planning and execution."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Callable
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
    write_storage_binding,
)
from ledgercore.tomlio import write_ledger_local_config, write_ledger_manifest

MigrationStrategy = Literal["copy", "rebuild", "noop"]
MigrationMode = Literal["copy", "move"]
VerifyMode = Literal["sha256", "size"]


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
    source_removed: bool
    journal_path: Path


@dataclass(frozen=True)
class StorageMigrationJournal:
    migration_id: str
    phase: str
    project_uuid: str
    journal_path: Path
    items: tuple[StorageMigrationItem, ...]
    error: str | None = None


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
    plan: StorageMigrationPlan, path: Path, phase: str, error: str | None = None
) -> None:
    doc = table()
    doc.add("schema_version", 1)
    doc.add("migration_id", plan.migration_id)
    doc.add("project_uuid", plan.project_uuid)
    doc.add("phase", phase)
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
    mode: MigrationMode = "move",
    verify: VerifyMode = "sha256",
    quiescence_check: Callable[[], None] | None = None,
    project_root: Path | None = None,
) -> StorageMigrationResult:
    """Execute a previously validated plan with journaled, verified switching."""
    if mode not in {"copy", "move"} or verify not in {"sha256", "size"}:
        raise StorageMigrationError("unsupported migration mode or verification mode")
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
        _write_journal(plan, journal, "planned")
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
                temporary = item.destination.with_name(
                    f".{item.destination.name}.migrating-{plan.migration_id}"
                )
                if temporary.exists():
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
            completed += 1
            _write_journal(plan, journal, "verified")
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
        _write_journal(plan, journal, "config-switched")
        removed = False
        if mode == "move":
            for item in plan.items:
                if (
                    item.strategy == "copy"
                    and item.source.exists()
                    and item.source != item.destination
                ):
                    if item.component == "config":
                        item.source.unlink()
                    else:
                        shutil.rmtree(item.source)
            removed = True
        _write_journal(plan, journal, "complete")
        return StorageMigrationResult(
            plan.migration_id, "complete", completed, removed, journal
        )
    except Exception as exc:
        try:
            _write_journal(plan, journal, "failed", str(exc))
        except Exception:
            pass
        if isinstance(exc, StorageMigrationError):
            raise
        raise StorageMigrationError(
            f"storage migration {plan.migration_id} failed: {exc}"
        ) from exc


def inspect_storage_migration(journal_path: Path) -> StorageMigrationJournal:
    """Read a migration journal for operator or recovery tooling."""
    try:
        document = parse(journal_path.read_text(encoding="utf-8"))
        items: list[StorageMigrationItem] = []
        for row in document.get("items", {}).values():
            binding = StorageBinding(
                1,
                3,
                document["project_uuid"],
                None,
                row["tool"],
                row["mount"],
                "project",
            )
            items.append(
                StorageMigrationItem(
                    row["component"],
                    row["tool"],
                    row["mount"],
                    Path(row["source"]),
                    Path(row["destination"]),
                    binding,
                    binding,
                    row["strategy"],
                )
            )
        return StorageMigrationJournal(
            document["migration_id"],
            document["phase"],
            document["project_uuid"],
            journal_path,
            tuple(items),
            document.get("error"),
        )
    except Exception as exc:
        raise StorageMigrationError(
            f"unable to inspect migration journal {journal_path}: {exc}"
        ) from exc


def recover_storage_migration(journal_path: Path) -> StorageMigrationResult:
    """Return the durable result of a completed journal or refuse failed recovery."""
    journal = inspect_storage_migration(journal_path)
    if journal.phase == "complete":
        return StorageMigrationResult(
            journal.migration_id, journal.phase, len(journal.items), True, journal_path
        )
    raise StorageMigrationError(
        f"migration journal {journal_path} is in phase {journal.phase}; "
        "recovery requires the original plan"
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
    "StorageMigrationItem",
    "StorageMigrationJournal",
    "StorageMigrationPlan",
    "StorageMigrationResult",
    "execute_storage_migration",
    "inspect_storage_migration",
    "plan_schema_v2_to_v3",
    "plan_storage_migration",
    "recover_storage_migration",
]
