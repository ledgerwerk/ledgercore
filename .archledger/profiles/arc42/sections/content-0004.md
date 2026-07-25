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

The architecture remains a stateless utility library organized by technical concern. The 0.5.1 layout layer standardizes schema-3 storage kinds, owns TOML and binding markers, and provides explicit copy-only migration with exact journal binding identity, truthful recovery reporting, and manual-intervention classification for incomplete migrations, without introducing services, Git synchronization, or process-global state.

1. **Filesystem safety by explicit primitives.** Atomic replacement writes a temporary sibling, optionally flushes it, calls `os.replace`, and optionally flushes the parent. Create-only writes use `O_CREAT | O_EXCL`.
2. **Validation at format boundaries.** JSON/YAML loaders require the expected root shape; front matter requires a mapping; IDs, refs, and paths are parsed before use.
3. **Canonical representations.** JSON hashing uses compact sorted-key output; JSON files use sorted keys and a final newline; references normalize aliases to one model.
4. **Explicit policies.** Missing/empty handling, atomic writes, sorting, body normalization, recursion, aliases, allowlists, and fsync behavior are arguments.
5. **Side-effect-free normal path.** Canonical project discovery, manifest parsing, overlay application, checkout identity, binding validation, and storage-path resolution do not write. Explicit initialization and migration APIs are the only layout write boundaries.
6. **Immutable value objects.** Parsed IDs, references, fingerprints, config locations, layouts, and JSONL results use frozen dataclasses.
7. **Layered errors.** Modules wrap low-level parse and I/O failures in package-specific errors and preserve causes.
8. **No retained state.** Calls depend only on arguments, filesystem state, environment, platform conventions, and clock.

## Decomposition rationale

- Serialization modules delegate atomic output to `atomic`.
- `hashing` composes front matter parsing and canonical JSON.
- `manifest` and `overrides` own typed schema parsing and immutable overlay semantics.
- `tomlio` owns round-trip TOML and loaded-project behavior.
- `storage_paths` owns pure formulas; `storage_binding` owns marker identity, validation, and binding mapping helpers; `migration` owns verified copy-only movement, schema-2 journals with exact binding identity, and truthful recovery reporting.
- `layout` remains the public resolution facade and schema-2 compatibility wrapper.
- `path_text` is separate from `paths`: normalization aids matching, while authorization requires strict validation.
- `refs` and `ids` are separate because references add namespaces and aliases while generic IDs support configurable segments.
- The package root provides discoverability; direct module imports permit narrow dependencies.
