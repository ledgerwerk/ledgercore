"""Ledger project manifest models and schema-versioned parsing."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, TypeVar, cast

from ledgercore.config import LedgerProjectLocator
from ledgercore.errors import LedgerLayoutError

StorageKind = Literal["project", "external", "user-data", "cache"]
MountSource = Literal["manifest", "local"]
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "project", "ledgers"})
_PROJECT_FIELDS = frozenset({"uuid", "name"})
_LEDGER_FIELDS = frozenset({"mounts"})
_MOUNT_FIELDS = frozenset({"storage", "root"})
_LOCAL_TOP_LEVEL_FIELDS = frozenset({"schema_version", "ledgers"})
_LOCAL_MOUNT_FIELDS = frozenset({"storage", "root"})

T = TypeVar("T")


def _freeze(values: Mapping[str, T] | dict[str, T]) -> Mapping[str, T]:
    return cast(Mapping[str, T], MappingProxyType(dict(values)))


def _expect_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LedgerLayoutError(f"{field_name} must be a table")
    return cast(Mapping[str, Any], value)


def _unknown(
    mapping: Mapping[str, Any], field_name: str, allowed: frozenset[str]
) -> None:
    fields = sorted(set(mapping) - set(allowed))
    if fields:
        raise LedgerLayoutError(
            f"{field_name} contains unsupported field(s): {', '.join(fields)}"
        )


def _string(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise LedgerLayoutError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise LedgerLayoutError(f"{field_name} must not be empty")
    return value


def _token(value: Any, field_name: str) -> str:
    text = _string(value, field_name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise LedgerLayoutError(
            f"{field_name} must match {_TOKEN_RE.pattern!r}: {text!r}"
        )
    return text


def _uuid(value: Any, field_name: str) -> str:
    try:
        return str(uuid.UUID(_string(value, field_name)))
    except ValueError as exc:
        raise LedgerLayoutError(f"{field_name} must be a valid UUID") from exc


def _storage(value: Any, field_name: str) -> StorageKind:
    value = _string(value, field_name)
    if value not in {"project", "external", "user-data", "cache"}:
        raise LedgerLayoutError(
            f"{field_name} must be one of project, external, user-data, or cache"
        )
    return cast(StorageKind, value)


def _root(value: Any, field_name: str, *, allow_absolute: bool) -> str:
    text = _string(value, field_name)
    if "\x00" in text or "\\" in text:
        raise LedgerLayoutError(f"{field_name} contains an invalid path")
    if text.startswith("~") and text != "~" and not text.startswith("~/"):
        raise LedgerLayoutError(f"{field_name} has an invalid home expansion")
    if text.startswith("/") and not allow_absolute:
        raise LedgerLayoutError(
            f"{field_name} must be project-relative in the committed manifest"
        )
    return text


@dataclass(frozen=True)
class MountDefinition:
    name: str
    storage: StorageKind
    external_root: str | None = None


@dataclass(frozen=True)
class LedgerRegistration:
    name: str
    mounts: Mapping[str, MountDefinition]


@dataclass(frozen=True)
class LedgerProjectManifest:
    schema_version: int
    project_uuid: str
    project_name: str | None
    ledgers: Mapping[str, LedgerRegistration]


@dataclass(frozen=True)
class MountOverride:
    storage: StorageKind | None = None
    external_root: str | None = None


@dataclass(frozen=True)
class LedgerLocalOverrides:
    schema_version: int
    ledgers: Mapping[str, Mapping[str, MountOverride]]


@dataclass(frozen=True)
class EffectiveMount:
    name: str
    storage: StorageKind
    external_root: str | None
    source: MountSource


@dataclass(frozen=True)
class EffectiveLedgerRegistration:
    name: str
    mounts: Mapping[str, EffectiveMount]


@dataclass(frozen=True)
class LoadedLedgerProject:
    locator: LedgerProjectLocator
    manifest: LedgerProjectManifest
    local_overrides: LedgerLocalOverrides
    effective_ledgers: Mapping[str, EffectiveLedgerRegistration]


def parse_ledger_manifest_v3(
    document: Mapping[str, Any],
    *,
    allow_absolute_external_root: bool = False,
) -> LedgerProjectManifest:
    """Parse a strict schema-3 project manifest from a plain mapping."""
    _unknown(document, "manifest", _TOP_LEVEL_FIELDS)
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise LedgerLayoutError("schema_version must be an integer")
    if version != 3:
        raise LedgerLayoutError(f"schema_version must be 3, got {version}")

    project = _expect_mapping(document.get("project"), "project")
    _unknown(project, "project", _PROJECT_FIELDS)
    project_uuid = _uuid(project.get("uuid"), "project.uuid")
    project_name = (
        _string(project.get("name"), "project.name") if "name" in project else None
    )

    ledgers_table = _expect_mapping(document.get("ledgers", {}), "ledgers")
    ledgers: dict[str, LedgerRegistration] = {}
    for raw_name, raw_ledger in ledgers_table.items():
        name = _token(raw_name, "ledgers key")
        ledger = _expect_mapping(raw_ledger, f"ledgers.{name}")
        _unknown(ledger, f"ledgers.{name}", _LEDGER_FIELDS)
        mounts_table = _expect_mapping(ledger.get("mounts"), f"ledgers.{name}.mounts")
        if not mounts_table:
            raise LedgerLayoutError(f"ledgers.{name}.mounts must not be empty")
        mounts: dict[str, MountDefinition] = {}
        for raw_mount_name, raw_mount in mounts_table.items():
            mount_name = _token(raw_mount_name, f"ledgers.{name}.mounts key")
            field = f"ledgers.{name}.mounts.{mount_name}"
            mount = _expect_mapping(raw_mount, field)
            _unknown(mount, field, _MOUNT_FIELDS)
            storage = _storage(mount.get("storage"), f"{field}.storage")
            external_root = None
            if "root" in mount:
                if storage != "external":
                    raise LedgerLayoutError(
                        f"{field}.root is only allowed for external storage"
                    )
                external_root = _root(
                    mount.get("root"),
                    f"{field}.root",
                    allow_absolute=allow_absolute_external_root,
                )
            elif storage == "external":
                raise LedgerLayoutError(
                    f"{field}.root is required for external storage"
                )
            mounts[mount_name] = MountDefinition(
                name=mount_name,
                storage=storage,
                external_root=external_root,
            )
        ledgers[name] = LedgerRegistration(name=name, mounts=_freeze(mounts))

    return LedgerProjectManifest(
        schema_version=3,
        project_uuid=project_uuid,
        project_name=project_name,
        ledgers=_freeze(ledgers),
    )


def parse_ledger_local_overrides_v3(
    document: Mapping[str, Any],
    *,
    base: LedgerProjectManifest,
    allow_absolute_external_root: bool = True,
) -> LedgerLocalOverrides:
    """Parse the strict schema-3 local mount overlay."""
    _unknown(document, "local config", _LOCAL_TOP_LEVEL_FIELDS)
    version = document.get("schema_version", 3)
    if isinstance(version, bool) or not isinstance(version, int):
        raise LedgerLayoutError("schema_version must be an integer")
    if version != 3:
        raise LedgerLayoutError(f"schema_version must be 3, got {version}")

    raw_ledgers = _expect_mapping(document.get("ledgers", {}), "ledgers")
    ledgers: dict[str, Mapping[str, MountOverride]] = {}
    for raw_tool, raw_tool_value in raw_ledgers.items():
        tool = _token(raw_tool, "ledgers key")
        if tool not in base.ledgers:
            raise LedgerLayoutError(f"local config references unknown tool {tool!r}")
        tool_table = _expect_mapping(raw_tool_value, f"ledgers.{tool}")
        _unknown(tool_table, f"ledgers.{tool}", frozenset({"mounts"}))
        raw_mounts = _expect_mapping(
            tool_table.get("mounts", {}), f"ledgers.{tool}.mounts"
        )
        overrides: dict[str, MountOverride] = {}
        for raw_mount_name, raw_override in raw_mounts.items():
            mount_name = _token(raw_mount_name, f"ledgers.{tool}.mounts key")
            if mount_name not in base.ledgers[tool].mounts:
                raise LedgerLayoutError(
                    f"local config references unknown mount {tool}.{mount_name}"
                )
            field = f"ledgers.{tool}.mounts.{mount_name}"
            override = _expect_mapping(raw_override, field)
            _unknown(override, field, _LOCAL_MOUNT_FIELDS)
            storage = (
                _storage(override.get("storage"), f"{field}.storage")
                if "storage" in override
                else None
            )
            external_root = (
                _root(
                    override.get("root"),
                    f"{field}.root",
                    allow_absolute=allow_absolute_external_root,
                )
                if "root" in override
                else None
            )
            effective_storage = storage or base.ledgers[tool].mounts[mount_name].storage
            if external_root is not None and effective_storage != "external":
                raise LedgerLayoutError(
                    f"{field}.root requires effective storage 'external'"
                )
            if storage == "external" and external_root is None:
                inherited = base.ledgers[tool].mounts[mount_name].external_root
                if inherited is None:
                    raise LedgerLayoutError(
                        f"{field}.root is required for external storage"
                    )
            overrides[mount_name] = MountOverride(
                storage=storage,
                external_root=external_root,
            )
        if overrides:
            ledgers[tool] = _freeze(overrides)

    return LedgerLocalOverrides(schema_version=3, ledgers=_freeze(ledgers))


def apply_ledger_local_overrides(
    manifest: LedgerProjectManifest,
    overrides: LedgerLocalOverrides,
) -> Mapping[str, EffectiveLedgerRegistration]:
    """Apply mount overrides using schema-aware, non-recursive semantics."""
    if overrides.schema_version != 3:
        raise LedgerLayoutError("schema-3 overlay requires schema_version 3")
    effective: dict[str, EffectiveLedgerRegistration] = {}
    for tool_name, registration in manifest.ledgers.items():
        tool_overrides = overrides.ledgers.get(tool_name, {})
        mounts: dict[str, EffectiveMount] = {}
        for mount_name, mount in registration.mounts.items():
            override = tool_overrides.get(mount_name)
            if override is None:
                storage = mount.storage
                root = mount.external_root
                source: MountSource = "manifest"
            else:
                storage = override.storage or mount.storage
                root = (
                    override.external_root
                    if override.external_root is not None
                    else (
                        None
                        if override.storage is not None
                        and override.storage != mount.storage
                        else mount.external_root
                    )
                )
                source = "local"
            if storage == "external" and root is None:
                raise LedgerLayoutError(
                    f"effective ledgers.{tool_name}.mounts.{mount_name}.root "
                    "is required"
                )
            if storage != "external" and root is not None:
                raise LedgerLayoutError(
                    f"effective ledgers.{tool_name}.mounts.{mount_name}.root "
                    "is not allowed"
                )
            mounts[mount_name] = EffectiveMount(
                name=mount_name,
                storage=storage,
                external_root=root,
                source=source,
            )
        effective[tool_name] = EffectiveLedgerRegistration(
            name=tool_name,
            mounts=_freeze(mounts),
        )
    unknown_tools = set(overrides.ledgers) - set(manifest.ledgers)
    if unknown_tools:
        raise LedgerLayoutError(
            f"local config references unknown tool {sorted(unknown_tools)[0]!r}"
        )
    return _freeze(effective)


__all__ = [
    "EffectiveLedgerRegistration",
    "EffectiveMount",
    "LedgerLocalOverrides",
    "LedgerProjectManifest",
    "LedgerRegistration",
    "LoadedLedgerProject",
    "MountDefinition",
    "MountOverride",
    "MountSource",
    "StorageKind",
    "apply_ledger_local_overrides",
    "parse_ledger_local_overrides_v3",
    "parse_ledger_manifest_v3",
]
