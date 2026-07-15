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

- The package is pre-1.0 (`0.4.0`); patch releases preserve the current minor API where practical, and minor releases may intentionally evolve public APIs before 1.0 with changelog and migration guidance. The 0.4.0 release adds one fixed built-in direct sibling workspace provider while preserving namespaced root overrides.
- The top-level package re-exports a curated convenience API, including `__version__`. The curated root layout facade exposes `LedgerProjectLocator`, `ResolvedLedgerLayout`, `locate_ledger_project`, `parse_ledger_project_manifest`, `parse_ledger_local_config`, `resolve_ledger_layout`, and `derive_checkout_id`; detailed layout dataclasses remain under `ledgercore.layout`.
- The canonical layout surface adds `.ledger/ledger.toml` as the canonical shared project marker while keeping schema-version-1 shared-config discovery as a compatibility path.
- Existing compatibility aliases and documented legacy reference syntax are retained.
- Persisted formats must stay inspectable with ordinary text tools.
- The machine-local provider value `sibling-ledger` is the only direct backend. It resolves project-scoped workspace mounts below `<project-root>/../ledger` and requires `.ledger-store`; arbitrary provider declarations, direct cache or checkout mounts, workspace tool configuration, and fallback are unsupported.

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
