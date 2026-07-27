---
schema_version: 4
id: content-0009
version: 4
kind: content
type: section
section: architecture_decisions
title: Architecture Decisions
order: 90
status: accepted
body_format: markdown
source_refs: []
---

| Decision                                     | Status   | Consequence                                                                             |
| -------------------------------------------- | -------- | --------------------------------------------------------------------------------------- |
| Stateless utility library, not a framework   | Accepted | Downstream applications retain orchestration and policy                                 |
| Text files and standard formats              | Accepted | Human inspection and version control are easy; no query engine or database transactions |
| Atomic single-file writes by default         | Accepted | Partial replacement is avoided at the cost of temp space and sync work                  |
| Caller-controlled fsync                      | Accepted | Consumers may trade crash durability for speed explicitly                               |
| Validate paths beneath a trusted base        | Accepted | Common traversal is blocked; hostile symlink races remain out of scope                  |
| PyYAML safe loading                          | Accepted | No arbitrary YAML object construction; YAML semantics still depend on PyYAML            |
| Canonical output with selected legacy inputs | Accepted | Stored form is stable while migrations remain practical                                 |
| Frozen dataclasses for parsed values         | Accepted | Values are explicit and resistant to accidental mutation                                |
| Package-specific exception categories        | Accepted | Consumers avoid dependency-specific exception coupling                                  |
| Canonical `.ledger` project layout           | Accepted | Shared project identity and storage topology stay consistent without adding a CLI       |
| Reviewed runtime dependencies                | Accepted | `platformdirs` is allowed when standard-library reimplementation would be riskier       |
| No domain schemas or reverse dependencies    | Accepted | Consumers validate domain data above primitive shapes                                   |
| Complete-file processing                     | Accepted | Simpler verification, but unsuitable for very large files                               |
| Curated package facade                       | Accepted | Convenient imports require deliberate `__all__` maintenance                             |

Decision drivers are source-control friendliness, a small reviewed dependency surface, clear downstream ownership, deterministic behavior, and prevention of common filesystem corruption and traversal mistakes. The implementation does not claim database-grade transactions or security in an adversarial filesystem.
