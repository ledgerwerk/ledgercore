"""Storage description and validation helpers.

Pure result builders around existing layout APIs.
"""

from __future__ import annotations

from typing import Any


def describe_storage(
    loaded_project: Any,
    layout: Any,
    report: Any,
) -> dict[str, object]:
    """Build a storage description mapping from resolved layout state."""
    result: dict[str, object] = {
        "project_root": str(getattr(layout, "project_root", "")),
        "manifest_path": str(getattr(layout, "manifest_path", "")),
        "local_config_path": str(getattr(layout, "local_config_path", "")),
        "tool_config_path": str(getattr(layout, "tool_config_path", "")),
    }
    mounts = []
    for mount_name, mount in getattr(layout, "mounts", {}).items():
        mounts.append(
            {
                "name": mount_name,
                "storage": getattr(mount, "storage", ""),
                "resolved_path": str(getattr(mount, "path", "")),
                "scope": getattr(mount, "scope", ""),
                "binding_path": str(getattr(mount, "binding_path", "")),
                "binding_valid": bool(getattr(mount, "binding_path", None)),
                "override_active": getattr(mount, "override_active", False),
            }
        )
    result["mounts"] = mounts
    legacy_paths = []
    for attr in ("legacy_config_path", "legacy_data_path"):
        val = getattr(layout, attr, None) or getattr(loaded_project, attr, None)
        if val:
            legacy_paths.append(str(val))
    result["legacy_paths"] = legacy_paths
    return result


def describe_storage_validation(
    report: Any, *, strict: bool = False
) -> dict[str, object]:
    """Build a validation result from a storage report."""
    return {
        "valid": bool(getattr(report, "valid", True)),
        "status": "ok" if getattr(report, "valid", True) else "invalid",
        "strict": strict,
        "issues": [
            str(r.reason)
            for r in getattr(report, "results", [])
            if not getattr(r, "valid", True)
        ],
    }
