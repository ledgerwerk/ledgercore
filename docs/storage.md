# Storage helpers

`ledgercore` provides several storage primitives for safely reading and writing
structured files.

## Atomic writes

Use `atomic_write_text` when replacing a file is expected:

```python
from pathlib import Path
from ledgercore.atomic import atomic_write_text

atomic_write_text(Path("index.json"), "{}\n")
```

The write goes to a temporary file first, then `os.replace` atomically moves it
to the target. Parent directories are created automatically. Replacing an
existing file preserves its permission bits; a newly created file keeps the
private `0600` mode created by `mkstemp`.

Use `atomic_create_text` when an existing file must not be overwritten:

```python
from pathlib import Path
from ledgercore.atomic import atomic_create_text

atomic_create_text(Path("records/task-0001.md"), "---\nid: task-0001\n---\n")
```

This uses `O_CREAT|O_EXCL` and raises `AtomicWriteError` if the target already
exists.

Both functions support an optional `fast_io_env_var` parameter. When the named
environment variable is set, `fsync` is skipped for faster I/O on temporary
filesystems.

## Front matter documents

Front matter documents are Markdown files with a YAML header:

```text
---
id: task-0001
status: open
---
# Task body here
```

### Reading

```python
from pathlib import Path
from ledgercore.frontmatter import read_front_matter_document

metadata, body = read_front_matter_document(Path("records/task-0001.md"))
```

The YAML block must be a mapping. `metadata` is always a `dict`. `body`
includes everything after the closing `---` delimiter.

For content already held in memory:

```python
from ledgercore.frontmatter import (
    render_front_matter_text,
    split_front_matter_text,
    update_front_matter_text,
)

metadata, body = split_front_matter_text(text, missing="empty")
text = update_front_matter_text(text, {"status": "ready"})
text = render_front_matter_text(metadata, body, key_order=("id", "status"))
```

Parsing can preserve YAML timestamps as strings and quote template
placeholders. Rendering supports caller-defined key order and body modes.
Minimal scalar rendering accepts only simple alphanumeric, underscore, and
hyphen metadata keys and raises `FrontMatterError` for unsafe YAML keys.

For deterministic front matter without PyYAML's formatting choices:

```python
text = render_front_matter_text(
    {"title": "Example", "tags": ["one", "two"], "empty": ""},
    "# Body\n",
    scalar_style="minimal",
    sequence_indent="  ",
    empty_string_style="double",
    remaining_key_order="sorted",
)
```

The default `scalar_style="pyyaml"` preserves existing output. Minimal mode
supports strings, booleans, integers, nulls, and flat scalar sequences. The minimal
renderer quotes any string that is not a conservative safe plain scalar
(alphanumeric lead character followed by letters, digits, spaces, underscores,
dots, slashes, or hyphens) and any value that folds to a YAML boolean or null
token, so values such as `- item`, `*alias`, `~`, `no`, or `2026-06-13` round-trip
without producing invalid YAML or silently changing type. Use
`quote_template_placeholders="anywhere"` to parse placeholders embedded in simple
unquoted scalar values.

### Writing

```python
from pathlib import Path
from ledgercore.frontmatter import write_front_matter_document

write_front_matter_document(
    Path("records/task-0001.md"),
    {"id": "task-0001", "status": "open"},
    "# Implement parser\n",
    body_mode="ensure-single-final-newline",
)
```

`body_mode="ensure-single-final-newline"` normalizes trailing whitespace in the
body. The default `"preserve"` writes the body as-is.

### Iterating files

```python
from pathlib import Path
from ledgercore.frontmatter import iter_markdown_files, iter_source_files

md_files = iter_markdown_files(Path("records/"))
all_files = iter_source_files(Path("records/"), (".md", ".yaml"))
```

Both return sorted `list[Path]`.

## JSON store

```python
from pathlib import Path
from ledgercore.jsonio import dumps_json, load_json_object, write_json

path = Path("state.json")
write_json(path, {"next": 4})
state = load_json_object(path, missing="empty")
compact = dumps_json(state, compact=True)
```

- `load_json_object` validates that the root is a JSON object.
- `load_json_array` validates that the root is a JSON array.
- `write_json` produces deterministic output: indent 2, sorted keys, final newline.
- `dumps_json` and `write_json` can change indentation, key sorting, ASCII
  escaping, compact separators, and final-newline behavior.
- All operations raise `JsonStoreError` on failure.

Both loaders accept `missing="empty"` to return an empty container only when the
file does not exist; an unreadable path that does exist (for example a directory,
or a permission error) raises `JsonStoreError` rather than being masked as empty.
`empty="empty"` (the default) returns an empty container when the file is blank.

## JSONL store

```python
from pathlib import Path
from ledgercore.jsonl import load_jsonl_object_map, write_jsonl_objects

path = Path("records.jsonl")
write_jsonl_objects(path, [{"id": 1}, {"id": 2}])
result = load_jsonl_object_map(path, key="id", missing="empty")
```

`load_jsonl_object_rows` retains each valid object's source line.
`load_jsonl_object_map` indexes rows by a selected field and reports missing,
invalid, and duplicate keys in `issues`. Duplicate policy can be `"last"`,
`"first"`, or `"error"`. Writes remain compact and deterministic.

## YAML store

```python
from pathlib import Path
from ledgercore.yamlio import load_yaml_object, write_yaml

path = Path("config.yaml")
write_yaml(path, {"records_dir": "records"}, sort_keys=True)
config = load_yaml_object(path, missing="empty")
```

- `load_yaml_object` validates that the root is a YAML mapping.
- `write_yaml` produces block-style output with a final newline. Keys can be
  sorted on request.
- All operations raise `YamlStoreError` on failure.

## Path safety

Path helpers enforce strict rules to prevent directory traversal:

```python
from ledgercore.paths import validate_relative_posix_path

validate_relative_posix_path("records/task-0001.md")  # ok
validate_relative_posix_path("../etc/passwd")          # raises PathValidationError
validate_relative_posix_path("/etc/passwd")            # raises PathValidationError
```

Rejected inputs include:

- Absolute paths (starting with `/`).
- Paths containing `..` or `.` segments.
- Paths containing backslashes.
- Paths that resolve outside the base directory.

### Config discovery

```python
from pathlib import Path
from ledgercore.config import locate_ledger_config
from ledgercore.paths import resolve_config_relative_path

locator = locate_ledger_config(Path.cwd())
if locator is not None:
    records_dir = resolve_config_relative_path(
        locator.config_path,
        "records",
        field_name="records_dir",
    )
```

`locate_ledger_config` walks upward from the starting directory, preferring
`.ledger.toml` over `ledger.toml`. It returns a `ConfigLocator` with
`workspace_root`, `config_path`, and `source` fields.

For canonical phase-2 project layout discovery, use `locate_ledger_project`
instead. It looks for `.ledger/ledger.toml` first, preserves legacy discovery
signals for migration-oriented callers, and returns a `LedgerProjectLocator`
with `project_root`, `config_root`, `manifest_path`, `local_config_path`, and
`source`.

### Shared ledger config convention

Ledgercore-based tools should place shared project metadata under `[project]`
and tool-specific settings under `[tools.<tool-name>]` in `.ledger.toml` when
they still use the schema-version-1 shared config compatibility convention.
Ledgercore provides discovery and generic mapping selectors, but deliberately
does not parse TOML or define tool schemas.

Downstream applications may pass legacy filenames to
`locate_ledger_config`. Canonical names are searched first, so a
`.ledger.toml` in the workspace wins over a legacy tool config. Applications
should parse only the selected file rather than merging canonical and legacy
configs implicitly.

`resolve_config_relative_path` resolves a path relative to the config file's
parent directory, applying the same safety checks.

### Canonical project layout resolution

`ledgercore` 0.4.0 resolves a common `.ledger/ledger.toml` topology through
`ledgercore.layout`. The layout is described by a schema-version-2 project
manifest, an optional machine-local override mapping, and an explicit checkout ID.
Tool configuration remains project-local (`config.location == "project"`). The
resolver evaluates only the workspace and cache families used by the selected
registration, so repository-only ledgers do not require external storage config.

```python
from pathlib import Path

from ledgercore import (
    locate_ledger_project,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)
from ledgercore.layout import PlatformRoots

locator = locate_ledger_project(Path.cwd())
if locator is not None and not locator.is_legacy:
    manifest = parse_ledger_project_manifest(
        {
            "schema_version": 2,
            "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
            "ledgers": {
                "taskledger": {
                    "mounts": {
                        "data": {
                            "storage": "workspace",
                            "scope": "project",
                            "path": "task/taskledger",
                        },
                        "records": {"storage": "repository", "path": "task/records"},
                    },
                }
            },
        }
    )
    layout = resolve_ledger_layout(
        locator,
        manifest,
        "taskledger",
        platform_roots=PlatformRoots(
            user_data=Path("/tmp/ledger-data"),
            user_cache=Path("/tmp/ledger-cache"),
        ),
    )
```

#### Repository-only example

A repository-only ledger keeps every artifact inside the source checkout.
It needs no external storage config and is unaffected by `workspace_root` or
`cache_root` in `.ledger/ledger.local.toml`.

```python
from pathlib import Path

from ledgercore import (
    locate_ledger_project,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)

locator = locate_ledger_project(Path.cwd())
manifest = parse_ledger_project_manifest(
    {
        "schema_version": 2,
        "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
        "ledgers": {
            "archledger": {
                "mounts": {
                    "records": {"storage": "repository", "path": "arch/records"},
                    "published": {"storage": "repository", "path": "arch/published"},
                }
            }
        },
    }
)
layout = resolve_ledger_layout(locator, manifest, "archledger")
assert layout.mounts["records"].path == (
    locator.project_root / ".ledger" / "arch" / "records"
).resolve()
```

#### Mixed-mount example

A mixed-mount ledger combines repository storage (durable, in-tree) with
workspace storage (external, user-data) and cache storage (rebuildable).
`platform_roots` is required for workspace and cache mounts; omit it only when
all mounts are repository mounts.

```python
from pathlib import Path

from ledgercore import (
    locate_ledger_project,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)
from ledgercore.layout import PlatformRoots

locator = locate_ledger_project(Path.cwd())
manifest = parse_ledger_project_manifest(
    {
        "schema_version": 2,
        "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
        "ledgers": {
            "taskledger": {
                "config": {"location": "project", "path": "task/config.toml"},
                "mounts": {
                    "records": {"storage": "repository", "path": "task/records"},
                    "data": {
                        "storage": "workspace",
                        "scope": "project",
                        "path": "task/taskledger",
                    },
                    "indexes": {"storage": "cache", "path": "task/indexes"},
                },
            }
        },
    }
)
layout = resolve_ledger_layout(
    locator,
    manifest,
    "taskledger",
    platform_roots=PlatformRoots(
        user_data=Path("/var/ledger-data"),
        user_cache=Path("/var/ledger-cache"),
    ),
)
```

#### Built-in sibling-ledger provider

The machine-local selection below opts into the one fixed direct workspace backend:

```toml
# .ledger/ledger.local.toml
schema_version = 1

[storage.workspace]
provider = "sibling-ledger"
```

For a project root `/work/ledgercore`, the provider root is fixed at
`/work/ledger`. It requires an existing directory and a regular
`/work/ledger/.ledger-store` marker. Resolution never creates either path, invokes
Git, or falls back to the platform data root. Missing or invalid selected storage
is a fatal error with remediation in the exception text.

A project-scoped workspace mount resolves directly below the provider root:

```text
<project-root>/../ledger/task/taskledger
```

Root overrides retain the existing namespaced behavior instead:

```text
root = "../ledger"
../ledger/projects/<project-uuid>/project/task/taskledger
```

The direct provider supports workspace/project mounts only. It does not support
cache selection, checkout-scoped mounts, provider declarations, configurable
markers, or workspace-located tool configuration.

#### Named mounts and lifecycle rules

- A mount is identified by name within one ledger registration. Two ledgers
  in the same project may reuse the same mount name; they do not share
  storage.
- Repository mounts resolve beneath `.ledger/` and cannot be redirected.
  They live with the source tree and are intended for durable, in-tree
  records.
- Workspace mounts normally resolve under `projects/<project-uuid>/...` outside
  the source checkout. The selected `sibling-ledger` provider is the fixed
  exception and resolves direct project-scoped mounts below `<project-root>/../ledger`.
- Cache mounts resolve under the same `projects/<project-uuid>/...` roots but are
  explicitly rebuildable. Deleting a cache mount is safe.
- The `config` block (when present) must point to a project-local file beneath
  `.ledger/`. Workspace-stored tool config is unsupported.

#### Local roots vs provider selections

`ledgercore` distinguishes two local override fields:

- `workspace_root` / `cache_root` are explicit local filesystem roots. They redirect
  the matching family root while retaining namespaced project and checkout paths.
- `workspace_provider` selects the fixed built-in `sibling-ledger` convention. It is
  valid only for workspace/project mounts and has no fallback.
- `cache_provider` selections are rejected. Root and provider cannot be combined.

`parse_ledger_project_manifest` and `parse_ledger_local_config` accept mappings,
not TOML file paths. Repository mounts stay beneath `.ledger`; root overrides for
workspace and cache mounts retain the fixed `projects/<uuid>/project` or
`projects/<uuid>/checkouts/<checkout-id>` structural roots.

#### External store bootstrap and downstream IDs

On a second computer, clone or provision the external store as the sibling `../ledger`
before resolving the project. Create or verify the regular `../ledger/.ledger-store`
marker, select `provider = "sibling-ledger"` in the machine-local config, and let the
downstream tool initialize its project-binding marker. Ledgercore only validates these
prerequisites. It does not clone, commit, push, or otherwise invoke Git.

Taskledger owns the binding file and authoritative record policy. It must derive the
next ID as the maximum validated allocated task number plus one across active records,
archives, and tombstones. Gaps are not reused, and the stable project config does not
store a next-task counter. Exclusive creation with bounded retry handles local races.
Disconnected computers can still allocate the same numeric ID, so operators should
pull or rebase first, create and push promptly, and resolve integration conflicts
without silently renumbering referenced tasks.

For arbitrary resolved paths, use `ensure_inside_base` before access and
`relative_to_base` when storing a POSIX relative path. `resolve_under_base`
combines strict relative validation with containment and optional existence
checking.
`normalize_path_text` is intentionally separate. It can normalize Unicode
punctuation, backslashes, whitespace, and casing for matching, but its output
must still pass the strict path helpers before filesystem use.

The default punctuation profile preserves existing behavior. Use
`punctuation_profile="wide"` for additional quote, prime, dash, and minus
variants, `"none"` to disable named translations, or
`punctuation_translation` to add application-specific matching substitutions.
