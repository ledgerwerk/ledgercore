---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: 0.5.0
kind: added
summary:
  Added a schema-3 storage model with derived paths, binding markers, TOML
  ownership, and migration
status: accepted
audience: null
scopes: []
source_refs:
  - git:df962e97093e350b65593a4d3de89b0acb6aa263
paths:
  - ledgercore/manifest.py
  - ledgercore/overrides.py
  - ledgercore/tomlio.py
  - ledgercore/storage_paths.py
  - ledgercore/storage_binding.py
  - ledgercore/migration.py
  - ledgercore/errors.py
  - ledgercore/layout.py
  - ledgercore/__init__.py
  - pyproject.toml
  - README.md
  - docs/storage.md
  - docs/api.md
  - ARCHITECTURE.md
  - examples/storage.py
issues: []
prs: []
sources:
  - git:df962e97093e350b65593a4d3de89b0acb6aa263
breaking: true
internal: false
order: 2
---

Replaces the schema-2 provider, workspace, path, and scope model with schema-3 storage kinds (project, external, user-data, cache). Tool config is fixed at .ledger/<tool>/config.toml. Mount paths are derived from project UUID, tool name, mount name, storage kind, and checkout identity. New public modules: manifest, overrides, tomlio, storage_paths, storage_binding, migration, and errors. Adds tomlkit runtime dependency. Schema-2 inputs remain readable for explicit migration with a deprecation warning.
