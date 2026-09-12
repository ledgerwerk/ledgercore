---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0001
release_version: 0.7.0
kind: added
summary:
  Added RFC 9562 UUIDv7 generation, prefixed IDs, and cross-ledger resource
  references for independently allocated records
status: accepted
audience: null
scopes: []
source_refs:
  - tl:task-0020
paths:
  - ledgercore/migration.py
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---

The additive UUIDv7 API is thread-safe within a process, preserves numeric ID and reference compatibility, exposes timestamp extraction, supports canonical local, global, and file-safe forms for downstream tools such as Taskledger, and uses UUIDv7 for new compact storage migration IDs while retaining historical journals
