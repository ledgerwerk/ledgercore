"""Shared deprecation warnings.

Do not rely on Python ``warnings.warn`` for the user-facing CLI contract.
Python warning filtering would make output nondeterministic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CLIWarning:
    """Collected, not printed immediately.

    The final emitter decides whether they appear on stderr or in the
    JSON envelope.
    """

    code: str
    message: str
    replacement: str | None = None


def deprecated_command_warning(old: str, replacement: str) -> CLIWarning:
    """Warning when a deprecated command path is invoked."""
    return CLIWarning(
        code="deprecated_command",
        message=f"`{old}` is deprecated; use `{replacement}` instead.",
        replacement=replacement,
    )


def deprecated_option_warning(old: str, replacement: str) -> CLIWarning:
    """Warning when a deprecated option is used."""
    return CLIWarning(
        code="deprecated_option",
        message=f"Option `{old}` is deprecated; use `{replacement}` instead.",
        replacement=replacement,
    )


def deprecated_executable_warning(old: str, replacement: str) -> CLIWarning:
    """Warning when a deprecated executable alias is invoked."""
    return CLIWarning(
        code="deprecated_executable",
        message=f"`{old}` is deprecated; use `{replacement}` instead.",
        replacement=replacement,
    )
