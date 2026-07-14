# API reference

Public API grouped by module.

(ledgercoreconfig)=

## `ledgercore.config`

Shared ledger workspace config discovery and namespaced mapping selection.
This module does not parse TOML or define tool-specific schemas.

`LEDGER_PROJECT_MANIFEST`

: Canonical manifest path segment: `".ledger/ledger.toml"`.

`LEDGER_PROJECT_LOCAL_CONFIG`

: Canonical machine-local override path segment: `".ledger/ledger.local.toml"`.

`LEDGER_LEGACY_SHARED_CONFIGS`

: Compatibility aliases for schema-version-1 shared config discovery.

`LEDGER_CONFIG_FILENAMES`

: Canonical hidden-first names: `(".ledger.toml", "ledger.toml")`.

`ledger_config_filenames(*legacy, include_visible=True)`

: Append caller-provided legacy names after canonical names.

`locate_ledger_config(start, *, legacy_filenames=(), ...)`

: Locate a canonical config or legacy fallback.

`LedgerProjectLocator`

: Frozen dataclass with `project_root`, `config_root`, `manifest_path`,
`local_config_path`, `source`, and `is_legacy`.

`locate_ledger_project(start, *, legacy_tool_filenames=(), default=False)`

: Locate a canonical `.ledger/ledger.toml` project manifest or a legacy fallback.

`select_project_config(document, *, table_name="project")`

: Select the optional shared project mapping.

`select_tool_config(document, tool_name, *, table_name="tools")`

: Select a required tool mapping.

(ledgercoreatomic)=

## `ledgercore.atomic`

Atomic UTF-8 text writes and race-safe file creation.

| Function                                                                                  | Description                                                         |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `atomic_write_text(path, contents, *, normalize=False, fsync=True, fast_io_env_var=None)` | Write text to a file atomically using a temp file and `os.replace`. |
| `atomic_create_text(path, contents, *, fsync=True, fast_io_env_var=None)`                 | Create a new file atomically using exclusive creation flags.        |

(ledgercoreerrors)=

## `ledgercore.errors`

Shared exception hierarchy with stable error codes.

| Class                 | Code                    | Description                                               |
| --------------------- | ----------------------- | --------------------------------------------------------- |
| `LedgerCoreError`     | `LEDGERCORE_ERROR`      | Base exception for all ledgercore errors.                 |
| `LedgerConfigError`   | `LEDGER_CONFIG_ERROR`   | Raised for missing or invalid shared config tables.       |
| `LedgerLayoutError`   | `LEDGER_LAYOUT_ERROR`   | Raised for invalid or unresolvable Ledger-family layouts. |
| `StorageError`        | `STORAGE_ERROR`         | Base exception for storage-related errors.                |
| `AtomicWriteError`    | `ATOMIC_WRITE_ERROR`    | Raised when an atomic write operation fails.              |
| `FrontMatterError`    | `FRONTMATTER_ERROR`     | Raised when front matter parsing or writing fails.        |
| `JsonStoreError`      | `JSON_STORE_ERROR`      | Raised when a JSON store operation fails.                 |
| `YamlStoreError`      | `YAML_STORE_ERROR`      | Raised when a YAML store operation fails.                 |
| `PathValidationError` | `PATH_VALIDATION_ERROR` | Raised when a path fails validation.                      |
| `IdFormatError`       | `ID_FORMAT_ERROR`       | Raised when an ID does not match the expected format.     |

All exceptions accept an optional `code` keyword argument to override the default code.

(ledgercorefrontmatter)=

## `ledgercore.frontmatter`

YAML front matter reader/writer and source file iteration.

| Symbol                                                                                    | Description                                                      |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `MissingFrontMatterMode`                                                                  | Literal type: `"error"` or `"empty"`.                            |
| `BodyMode`                                                                                | Body preservation and newline normalization policy.              |
| `ScalarStyle`                                                                             | Literal type: `"pyyaml"` or `"minimal"`.                         |
| `RemainingKeyOrder`                                                                       | Literal type: `"input"` or `"sorted"`.                           |
| `EmptyStringStyle`                                                                        | Literal type: `"single"` or `"double"`.                          |
| `TemplatePlaceholderMode`                                                                 | Boolean-compatible placeholder parsing mode.                     |
| `FrontMatterRenderOptions`                                                                | Frozen collection of all front matter rendering options.         |
| `split_front_matter_text(text, *, ...)`                                                   | Parse front matter from in-memory text.                          |
| `render_front_matter_text(metadata, body="", *, ...)`                                     | Render ordered metadata and body.                                |
| `update_front_matter_text(text, updates, *, ...)`                                         | Merge metadata updates into in-memory text.                      |
| `read_front_matter_document(path)`                                                        | Read a YAML front matter document, returning `(metadata, body)`. |
| `write_front_matter_document(path, metadata, body, *, body_mode="preserve", atomic=True)` | Write a YAML front matter document.                              |
| `iter_source_files(directory, extensions, *, recursive=True)`                             | Iterate source files matching given extensions in sorted order.  |
| `iter_markdown_files(directory, *, recursive=False)`                                      | Iterate markdown files in sorted order.                          |
| `read_markdown_front_matter`                                                              | Compatibility alias for `read_front_matter_document`.            |
| `write_markdown_front_matter`                                                             | Compatibility alias for `write_front_matter_document`.           |

(ledgercoreids)=

## `ledgercore.ids`

Prefixed numeric ID formatting, parsing, next-ID generation, and slug helpers.

| Symbol                                                                                           | Description                                                                                                                      |
| ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `LedgerIdParts`                                                                                  | Frozen dataclass: `prefix`, `number`, `segment`.                                                                                 |
| `LedgerIdFormat(prefix, separator="-", width=4, segment_separator=None, segment_required=False)` | Configurable ID format with optional segment support. Methods: `format`, `parse`, `parse_parts`, `next`, `is_valid`, `filename`. |
| `NumericIdFormat(prefix, separator="-", width=4)`                                                | Simpler ID format for compatibility. Methods: `format`, `parse`, `next`.                                                         |
| `parse_prefixed_number(value, *, prefix, separator="-", width=4)`                                | Parse a prefixed numeric ID and return the number.                                                                               |
| `next_prefixed_id(prefix, existing_ids, *, separator="-", width=4)`                              | Return the next prefixed ID given existing IDs.                                                                                  |
| `slugify_ref(value, *, empty="item")`                                                            | Lowercase, trim, collapse non-alphanumeric runs to dashes.                                                                       |

(ledgercoreio)=

## `ledgercore.io`

UTF-8 text helpers, newline normalization, content hash, text merging.

| Function                                          | Description                                              |
| ------------------------------------------------- | -------------------------------------------------------- |
| `normalize_newlines(text)`                        | Convert CRLF and CR to LF.                               |
| `ensure_dir(path)`                                | Create parent directories as needed.                     |
| `read_text(path, *, normalize=True)`              | Read UTF-8 text from a file.                             |
| `write_text(path, text, *, normalize=True)`       | Write UTF-8 text to a file, creating parent directories. |
| `content_hash(text)`                              | Return a stable SHA-256 hex digest of UTF-8 text.        |
| `summarize_text(text, max_chars=80)`              | Collapse whitespace and truncate safely.                 |
| `merge_text(current, incoming, *, prepend=False)` | Combine text blocks without excessive blank lines.       |

(ledgercorejsonio)=

## `ledgercore.jsonio`

Validated JSON object/array loading and deterministic JSON writing.

| Function                                                                           | Description                                                |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `load_json_object(path, *, label="JSON document", missing="error", empty="empty")` | Load and validate a JSON object.                           |
| `load_json_array(path, *, label="JSON document", missing="error", empty="empty")`  | Load and validate a JSON array.                            |
| `dumps_json(payload, *, ...)`                                                      | Render configurable deterministic JSON text.               |
| `write_json(path, payload, *, ...)`                                                | Write JSON with configurable indentation and compact mode. |
| `canonical_json(payload)`                                                          | Render compact sorted-key JSON for hashing.                |

(ledgercorejsonl)=

## `ledgercore.jsonl`

Recoverable JSON Lines object loading and deterministic writing.

| Symbol                                     | Description                                                |
| ------------------------------------------ | ---------------------------------------------------------- |
| `JsonlLoadIssue`                           | Frozen line issue: `line`, `code`, and `message`.          |
| `JsonlLoadResult`                          | Valid `rows` plus recoverable `issues`.                    |
| `JsonlObjectRow`                           | Valid object plus its source line number.                  |
| `JsonlLoadRowsResult`                      | Line-aware valid rows plus recoverable issues.             |
| `JsonlObjectMapLoadResult`                 | Object rows keyed by a selected string field plus issues.  |
| `DuplicateKeyPolicy`                       | Literal type: `"last"`, `"first"`, or `"error"`.           |
| `load_jsonl_object_rows(path, *, ...)`     | Load object rows while preserving source line numbers.     |
| `load_jsonl_object_map(path, *, key, ...)` | Load object rows into a keyed map with recoverable issues. |
| `load_jsonl_objects(path, *, ...)`         | Load object rows while reporting malformed lines.          |
| `write_jsonl_objects(path, rows, *, ...)`  | Write compact object rows atomically by default.           |

(ledgercorepaths)=

## `ledgercore.paths`

Safe relative POSIX path validation, config discovery, config-relative resolution.

| Symbol                                                                                  | Description                                                         |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `is_relative_to(path, parent)`                                                          | Check whether path is relative to parent.                           |
| `validate_relative_posix_path(value, *, field_name="path", allow_trailing_slash=False)` | Validate that a path is a safe relative POSIX path.                 |
| `resolve_relative_child(base_dir, relative_path, *, field_name="path")`                 | Validate and resolve a relative path under a base directory.        |
| `ensure_inside_base(base_dir, path, *, field_name="path")`                              | Resolve a path and reject paths outside the base.                   |
| `relative_to_base(base_dir, path, *, field_name="path")`                                | Return a safe POSIX base-relative path string.                      |
| `resolve_under_base(base_dir, relative_path, *, ...)`                                   | Resolve a safe relative path with optional existence checking.      |
| `find_config_upwards(start, filenames)`                                                 | Walk from start upward, returning the first matching file, or None. |
| `ConfigLocator`                                                                         | Frozen dataclass: `workspace_root`, `config_path`, `source`.        |
| `locate_config(start, filenames, *, default_filename=None)`                             | Find a config file and return a `ConfigLocator`.                    |
| `resolve_config_relative_path(config_path, value, *, field_name)`                       | Resolve a relative path relative to the config file's directory.    |

(ledgercorelayout)=
TK:

## `ledgercore.layout`

TK:
PM:Typed Ledger-family project layout parsing and resolution. The public parser
WB:APIs accept mappings rather than TOML file paths.
JR:
**Package-root facade.** The following layout symbols are re-exported from the
top-level `ledgercore` package for convenience and form the supported public
layout facade. Detailed layout dataclasses are intentionally kept under
`ledgercore.layout` and must not be imported from the package root.

| Symbol                               | Description                                                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| `LedgerProjectLocator`               | Frozen dataclass with `project_root`, `config_root`, `manifest_path`, `local_config_path`, and `source`.     |
| `ResolvedLedgerLayout`               | Frozen dataclass with resolved project, config, optional tool config, checkout ID, and named mounts.         |
| `locate_ledger_project(start, ...)`  | Locate a canonical `.ledger/ledger.toml` project manifest or a legacy fallback.                              |
| `parse_ledger_project_manifest(...)` | Strictly parse a schema-version-2 project manifest mapping.                                                  |
| `parse_ledger_local_config(...)`     | Parse the optional schema-version-1 local override mapping.                                                  |
| `resolve_ledger_layout(...)`         | Resolve repository, workspace, cache, and tool-config paths for one registered ledger.                       |
| `derive_checkout_id(project_root)`   | Derive a deterministic checkout ID from the normalized project path. Retained at the root for 0.2.x callers. |

**Detailed layout surface.** The symbols below are public from `ledgercore.layout`
but are intentionally NOT re-exported from the package root. Use the explicit
module import to keep the curated facade small.

| Symbol                  | Description                                                                 |
| ----------------------- | --------------------------------------------------------------------------- |
| `StorageClass`          | Literal type: `"repository"`, `"workspace"`, or `"cache"`.                  |
| `StorageScope`          | Literal type: `"project"` or `"checkout"`.                                  |
| `ConfigLocation`        | Literal type: `"project"` or `"workspace"`.                                 |
| `PlatformRoots`         | Frozen dataclass with `user_data` and `user_cache` family-root paths.       |
| `LedgerMount`           | Frozen dataclass describing one named mount.                                |
| `ToolConfigDefinition`  | Frozen dataclass describing one ledger config location.                     |
| `LedgerRegistration`    | Frozen dataclass with one ledger name, config definition, and named mounts. |
| `LedgerProjectManifest` | Frozen dataclass describing the parsed schema-version-2 project manifest.   |
| `LedgerLocalConfig`     | Frozen dataclass for optional machine-local overrides.                      |
| `ResolvedMount`         | Frozen dataclass with resolved mount path, scoped root, and source.         |

**Reserved for a later phase.** The following symbols exist for forward
compatibility and migration diagnostics. They are not part of the 0.3.0
compatibility surface and must not be relied on by downstream tools yet.

| Symbol                      | Status                                                                                              |
| --------------------------- | --------------------------------------------------------------------------------------------------- |
| `ProviderKind`              | Reserved literal type for built-in and future provider kinds. Stable in 0.3.0 but unused.           |
| `StorageProviderDefinition` | Reserved frozen dataclass for named provider definitions. Stable in 0.3.0 but unused.               |
| `StorageResolutionSource`   | The `"local-provider"` value is reserved for the private-provider phase and never emitted in 0.3.0. |

**Supported construction flow.** `parse_ledger_project_manifest` and
`parse_ledger_local_config` are the only supported ways to construct manifest
and local-config objects. Manually built `LedgerProjectManifest` instances that
bypass the parser (for example, with a workspace tool config) are not a
supported input to `resolve_ledger_layout` in 0.3.0; the resolver rejects them.
This is a deliberate gate until the private-provider phase lands.
SM:

## `ledgercore.path_text`

Human-authored path matching helpers. These functions do not authorize
filesystem access.

| Symbol                                  | Description                                                    |
| --------------------------------------- | -------------------------------------------------------------- |
| `PunctuationProfile`                    | Literal type: `"basic"`, `"wide"`, or `"none"`.                |
| `decode_unicode_escape_literals(value)` | Decode literal `\uXXXX` and `\UXXXXXXXX` sequences only.       |
| `normalize_path_text(value, *, ...)`    | Normalize Unicode, punctuation, slashes, whitespace, and case. |

(ledgercorehashing)=

## `ledgercore.hashing`

| Symbol                                   | Description                                              |
| ---------------------------------------- | -------------------------------------------------------- |
| `TextFingerprint`                        | Full, body, and canonical metadata SHA-256 values.       |
| `sha256_text(text)`                      | Hash UTF-8 text.                                         |
| `sha256_bytes(data)`                     | Hash bytes directly.                                     |
| `front_matter_fingerprint(text, *, ...)` | Fingerprint components with front matter parser options. |

(ledgercorerefs)=

## `ledgercore.refs`

Canonical cross-ledger resource references.

| Symbol                                 | Description                                                                                                            |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `RefStyle`                             | Literal type: `"canonical"`, `"file"`, `"local"`.                                                                      |
| `LedgerResourceRef`                    | Frozen dataclass with properties: `local_id`, `is_global`, `global_ref`, `file_ref`. Methods: `format`, `with_ledger`. |
| `parse_resource_ref(value, *, ...)`    | Parse a canonical, file-safe, legacy, or local resource reference.                                                     |
| `parse_global_ref(value, **kwargs)`    | Parse and require a ledger namespace.                                                                                  |
| `parse_local_ref(value, *, width=4)`   | Parse a local kind-number ID without assigning a ledger.                                                               |
| `is_resource_ref(value, **kwargs)`     | Return True if value is a valid resource ref.                                                                          |
| `normalize_ref_token(value, *, label)` | Lowercase and validate a short token.                                                                                  |
| `normalize_kind(value)`                | Lowercase, replace underscores with hyphens, and validate a resource kind.                                             |

(ledgercoretime)=

## `ledgercore.time`

UTC timestamp generation with configurable precision and suffix style.

| Symbol          | Description                                                  |
| --------------- | ------------------------------------------------------------ |
| `Timespec`      | Supported `datetime.isoformat()` precision values.           |
| `TimezoneStyle` | Literal type: `"z"` or `"offset"`.                           |
| `utc_now_iso()` | Normalize an aware datetime to UTC and render ISO-8601 text. |

(ledgercoreyamlio)=

## `ledgercore.yamlio`

Validated YAML mapping loading and deterministic YAML writing.

| Function                                                                           | Description                                                |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `load_yaml_object(path, *, label="YAML document", missing="error", empty="empty")` | Load and validate a YAML mapping.                          |
| `write_yaml(path, payload, *, atomic=True, sort_keys=False)`                       | Write a YAML mapping with block style and a final newline. |
