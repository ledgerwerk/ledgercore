---
schema_version: 4
id: content-0005
version: 6
kind: content
type: section
section: building_block_view
title: Building Block View
order: 50
status: accepted
body_format: markdown
source_refs: []
---

```text
ledgercore
├── storage foundation: errors, atomic, io
├── structured documents: jsonio, jsonl, yamlio, frontmatter, tomlio
├── identity and references: ids, refs
├── path handling: paths, path_text, config
├── project layout: manifest, overrides, storage_paths, storage_binding, layout, migration
├── derived values: hashing, time
└── public facade: __init__
```

| Module            | Responsibility                                                          | Dependencies                                                        |
| ----------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `errors`          | Shared exception hierarchy                                              | None                                                                |
| `atomic`          | Atomic replacement and exclusive creation                               | OS, tempfile, errors                                                |
| `io`              | Basic UTF-8 text, newline, merge, summary, and hash helpers             | Standard library                                                    |
| `jsonio`          | Shape validation, deterministic and canonical JSON                      | atomic, errors                                                      |
| `jsonl`           | Recoverable object-per-line reads and deterministic writes              | atomic, errors                                                      |
| `yamlio`          | Mapping-only YAML and deterministic output                              | PyYAML, atomic, errors                                              |
| `frontmatter`     | YAML front matter and source iteration                                  | PyYAML, atomic, errors                                              |
| `tomlio`          | Round-trip TOML I/O with comment preservation                           | tomlkit, atomic, errors                                             |
| `ids`             | Configurable prefixed numeric IDs and slugs                             | Standard library                                                    |
| `refs`            | Canonical/local/file/legacy resource references                         | errors                                                              |
| `paths`           | Strict path validation and confinement                                  | pathlib, errors                                                     |
| `path_text`       | Human-authored path matching normalization                              | Unicode/regex stdlib                                                |
| `config`          | Upward config discovery and `ConfigLocator`                             | pathlib, errors                                                     |
| `manifest`        | Schema-3 TOML manifest parsing and immutable overlay semantics          | tomlkit, config, errors                                             |
| `overrides`       | Local strict overlay parsing and validation                             | tomlkit, manifest, errors                                           |
| `storage_paths`   | Pure storage-path formulas for four schema-3 kinds                      | pathlib, config, manifest                                           |
| `storage_binding` | Ownership marker identity, validation, and binding mapping helpers      | pathlib, errors                                                     |
| `layout`          | Public resolution facade, layout derivation, and schema-2 compatibility | manifest, overrides, storage_paths, storage_binding, config, errors |
| `migration`       | Copy-only migration planning, execution, journals, and recovery         | layout, storage_binding, atomic, errors                             |
| `hashing`         | SHA-256 and component fingerprints                                      | frontmatter, jsonio                                                 |
| `time`            | Timestamp strings                                                       | datetime                                                            |
| `__init__`        | Curated package-level facade                                            | Public modules                                                      |

## Dependency rules

- Domain packages may depend on `ledgercore`; `ledgercore` must not depend on them.
- Storage formats may delegate writes to `atomic`.
- Foundational modules (`errors`, `atomic`, `io`) do not depend on higher-level formats.
- Layout and migration modules depend on lower-level building blocks but not on serialization formats.
- No module owns mutable singleton state.

Names exported from modules and the curated package `__all__` are intended API. Underscore-prefixed helpers are internal. Front matter compatibility aliases are public legacy surfaces.
