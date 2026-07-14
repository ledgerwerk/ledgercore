# ledgercore

Generic, typed storage, project-layout, and reference primitives for ledger-like Python applications.

`ledgercore` is a small Python library for projects that store structured records
as files. It provides reusable primitives for atomic writes, YAML front matter,
deterministic JSON/YAML storage, safe relative paths, Ledger-family project
layout discovery and resolution, numeric IDs, and cross-ledger references.

It has no CLI and no dependency on any downstream ledger application.

## Why ledgercore exists

Ledger-like tools (task trackers, architecture logs, spec registries) share the
same low-level problems: safely writing files, formatting IDs, validating paths,
and linking records across namespaces. `ledgercore` extracts those shared
primitives into one typed, zero-surprise package so downstream projects do not
reinvent them.

## What is included

- Atomic UTF-8 text writes and create-only writes.
- YAML front matter read/write helpers.
- Deterministic JSON, JSONL, and YAML file I/O.
- Safe relative POSIX path validation.
- Canonical Ledger-family project layout discovery and resolution.
- Generic content fingerprints and path-text normalization.
- Upward config discovery.
- Prefixed numeric ID formatting.
- Cross-ledger references such as `tl:task-0001`.
- A typed public API and shared exception hierarchy.

## What is not included

- No command-line interface.
- No database layer.
- No sync protocol.
- No task, architecture, or project-specific schema.
- No dependency on `taskledger`, `archledger`, or another product package.

## Installation

```bash
pip install ledgercore
```

Requirements:

- Python 3.10+
- PyYAML
- platformdirs

## Quick start

```python
from pathlib import Path

from ledgercore.frontmatter import write_front_matter_document
from ledgercore.ids import LedgerIdFormat
from ledgercore.refs import parse_resource_ref

task_ids = LedgerIdFormat(prefix="task")
task_id = task_ids.next(["task-0001", "task-0002"])

write_front_matter_document(
    Path(f"records/{task_id}.md"),
    {"id": task_id, "status": "open"},
    "# New task\n",
)

ref = parse_resource_ref("tl:task-0003")
assert ref.local_id == "task-0003"
assert ref.global_ref == "tl:task-0003"
```

## Cross-ledger references

Inside a single ledger, keep local IDs short:

```text
task-0001
adr-0002
```

When linking records across ledgers, use canonical global refs:

```text
<ledger>:<kind>-<number>
```

Examples:

```text
tl:task-0001
al:adr-0002
sw:spec-0003
```

A cross-ledger link can then store both endpoints unambiguously:

```yaml
source: tl:task-0001
target: al:adr-0002
relation: implements
```

For filenames or systems that cannot use `:`, use the file-safe alias:

```text
tl-task-0001
al-adr-0002
```

```python
from ledgercore.refs import parse_resource_ref

ref = parse_resource_ref("tl:task-0001")

assert ref.ledger == "tl"
assert ref.kind == "task"
assert ref.number == 1
assert ref.local_id == "task-0001"
assert ref.global_ref == "tl:task-0001"
assert ref.file_ref == "tl-task-0001"
```

## ID formatting

Use `LedgerIdFormat` as the primary ID formatter:

```python
from ledgercore.ids import LedgerIdFormat

ids = LedgerIdFormat(prefix="task")

assert ids.format(1) == "task-0001"
assert ids.parse("task-0007") == 7
assert ids.next(["task-0001", "task-0002"]) == "task-0003"
```

For segmented, legacy-compatible IDs:

```python
from ledgercore.ids import LedgerIdFormat

adr_ids = LedgerIdFormat(prefix="adr", separator="-", segment_separator="-")

assert adr_ids.format(13, segment="content") == "adr-content-0013"
```

`NumericIdFormat` remains available as a simpler compatibility wrapper.

## Front matter documents

```python
from pathlib import Path
from ledgercore.frontmatter import read_front_matter_document, write_front_matter_document

path = Path("records/task-0001.md")

write_front_matter_document(
    path,
    {"id": "task-0001", "status": "open"},
    "# Implement parser\n",
    body_mode="ensure-single-final-newline",
)

metadata, body = read_front_matter_document(path)
```

Front matter documents must start with `---` followed by a newline and contain a
YAML mapping. The body follows the closing `---` delimiter.

For in-memory content, use `split_front_matter_text`,
`render_front_matter_text`, and `update_front_matter_text`. Permissive parsing,
timestamp-as-string loading, template placeholders, key ordering, and body
normalization are explicit options.

Use `scalar_style="minimal"` for deterministic simple front matter:

```python
from ledgercore.frontmatter import render_front_matter_text

text = render_front_matter_text(
    {"title": "Example", "tags": ["one", "two"], "empty": ""},
    scalar_style="minimal",
    sequence_indent="  ",
    empty_string_style="double",
)
```

The default remains PyYAML-compatible. Render options also pass through update
and file-writing helpers. Template parsing supports whole-value placeholders
and a conservative `"anywhere"` mode for simple scalar values.

## JSON and YAML stores

```python
from pathlib import Path
from ledgercore.jsonio import dumps_json, load_json_object, write_json
from ledgercore.yamlio import load_yaml_object, write_yaml

state_path = Path("state.json")
write_json(state_path, {"next": 4})
state = load_json_object(state_path, missing="empty")
compact = dumps_json(state, compact=True)
```

JSON output uses indent 2, sorted keys, and a final newline. YAML uses block
style and can sort keys when requested.

`canonical_json` produces compact deterministic JSON for hashing.
`load_jsonl_object_rows` retains source lines. `load_jsonl_object_map` builds a
keyed manifest while reporting missing, invalid, and duplicate keys.
`write_jsonl_objects` writes one compact object per line atomically.

Timestamp output supports precision and suffix control:

```python
from ledgercore.time import utc_now_iso

timestamp = utc_now_iso(timespec="microseconds", timezone_style="offset")
```

## Safe paths and config discovery

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

`locate_ledger_config` prefers `.ledger.toml`, then `ledger.toml`, and returns
a `ConfigLocator` with `workspace_root`, `config_path`, and `source` fields.
Path helpers reject absolute paths, `..`, `.` segments, backslashes, and paths
escaping the base directory.

Use `ensure_inside_base`, `relative_to_base`, and `resolve_under_base` when
converting between resolved paths and safe base-relative paths. The separate
`normalize_path_text` helper is for matching human-authored path text; it does
not authorize filesystem access. It supports `"basic"`, `"wide"`, and
`"none"` punctuation profiles plus custom translations.

## Ledger project layout

Phase-2 Ledger-family projects use `.ledger/ledger.toml` as the canonical
shared manifest and `.ledger/ledger.local.toml` for machine-local overrides.
`ledgercore` parses mappings only: downstream tools remain responsible for TOML
loading, migration workflows, and any CLI behavior.

```python
from pathlib import Path

from ledgercore import (
    PlatformRoots,
    locate_ledger_project,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)

locator = locate_ledger_project(Path.cwd())
if locator is not None and not locator.is_legacy:
    manifest = parse_ledger_project_manifest(
        {
            "schema_version": 2,
            "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
            "ledgers": {
                "taskledger": {
                    "config": {"location": "project", "path": "task/config.toml"},
                    "mounts": {
                        "data": {"storage": "workspace", "path": "task/data"},
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
    data_dir = layout.mounts["data"].path
    records_dir = layout.mounts["records"].path
```

Repository mounts resolve beneath `.ledger/`; workspace and cache mounts resolve
under `projects/<project-uuid>/project` or
`projects/<project-uuid>/checkouts/<checkout-id>` depending on scope.

## Shared ledger config convention

Ledgercore-based tools may still use the schema-version-1 shared config
convention as a compatibility surface. In that mode, shared project metadata
belongs under `[project]`; tool-specific configuration belongs under
`[tools.<tool-name>]` in `.ledger.toml` or `ledger.toml`.

```toml
schema_version = 1

[project]
uuid = "565c0312-b531-4d07-aa1f-32c796f58dae"
name = "example"

[tools.example]
config_version = 1
state_dir = ".example"
```

Ledgercore standardizes discovery and generic table selection; it does not
parse TOML or define downstream schemas. Applications remain responsible for
parsing the selected file and may pass legacy names as fallbacks:

```python
from ledgercore.config import (
    locate_ledger_config,
    select_project_config,
    select_tool_config,
)

locator = locate_ledger_config(
    Path.cwd(),
    legacy_filenames=(".example.toml", "example.toml"),
)
```

Canonical shared-config files win over legacy fallbacks. Applications should not
implicitly merge both live configs. For the newer layout API, prefer
`locate_ledger_project` and `.ledger/ledger.toml`.

## Atomic writes

```python
from pathlib import Path
from ledgercore.atomic import atomic_create_text, atomic_write_text

atomic_create_text(Path("records/task-0001.md"), "---\nid: task-0001\n---\n")
atomic_write_text(Path("index.json"), "{}\n")
```

- `atomic_create_text`: create only; fails if target exists.
- `atomic_write_text`: replace target atomically via temp file and `os.replace`.

## Error model

All package-specific errors inherit from `LedgerCoreError`.

```python
from ledgercore.errors import (
    LedgerCoreError, LedgerConfigError, StorageError, AtomicWriteError,
    FrontMatterError, JsonStoreError, YamlStoreError,
    PathValidationError, IdFormatError,
)

try:
    ...
except LedgerCoreError as exc:
    print(exc.code, str(exc))
```

Each exception carries a stable `code` attribute for programmatic handling.

## Using ledgercore from a CLI application

`ledgercore` does not depend on a CLI framework. Adapt its errors at the
application boundary:

```python
from ledgercore.errors import LedgerCoreError

def to_usage_error(exc: LedgerCoreError) -> UsageError:
    return UsageError(str(exc))

try:
    load_application_state()
except LedgerCoreError as exc:
    raise to_usage_error(exc) from exc
```

This keeps exit codes, terminal formatting, and framework-specific exception
types in the downstream application.

## Type checking

`ledgercore` ships a `py.typed` marker. It is fully typed and passes strict
mypy with `strict = true`.

## Development

```bash
python -m pip install -e ".[dev,docs]"
python -m pytest -q
python -m ruff check .
python -m mypy ledgercore
python -m sphinx -W -b html docs docs/_build/html
```

## Release checklist

Versions are derived from VCS tags; there is no static version in
`pyproject.toml` to update.

1. Update `CHANGELOG.md` and create or sign the target tag, such as `v0.2.0`.
2. Run the test, coverage, lint, formatting, typing, example, and docs gates in
   [`docs/release.md`](docs/release.md).
3. Run `python -m build` and `python -m twine check dist/*`.
4. Verify the wheel and sdist contain `LICENSE` and generated `_version.py`.
5. Smoke-test the built wheel in a clean virtualenv.

For a supported non-git source archive, provide the intended version:

```bash
SETUPTOOLS_SCM_PRETEND_VERSION=0.2.0 python -m build
```

## Stability

`ledgercore` is pre-1.0. Public APIs are intended to be stable within the
0.2.x series, but breaking changes may still happen before 1.0.0 when needed
to keep the core API small and consistent.

- No CLI is included.
- No global configuration format is imposed.
- No ledger schema is imposed.
- No product-specific IDs are baked in.
- All paths and refs are strings/paths chosen by downstream packages.

## License

Apache-2.0.
