"""Round-trip TOML ownership for Ledgercore project configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tomlkit import dumps, parse, table
from tomlkit.items import AbstractTable

from ledgercore.atomic import atomic_write_text
from ledgercore.config import locate_ledger_project
from ledgercore.errors import LedgerConfigError, TomlConfigError
from ledgercore.layout import parse_ledger_project_manifest
from ledgercore.manifest import (
    LedgerLocalOverrides,
    LedgerProjectManifest,
    LoadedLedgerProject,
    apply_ledger_local_overrides,
    parse_ledger_local_overrides_v3,
)
from ledgercore.overrides import (
    clear_local_mount_override as _clear_local_mount_override,
)
from ledgercore.overrides import (
    set_local_mount_override as _set_local_mount_override,
)


def _read_document(path: Path) -> Any:
    try:
        return parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TomlConfigError(
            f"Unable to read TOML configuration {path}: {exc}"
        ) from exc


def _as_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _as_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_plain(item) for item in value]
    return value


def read_ledger_manifest(path: Path) -> Any:
    """Read and parse a Ledger project manifest from TOML."""
    document = _read_document(path)
    try:
        plain = _as_plain(document)
        return parse_ledger_project_manifest(plain)
    except TomlConfigError:
        raise
    except LedgerConfigError:
        raise
    except Exception as exc:
        raise TomlConfigError(f"Invalid Ledger manifest {path}: {exc}") from exc


def _manifest_document(manifest: LedgerProjectManifest) -> Any:
    if manifest.schema_version != 3:
        raise TomlConfigError("writers emit schema version 3 only")
    doc = table()
    doc.add("schema_version", 3)
    project = table()
    project.add("uuid", manifest.project_uuid)
    if manifest.project_name is not None:
        project.add("name", manifest.project_name)
    doc.add("project", project)
    ledgers = table()
    for tool_name, registration in manifest.ledgers.items():
        tool = table()
        mounts = table()
        for mount_name, mount in registration.mounts.items():
            mount_table = table()
            mount_table.add("storage", mount.storage)
            if mount.external_root is not None:
                mount_table.add("root", mount.external_root)
            mounts.add(mount_name, mount_table)
        tool.add("mounts", mounts)
        ledgers.add(tool_name, tool)
    doc.add("ledgers", ledgers)
    return doc


def _update_table(target: Any, source: Any) -> None:
    for key in list(target):
        if key not in source:
            del target[key]
    for key, value in source.items():
        if isinstance(value, AbstractTable):
            existing = target.get(key)
            if isinstance(existing, AbstractTable):
                _update_table(existing, value)
            else:
                target[key] = value
        else:
            target[key] = value


def _load_or_create_document(
    path: Path, new_document: Any, preserve_comments: bool
) -> Any:
    if preserve_comments and path.is_file():
        try:
            existing = parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TomlConfigError(
                f"Unable to read TOML configuration {path}: {exc}"
            ) from exc
        _update_table(existing, new_document)
        return existing
    return new_document


def _write_document(path: Path, document: Any) -> None:
    text = dumps(document)
    if not text.endswith("\n"):
        text += "\n"
    try:
        atomic_write_text(path, text)
    except Exception as exc:
        if isinstance(exc, TomlConfigError):
            raise
        raise TomlConfigError(
            f"Unable to write TOML configuration {path}: {exc}"
        ) from exc


def write_ledger_manifest(
    path: Path,
    manifest: LedgerProjectManifest,
    *,
    preserve_comments: bool = True,
) -> None:
    """Atomically write a schema-3 manifest."""
    document = _load_or_create_document(
        path, _manifest_document(manifest), preserve_comments
    )
    _write_document(path, document)


def read_ledger_local_config(
    path: Path,
    *,
    base: LedgerProjectManifest,
) -> LedgerLocalOverrides:
    """Read a schema-3 local overlay against an existing manifest."""
    document = _read_document(path)
    try:
        return parse_ledger_local_overrides_v3(_as_plain(document), base=base)
    except LedgerConfigError:
        raise
    except Exception as exc:
        raise TomlConfigError(
            f"Invalid local Ledger configuration {path}: {exc}"
        ) from exc


def _overrides_document(overrides: LedgerLocalOverrides) -> Any:
    if overrides.schema_version != 3:
        raise TomlConfigError("writers emit schema version 3 only")
    doc = table()
    doc.add("schema_version", 3)
    ledgers = table()
    for tool_name, mounts_mapping in overrides.ledgers.items():
        tool = table()
        mounts = table()
        for mount_name, override in mounts_mapping.items():
            mount = table()
            if override.storage is not None:
                mount.add("storage", override.storage)
            if override.external_root is not None:
                mount.add("root", override.external_root)
            if len(mount):
                mounts.add(mount_name, mount)
        if len(mounts):
            tool.add("mounts", mounts)
            ledgers.add(tool_name, tool)
    if len(ledgers):
        doc.add("ledgers", ledgers)
    return doc


def render_ledger_manifest(manifest: LedgerProjectManifest) -> str:
    """Render a schema-3 manifest to TOML string without writing to file."""
    from tomlkit import dumps

    doc = _manifest_document(manifest)
    return dumps(doc)


def render_ledger_local_config(overrides: LedgerLocalOverrides) -> str:
    """Render schema-3 local overrides to TOML string without writing to file."""
    from tomlkit import dumps

    doc = _overrides_document(overrides)
    return dumps(doc)


def write_ledger_local_config(
    path: Path,
    overrides: LedgerLocalOverrides,
    *,
    preserve_comments: bool = True,
    delete_if_empty: bool = False,
) -> None:
    """Atomically write a schema-3 local overlay."""
    if not overrides.ledgers and delete_if_empty and path.exists():
        try:
            path.unlink()
        except OSError as exc:
            raise TomlConfigError(
                f"Unable to delete empty local configuration {path}: {exc}"
            ) from exc
        return
    document = _load_or_create_document(
        path, _overrides_document(overrides), preserve_comments
    )
    _write_document(path, document)


def load_ledger_project(
    start: Path,
    *,
    legacy_tool_filenames: tuple[str, ...] = (),
) -> LoadedLedgerProject:
    """Locate, read, overlay, and return a schema-3 project."""
    locator = locate_ledger_project(
        start,
        legacy_tool_filenames=legacy_tool_filenames,
    )
    if locator is None or locator.is_legacy:
        raise TomlConfigError(
            f"No canonical .ledger/ledger.toml project found from {start}"
        )
    manifest = read_ledger_manifest(locator.manifest_path)
    if not isinstance(manifest, LedgerProjectManifest) or manifest.schema_version != 3:
        raise TomlConfigError(
            f"{locator.manifest_path} is schema 2; migrate it explicitly "
            "before loading schema 3"
        )
    if locator.local_config_path.is_file():
        local = read_ledger_local_config(locator.local_config_path, base=manifest)
    else:
        local = LedgerLocalOverrides(schema_version=3, ledgers={})
    return LoadedLedgerProject(
        locator=locator,
        manifest=manifest,
        local_overrides=local,
        effective_ledgers=apply_ledger_local_overrides(manifest, local),
    )


def set_local_mount_override(
    project: LoadedLedgerProject,
    tool_name: str,
    mount_name: str,
    *,
    storage: Any = None,
    root: str | None = None,
) -> LedgerLocalOverrides:
    """Return updated local overrides without writing them."""
    return _set_local_mount_override(
        project.manifest,
        project.local_overrides,
        tool_name,
        mount_name,
        storage=storage,
        root=root,
    )


def clear_local_mount_override(
    project: LoadedLedgerProject,
    tool_name: str,
    mount_name: str,
) -> LedgerLocalOverrides:
    """Return local overrides with one mount override removed."""
    return _clear_local_mount_override(
        project.manifest,
        project.local_overrides,
        tool_name,
        mount_name,
    )


__all__ = [
    "clear_local_mount_override",
    "load_ledger_project",
    "read_ledger_local_config",
    "read_ledger_manifest",
    "set_local_mount_override",
    "write_ledger_local_config",
    "write_ledger_manifest",
]
