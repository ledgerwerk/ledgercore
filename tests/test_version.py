"""Tests for the build-generated version metadata."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import ledgercore


def test_package_exposes_version() -> None:
    assert hasattr(ledgercore, "__version__")
    assert isinstance(ledgercore.__version__, str)
    assert ledgercore.__version__


def test_version_in_all() -> None:
    assert "__version__" in ledgercore.__all__


def test_generated_version_module_matches_package_when_present() -> None:
    try:
        from ledgercore import _version
    except ImportError:
        assert ledgercore.__version__ == "0.0.0+unknown"
    else:
        assert _version.__version__ == ledgercore.__version__
        assert isinstance(_version.__version_tuple__, tuple)


def test_source_tree_import_falls_back_without_generated_version(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "ledgercore"
    shutil.copytree(Path(ledgercore.__file__).parent, package_dir)
    (package_dir / "_version.py").unlink(missing_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(tmp_path)!r}); "
                "import ledgercore; "
                "print(ledgercore.__version__)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "0.0.0+unknown"


def test_all_exports_include_imported_public_symbols() -> None:
    assert "atomic_create_text" in ledgercore.__all__


def test_version_is_pep440ish() -> None:
    # Accept release (0.2.0), dev (0.2.0.dev1 / 0.1.dev1), and
    # dirty/git-suffixed forms produced by hatch-vcs / setuptools_scm.
    # The release segment may have two or three numeric components.
    pattern = r"^\d+(\.\d+)*([abrc]\d+|\.dev\d+)?(\+[\w.]+)?$"
    assert re.match(pattern, ledgercore.__version__)
