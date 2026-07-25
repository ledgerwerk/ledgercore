"""Deterministic JSON envelope models.

Ledgercore should expose deterministic conversion to plain mappings and
deterministic JSON text. It should not call ``typer.echo``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Literal

from .deprecation import CLIWarning


@dataclass(frozen=True)
class SuccessEnvelope:
    """Success envelope for ``ledgerwerk.cli.v1``."""

    schema: str = "ledgerwerk.cli.v1"
    ok: Literal[True] = True
    tool: str = ""
    command: str = ""
    result: Mapping[str, object] = field(default_factory=dict)
    events: tuple[Mapping[str, object], ...] = ()
    warnings: tuple[CLIWarning, ...] = ()

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "tool": self.tool,
            "command": self.command,
            "result": dict(self.result),
            "events": list(self.events),
            "warnings": [asdict(w) for w in self.warnings],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_mapping(), indent=2, sort_keys=True, default=str)


@dataclass(frozen=True)
class ErrorEnvelope:
    """Error envelope for ``ledgerwerk.cli.v1``."""

    schema: str = "ledgerwerk.cli.v1"
    ok: Literal[False] = False
    tool: str = ""
    command: str = ""
    error: Mapping[str, object] = field(default_factory=dict)
    events: tuple[Mapping[str, object], ...] = ()
    warnings: tuple[CLIWarning, ...] = ()

    def as_mapping(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "tool": self.tool,
            "command": self.command,
            "error": dict(self.error),
            "events": list(self.events),
            "warnings": [asdict(w) for w in self.warnings],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_mapping(), indent=2, sort_keys=True, default=str)
