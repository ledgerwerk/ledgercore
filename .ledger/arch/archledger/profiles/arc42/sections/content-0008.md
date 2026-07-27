---
schema_version: 4
id: content-0008
version: 1
kind: content
type: section
section: cross_cutting_concepts
title: Cross-cutting Concepts
order: 80
status: accepted
body_format: markdown
source_refs:
  - path: ledgercore/paths.py
    reason: Cross-cutting path validation and confinement
---

## Errors

Package failures derive from `LedgerCoreError`. Storage failures derive from `StorageError`; specialized categories identify atomic, front matter, JSON, YAML, path, and ID failures. Each exception class exposes a stable `code` class attribute (`LEDGERCORE_ERROR`, `STORAGE_ERROR`, `ATOMIC_WRITE_ERROR`, `FRONTMATTER_ERROR`, `JSON_STORE_ERROR`, `YAML_STORE_ERROR`, `PATH_VALIDATION_ERROR`, `ID_FORMAT_ERROR`) for programmatic handling. Downstream applications render them at their own boundary.

## Determinism

- JSON files use indent 2, sorted keys, and a final newline.
- Canonical JSON uses sorted keys and compact separators.
- JSONL output uses compact objects.
- YAML has explicit key sorting.
- File iteration is sorted.
- References normalize aliases and numeric width.
- Hashes use SHA-256 over UTF-8.

## Integrity and durability

Atomic output is default for structured writers. Temp files live beside targets. Optional fsync covers contents and the parent directory. This prevents partial ordinary replacement but provides no rollback, locking, or multi-file transaction. Race-safe creation loops `os.write()` to completion so partial writes cannot truncate a file.

## Path safety

Strict POSIX-relative validation rejects absolute paths, backslashes, empty segments, and traversal before resolution. Resolved paths are checked against a base. `normalize_path_text` is only a matching aid and must not authorize access.

## Serialization

YAML/object APIs and front matter accept mapping roots. JSON has separate object and array APIs. The `missing="empty"` policy returns an empty container only for absent files; an existing-but-unreadable path (such as a directory or a permission error) raises the store error instead of being masked. Safe YAML loaders avoid arbitrary object construction. The minimal front matter renderer quotes any string that is not a conservative safe plain scalar, or that folds to a YAML boolean or null token, so values such as `- item`, `*alias`, `~`, or `2026-06-13` round-trip without producing invalid YAML. Timestamp strings and template placeholders have opt-in compatibility handling.

## Identity

Numbers are positive and normally padded to four digits. Formatting, parsing, and validity checks consistently reject zero, negative, and boolean values. Generic IDs support separators and segments. Cross-ledger refs use `ledger:kind-number` canonically and accept selected aliases. Scan-based next-ID allocation is deterministic but not concurrency-safe.

## Time

`utc_now_iso` emits second-precision strings ending in `Z`. Aware injected datetimes are normalized to UTC before formatting; naive values are rejected.

## Evolution and testing

Compatibility uses permissive input and canonical output. Public additions should be exported, documented, typed, and tested. Pytest covers behavior; Ruff and strict mypy cover style and typing.
