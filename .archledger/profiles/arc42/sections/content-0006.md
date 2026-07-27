---
schema_version: 4
id: content-0006
version: 2
kind: content
type: section
section: runtime_view
title: Runtime View
order: 60
status: accepted
body_format: markdown
source_refs:
  - path: ledgercore/frontmatter.py
    reason: Representative parsing and writing runtime flow
---

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
