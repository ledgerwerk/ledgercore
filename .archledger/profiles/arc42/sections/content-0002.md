---
schema_version: 4
id: content-0002
version: 2
kind: content
type: section
section: architecture_constraints
title: Architecture Constraints
order: 20
status: accepted
body_format: markdown
source_refs:
  - path: pyproject.toml
    reason: Runtime, packaging, typing, and toolchain constraints
---

| Constraint                    | Architectural consequence                                                                                |
| ----------------------------- | -------------------------------------------------------------------------------------------------------- |
| Python 3.10 or newer          | Modern annotations, dataclasses, literals, and `pathlib` are available                                   |
| Reviewed runtime dependencies | PyYAML handles YAML safely, `platformdirs` provides OS roots, and `tomlkit` round-trips user-edited TOML |
| Typed package (`py.typed`)    | Public behavior must remain statically consumable; strict mypy is the target                             |
| Local filesystem abstraction  | Atomicity, layout resolution, and durability depend on host filesystem and OS semantics                  |
| UTF-8 text files              | Text readers and writers explicitly encode/decode UTF-8                                                  |
| No application framework      | Downstream code owns logging, CLI output, domain locks, synchronization, and CLI policy                  |
| Apache-2.0 distribution       | Source and packages remain compatible with that license                                                  |

## Product constraints

- The package is pre-1.0 (`0.5.0`); breaking minor evolution is documented with compatibility and migration guidance.
- The top-level package re-exports project loading, schema-3 TOML, path, binding, and migration APIs while detailed values remain in focused modules.
- `.ledger/ledger.toml` is the canonical manifest and `.ledger/ledger.local.toml` is an optional strict overlay.
- Persisted formats remain inspectable ordinary UTF-8 text, with comments preserved when TOML documents are edited.
- Schema 2 and its provider vocabulary remain readable compatibility input only; schema 3 has four named storage kinds and fixed formulas.

## Engineering constraints

- Tests use pytest and mirror modules by concern.
- Ruff and strict mypy define static quality expectations.
- GitHub Actions runs tests, pre-commit checks, coverage, and publishing workflows.
- Releases are wheels and source distributions built with Hatchling; versions come from Git tags via hatch-vcs and are written to a gitignored `ledgercore/_version.py`.

## Filesystem assumptions

- Atomic replacement requires source and destination on the same filesystem, so temporary files are created in the target directory.
- `fsync` improves crash durability but cannot guarantee every device or filesystem.
- Path confinement observes symlink resolution at validation time; downstream code must account for time-of-check/time-of-use races in hostile writable trees.
- Ordinary discovery, parsing, resolution, and validation do not write. Explicit initialization and migration APIs own their writes and recovery journals.
