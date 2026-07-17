"""Pure path formulas for Ledgercore schema-3 storage."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ledgercore.ids import slugify_ref
from ledgercore.paths import ensure_inside_base


def derive_tool_config_path(project_root: Path, tool_name: str) -> Path:
    """Derive the fixed project-local configuration path for a tool."""
    return (
        project_root.resolve(strict=False) / ".ledger" / tool_name / "config.toml"
    ).resolve(strict=False)


def derive_project_mount_path(
    project_root: Path, tool_name: str, mount_name: str
) -> Path:
    """Derive a project-scoped mount below the checkout's ``.ledger`` tree."""
    return (
        project_root.resolve(strict=False) / ".ledger" / tool_name / mount_name
    ).resolve(strict=False)


def resolve_external_root(root: Path | str, *, project_root: Path) -> Path:
    """Resolve an external root relative to the project with explicit ``~`` support."""
    raw = os.fspath(root)
    if raw.startswith("~"):
        home = os.environ.get("HOME")
        if home and (raw == "~" or raw.startswith("~/")):
            raw = home if raw == "~" else os.path.join(home, raw[2:])
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def derive_external_mount_path(
    external_root: Path | str,
    tool_name: str,
    project_uuid: str,
    mount_name: str,
    *,
    project_root: Path,
) -> Path:
    """Derive a project-scoped mount below an external root."""
    root = resolve_external_root(external_root, project_root=project_root)
    return ensure_inside_base(
        root,
        root / tool_name / project_uuid / mount_name,
        field_name="external mount path",
    )


def derive_user_data_mount_path(
    user_data_root: Path,
    tool_name: str,
    project_uuid: str,
    mount_name: str,
) -> Path:
    """Derive a project-scoped mount below the Ledgerwerk user-data root."""
    root = user_data_root.resolve(strict=False)
    return ensure_inside_base(
        root,
        root / tool_name / project_uuid / mount_name,
        field_name="user-data mount path",
    )


def derive_cache_mount_path(
    user_cache_root: Path,
    tool_name: str,
    project_uuid: str,
    checkout_id: str,
    mount_name: str,
) -> Path:
    """Derive a checkout-scoped cache mount below the user-cache root."""
    root = user_cache_root.resolve(strict=False)
    return ensure_inside_base(
        root,
        root / tool_name / project_uuid / checkout_id / mount_name,
        field_name="cache mount path",
    )


def derive_checkout_id(project_root: Path) -> str:
    """Derive a deterministic, readable checkout identity."""
    resolved = project_root.resolve(strict=False)
    normalized = os.path.normcase(os.fspath(resolved))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{slugify_ref(resolved.name)}-{digest}"


__all__ = [
    "derive_cache_mount_path",
    "derive_checkout_id",
    "derive_external_mount_path",
    "derive_project_mount_path",
    "derive_tool_config_path",
    "derive_user_data_mount_path",
    "resolve_external_root",
]
