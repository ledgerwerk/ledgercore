---
title: "Architecture Documentation"
version: 3
generator: "archledger 0.3.2"
arc42_template_version: "9.0-EN"
---

# Architecture Documentation

Generated from archledger records. Do not edit this generated file directly.

# Introduction and Goals

## Purpose

`ledgercore` is a small, typed Python library that supplies reusable storage, project-layout, and reference primitives for file-backed ledger applications. It centralizes low-level behavior shared by task, architecture, release, specification, and similar tools without defining a domain-specific record model.

The library is embedded by a downstream Python application. It has no CLI, server, database, background process, or network protocol.

## Stakeholders

| Stakeholder                             | Concern                                                                                       |
| --------------------------------------- | --------------------------------------------------------------------------------------------- |
| Downstream application developers       | Stable, unsurprising primitives that are easy to compose and catch at an application boundary |
| Maintainers                             | Small dependency surface, strict typing, focused modules, and deliberate compatibility        |
| Operators and users of downstream tools | Durable file updates, deterministic files, actionable failures, and path confinement          |
| Package releasers                       | Reproducible validation and conventional Python artifacts                                     |

## Goals

1. Prevent torn or partially visible file replacement during ordinary writes.
2. Produce deterministic, human-readable JSON, JSONL, YAML, and YAML-front-matter files.
3. Validate untrusted relative path strings before resolving them under a trusted base.
4. Provide canonical local and cross-ledger numeric identifiers.
5. Discover canonical Ledger-family manifests and resolve the deterministic schema-3 storage model without writing during ordinary resolution.
6. Own typed TOML configuration, storage binding markers, and explicit migration planning and execution behind a framework-neutral API.
7. Keep domain schemas, locking, synchronization, and user interfaces in downstream applications.

## Quality priorities

1. **Correctness and data integrity:** invalid shapes and unsafe paths fail explicitly; atomic writers avoid partial replacement.
2. **Predictability:** canonical formatting, sorted iteration, explicit policies, and stable exception categories.
3. **Portability:** Python 3.10+, UTF-8 text, `pathlib`, `platformdirs`, and standard filesystem operations.
4. **Maintainability:** one-purpose modules, strict type checking, broad unit tests, and a small reviewed dependency surface.
5. **Performance:** repository-scale files; whole-file processing is favored over streaming complexity.

## Non-goals

- Domain-specific schemas or workflow rules
- Global ID allocation across concurrent processes
- Transactions spanning multiple files
- Authentication, authorization, encryption, or secret management
- Remote storage, synchronization, indexing, querying, or database abstraction
- A Ledger-family CLI, CLI error rendering, or exit-code policy
- Domain-specific lock parsing, synchronization, Git operations, or background migration
- Remote, object, database, plug-in, arbitrary path-template, namespace, or generic scope storage
- Silent data adoption or implicit movement during reads and ordinary layout resolution

## Requirements Overview

<!-- archledger: no accepted records for this section yet -->

## Quality Goals

<!-- archledger: no accepted records for this section yet -->

## Stakeholders

<!-- archledger: no accepted records for this section yet -->

# Architecture Constraints

| Constraint                    | Architectural consequence                                                                                |
| ----------------------------- | -------------------------------------------------------------------------------------------------------- |
| Python 3.10 or newer          | Modern annotations, dataclasses, literals, and `pathlib` are available                                   |
| Reviewed runtime dependencies | PyYAML handles YAML safely, `platformdirs` provides OS roots, and `tomlkit` round-trips user-edited TOML |
| Typed package (`py.typed`)    | Public behavior must remain statically consumable; strict mypy is the target                             |
| Local filesystem abstraction  | Atomicity, layout resolution, and durability depend on host filesystem and OS semantics                  |
| UTF-8 text files              | Text readers and writers explicitly encode/decode UTF-8                                                  |
| No application framework      | Downstream code owns logging, CLI output, domain locks, synchronization, and CLI policy                  |
| Apache-2.0 distribution       | Source and packages remain compatible with that license                                                  |

## Product constraints

- The package is pre-1.0 (`0.5.0`); breaking minor evolution is documented with compatibility and migration guidance.
- The top-level package re-exports project loading, schema-3 TOML, path, binding, and migration APIs while detailed values remain in focused modules.
- `.ledger/ledger.toml` is the canonical manifest and `.ledger/ledger.local.toml` is an optional strict overlay.
- Persisted formats remain inspectable ordinary UTF-8 text, with comments preserved when TOML documents are edited.
- Schema 2 and its provider vocabulary remain readable compatibility input only; schema 3 has four named storage kinds and fixed formulas.

## Engineering constraints

- Tests use pytest and mirror modules by concern.
- Ruff and strict mypy define static quality expectations.
- GitHub Actions runs tests, pre-commit checks, coverage, and publishing workflows.
- Releases are wheels and source distributions built with Hatchling; versions come from Git tags via hatch-vcs and are written to a gitignored `ledgercore/_version.py`.

## Filesystem assumptions

- Atomic replacement requires source and destination on the same filesystem, so temporary files are created in the target directory.
- `fsync` improves crash durability but cannot guarantee every device or filesystem.
- Path confinement observes symlink resolution at validation time; downstream code must account for time-of-check/time-of-use races in hostile writable trees.
- Ordinary discovery, parsing, resolution, and validation do not write. Explicit initialization and migration APIs own their writes and recovery journals.

<!-- archledger: no accepted records for this section yet -->

# Context and Scope

```text
Developer / operator
        |
        v
Downstream Python application
        |
        | imports functions and dataclasses
        v
ledgercore ----> PyYAML
    |          \
    |           -> platformdirs
    v
Local filesystem
```

`ledgercore` is not directly operated by an end user. A downstream application invokes it to validate identifiers and paths, load schema-3 project TOML, resolve deterministic storage, validate ownership markers, and plan or execute explicit migrations. The application supplies domain semantics and downstream quiescence checks, then translates `LedgerCoreError` failures into its own interface.

## External interfaces

| Interface            | Contract                                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Python API           | Functions, frozen dataclasses, literal policy arguments, and package exceptions                                          |
| Local filesystem     | UTF-8 text; JSON, JSONL, YAML, TOML, front-matter documents, `.ledger/` layouts, binding markers, and migration journals |
| PyYAML               | Safe YAML loading and dumping                                                                                            |
| platformdirs         | OS-correct Ledgerwerk user-data and cache roots                                                                          |
| Environment variable | Optional caller-selected variables can disable fsync or override workspace/cache roots and checkout identity             |
| Clock                | Current time is rendered at second precision with a `Z` suffix                                                           |

## Inside the boundary

- Atomic create and replace of one text file
- Generic text read/write/merge/hash helpers
- JSON, JSONL, YAML, and front matter serialization
- Path normalization, strict path validation, confinement, and config discovery
- Canonical Ledger-family project discovery, schema parsing, and typed layout resolution
- Deterministic project, external, user-data, cache, and tool-config paths
- TOML ownership, binding marker validation, migration planning, execution, and journals
- Numeric ID and cross-ledger reference parsing/formatting
- SHA-256 fingerprints and UTC timestamp formatting
- Package-specific exception taxonomy

## Outside the boundary

- Record schemas, ownership, and workflows
- Downstream CLI presentation, domain lock parsing, Git synchronization, and network access
- Remote storage, background work, or cross-process locking policy
- Filesystem permissions and trust policy
- UI, observability, configuration parsing, Git synchronization, and network access
- Choice of ledger codes, kinds, and relation semantics

The downstream application owns all persisted data. `ledgercore` keeps no catalog or process-global state and performs no writes during layout discovery or resolution.



## Business Context

<!-- archledger: no accepted records for this section yet -->

## Technical Context

<!-- archledger: no accepted records for this section yet -->

# Solution Strategy

The architecture remains a stateless utility library organized by technical concern. The 0.5.1 layout layer standardizes schema-3 storage kinds, owns TOML and binding markers, and provides explicit copy-only migration with exact journal binding identity, truthful recovery reporting, and manual-intervention classification for incomplete migrations, without introducing services, Git synchronization, or process-global state. Recovery is deliberately completed-only in 0.5.1: incomplete journals are inspected without invented facts but are not automatically resumed.

1. **Filesystem safety by explicit primitives.** Atomic replacement writes a temporary sibling, optionally flushes it, calls `os.replace`, and optionally flushes the parent. Create-only writes use `O_CREAT | O_EXCL`.
2. **Validation at format boundaries.** JSON/YAML loaders require the expected root shape; front matter requires a mapping; IDs, refs, and paths are parsed before use.
3. **Canonical representations.** JSON hashing uses compact sorted-key output; JSON files use sorted keys and a final newline; references normalize aliases to one model.
4. **Explicit policies.** Missing/empty handling, atomic writes, sorting, body normalization, recursion, aliases, allowlists, and fsync behavior are arguments.
5. **Side-effect-free normal path.** Canonical project discovery, manifest parsing, overlay application, checkout identity, binding validation, and storage-path resolution do not write. Explicit initialization and migration APIs are the only layout write boundaries.
6. **Immutable value objects.** Parsed IDs, references, fingerprints, config locations, layouts, and JSONL results use frozen dataclasses.
7. **Layered errors.** Modules wrap low-level parse and I/O failures in package-specific errors and preserve causes.
8. **No retained state.** Calls depend only on arguments, filesystem state, environment, platform conventions, and clock.

## Decomposition rationale

- Serialization modules delegate atomic output to `atomic`.
- `hashing` composes front matter parsing and canonical JSON.
- `manifest` and `overrides` own typed schema parsing and immutable overlay semantics.
- `tomlio` owns round-trip TOML and loaded-project behavior.
- `storage_paths` owns pure formulas; `storage_binding` owns marker identity, validation, and binding mapping helpers; `migration` owns verified copy-only movement, schema-2 journals with exact binding identity, and truthful recovery reporting.
- `layout` remains the public resolution facade and schema-2 compatibility wrapper.
- `path_text` is separate from `paths`: normalization aids matching, while authorization requires strict validation.
- `refs` and `ids` are separate because references add namespaces and aliases while generic IDs support configurable segments.
- The package root provides discoverability; direct module imports permit narrow dependencies.

## Strategy Items

<!-- archledger: no accepted records for this section yet -->

# Building Block View

```text
ledgercore
├── storage foundation: errors, atomic, io
├── structured documents: jsonio, jsonl, yamlio, frontmatter
├── identity and references: ids, refs
├── path handling: paths, path_text
├── derived values: hashing, time
└── public facade: __init__
```

| Module        | Responsibility                                              | Dependencies           |
| ------------- | ----------------------------------------------------------- | ---------------------- |
| `errors`      | Shared exception hierarchy                                  | None                   |
| `atomic`      | Atomic replacement and exclusive creation                   | OS, tempfile, errors   |
| `io`          | Basic UTF-8 text, newline, merge, summary, and hash helpers | Standard library       |
| `jsonio`      | Shape validation, deterministic and canonical JSON          | atomic, errors         |
| `jsonl`       | Recoverable object-per-line reads and deterministic writes  | atomic, errors         |
| `yamlio`      | Mapping-only YAML and deterministic output                  | PyYAML, atomic, errors |
| `frontmatter` | YAML front matter and source iteration                      | PyYAML, atomic, errors |
| `ids`         | Configurable prefixed numeric IDs and slugs                 | Standard library       |
| `refs`        | Canonical/local/file/legacy resource references             | errors                 |
| `paths`       | Validation, confinement, and config discovery               | pathlib, errors        |
| `path_text`   | Human-authored path matching normalization                  | Unicode/regex stdlib   |
| `hashing`     | SHA-256 and component fingerprints                          | frontmatter, jsonio    |
| `time`        | Timestamp strings                                           | datetime               |
| `__init__`    | Curated package-level facade                                | Public modules         |

## Dependency rules

- Domain packages may depend on `ledgercore`; `ledgercore` must not depend on them.
- Storage formats may delegate writes to `atomic`.
- Foundational modules do not depend on higher-level formats.
- No module owns mutable singleton state.

Names exported from modules and the curated package `__all__` are intended API. Underscore-prefixed helpers are internal. Front matter compatibility aliases are public legacy surfaces.



<!-- archledger: no accepted records for this section yet -->

# Runtime View

## Atomic replacement

```text
caller -> atomic_write_text
  -> create parent directories
  -> create temporary sibling
  -> write UTF-8 bytes
  -> flush and fsync (policy permitting)
  -> os.replace(temp, target)
  -> fsync parent (policy permitting)
  -> return
```

Before replacement, a failure triggers best-effort cleanup and `AtomicWriteError`. This is not a multi-file transaction.

## Exclusive record creation

`atomic_create_text` creates parents, opens the final path with `O_CREAT | O_EXCL`, writes bytes, optionally syncs, and closes it. An existing target or racing creator raises `AtomicWriteError`; write failure removes the incomplete target on a best-effort basis.

## Front matter round trip

1. Normalize input newlines for parsing.
2. Require an opening delimiter unless missing-as-empty is selected.
3. Split YAML metadata from body at the closing delimiter.
4. Safe-load YAML and require a mapping.
5. Merge updates and render with selected key/body policy.
6. Delegate file output to atomic replacement by default.

## Safe config-relative path

1. Locate a config by walking upward.
2. Reject an empty, absolute, backslash-based, or segmented traversal value.
3. Join it to the resolved config directory.
4. Require the result to remain beneath that directory.
5. Return a resolved `Path`, not a permanent authorization token.

## Project layout resolution

1. Discover `.ledger/ledger.toml` and read schema 2 or schema 3 through Ledgercore TOML I/O.
2. Parse schema 3 and an optional strict local overlay, then derive effective mount values.
3. Derive `.ledger/<tool>/config.toml` and fixed project, external, user-data, or checkout-cache paths.
4. Validate external store and project binding markers without writing.
5. Plan migrations from independently resolved source and target layouts.
6. Execute explicit migrations through temporary destinations, verification, quiescence checks, atomic configuration switching, and schema-2 journals that preserve exact binding identity. Execution defaults to copy-only mode; destructive mode is disabled. Source storage is always retained. Completed journals return truthful recovery results; incomplete journals require manual intervention. Recovery itself is read-only and does not copy, delete, switch configuration, or rewrite journals.
7. Return immutable layout and migration values; ordinary resolution creates no directories, markers, or config files.

## Reference normalization

The parser tries canonical, legacy underscore, file-safe, and local forms in order. It normalizes tokens, requires a positive number, preserves wider padding, optionally supplies a ledger, then applies allowlists.

## Recoverable JSONL loading

Valid object rows are retained in order. Invalid JSON and non-object rows become line-numbered issues. File-level read failures raise a store exception.



<!-- archledger: no accepted records for this section yet -->

# Deployment View

```text
Python 3.10+ process
├── downstream ledger application
├── ledgercore package
├── PyYAML package
└── platformdirs package
└── operating-system filesystem APIs
    └── application-selected local data directories
```

The package is installed into the same environment as its consumer. It opens only caller-supplied or derived paths and creates no default data directory. There is no daemon, port, container, queue, or external service.

## Distribution

- Build backend: Hatchling
- Artifacts: Python wheel and source distribution
- Package data: `py.typed`
- Runtime dependencies: PyYAML and platformdirs
- Development dependencies: pytest, Ruff, mypy, and PyYAML stubs
- Release tools: build and Twine

Project metadata declares Python 3.10 through 3.13. The code is primarily OS-neutral, but atomic and path behavior follows the host OS and filesystem.

## Operational characteristics

- There is no package configuration file; behavior is configured by arguments.
- A caller-selected environment variable may disable fsync for faster, less durable writes.
- Structured data is processed as complete files in memory.
- Atomic replacement temporarily needs space for both old and new contents.
- Config discovery walks upward; source iteration returns a fully materialized sorted list.

The deployment model fits repository-scale ledgers, not large datasets or high-throughput storage services.



<!-- archledger: no accepted records for this section yet -->

# Cross-cutting Concepts

## Errors

Package failures derive from `LedgerCoreError`. Storage failures derive from `StorageError`; specialized categories identify atomic, front matter, JSON, YAML, path, and ID failures. Each exception class exposes a stable `code` class attribute (`LEDGERCORE_ERROR`, `STORAGE_ERROR`, `ATOMIC_WRITE_ERROR`, `FRONTMATTER_ERROR`, `JSON_STORE_ERROR`, `YAML_STORE_ERROR`, `PATH_VALIDATION_ERROR`, `ID_FORMAT_ERROR`) for programmatic handling. Downstream applications render them at their own boundary.

## Determinism

- JSON files use indent 2, sorted keys, and a final newline.
- Canonical JSON uses sorted keys and compact separators.
- JSONL output uses compact objects.
- YAML has explicit key sorting.
- File iteration is sorted.
- References normalize aliases and numeric width.
- Hashes use SHA-256 over UTF-8.

## Integrity and durability

Atomic output is default for structured writers. Temp files live beside targets. Optional fsync covers contents and the parent directory. This prevents partial ordinary replacement but provides no rollback, locking, or multi-file transaction. Race-safe creation loops `os.write()` to completion so partial writes cannot truncate a file.

## Path safety

Strict POSIX-relative validation rejects absolute paths, backslashes, empty segments, and traversal before resolution. Resolved paths are checked against a base. `normalize_path_text` is only a matching aid and must not authorize access.

## Serialization

YAML/object APIs and front matter accept mapping roots. JSON has separate object and array APIs. The `missing="empty"` policy returns an empty container only for absent files; an existing-but-unreadable path (such as a directory or a permission error) raises the store error instead of being masked. Safe YAML loaders avoid arbitrary object construction. The minimal front matter renderer quotes any string that is not a conservative safe plain scalar, or that folds to a YAML boolean or null token, so values such as `- item`, `*alias`, `~`, or `2026-06-13` round-trip without producing invalid YAML. Timestamp strings and template placeholders have opt-in compatibility handling.

## Identity

Numbers are positive and normally padded to four digits. Formatting, parsing, and validity checks consistently reject zero, negative, and boolean values. Generic IDs support separators and segments. Cross-ledger refs use `ledger:kind-number` canonically and accept selected aliases. Scan-based next-ID allocation is deterministic but not concurrency-safe.

## Time

`utc_now_iso` emits second-precision strings ending in `Z`. Aware injected datetimes are normalized to UTC before formatting; naive values are rejected.

## Evolution and testing

Compatibility uses permissive input and canonical output. Public additions should be exported, documented, typed, and tested. Pytest covers behavior; Ruff and strict mypy cover style and typing.



<!-- archledger: no accepted records for this section yet -->

# Architecture Decisions

| Decision                                     | Status   | Consequence                                                                             |
| -------------------------------------------- | -------- | --------------------------------------------------------------------------------------- |
| Stateless utility library, not a framework   | Accepted | Downstream applications retain orchestration and policy                                 |
| Text files and standard formats              | Accepted | Human inspection and version control are easy; no query engine or database transactions |
| Atomic single-file writes by default         | Accepted | Partial replacement is avoided at the cost of temp space and sync work                  |
| Caller-controlled fsync                      | Accepted | Consumers may trade crash durability for speed explicitly                               |
| Validate paths beneath a trusted base        | Accepted | Common traversal is blocked; hostile symlink races remain out of scope                  |
| PyYAML safe loading                          | Accepted | No arbitrary YAML object construction; YAML semantics still depend on PyYAML            |
| Canonical output with selected legacy inputs | Accepted | Stored form is stable while migrations remain practical                                 |
| Frozen dataclasses for parsed values         | Accepted | Values are explicit and resistant to accidental mutation                                |
| Package-specific exception categories        | Accepted | Consumers avoid dependency-specific exception coupling                                  |
| Canonical `.ledger` project layout           | Accepted | Shared project identity and storage topology stay consistent without adding a CLI       |
| Reviewed runtime dependencies                | Accepted | `platformdirs` is allowed when standard-library reimplementation would be riskier       |
| No domain schemas or reverse dependencies    | Accepted | Consumers validate domain data above primitive shapes                                   |
| Complete-file processing                     | Accepted | Simpler verification, but unsuitable for very large files                               |
| Curated package facade                       | Accepted | Convenient imports require deliberate `__all__` maintenance                             |

Decision drivers are source-control friendliness, a small reviewed dependency surface, clear downstream ownership, deterministic behavior, and prevention of common filesystem corruption and traversal mistakes. The implementation does not claim database-grade transactions or security in an adversarial filesystem.

<!-- archledger: no accepted records for this section yet -->

# Quality Requirements

## Quality tree

- **Reliability:** atomic visibility, exclusive creation, explicit malformed-data reporting
- **Safety:** safe YAML, path confinement, no implicit network or command execution
- **Maintainability:** narrow modules, typed APIs, shared errors, deterministic tests
- **Compatibility:** Python 3.10+, canonical output, supported legacy inputs, UTF-8
- **Performance:** low overhead for repository-scale files and explicit fsync tradeoff

| ID   | Scenario                                                            | Expected response                                                                     |
| ---- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Q-01 | Update an existing JSON state file                                  | Readers see the old complete file or new complete file under normal replace semantics |
| Q-02 | Two processes create the same path                                  | At most one exclusive create succeeds                                                 |
| Q-03 | YAML/JSON has the wrong root type                                   | Loading raises the corresponding store error                                          |
| Q-04 | A path is absolute, traversing, empty-segmented, or backslash-based | Validation rejects it before use beneath the base                                     |
| Q-05 | Canonicalize the same mapping repeatedly                            | JSON bytes and SHA-256 remain identical                                               |
| Q-06 | JSONL contains good and malformed rows                              | Good rows are returned; each bad row has a line and issue code                        |
| Q-07 | Read a supported legacy reference                                   | It parses to a canonical immutable value                                              |
| Q-08 | Disposable data does not need crash durability                      | The caller can explicitly disable fsync                                               |
| Q-09 | A downstream boundary catches a failure                             | It can catch `LedgerCoreError` or a narrower subclass                                 |
| Q-10 | A public primitive changes                                          | Pytest, Ruff, and strict mypy expose behavioral, style, and typing regressions        |

Most functions are pure transformations or accept explicit paths and policies. Time supports injection, filesystem tests use temporary directories, and no global mutable state prevents isolation.



## Quality Requirements Overview

<!-- archledger: no accepted records for this section yet -->

## Quality Scenarios

<!-- archledger: no accepted records for this section yet -->

# Risks and Technical Debt

| Risk / debt                                                | Impact                                                                        | Mitigation                                                                            |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| No inter-process lock or transactional ID allocator        | Concurrent scans can choose the same ID                                       | Pair with exclusive create and retry downstream                                       |
| Filesystem-dependent atomicity/fsync                       | Crash behavior varies on unusual or network filesystems                       | Colocate temp files and test target environments                                      |
| Symlink changes after path validation                      | Hostile writable trees can defeat confinement                                 | Treat base trees as trusted; consider descriptor-relative APIs for hardened use       |
| Whole-file processing                                      | Memory and latency scale with size                                            | Restrict use to ledger-scale artifacts                                                |
| YAML implicit typing                                       | Scalar interpretation can surprise                                            | Safe loading, timestamp-string option, minimal quoting, and downstream schemas        |
| Error code declarations may drift from docs                | Consumers may see inconsistent codes                                          | Subclass code attributes are covered by tests before promising code stability         |
| Package facade may drift from module APIs                  | Imports/docs can lag                                                          | Review `__all__`, docs, and tests together                                            |
| Permissive reference aliases                               | Ambiguity pressure grows with kind formats                                    | Prefer canonical form and apply allowlists                                            |
| Informal pre-1.0 compatibility                             | Upgrades may break consumers                                                  | Define deprecation/version policy before 1.0                                          |
| No property-based or fault-injection tests                 | Rare parser and cleanup edges may escape                                      | Add them where risk justifies complexity                                              |
| Architecture drift is not CI-gated                         | Documentation can become stale                                                | Maintain source refs and run `archledger source changed` in review                    |
| Direct sibling roots can collide across projects           | One external store may be selected accidentally                               | Require `.ledger-store` and downstream project-binding markers; fail without fallback |
| External Git is operator-owned                             | Offline computers can diverge or allocate conflicting IDs                     | Pull, commit, push promptly, and resolve integration conflicts downstream             |
| Incomplete migration recovery requires manual intervention | Ledgercore 0.5.1 can inspect but not automatically resume incomplete journals | Classify honestly as manual intervention; implement full recovery in 0.6.0            |
| Completed-only migration recovery                    | A completed journal is reportable, but incomplete work may need operator cleanup | Keep source storage, expose persisted facts, and defer cleanup/recovery APIs to 0.6.0 |

Lack of multi-file transactions, indexing, remote access, and domain validation is an intentional boundary, not an incomplete feature list.

## Risk Overview

<!-- archledger: no accepted records for this section yet -->

# Glossary

| Term                       | Meaning                                                                  |
| -------------------------- | ------------------------------------------------------------------------ |
| Atomic create              | Create the final path with exclusive OS flags without overwriting        |
| Atomic replace             | Replace a path so ordinary readers do not observe partial target content |
| Canonical JSON             | Compact sorted-key JSON used for stable fingerprints                     |
| Canonical reference        | Global form `ledger:kind-number`                                         |
| Config locator             | Immutable workspace root, config path, and source result                 |
| Downstream application     | A ledger product that imports `ledgercore`                               |
| File-safe reference        | Global alias such as `tl-task-0001`                                      |
| Fingerprint                | SHA-256 digest for text or canonical data                                |
| Front matter               | YAML mapping delimited by `---` at the beginning of a text document      |
| Global reference           | Identity containing ledger namespace and local ID                        |
| Ledger                     | File-backed collection of records owned by a downstream application      |
| Ledger code                | Short namespace token such as `tl`, `al`, or `sw`                        |
| Local ID                   | Identity without namespace, such as `task-0001`                          |
| Normalization              | Converting accepted variants consistently; not security validation       |
| Path confinement           | Requiring a resolved path to remain under a trusted base                 |
| Resource kind              | Record-type token such as `task` or `quality-requirement`                |
| Source-first documentation | Canonical architecture fragments from which builds are derived           |
| Store error                | Package error for malformed structured data or file I/O                  |
| Whole-file processing      | Reading or constructing a complete artifact in memory                    |

<!-- archledger: no accepted records for this section yet -->
