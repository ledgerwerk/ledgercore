from __future__ import annotations

from pathlib import Path

import pytest

from ledgercore.config import LedgerProjectLocator
from ledgercore.errors import StorageBindingError
from ledgercore.layout import PlatformRoots, resolve_ledger_layout
from ledgercore.manifest import parse_ledger_manifest_v3
from ledgercore.storage_binding import (
    StorageBinding,
    initialize_external_store,
    initialize_storage_binding,
    read_storage_binding,
    storage_binding_from_mapping,
    storage_binding_to_mapping,
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


def _sample_binding(**overrides: object) -> StorageBinding:
    defaults = {
        "schema_version": 1,
        "layout_version": 3,
        "project_uuid": UUID,
        "project_name": "example",
        "tool": "taskledger",
        "mount": "data",
        "storage": "external",
    }
    defaults.update(overrides)
    return StorageBinding(**defaults)  # type: ignore[arg-type]


def test_mapping_roundtrip_preserves_all_fields() -> None:
    binding = _sample_binding()
    mapping = storage_binding_to_mapping(binding)
    restored = storage_binding_from_mapping(mapping, source="test")
    assert restored == binding


def test_mapping_roundtrip_external_to_user_data() -> None:
    source = _sample_binding(storage="external")
    dest = _sample_binding(storage="user-data")
    s_map = storage_binding_to_mapping(source)
    d_map = storage_binding_to_mapping(dest)
    assert s_map["storage"] == "external"
    assert d_map["storage"] == "user-data"
    assert storage_binding_from_mapping(s_map, source="test") == source
    assert storage_binding_from_mapping(d_map, source="test") == dest


def test_mapping_project_name_none_omitted_and_restored() -> None:
    binding = _sample_binding(project_name=None)
    mapping = storage_binding_to_mapping(binding)
    assert "project_name" not in mapping
    restored = storage_binding_from_mapping(mapping, source="test")
    assert restored.project_name is None


def test_mapping_nonnull_project_name_preserved() -> None:
    binding = _sample_binding(project_name="my-project")
    mapping = storage_binding_to_mapping(binding)
    assert mapping["project_name"] == "my-project"
    restored = storage_binding_from_mapping(mapping, source="test")
    assert restored.project_name == "my-project"


def test_mapping_rejects_missing_required_field() -> None:
    binding = _sample_binding()
    mapping = storage_binding_to_mapping(binding)
    del mapping["project_uuid"]
    with pytest.raises(StorageBindingError):
        storage_binding_from_mapping(mapping, source="test")


def test_mapping_rejects_invalid_storage() -> None:
    binding = _sample_binding()
    mapping = storage_binding_to_mapping(binding)
    mapping["storage"] = "invalid-kind"
    with pytest.raises(StorageBindingError):
        storage_binding_from_mapping(mapping, source="test")


def test_mapping_rejects_invalid_schema_layout() -> None:
    binding = _sample_binding()
    mapping = storage_binding_to_mapping(binding)
    mapping["schema_version"] = 99
    with pytest.raises(StorageBindingError):
        storage_binding_from_mapping(mapping, source="test")
