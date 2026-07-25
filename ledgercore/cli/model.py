"""Shared immutable CLI state model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .deprecation import CLIWarning


@dataclass(frozen=True)
class CommonCLIState:
    """One immutable CLI state object passed through Typer context.

    Rules:
    1. Resolve ``--root`` with ``Path.resolve(strict=False)``.
    2. Do not call ``os.chdir``.
    3. Pass the selected root to all project discovery, initialization,
       migration, import, adoption, rendering, and export functions.
    4. Cache a resolved workspace only after a command needs it.
    """

    tool: str
    root: Path
    json_output: bool = False
    quiet: bool = False
    verbose: bool = False
    warnings: tuple[CLIWarning, ...] = ()

    def with_warning(self, warning: CLIWarning) -> CommonCLIState:
        """Return a new state with one additional warning appended."""
        return CommonCLIState(
            tool=self.tool,
            root=self.root,
            json_output=self.json_output,
            quiet=self.quiet,
            verbose=self.verbose,
            warnings=(*self.warnings, warning),
        )
