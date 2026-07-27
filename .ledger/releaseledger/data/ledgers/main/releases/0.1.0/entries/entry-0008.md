---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0008
release_version: 0.1.0
kind: changed
summary:
  atomic_create_text uses O_CREAT|O_EXCL for race-safe file creation instead
  of check-then-create
status: accepted
audience: null
scopes: []
source_refs:
  - git:406e3ccbb6786ef39232f7dfa3286aaab346ae99
paths:
  - ledgercore/atomic.py
issues: []
prs: []
sources: []
breaking: false
internal: false
order: 8
---
