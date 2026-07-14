---
schema_version: 3
id: content-0006
kind: content
type: section
section: runtime_view
title: Runtime View
order: 60
status: accepted
date: "2026-06-13"
body_format: markdown
created_at: "2026-06-13T08:41:40.792531+00:00"
updated_at: "2026-06-13T08:55:59.841090+00:00"
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

1. Discover `.ledger/ledger.toml` from a starting path while preserving legacy-source signals when needed for migration diagnostics.
2. Parse the project manifest and optional local config from caller-supplied mappings.
3. Select workspace and cache family roots from explicit arguments, environment overrides, local config, or built-in `platformdirs` defaults.
4. Derive a checkout ID only when a ledger needs checkout-scoped data.
5. Resolve repository mounts beneath `.ledger/` and external mounts beneath fixed `projects/<uuid>/project` or `projects/<uuid>/checkouts/<checkout-id>` roots.
6. Return immutable layout objects without creating directories, markers, or config files.

## Reference normalization

The parser tries canonical, legacy underscore, file-safe, and local forms in order. It normalizes tokens, requires a positive number, preserves wider padding, optionally supplies a ledger, then applies allowlists.

## Recoverable JSONL loading

Valid object rows are retained in order. Invalid JSON and non-object rows become line-numbered issues. File-level read failures raise a store exception.
