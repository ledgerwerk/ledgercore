---
schema_version: 3
id: content-0010
version: 1
kind: content
type: section
section: quality_requirements
title: Quality Requirements
order: 100
status: accepted
date: "2026-06-13"
body_format: markdown
created_at: "2026-06-13T08:41:40.792531+00:00"
updated_at: "2026-06-13T08:56:01.900444+00:00"
source_refs:
  - path: tests
    reason: Behavioral quality scenarios and regression coverage
---

## Quality tree

- **Reliability:** atomic visibility, exclusive creation, explicit malformed-data reporting
- **Safety:** safe YAML, path confinement, no implicit network or command execution
- **Maintainability:** narrow modules, typed APIs, shared errors, deterministic tests
- **Compatibility:** Python 3.10+, canonical output, supported legacy inputs, UTF-8
- **Performance:** low overhead for repository-scale files and explicit fsync tradeoff

| ID   | Scenario                                                            | Expected response                                                                     |
| ---- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Q-01 | Update an existing JSON state file                                  | Readers see the old complete file or new complete file under normal replace semantics |
| Q-02 | Two processes create the same path                                  | At most one exclusive create succeeds                                                 |
| Q-03 | YAML/JSON has the wrong root type                                   | Loading raises the corresponding store error                                          |
| Q-04 | A path is absolute, traversing, empty-segmented, or backslash-based | Validation rejects it before use beneath the base                                     |
| Q-05 | Canonicalize the same mapping repeatedly                            | JSON bytes and SHA-256 remain identical                                               |
| Q-06 | JSONL contains good and malformed rows                              | Good rows are returned; each bad row has a line and issue code                        |
| Q-07 | Read a supported legacy reference                                   | It parses to a canonical immutable value                                              |
| Q-08 | Disposable data does not need crash durability                      | The caller can explicitly disable fsync                                               |
| Q-09 | A downstream boundary catches a failure                             | It can catch `LedgerCoreError` or a narrower subclass                                 |
| Q-10 | A public primitive changes                                          | Pytest, Ruff, and strict mypy expose behavioral, style, and typing regressions        |

Most functions are pure transformations or accept explicit paths and policies. Time supports injection, filesystem tests use temporary directories, and no global mutable state prevents isolation.
