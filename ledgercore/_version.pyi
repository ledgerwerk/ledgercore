"""Type stub for the build-generated ``ledgercore._version`` module.

The real module is produced by ``hatch-vcs`` at install or build time and is
gitignored. This stub mirrors the public attributes that hatch-vcs generates
so that strict mypy passes in a pristine source tree where the generated
``_version.py`` is absent.
"""

from __future__ import annotations

__all__ = [
    "__version__",
    "__version_tuple__",
    "version",
    "version_tuple",
    "__commit_id__",
    "commit_id",
]

version: str
__version__: str
__version_tuple__: tuple[int | str, ...]
version_tuple: tuple[int | str, ...]
commit_id: str | None
__commit_id__: str | None
