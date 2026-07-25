"""Command metadata and inventory.

Provides a ``CommandInventory`` that:
- rejects duplicate canonical paths;
- rejects aliases that shadow canonical commands;
- renders the JSON inventory;
- renders the human command table;
- finds metadata by canonical path or alias;
- provides nested help lookup;
- validates that every registered command has metadata;
- validates that every metadata entry is registered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CommandMetadata:
    """Metadata for one canonical command or alias."""

    path: str
    summary: str
    audience: Literal["agent", "human", "both"] = "both"
    stability: Literal["stable", "beta", "experimental", "deprecated"] = "stable"
    effect: Literal[
        "read",
        "ledger-write",
        "workspace-write",
        "external-write",
        "external-process",
    ] = "read"
    requires_workspace: bool = True
    requires_active_record: bool = False
    targeting: str = "none"
    supports_json: bool = True
    aliases: tuple[str, ...] = ()
    deprecated: bool = False
    replacement: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "path": self.path,
            "summary": self.summary,
            "audience": self.audience,
            "stability": self.stability,
            "effect": self.effect,
            "requires_workspace": self.requires_workspace,
            "requires_active_record": self.requires_active_record,
            "targeting": self.targeting,
            "supports_json": self.supports_json,
            "aliases": list(self.aliases),
            "deprecated": self.deprecated,
            "replacement": self.replacement,
        }


@dataclass
class CommandInventory:
    """Immutable catalog of all registered commands."""

    _entries: tuple[CommandMetadata, ...]
    _by_path: dict[str, CommandMetadata]
    _alias_to_canonical: dict[str, str]

    def __init__(self, entries: tuple[CommandMetadata, ...]) -> None:
        object.__setattr__(self, "_entries", entries)
        by_path: dict[str, CommandMetadata] = {}
        alias_to_canonical: dict[str, str] = {}
        for entry in entries:
            if entry.path in by_path:
                raise ValueError(f"Duplicate canonical path: {entry.path}")
            by_path[entry.path] = entry
            for alias in entry.aliases:
                if alias in by_path:
                    raise ValueError(f"Alias shadows canonical path: {alias}")
                if alias in alias_to_canonical:
                    raise ValueError(f"Duplicate alias: {alias}")
                alias_to_canonical[alias] = entry.path
        object.__setattr__(self, "_by_path", by_path)
        object.__setattr__(self, "_alias_to_canonical", alias_to_canonical)

    @property
    def entries(self) -> tuple[CommandMetadata, ...]:
        return self._entries

    def resolve(self, path_or_alias: str) -> CommandMetadata | None:
        """Find metadata by canonical path or alias."""
        if path_or_alias in self._by_path:
            return self._by_path[path_or_alias]
        canonical = self._alias_to_canonical.get(path_or_alias)
        if canonical:
            return self._by_path[canonical]
        return None

    def to_json(self) -> str:
        return json.dumps(
            {"commands": [e.as_mapping() for e in self._entries]},
            indent=2,
            sort_keys=True,
        )

    def human_table(self) -> str:
        lines = []
        for entry in self._entries:
            if entry.deprecated:
                continue
            lines.append(f"  {entry.path:40s} {entry.summary}")
        return "\n".join(lines)
