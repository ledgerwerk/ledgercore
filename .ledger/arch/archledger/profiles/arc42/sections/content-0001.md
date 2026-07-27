---
schema_version: 4
id: content-0001
version: 2
kind: content
type: section
section: introduction_and_goals
title: Introduction and Goals
order: 10
status: accepted
body_format: markdown
source_refs:
  - path: README.md
    reason: Purpose, goals, public scope, and non-goals
---

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
