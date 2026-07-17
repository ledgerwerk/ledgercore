from __future__ import annotations

import pytest

from ledgercore.errors import LedgerLayoutError
from ledgercore.manifest import (
    LedgerLocalOverrides,
    apply_ledger_local_overrides,
    parse_ledger_local_overrides_v3,
    parse_ledger_manifest_v3,
)
from ledgercore.overrides import clear_local_mount_override, set_local_mount_override

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def base_manifest():
    return parse_ledger_manifest_v3(
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


def test_storage_change_drops_inherited_external_root() -> None:
    base = base_manifest()
    overrides = parse_ledger_local_overrides_v3(
        {
            "schema_version": 3,
            "ledgers": {"taskledger": {"mounts": {"data": {"storage": "user-data"}}}},
        },
        base=base,
    )
    effective = apply_ledger_local_overrides(base, overrides)
    assert effective["taskledger"].mounts["data"].storage == "user-data"
    assert effective["taskledger"].mounts["data"].external_root is None


def test_update_helpers_are_immutable() -> None:
    base = base_manifest()
    empty = LedgerLocalOverrides(3, {})
    updated = set_local_mount_override(
        base, empty, "taskledger", "data", storage="user-data"
    )
    assert not empty.ledgers
    assert updated.ledgers["taskledger"]["data"].storage == "user-data"
    assert not clear_local_mount_override(base, updated, "taskledger", "data").ledgers


def test_unknown_tool_and_mount_are_rejected() -> None:
    base = base_manifest()
    with pytest.raises(LedgerLayoutError, match="unknown tool"):
        parse_ledger_local_overrides_v3({"ledgers": {"other": {}}}, base=base)
    with pytest.raises(LedgerLayoutError, match="unknown mount"):
        parse_ledger_local_overrides_v3(
            {"ledgers": {"taskledger": {"mounts": {"other": {"storage": "cache"}}}}},
            base=base,
        )
