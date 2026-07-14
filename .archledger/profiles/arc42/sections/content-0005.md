---
schema_version: 3
id: content-0005
version: 1
kind: content
type: section
section: building_block_view
title: Building Block View
order: 50
status: accepted
date: "2026-06-13"
body_format: markdown
created_at: "2026-06-13T08:41:40.792531+00:00"
updated_at: "2026-06-13T08:55:59.315690+00:00"
source_refs:
  - path: ledgercore/__init__.py
    reason: Package module facade and building blocks
---

```text
ledgercore
├── storage foundation: errors, atomic, io
├── structured documents: jsonio, jsonl, yamlio, frontmatter
├── identity and references: ids, refs
├── path handling: paths, path_text
├── derived values: hashing, time
└── public facade: __init__
```

| Module        | Responsibility                                              | Dependencies           |
| ------------- | ----------------------------------------------------------- | ---------------------- |
| `errors`      | Shared exception hierarchy                                  | None                   |
| `atomic`      | Atomic replacement and exclusive creation                   | OS, tempfile, errors   |
| `io`          | Basic UTF-8 text, newline, merge, summary, and hash helpers | Standard library       |
| `jsonio`      | Shape validation, deterministic and canonical JSON          | atomic, errors         |
| `jsonl`       | Recoverable object-per-line reads and deterministic writes  | atomic, errors         |
| `yamlio`      | Mapping-only YAML and deterministic output                  | PyYAML, atomic, errors |
| `frontmatter` | YAML front matter and source iteration                      | PyYAML, atomic, errors |
| `ids`         | Configurable prefixed numeric IDs and slugs                 | Standard library       |
| `refs`        | Canonical/local/file/legacy resource references             | errors                 |
| `paths`       | Validation, confinement, and config discovery               | pathlib, errors        |
| `path_text`   | Human-authored path matching normalization                  | Unicode/regex stdlib   |
| `hashing`     | SHA-256 and component fingerprints                          | frontmatter, jsonio    |
| `time`        | Timestamp strings                                           | datetime               |
| `__init__`    | Curated package-level facade                                | Public modules         |

## Dependency rules

- Domain packages may depend on `ledgercore`; `ledgercore` must not depend on them.
- Storage formats may delegate writes to `atomic`.
- Foundational modules do not depend on higher-level formats.
- No module owns mutable singleton state.

Names exported from modules and the curated package `__all__` are intended API. Underscore-prefixed helpers are internal. Front matter compatibility aliases are public legacy surfaces.
