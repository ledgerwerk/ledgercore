---
schema_version: 4
id: content-0012
version: 4
kind: content
type: section
section: glossary
title: Glossary
order: 120
status: accepted
body_format: markdown
source_refs: []
---

| Term                       | Meaning                                                                  |
| -------------------------- | ------------------------------------------------------------------------ |
| Atomic create              | Create the final path with exclusive OS flags without overwriting        |
| Atomic replace             | Replace a path so ordinary readers do not observe partial target content |
| Canonical JSON             | Compact sorted-key JSON used for stable fingerprints                     |
| Canonical reference        | Global form `ledger:kind-number`                                         |
| Config locator             | Immutable workspace root, config path, and source result                 |
| Downstream application     | A ledger product that imports `ledgercore`                               |
| File-safe reference        | Global alias such as `tl-task-0001`                                      |
| Fingerprint                | SHA-256 digest for text or canonical data                                |
| Front matter               | YAML mapping delimited by `---` at the beginning of a text document      |
| Global reference           | Identity containing ledger namespace and local ID                        |
| Ledger                     | File-backed collection of records owned by a downstream application      |
| Ledger code                | Short namespace token such as `tl`, `al`, or `sw`                        |
| Local ID                   | Identity without namespace, such as `task-0001`                          |
| Normalization              | Converting accepted variants consistently; not security validation       |
| Path confinement           | Requiring a resolved path to remain under a trusted base                 |
| Resource kind              | Record-type token such as `task` or `quality-requirement`                |
| Source-first documentation | Canonical architecture fragments from which builds are derived           |
| Store error                | Package error for malformed structured data or file I/O                  |
| Whole-file processing      | Reading or constructing a complete artifact in memory                    |
