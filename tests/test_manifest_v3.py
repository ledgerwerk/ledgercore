from __future__ import annotations

import pytest

from ledgercore.errors import LedgerLayoutError
from ledgercore.manifest import parse_ledger_manifest_v3

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def manifest(storage: str, **extra: object) -> dict[str, object]:
    mount: dict[str, object] = {"storage": storage}
    mount.update(extra)
    return {
        "schema_version": 3,
        "project": {"uuid": UUID},
        "ledgers": {"taskledger": {"mounts": {"data": mount}}},
    }


def test_parses_all_storage_kinds() -> None:
    for storage, extra in (
        ("project", {}),
        ("external", {"root": "../ledger"}),
        ("user-data", {}),
        ("cache", {}),
    ):
        parsed = parse_ledger_manifest_v3(manifest(storage, **extra))
        assert parsed.project_uuid == UUID
        assert parsed.ledgers["taskledger"].mounts["data"].storage == storage


@pytest.mark.parametrize(
    "field", ["path", "scope", "provider", "namespace", "location"]
)
def test_rejects_removed_schema_fields(field: str) -> None:
    document = manifest("project")
    document["ledgers"]["taskledger"]["mounts"]["data"][field] = "value"  # type: ignore[index]
    with pytest.raises(LedgerLayoutError):
        parse_ledger_manifest_v3(document)


def test_external_root_is_required_and_non_external_root_is_rejected() -> None:
    with pytest.raises(LedgerLayoutError, match="root is required"):
        parse_ledger_manifest_v3(manifest("external"))
    with pytest.raises(LedgerLayoutError, match="only allowed"):
        parse_ledger_manifest_v3(manifest("project", root="../ledger"))
