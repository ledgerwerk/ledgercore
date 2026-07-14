"""Regression test that the wheel smoke script runs against the source tree.

The script is also executed as a release gate against a built wheel installed
in a clean virtualenv, but running it against the source tree catches
import drift early and gives us a deterministic in-tree test.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "smoke_wheel.py"


def _load_smoke_module() -> object:
    spec = importlib.util.spec_from_file_location("scripts.smoke_wheel", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load smoke script from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_wheel_script_runs_from_source_tree() -> None:
    assert SCRIPT_PATH.is_file(), f"smoke script missing: {SCRIPT_PATH}"

    main = getattr(_load_smoke_module(), "main", None)
    assert callable(main), "scripts.smoke_wheel must expose a callable main()"

    result = main()
    assert result == 0


def test_smoke_wheel_script_uses_layout_facade() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "from ledgercore.layout import PlatformRoots" in source, (
        "scripts/smoke_wheel.py must import PlatformRoots from ledgercore.layout "
        "because the package-root facade is intentionally small"
    )
    assert (
        "PlatformRoots," not in source.split("from ledgercore import")[1].split(")")[0]
    ), "scripts/smoke_wheel.py must not import PlatformRoots from the package root"


@pytest.mark.parametrize("missing", ["__version__", "locate_ledger_project"])
def test_smoke_wheel_script_retains_root_facade(missing: str) -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert missing in source, (
        f"scripts/smoke_wheel.py must keep {missing!r} in its root-facade import"
    )
