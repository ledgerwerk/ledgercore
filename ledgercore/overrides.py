"""Schema-aware local Ledger project overlays."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ledgercore.errors import LedgerLayoutError
from ledgercore.manifest import (
    LedgerLocalOverrides,
    LedgerProjectManifest,
    MountOverride,
    StorageKind,
    parse_ledger_local_overrides_v3,
)


def set_local_mount_override(
    base: LedgerProjectManifest,
    overrides: LedgerLocalOverrides,
    tool_name: str,
    mount_name: str,
    *,
    storage: StorageKind | None = None,
    root: str | None = None,
) -> LedgerLocalOverrides:
    """Return a new local overlay with one existing mount override set."""
    registration = base.ledgers.get(tool_name)
    if registration is None:
        raise LedgerLayoutError(f"unknown tool {tool_name!r}")
    if mount_name not in registration.mounts:
        raise LedgerLayoutError(f"unknown mount {tool_name}.{mount_name}")
    if storage != "external" and root is not None:
        effective = storage or registration.mounts[mount_name].storage
        if effective != "external":
            raise LedgerLayoutError("root is only allowed for external storage")
    if storage == "external" and root is None:
        inherited = registration.mounts[mount_name].external_root
        existing = overrides.ledgers.get(tool_name, {}).get(mount_name)
        if inherited is None and (existing is None or existing.external_root is None):
            raise LedgerLayoutError("root is required when selecting external storage")
    if storage is None and root is None:
        return clear_local_mount_override(base, overrides, tool_name, mount_name)

    tools = {name: dict(mounts) for name, mounts in overrides.ledgers.items()}
    tool_overrides = tools.setdefault(tool_name, {})
    tool_overrides[mount_name] = MountOverride(storage=storage, external_root=root)
    return LedgerLocalOverrides(
        schema_version=3,
        ledgers=MappingProxyType(
            {
                name: MappingProxyType(dict(mounts))
                for name, mounts in tools.items()
                if mounts
            }
        ),
    )


def clear_local_mount_override(
    base: LedgerProjectManifest,
    overrides: LedgerLocalOverrides,
    tool_name: str,
    mount_name: str,
) -> LedgerLocalOverrides:
    """Return a new local overlay without one existing mount override."""
    if tool_name not in base.ledgers:
        raise LedgerLayoutError(f"unknown tool {tool_name!r}")
    if mount_name not in base.ledgers[tool_name].mounts:
        raise LedgerLayoutError(f"unknown mount {tool_name}.{mount_name}")
    tools: dict[str, dict[str, MountOverride]] = {
        name: dict(mounts) for name, mounts in overrides.ledgers.items()
    }
    mounts = tools.get(tool_name)
    if mounts is not None:
        mounts.pop(mount_name, None)
        if not mounts:
            tools.pop(tool_name, None)
    return LedgerLocalOverrides(
        schema_version=3,
        ledgers=MappingProxyType(
            {
                name: MappingProxyType(dict(mounts))
                for name, mounts in tools.items()
                if mounts
            }
        ),
    )


def parse_local_overrides(
    document: Mapping[str, object],
    *,
    base: LedgerProjectManifest,
) -> LedgerLocalOverrides:
    """Compatibility name for schema-3 local overlay parsing."""
    return parse_ledger_local_overrides_v3(document, base=base)


__all__ = [
    "clear_local_mount_override",
    "parse_local_overrides",
    "set_local_mount_override",
]
