"""Framework-neutral CLI contracts for Ledgerwerk-family tools.

Ledgercore owns framework-neutral CLI contracts and result models.
Ledgercore does not own console scripts, terminal UI, Typer registration,
or domain command definitions.
"""

from .deprecation import (
    CLIWarning,
    deprecated_command_warning,
    deprecated_executable_warning,
    deprecated_option_warning,
)
from .envelope import ErrorEnvelope, SuccessEnvelope
from .errors import CLIError, ExitCode
from .inventory import CommandInventory, CommandMetadata
from .migrate import MigrationCapabilities, MigrationHandler
from .model import CommonCLIState

__all__ = [
    "CLIError",
    "CLIWarning",
    "CommandInventory",
    "CommandMetadata",
    "CommonCLIState",
    "ErrorEnvelope",
    "ExitCode",
    "MigrationCapabilities",
    "MigrationHandler",
    "SuccessEnvelope",
    "deprecated_command_warning",
    "deprecated_executable_warning",
    "deprecated_option_warning",
]
