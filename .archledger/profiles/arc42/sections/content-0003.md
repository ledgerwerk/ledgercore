---
schema_version: 3
id: content-0003
version: 1
kind: content
type: section
section: context_and_scope
title: Context and Scope
order: 30
status: accepted
date: "2026-06-13"
body_format: markdown
created_at: "2026-06-13T08:41:40.792531+00:00"
updated_at: "2026-06-13T08:55:58.317204+00:00"
source_refs:
  - path: ledgercore/__init__.py
    reason: Public integration boundary
---

```text
Developer / operator
        |
        v
Downstream Python application
        |
        | imports functions and dataclasses
        v
ledgercore ----> PyYAML
    |          \
    |           -> platformdirs
    v
Local filesystem
```

`ledgercore` is not directly operated by an end user. A downstream application invokes it to validate identifiers and paths, parse or render records, discover canonical Ledger-family project markers, and resolve read-only storage topology. The application supplies domain semantics, loads TOML into mappings, chooses locations, and translates `LedgerCoreError` failures into its own interface.

## External interfaces

| Interface            | Contract                                                                                                          |
| -------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Python API           | Functions, frozen dataclasses, literal policy arguments, and package exceptions                                   |
| Local filesystem     | UTF-8 text; JSON, JSONL, YAML, and front-matter documents; `.ledger/` layouts; atomic replacement where requested |
| PyYAML               | Safe YAML loading and dumping                                                                                     |
| platformdirs         | OS-correct user data and cache roots for the built-in layout providers                                            |
| Environment variable | Optional caller-selected variables can disable fsync or override workspace/cache roots and checkout identity      |
| Clock                | Current time is rendered at second precision with a `Z` suffix                                                    |

## Inside the boundary

- Atomic create and replace of one text file
- Generic text read/write/merge/hash helpers
- JSON, JSONL, YAML, and front matter serialization
- Path normalization, strict path validation, confinement, and config discovery
- Canonical Ledger-family project discovery and typed layout parsing
- Read-only repository, workspace, cache, and tool-config path resolution
- Numeric ID and cross-ledger reference parsing/formatting
- SHA-256 fingerprints and UTC timestamp formatting
- Package-specific exception taxonomy

## Outside the boundary

- Record schemas, ownership, and workflows
- TOML parsing, migration commands, and layout-writing workflows
- Multi-file consistency, recovery journals, and inter-process locking
- Filesystem permissions and trust policy
- UI, observability, configuration parsing, and network access
- Choice of ledger codes, kinds, and relation semantics

The downstream application owns all persisted data. `ledgercore` keeps no catalog or process-global state and performs no writes during layout discovery or resolution.
