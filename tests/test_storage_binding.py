from __future__ import annotations

from pathlib import Path

from ledgercore.config import LedgerProjectLocator
from ledgercore.layout import PlatformRoots, resolve_ledger_layout
from ledgercore.manifest import parse_ledger_manifest_v3
from ledgercore.storage_binding import (
    initialize_external_store,
    initialize_storage_binding,
    read_storage_binding,
    validate_ledger_layout_storage,
)

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def test_binding_markers_validate_project_and_external_storage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".ledger").mkdir(parents=True)
    initialize_external_store(tmp_path / "ledger")
    locator = LedgerProjectLocator(
        project,
        project / ".ledger",
        project / ".ledger/ledger.toml",
        project / ".ledger/ledger.local.toml",
        "canonical",
    )
    manifest = parse_ledger_manifest_v3(
        {
            "schema_version": 3,
            "project": {"uuid": UUID},
            "ledgers": {
                "taskledger": {
                    "mounts": {
                        "config-data": {"storage": "project"},
                        "data": {"storage": "external", "root": "../ledger"},
                    }
                }
            },
        }
    )
    layout = resolve_ledger_layout(
        locator,
        manifest,
        "taskledger",
        platform_roots=PlatformRoots(tmp_path / "data", tmp_path / "cache"),
    )
    initialize_storage_binding(layout.mounts["data"])
    assert read_storage_binding(layout.mounts["data"].path).mount == "data"
    report = validate_ledger_layout_storage(layout)
    assert report.valid
