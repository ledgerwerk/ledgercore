---
schema_version: 3
id: content-0011
version: 1
kind: content
type: section
section: risks_and_technical_debt
title: Risks and Technical Debt
order: 110
status: accepted
date: "2026-06-13"
body_format: markdown
created_at: "2026-06-13T08:41:40.792531+00:00"
updated_at: "2026-06-13T11:05:13.954040+00:00"
source_refs:
  - path: ledgercore/time.py
    reason: Known timestamp semantic limitation
---

| Risk / debt                                         | Impact                                                  | Mitigation                                                                      |
| --------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------- |
| No inter-process lock or transactional ID allocator | Concurrent scans can choose the same ID                 | Pair with exclusive create and retry downstream                                 |
| Filesystem-dependent atomicity/fsync                | Crash behavior varies on unusual or network filesystems | Colocate temp files and test target environments                                |
| Symlink changes after path validation               | Hostile writable trees can defeat confinement           | Treat base trees as trusted; consider descriptor-relative APIs for hardened use |
| Whole-file processing                               | Memory and latency scale with size                      | Restrict use to ledger-scale artifacts                                          |
| YAML implicit typing                                | Scalar interpretation can surprise                      | Safe loading, timestamp-string option, minimal quoting, and downstream schemas  |
| Error code declarations may drift from docs         | Consumers may see inconsistent codes                    | Subclass code attributes are covered by tests before promising code stability   |
| Package facade may drift from module APIs           | Imports/docs can lag                                    | Review `__all__`, docs, and tests together                                      |
| Permissive reference aliases                        | Ambiguity pressure grows with kind formats              | Prefer canonical form and apply allowlists                                      |
| Informal pre-1.0 compatibility                      | Upgrades may break consumers                            | Define deprecation/version policy before 1.0                                    |
| No property-based or fault-injection tests          | Rare parser and cleanup edges may escape                | Add them where risk justifies complexity                                        |
| Architecture drift is not CI-gated                  | Documentation can become stale                          | Maintain source refs and run `archledger source changed` in review              |

Lack of multi-file transactions, indexing, remote access, and domain validation is an intentional boundary, not an incomplete feature list.
