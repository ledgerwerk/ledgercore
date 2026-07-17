"""Example: schema-3 project loading, bindings, and explicit migration APIs."""

from pathlib import Path
from tempfile import TemporaryDirectory

from ledgercore import (
    initialize_config_binding,
    initialize_external_store,
    initialize_storage_binding,
    load_ledger_project,
    read_ledger_manifest,
    resolve_ledger_layout,
    validate_ledger_layout_storage,
    write_ledger_manifest,
)
from ledgercore.manifest import parse_ledger_manifest_v3

with TemporaryDirectory() as temporary:
    root = Path(temporary)
    project_root = root / "project"
    manifest_path = project_root / ".ledger" / "ledger.toml"
    manifest = parse_ledger_manifest_v3(
        {
            "schema_version": 3,
            "project": {
                "uuid": "081c7c05-2d10-42b7-9b37-3d814c2f400a",
                "name": "example-project",
            },
            "ledgers": {
                "taskledger": {
                    "mounts": {
                        "data": {"storage": "external", "root": "../ledger"},
                        "indexes": {"storage": "cache"},
                    }
                }
            },
        }
    )
    initialize_external_store(root / "ledger")
    write_ledger_manifest(manifest_path, manifest)
    assert read_ledger_manifest(manifest_path).project_uuid == manifest.project_uuid

    loaded = load_ledger_project(project_root)
    layout = resolve_ledger_layout(
        loaded.locator,
        loaded.manifest,
        "taskledger",
        local_overrides=loaded.local_overrides,
    )
    initialize_config_binding(layout)
    initialize_storage_binding(layout.mounts["data"])
    assert validate_ledger_layout_storage(layout).valid

print("schema-3 storage example passed")
