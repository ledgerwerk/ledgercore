---
schema_version: 3
id: content-0002
kind: content
type: section
section: architecture_constraints
title: Architecture Constraints
order: 20
status: accepted
date: "2026-06-13"
body_format: markdown
created_at: "2026-06-13T08:41:40.792531+00:00"
updated_at: "2026-06-13T11:05:13.161616+00:00"
source_refs:
  - path: pyproject.toml
    reason: Runtime, packaging, typing, and toolchain constraints
---

| Constraint                    | Architectural consequence                                                                 |
| ----------------------------- | ----------------------------------------------------------------------------------------- |
| Python 3.10 or newer          | Modern annotations, dataclasses, literals, and `pathlib` are available                    |
| Reviewed runtime dependencies | PyYAML handles YAML safely and `platformdirs` provides OS-correct user data/cache roots   |
| Typed package (`py.typed`)    | Public behavior must remain statically consumable; strict mypy is the target              |
| Local filesystem abstraction  | Atomicity, layout resolution, and durability depend on host filesystem and OS semantics   |
| UTF-8 text files              | Text readers and writers explicitly encode/decode UTF-8                                   |
| No application framework      | Downstream code owns logging, CLI output, configuration, parsing, migration, and recovery |
| Apache-2.0 distribution       | Source and packages remain compatible with that license                                   |

## Product constraints

- The package is pre-1.0 (`0.2.0`), with an intent to keep the 0.2.x public API stable where practical.
- The top-level package re-exports a curated convenience API, including `__version__`.
- The phase-2 layout surface adds `.ledger/ledger.toml` as the canonical shared project marker while keeping schema-version-1 shared-config discovery as a compatibility path.
- Existing compatibility aliases and documented legacy reference syntax are retained.
- Persisted formats must stay inspectable with ordinary text tools.

## Engineering constraints

- Tests use pytest and mirror modules by concern.
- Ruff and strict mypy define static quality expectations.
- GitHub Actions runs tests, pre-commit checks, coverage, and publishing workflows.
- Releases are wheels and source distributions built with Hatchling; versions come from Git tags via hatch-vcs and are written to a gitignored `ledgercore/_version.py`.

## Filesystem assumptions

- Atomic replacement requires source and destination on the same filesystem, so temporary files are created in the target directory.
- `fsync` improves crash durability but cannot guarantee every device or filesystem.
- Path confinement observes symlink resolution at validation time; downstream code must account for time-of-check/time-of-use races in hostile writable trees.
- Layout discovery and resolution must not create directories, config files, caches, or markers.
