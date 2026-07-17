from __future__ import annotations

from pathlib import Path

from ledgercore.manifest import (
    LedgerLocalOverrides,
    MountOverride,
    parse_ledger_manifest_v3,
)
from ledgercore.tomlio import (
    read_ledger_local_config,
    read_ledger_manifest,
    write_ledger_local_config,
    write_ledger_manifest,
)

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def test_manifest_and_local_config_round_trip(tmp_path: Path) -> None:
    manifest = parse_ledger_manifest_v3(
        {
            "schema_version": 3,
            "project": {"uuid": UUID, "name": "example"},
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
    path = tmp_path / "ledger.toml"
    write_ledger_manifest(path, manifest)
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert read_ledger_manifest(path).project_uuid == UUID

    overrides = LedgerLocalOverrides(
        3, {"taskledger": {"data": MountOverride(storage="user-data")}}
    )
    local_path = tmp_path / "ledger.local.toml"
    write_ledger_local_config(local_path, overrides)
    assert read_ledger_local_config(local_path, base=manifest) == overrides
