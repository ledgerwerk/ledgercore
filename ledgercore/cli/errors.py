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


def cli_error_from_exception(exc: Exception) -> CLIError:
    """Translate a Ledgercore domain failure to the stable CLI contract."""
    domain_code = getattr(exc, "code", "LEDGERCORE_ERROR")
    normalized = (
        str(domain_code).lower().replace("storage_migration_", "").replace("_", "-")
    )
    if "foreign" in normalized or "conflict" in normalized or "locked" in normalized:
        exit_code = ExitCode.CONFLICT
    elif "manual" in normalized or "ambiguous" in normalized:
        exit_code = ExitCode.CONFLICT
    elif "invalid" in normalized or "unsupported" in normalized:
        exit_code = ExitCode.USAGE
    else:
        exit_code = ExitCode.DOMAIN_FAILURE
    return CLIError(
        code=normalized,
        message=str(exc),
        exit_code=exit_code,
        details={"domain_code": domain_code},
    )
