---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.5.1
kind: fixed
summary:
  Fixed completed recovery to return truthful source_removed (False for schema-2
  copy, None for schema-1)
status: accepted
audience: null
scopes: []
source_refs:
  - git:9d8945ad3ad44d293958f92acbd26ab73de0c657
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
