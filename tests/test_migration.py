from __future__ import annotations

from pathlib import Path

from ledgercore.config import LedgerProjectLocator
from ledgercore.layout import PlatformRoots, resolve_ledger_layout
from ledgercore.manifest import (
    LedgerLocalOverrides,
    LoadedLedgerProject,
    MountOverride,
    parse_ledger_manifest_v3,
)
from ledgercore.migration import plan_storage_migration
from ledgercore.storage_binding import (
    initialize_external_store,
    initialize_storage_binding,
)

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def test_plan_rejects_unbound_source_and_does_not_write(tmp_path: Path) -> None:
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
                    "mounts": {"data": {"storage": "external", "root": "../ledger"}}
                }
            },
        }
    )
    current = LoadedLedgerProject(locator, manifest, LedgerLocalOverrides(3, {}), {})
    layout = resolve_ledger_layout(
        locator,
        manifest,
        "taskledger",
        platform_roots=PlatformRoots(tmp_path / "data", tmp_path / "cache"),
    )
    initialize_storage_binding(layout.mounts["data"])
    target = LedgerLocalOverrides(
        3, {"taskledger": {"data": MountOverride(storage="user-data")}}
    )
    plan = plan_storage_migration(current, manifest, target, "taskledger")
    assert plan.items[0].strategy == "copy"
    assert not (project / ".ledger/migrations").exists()
