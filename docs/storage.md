# Ledgercore storage

Ledgercore 0.5.1 provides one deterministic storage model for Ledgerwerk tools.
The normal configuration is schema 3:

```toml
schema_version = 3

[project]
uuid = "081c7c05-2d10-42b7-9b37-3d814c2f400a"
name = "taskledger"

[ledgers.taskledger.mounts.data]
storage = "external"
root = "../ledger"

[ledgers.taskledger.mounts.indexes]
storage = "cache"
```

The tool configuration path is always:

```text
.ledger/taskledger/config.toml
```

No local file is required for the committed external default. A machine-local
override can change one existing mount:

```toml
schema_version = 3

[ledgers.taskledger.mounts.data]
storage = "user-data"
```

## Storage kinds

| Kind        | Scope    | Root or formula                                                                          |
| ----------- | -------- | ---------------------------------------------------------------------------------------- |
| `project`   | project  | `.ledger/<tool>/<mount>`                                                                 |
| `external`  | project  | `<root>/<tool>/<project-uuid>/<mount>`                                                   |
| `user-data` | project  | `platformdirs.user_data_path("ledgerwerk")/<tool>/<project-uuid>/<mount>`                |
| `cache`     | checkout | `platformdirs.user_cache_path("ledgerwerk")/<tool>/<project-uuid>/<checkout-id>/<mount>` |

Schema 3 has no provider, namespace, configurable path, or generic scope fields.
The mount name is always present, including for a mount named `data`.
External roots may be project-relative, absolute in local overrides, or use `~`.
Relative roots resolve from the project root. Committed absolute roots are rejected.

## Loading and resolving

```python
from pathlib import Path

from ledgercore import load_ledger_project, resolve_ledger_layout

project = load_ledger_project(Path.cwd())
layout = resolve_ledger_layout(
    project.locator,
    project.manifest,
    "taskledger",
    local_overrides=project.local_overrides,
)
print(layout.tool_config_path)
print(layout.mounts["data"].path)
```

`load_ledger_project` reads `.ledger/ledger.toml`, reads an optional
`.ledger/ledger.local.toml`, applies the strict overlay, and returns base,
local, and effective values. Resolution and ordinary reads never create or move
files.

## Local overlays

A local file may only address an existing tool and mount. It may set `storage`
and, for external storage, `root`. It cannot change project identity, add a
registration, add a mount, define a config path, or use provider/scope fields.
Changing storage resets incompatible inherited fields. Thus changing an external
mount to `user-data` never leaves the old external root attached.

Use `set_local_mount_override` and `clear_local_mount_override` to create new
immutable values, then explicitly call `write_ledger_local_config`. Missing local
files are normal. Empty schema-3 overlays are valid. Writers can remove an empty
file with `delete_if_empty=True`.

## Binding markers

Ledgercore owns the marker at every resolved mount:

```text
<mount>/.ledger-project.toml
```

The tool config directory uses the same marker with `mount = "config"`:

```text
.ledger/<tool>/.ledger-project.toml
```

A marker contains schema and layout versions, project UUID, tool, mount, storage,
and optional informational project name. Validation checks regular-file status,
exact identity, containment, and storage kind. Validation is read-only. Use
`initialize_storage_binding` or `initialize_config_binding` explicitly for empty
or new locations.

External roots additionally contain:

```text
<external-root>/.ledger-store.toml
```

with `schema_version = 1` and `kind = "ledgerwerk-store"`. The legacy regular
`.ledger-store` marker can be accepted during compatibility validation but new
initialization writes the structured marker.

Unbound non-empty directories and mismatched markers are errors. Missing cache
locations are not corruption when validation allows missing locations.

## Migration

Storage changes are explicit. Planning does not write:

```python
from ledgercore import plan_storage_migration, execute_storage_migration

plan = plan_storage_migration(
    project,
    project.manifest,
    target_overrides,
    "taskledger",
    mounts=("data",),
)
result = execute_storage_migration(
    plan,
    verify="sha256",
    quiescence_check=downstream_has_no_active_writers,
)
```

Planning resolves current and target layouts independently, validates source
bindings, refuses conflicting destinations, and selects cache rebuild by default.
Execution defaults to copy-only mode. Destructive `mode="move"` is disabled in
0.5.1 because source cleanup is not safely recoverable. Durable mounts require
the downstream quiescence callback.

Execution uses a temporary sibling directory, refuses unexpected symlinks,
writes the destination binding, verifies regular files, switches configuration
atomically, and retains the source after successful activation. A schema-2
journal is stored under `.ledger/migrations/<migration-id>.toml` with phases
`planned`, `copying`, `verified`, `config-switched`, `complete`, or `failed`.

Journal schema 2 persists exact source and destination binding identity,
execution mode, verification mode, project root, items completed, and source
removal outcome. Schema-1 journals from earlier versions remain inspectable
but bindings are represented as `None` because the original journal did not
persist them.

Recovery of completed journals returns `source_removed=False` for schema-2
copy journals and `source_removed=None` for schema-1 completed journals.
Incomplete journals in any phase (`planned`, `copying`, `verified`,
`config-switched`, or `failed`) require manual intervention; Ledgercore 0.5.1
can inspect them but cannot safely resume or complete them automatically.

Schema 2 can be read for migration. `plan_schema_v2_to_v3` provides conservative
conversion for simple layouts. Schema-2 provider, namespace, custom path, and
scope combinations that cannot be mapped safely require an operator decision.
Writers emit schema 3 only. Schema 2 is deprecated outside explicit migration.

## Compatibility

The old `ledgercore.layout` parser and resolver remain available for schema-2
callers during the 0.5.x compatibility window. They emit `DeprecationWarning`.
The old `workspace`, `repository`, `sibling-ledger`, provider, namespace, and
scope vocabulary is compatibility input only and is not part of normal schema-3
configuration.
