---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: 0.2.1
kind: added
summary:
  Added shared ledger configuration helpers for locating ledger.toml files
  and selecting project or tool tables
status: accepted
audience: null
scopes: []
source_refs:
  - git:4b783978cef28c8ead085a55c294f881da844b17
paths:
  - ledgercore/config.py
  - ledgercore/errors.py
  - ledgercore/__init__.py
  - tests/test_config.py
  - tests/test_errors.py
issues: []
prs: []
sources:
  - git:4b783978cef28c8ead085a55c294f881da844b17
breaking: false
internal: false
order: 2
---

The public API now includes canonical ledger config filename helpers, shared config discovery, project and tool table selectors, and LedgerConfigError for missing or invalid config tables.
