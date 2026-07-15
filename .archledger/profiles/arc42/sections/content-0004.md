---
schema_version: 4
id: content-0004
version: 2
kind: content
type: section
section: solution_strategy
title: Solution Strategy
order: 40
status: accepted
body_format: markdown
source_refs:
  - path: ledgercore/atomic.py
    reason: Core safety and composition strategy
---

The architecture remains a stateless utility library organized by technical concern. The 0.4.0 canonical layout layer standardizes shared Ledger-family topology and adds one explicitly selected direct sibling workspace convention without introducing services, Git synchronization, migration flows, or process-global state.

1. **Filesystem safety by explicit primitives.** Atomic replacement writes a temporary sibling, optionally flushes it, calls `os.replace`, and optionally flushes the parent. Create-only writes use `O_CREAT | O_EXCL`.
2. **Validation at format boundaries.** JSON/YAML loaders require the expected root shape; front matter requires a mapping; IDs, refs, and paths are parsed before use.
3. **Canonical representations.** JSON hashing uses compact sorted-key output; JSON files use sorted keys and a final newline; references normalize aliases to one model.
4. **Explicit policies.** Missing/empty handling, atomic writes, sorting, body normalization, recursion, aliases, allowlists, and fsync behavior are arguments.
5. **Read-only layout resolution.** Canonical project discovery, manifest parsing, checkout identity, sibling marker validation, and storage-path resolution are mapping-based and perform no writes. The sibling backend fails without fallback when its root or marker is absent.
6. **Immutable value objects.** Parsed IDs, references, fingerprints, config locations, layouts, and JSONL results use frozen dataclasses.
7. **Layered errors.** Modules wrap low-level parse and I/O failures in package-specific errors and preserve causes.
8. **No retained state.** Calls depend only on arguments, filesystem state, environment, platform conventions, and clock.

## Decomposition rationale

- Serialization modules delegate atomic output to `atomic`.
- `hashing` composes front matter parsing and canonical JSON.
- `layout` composes `config`, `ids`, and strict path helpers while keeping TOML parsing downstream.
- `path_text` is separate from `paths`: normalization aids matching, while authorization requires strict validation.
- `refs` and `ids` are separate because references add namespaces and aliases while generic IDs support configurable segments.
- The package root provides discoverability; direct module imports permit narrow dependencies.
