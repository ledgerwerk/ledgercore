"""Framework-neutral exit codes and error model.

Do not add Typer or Click as a Ledgercore runtime dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum


class ExitCode(IntEnum):
    """Canonical Ledgerwerk exit codes."""

    SUCCESS = 0
    DOMAIN_FAILURE = 1
    USAGE = 2
    UNAVAILABLE = 3
    CONFLICT = 4
    EXTERNAL_FAILURE = 5


@dataclass
class CLIError(Exception):
    """Framework-neutral CLI error.

    Memoryledger's domain exceptions can remain, but the CLI boundary must
    translate them into ``CLIError``.

    Recommended canonical error code format: lowercase snake case.
    Preserve the old uppercase code under ``details["domain_code"]``.
    """

    code: str
    message: str
    exit_code: ExitCode = ExitCode.DOMAIN_FAILURE
    remediation: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
