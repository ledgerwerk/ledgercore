"""Shared ledger workspace configuration conventions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ledgercore.errors import LedgerConfigError
from ledgercore.paths import ConfigLocator, locate_config

LEDGER_CONFIG_FILENAMES: tuple[str, ...] = (".ledger.toml", "ledger.toml")
LEDGER_PROJECT_MANIFEST = ".ledger/ledger.toml"
LEDGER_PROJECT_LOCAL_CONFIG = ".ledger/ledger.local.toml"
LEDGER_LEGACY_SHARED_CONFIGS = LEDGER_CONFIG_FILENAMES

LedgerProjectSource = Literal["canonical", "legacy-shared", "legacy-tool", "default"]


@dataclass(frozen=True)
class LedgerProjectLocator:
    """Result of canonical or legacy ledger project discovery."""

    project_root: Path
    config_root: Path
    manifest_path: Path
    local_config_path: Path
    source: LedgerProjectSource

    @property
    def is_legacy(self) -> bool:
        """Return whether the project was discovered through a legacy config."""
        return self.source in {"legacy-shared", "legacy-tool"}


def ledger_config_filenames(
    *legacy_filenames: str,
    include_visible: bool = True,
) -> tuple[str, ...]:
    """Return canonical ledger config names followed by legacy fallbacks."""
    base = LEDGER_CONFIG_FILENAMES if include_visible else (".ledger.toml",)
    return (*base, *legacy_filenames)


def locate_ledger_config(
    start: Path,
    *,
    legacy_filenames: tuple[str, ...] = (),
    default: bool = False,
    default_filename: str = ".ledger.toml",
) -> ConfigLocator | None:
    """Locate a canonical ledger config or a caller-provided legacy fallback."""
    return locate_config(
        start,
        ledger_config_filenames(*legacy_filenames),
        default_filename=default_filename if default else None,
    )


def _project_search_start(start: Path) -> Path:
    """Normalize the project search start without requiring existence."""
    search_start = start.resolve(strict=False)
    if start.exists() and start.is_file():
        return search_start.parent
    return search_start


def locate_ledger_project(
    start: Path,
    *,
    legacy_tool_filenames: tuple[str, ...] = (),
    default: bool = False,
) -> LedgerProjectLocator | None:
    """Locate a canonical Ledger project manifest or a legacy fallback."""
    search_start = _project_search_start(start)
    current = search_start
    while True:
        manifest_path = (current / LEDGER_PROJECT_MANIFEST).resolve(strict=False)
        if manifest_path.is_file():
            config_root = manifest_path.parent
            return LedgerProjectLocator(
                project_root=current,
                config_root=config_root,
                manifest_path=manifest_path,
                local_config_path=(current / LEDGER_PROJECT_LOCAL_CONFIG).resolve(
                    strict=False
                ),
                source="canonical",
            )

        shared_candidates: tuple[tuple[str, LedgerProjectSource], ...] = (
            (".ledger.toml", "legacy-shared"),
            ("ledger.toml", "legacy-shared"),
        )
        for filename, source in shared_candidates:
            candidate = (current / filename).resolve(strict=False)
            if candidate.is_file():
                return LedgerProjectLocator(
                    project_root=current,
                    config_root=current,
                    manifest_path=candidate,
                    local_config_path=(current / LEDGER_PROJECT_LOCAL_CONFIG).resolve(
                        strict=False
                    ),
                    source=source,
                )

        for filename in legacy_tool_filenames:
            candidate = (current / filename).resolve(strict=False)
            if candidate.is_file():
                return LedgerProjectLocator(
                    project_root=current,
                    config_root=current,
                    manifest_path=candidate,
                    local_config_path=(current / LEDGER_PROJECT_LOCAL_CONFIG).resolve(
                        strict=False
                    ),
                    source="legacy-tool",
                )

        parent = current.parent
        if parent == current:
            break
        current = parent

    if not default:
        return None

    config_root = (search_start / ".ledger").resolve(strict=False)
    return LedgerProjectLocator(
        project_root=search_start,
        config_root=config_root,
        manifest_path=(search_start / LEDGER_PROJECT_MANIFEST).resolve(strict=False),
        local_config_path=(search_start / LEDGER_PROJECT_LOCAL_CONFIG).resolve(
            strict=False
        ),
        source="default",
    )


def select_tool_config(
    document: Mapping[str, Any],
    tool_name: str,
    *,
    table_name: str = "tools",
) -> Mapping[str, Any]:
    """Select and validate a tool-specific config table."""
    tools = document.get(table_name)
    if not isinstance(tools, Mapping):
        raise LedgerConfigError(f"missing [{table_name}] table")
    tool_config = tools.get(tool_name)
    if not isinstance(tool_config, Mapping):
        raise LedgerConfigError(f"missing [{table_name}.{tool_name}] table")
    return tool_config


def select_project_config(
    document: Mapping[str, Any],
    *,
    table_name: str = "project",
) -> Mapping[str, Any]:
    """Select and validate the shared project table, defaulting to empty."""
    project = document.get(table_name, {})
    if not isinstance(project, Mapping):
        raise LedgerConfigError(f"[{table_name}] must be a table")
    return project
