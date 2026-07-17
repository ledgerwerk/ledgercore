from __future__ import annotations

from pathlib import Path

from ledgercore.storage_paths import (
    derive_cache_mount_path,
    derive_external_mount_path,
    derive_project_mount_path,
    derive_tool_config_path,
    derive_user_data_mount_path,
)

UUID = "081c7c05-2d10-42b7-9b37-3d814c2f400a"


def test_schema3_path_formulas(tmp_path: Path) -> None:
    project = tmp_path / "project"
    assert (
        derive_tool_config_path(project, "taskledger")
        == (project / ".ledger/taskledger/config.toml").resolve()
    )
    assert (
        derive_project_mount_path(project, "taskledger", "data")
        == (project / ".ledger/taskledger/data").resolve()
    )
    assert (
        derive_external_mount_path(
            "../ledger", "taskledger", UUID, "data", project_root=project
        )
        == (tmp_path / "ledger/taskledger" / UUID / "data").resolve()
    )
    assert (
        derive_user_data_mount_path(tmp_path / "data", "taskledger", UUID, "data")
        == (tmp_path / "data/taskledger" / UUID / "data").resolve()
    )
    assert (
        derive_cache_mount_path(
            tmp_path / "cache", "taskledger", UUID, "checkout", "indexes"
        )
        == (tmp_path / "cache/taskledger" / UUID / "checkout/indexes").resolve()
    )
