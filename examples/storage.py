"""Example: working with atomic writes, JSON, YAML, path helpers, and layout."""

import tempfile
from pathlib import Path

from ledgercore.atomic import atomic_create_text, atomic_write_text
from ledgercore.config import locate_ledger_project
from ledgercore.errors import AtomicWriteError
from ledgercore.jsonio import load_json_object, write_json
from ledgercore.layout import (
    PlatformRoots,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)
from ledgercore.paths import (
    locate_config,
    resolve_config_relative_path,
    validate_relative_posix_path,
)
from ledgercore.yamlio import load_yaml_object, write_yaml

# Create a temporary directory for the example
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)

    # --- Atomic writes ---
    target = base / "hello.txt"
    atomic_write_text(target, "Hello, world!\n")
    assert target.read_text() == "Hello, world!\n"

    # atomic_create_text fails if file exists
    try:
        atomic_create_text(target, "overwrite\n")
        raise AssertionError("Should have raised AtomicWriteError")
    except AtomicWriteError:
        pass

    # atomic_write_text replaces existing files
    atomic_write_text(target, "Updated!\n")
    assert target.read_text() == "Updated!\n"

    # --- JSON store ---
    json_path = base / "state.json"
    write_json(json_path, {"next_id": 5, "active": True})
    state = load_json_object(json_path)
    assert state["next_id"] == 5

    # --- YAML store ---
    yaml_path = base / "config.yaml"
    write_yaml(yaml_path, {"records_dir": "records", "format": "md"}, sort_keys=True)
    config = load_yaml_object(yaml_path)
    assert config["records_dir"] == "records"

    # --- Path validation ---
    validate_relative_posix_path("records/task-0001.md")

    # --- Config discovery ---
    config_file = base / "ledger.toml"
    config_file.write_text("[tool]\n", encoding="utf-8")
    locator = locate_config(base, ("ledger.toml",))
    assert locator is not None
    assert locator.source == "found"

    records_dir = resolve_config_relative_path(
        locator.config_path,
        "records",
        field_name="records_dir",
    )
    assert records_dir.name == "records"

    # --- Project layout resolution ---
    project_root = base / "project"
    manifest_dir = project_root / ".ledger"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "ledger.toml").write_text("schema_version = 2\n", encoding="utf-8")
    locator = locate_ledger_project(project_root)
    assert locator is not None

    manifest = parse_ledger_project_manifest(
        {
            "schema_version": 2,
            "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
            "ledgers": {
                "taskledger": {
                    "config": {"location": "project", "path": "task/config.toml"},
                    "mounts": {
                        "data": {"storage": "workspace", "path": "task/data"},
                        "records": {"storage": "repository", "path": "task/records"},
                    },
                }
            },
        }
    )
    layout = resolve_ledger_layout(
        locator,
        manifest,
        "taskledger",
        platform_roots=PlatformRoots(
            user_data=base / "platform-data",
            user_cache=base / "platform-cache",
        ),
    )
    assert (
        layout.mounts["records"].path
        == (project_root / ".ledger" / "task" / "records").resolve()
    )
    assert "checkouts" in layout.mounts["data"].path.parts

print("storage example passed")
