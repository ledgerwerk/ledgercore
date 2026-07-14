# Release process

This document describes how to build, validate, and publish a `ledgercore`
release. The release gate is the clean-wheel smoke test in
[`scripts/smoke_wheel.py`](../scripts/smoke_wheel.py) executed against a
wheel installed in a fresh virtualenv.

## Prerequisites

Install build and validation tools:

```bash
python -m pip install -e ".[dev,docs,release]"
# or, equivalently:
python -m pip install -e ".[dev]" && python -m pip install build twine
```

`ledgercore` uses `hatch-vcs` for versioning. Installing or building the
project generates a gitignored `ledgercore/_version.py` that exposes
`ledgercore.__version__`; do not commit that file. Direct source-tree imports
fall back to `0.0.0+unknown` when that generated module is absent, and a
matching `ledgercore/_version.pyi` ships with the package so strict mypy
passes in a pristine source tree.

## Pre-release checklist

1. Ensure all tests pass:

   ```bash
   python -m pytest -q
   ```

2. Ensure lint is clean:

   ```bash
   python -m ruff check .
   ```

3. Ensure type checking passes in a pristine source tree. The generated
   `_version.py` is removed first so the documented source-tree fallback is
   actually exercised:

   ```bash
   rm -f ledgercore/_version.py
   python -m mypy ledgercore
   ```

4. Ensure formatting and documentation are clean. The Sphinx build no longer
   requires network access; `sphinx.ext.intersphinx` is disabled because no
   cross-project Python references are used yet.

   ```bash
   python -m ruff format --check .
   python -m sphinx -W -b html docs docs/_build/html
   ```

5. Ensure the three example scripts run from the source tree:

   ```bash
   PYTHONPATH=. python examples/frontmatter.py
   PYTHONPATH=. python examples/refs.py
   PYTHONPATH=. python examples/storage.py
   ```

## Building

```bash
python -m build
```

Builds from a non-git source archive are supported when the intended version
is provided explicitly. Use a placeholder for repeatable local runs:

```bash
SETUPTOOLS_SCM_PRETEND_VERSION=X.Y.Z python -m build
```

For an actual 0.3.0 release build, use `0.3.0`:

```bash
SETUPTOOLS_SCM_PRETEND_VERSION=0.3.0 python -m build
```

This produces `dist/ledgercore-<version>.tar.gz` and
`dist/ledgercore-<version>-py3-none-any.whl`.

## Validating the distribution

```bash
python -m twine check dist/*
```

## Smoke testing (required release gate)

Install the built wheel into a clean virtualenv and run the release smoke
script. The script exercises a representative slice of the public API so that
packaging regressions (missing modules, lost data files, broken imports)
surface before publishing. Use a writable location for the venv; on some
platforms `/tmp` is not writable. Run the script from a working directory
that does not shadow the installed package:

```bash
smoke_dir="$(pwd)/.smoke"
rm -rf "$smoke_dir"
python -m venv "$smoke_dir"
"$smoke_dir/bin/python" -m pip install "$(echo dist/*.whl)"
"$smoke_dir/bin/python" scripts/smoke_wheel.py
```

The script must print `ledgercore 0.3.0 smoke test passed` and exit 0. The
source-tree smoke test (`tests/test_smoke_wheel_source.py`) covers the same
`main()` function and must also pass in CI.

## Artifact content verification

Verify the wheel and sdist ship the `LICENSE` file, the `py.typed` marker,
and the generated `ledgercore/_version.py`:

```bash
python - <<'PY'
import glob, tarfile, zipfile

wheel = glob.glob("dist/*.whl")[0]
sdist = glob.glob("dist/*.tar.gz")[0]

with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    assert any(name.endswith("LICENSE") for name in names)
    assert "ledgercore/_version.py" in names
    assert "ledgercore/py.typed" in names

with tarfile.open(sdist) as archive:
    names = archive.getnames()
    assert any(name.endswith("/LICENSE") for name in names)
    assert any(name.endswith("/ledgercore/_version.py") for name in names)
    assert any(name.endswith("/ledgercore/py.typed") for name in names)

print("artifact check passed")
PY
```

## Publishing

```bash
python -m twine upload dist/*
```

## Version policy

`ledgercore` is pre-1.0. Patch releases preserve the current minor API where
practical. Minor releases may intentionally evolve public APIs before 1.0,
with changelog and migration guidance. The 0.3.0 release is the pilot API
for the canonical Ledger-family layout; downstream tools that adopt the
0.3.x series should pin `ledgercore>=0.3.0,<0.4.0` during the pilot window.
