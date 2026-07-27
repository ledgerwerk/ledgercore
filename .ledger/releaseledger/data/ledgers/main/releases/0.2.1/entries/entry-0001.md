---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0001
release_version: 0.2.1
kind: changed
summary:
  Changed core storage and validation behavior for atomic writes, front matter,
  IDs, and source-tree versions
status: accepted
audience: null
scopes: []
source_refs:
  - git:2aa45ae21bc532caa37f2bf7d2b60735d211c613
paths:
  - ledgercore/__init__.py
  - ledgercore/atomic.py
  - ledgercore/frontmatter.py
  - ledgercore/ids.py
  - tests/test_atomic.py
  - tests/test_frontmatter.py
  - tests/test_ids.py
  - tests/test_version.py
issues: []
prs: []
sources:
  - git:2aa45ae21bc532caa37f2bf7d2b60735d211c613
breaking: false
internal: false
order: 1
---

atomic_write_text now preserves an existing file mode on overwrite, minimal scalar front matter rendering rejects unsafe metadata keys, ID format objects validate their format and segment settings, atomic_create_text is exported, and source trees without generated version metadata fall back to an unknown version.
