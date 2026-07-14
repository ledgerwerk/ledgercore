---
schema_version: 3
id: content-0007
version: 1
kind: content
type: section
section: deployment_view
title: Deployment View
order: 70
status: accepted
date: "2026-06-13"
body_format: markdown
created_at: "2026-06-13T08:41:40.792531+00:00"
updated_at: "2026-06-13T08:56:00.329158+00:00"
source_refs:
  - path: pyproject.toml
    reason: Distribution and runtime deployment metadata
---

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
