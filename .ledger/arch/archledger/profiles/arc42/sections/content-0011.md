---
schema_version: 4
id: content-0011
version: 3
kind: content
type: section
section: risks_and_technical_debt
title: Risks and Technical Debt
order: 110
status: accepted
body_format: markdown
source_refs:
  - path: ledgercore/time.py
    reason: Known timestamp semantic limitation
---

| Risk / debt                                                | Impact                                                                           | Mitigation                                                                            |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| No inter-process lock or transactional ID allocator        | Concurrent scans can choose the same ID                                          | Pair with exclusive create and retry downstream                                       |
| Filesystem-dependent atomicity/fsync                       | Crash behavior varies on unusual or network filesystems                          | Colocate temp files and test target environments                                      |
| Symlink changes after path validation                      | Hostile writable trees can defeat confinement                                    | Treat base trees as trusted; consider descriptor-relative APIs for hardened use       |
| Whole-file processing                                      | Memory and latency scale with size                                               | Restrict use to ledger-scale artifacts                                                |
| YAML implicit typing                                       | Scalar interpretation can surprise                                               | Safe loading, timestamp-string option, minimal quoting, and downstream schemas        |
| Error code declarations may drift from docs                | Consumers may see inconsistent codes                                             | Subclass code attributes are covered by tests before promising code stability         |
| Package facade may drift from module APIs                  | Imports/docs can lag                                                             | Review `__all__`, docs, and tests together                                            |
| Permissive reference aliases                               | Ambiguity pressure grows with kind formats                                       | Prefer canonical form and apply allowlists                                            |
| Informal pre-1.0 compatibility                             | Upgrades may break consumers                                                     | Define deprecation/version policy before 1.0                                          |
| No property-based or fault-injection tests                 | Rare parser and cleanup edges may escape                                         | Add them where risk justifies complexity                                              |
| Architecture drift is not CI-gated                         | Documentation can become stale                                                   | Maintain source refs and run `archledger source changed` in review                    |
| Direct sibling roots can collide across projects           | One external store may be selected accidentally                                  | Require `.ledger-store` and downstream project-binding markers; fail without fallback |
| External Git is operator-owned                             | Offline computers can diverge or allocate conflicting IDs                        | Pull, commit, push promptly, and resolve integration conflicts downstream             |
| Incomplete migration recovery requires manual intervention | Ledgercore 0.5.1 can inspect but not automatically resume incomplete journals    | Classify honestly as manual intervention; implement full recovery in 0.6.0            |
| Completed-only migration recovery                          | A completed journal is reportable, but incomplete work may need operator cleanup | Keep source storage, expose persisted facts, and defer cleanup/recovery APIs to 0.6.0 |

Lack of multi-file transactions, indexing, remote access, and domain validation is an intentional boundary, not an incomplete feature list.
