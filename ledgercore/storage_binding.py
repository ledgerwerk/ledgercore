"""Ledgercore-owned storage binding and external store markers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

from tomlkit import dumps, parse, table

from ledgercore.atomic import atomic_write_text
from ledgercore.errors import StorageBindingError

BindingStorage = Literal["project", "external", "user-data", "cache"]


@dataclass(frozen=True)
class StorageBinding:
    schema_version: int
    layout_version: int
    project_uuid: str
    project_name: str | None
    tool: str
    mount: str
    storage: BindingStorage


@dataclass(frozen=True)
class StorageValidationResult:
    valid: bool
    path: Path
    binding: StorageBinding | None = None
    reason: str | None = None


@dataclass(frozen=True)
class StorageValidationReport:
    results: tuple[StorageValidationResult, ...]

    @property
    def valid(self) -> bool:
        return all(result.valid for result in self.results)


def _marker_path(path: Path) -> Path:
    return path / ".ledger-project.toml" if path.is_dir() else path


def _string(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str) or not value:
        raise StorageBindingError(f"{field} must be a non-empty string")
    return value


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StorageBindingError(f"{field} must be an integer")
    return value


def _parse_binding(document: Any, path: Path) -> StorageBinding:
    if not hasattr(document, "get"):
        raise StorageBindingError(f"binding marker {path} must contain a TOML table")
    schema = _int(document.get("schema_version"), f"{path}: schema_version")
    layout = _int(document.get("layout_version"), f"{path}: layout_version")
    if schema != 1 or layout != 3:
        raise StorageBindingError(
            f"binding marker {path} has unsupported schema/layout {schema}/{layout}; "
            "initialize it explicitly for Ledgercore layout 3"
        )
    project_uuid = _string(document.get("project_uuid"), f"{path}: project_uuid")
    project_name_value = document.get("project_name")
    project_name = (
        None
        if project_name_value is None
        else _string(project_name_value, f"{path}: project_name")
    )
    tool = _string(document.get("tool"), f"{path}: tool")
    mount = _string(document.get("mount"), f"{path}: mount")
    storage = _string(document.get("storage"), f"{path}: storage")
    if storage not in {"project", "external", "user-data", "cache"}:
        raise StorageBindingError(f"{path}: unsupported storage {storage!r}")
    return StorageBinding(
        schema_version=schema,
        layout_version=layout,
        project_uuid=project_uuid,
        project_name=project_name,
        tool=tool,
        mount=mount,
        storage=cast(BindingStorage, storage),
    )


def read_storage_binding(path: Path) -> StorageBinding:
    """Read a binding marker from a marker path or its containing directory."""
    marker = _marker_path(path)
    if marker.is_symlink() or not marker.is_file():
        raise StorageBindingError(
            f"storage binding marker {marker} is missing or is not a regular file"
        )
    try:
        document = parse(marker.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StorageBindingError(
            f"unable to read storage binding marker {marker}: {exc}"
        ) from exc
    try:
        return _parse_binding(document, marker)
    except StorageBindingError:
        raise
    except Exception as exc:
        raise StorageBindingError(
            f"invalid storage binding marker {marker}: {exc}"
        ) from exc


def write_storage_binding(path: Path, binding: StorageBinding) -> None:
    """Atomically write a binding marker."""
    marker = _marker_path(path)
    doc = table()
    doc.add("schema_version", binding.schema_version)
    doc.add("layout_version", binding.layout_version)
    doc.add("project_uuid", binding.project_uuid)
    if binding.project_name is not None:
        doc.add("project_name", binding.project_name)
    doc.add("tool", binding.tool)
    doc.add("mount", binding.mount)
    doc.add("storage", binding.storage)
    text = dumps(doc)
    if not text.endswith("\n"):
        text += "\n"
    try:
        atomic_write_text(marker, text)
    except Exception as exc:
        raise StorageBindingError(
            f"unable to write storage binding marker {marker}: {exc}"
        ) from exc


def _binding_for_mount(mount: Any) -> StorageBinding:
    if mount.project_uuid is None or mount.tool is None:
        raise StorageBindingError(
            "resolved mount does not carry project UUID and tool identity"
        )
    return StorageBinding(
        schema_version=1,
        layout_version=3,
        project_uuid=mount.project_uuid,
        project_name=None,
        tool=mount.tool,
        mount=mount.name,
        storage=mount.storage,
    )


def _validate_directory(path: Path, *, require_empty: bool) -> None:
    if path.exists() and path.is_symlink():
        raise StorageBindingError(f"storage directory {path} must not be a symlink")
    if path.exists() and not path.is_dir():
        raise StorageBindingError(f"storage path {path} is not a directory")
    if require_empty and path.exists() and any(path.iterdir()):
        raise StorageBindingError(f"storage directory {path} is non-empty and unbound")
    path.mkdir(parents=True, exist_ok=True)


def initialize_storage_binding(
    resolved_mount: Any,
    *,
    require_empty: bool = True,
) -> StorageBinding:
    """Initialize an empty resolved mount with its expected ownership marker."""
    path = resolved_mount.path
    _validate_directory(path, require_empty=require_empty)
    binding = _binding_for_mount(resolved_mount)
    marker = path / ".ledger-project.toml"
    if marker.exists():
        existing = read_storage_binding(marker)
        if existing != binding:
            raise StorageBindingError(
                f"storage binding marker {marker} belongs to another location"
            )
        return existing
    write_storage_binding(marker, binding)
    return binding


def _expected_from_layout(layout: Any, mount: Any) -> StorageBinding:
    return StorageBinding(
        schema_version=1,
        layout_version=3,
        project_uuid=layout.project_uuid,
        project_name=None,
        tool=layout.ledger_name,
        mount=mount.name,
        storage=mount.storage,
    )


def validate_storage_binding(
    resolved_mount: Any,
    *,
    allow_missing: bool = False,
    expected: StorageBinding | None = None,
) -> StorageValidationResult:
    """Validate one resolved mount marker without writing."""
    path = resolved_mount.path
    marker = path / ".ledger-project.toml"
    if not path.exists():
        if allow_missing:
            return StorageValidationResult(
                True, path, reason="missing location allowed"
            )
        return StorageValidationResult(
            False, path, reason=f"missing storage directory {path}"
        )
    if path.is_symlink() or not path.is_dir():
        return StorageValidationResult(
            False, path, reason=f"storage path {path} is not a real directory"
        )
    if not marker.exists():
        if not any(path.iterdir()) and allow_missing:
            return StorageValidationResult(
                True, path, reason="empty uninitialized location allowed"
            )
        return StorageValidationResult(
            False, path, reason=f"unbound non-empty storage directory {path}"
        )
    try:
        actual = read_storage_binding(marker)
        if (
            expected is None
            and getattr(resolved_mount, "project_uuid", None) is not None
        ):
            expected = _binding_for_mount(resolved_mount)
        if expected is not None and actual != expected:
            return StorageValidationResult(
                False,
                path,
                actual,
                reason=(
                    f"binding mismatch at {marker}: expected "
                    "project/tool/mount/storage "
                    f"{expected.project_uuid}/{expected.tool}/"
                    f"{expected.mount}/{expected.storage}, "
                    f"got {actual.project_uuid}/{actual.tool}/"
                    f"{actual.mount}/{actual.storage}"
                ),
            )
        return StorageValidationResult(True, path, actual)
    except StorageBindingError as exc:
        return StorageValidationResult(False, path, reason=str(exc))


def initialize_config_binding(layout: Any) -> StorageBinding:
    """Initialize the tool configuration directory binding explicitly."""
    if layout.tool_config_path is None:
        raise StorageBindingError("layout has no tool configuration path")
    component = SimpleNamespace(
        path=layout.tool_config_path.parent,
        project_uuid=layout.project_uuid,
        tool=layout.ledger_name,
        name="config",
        storage="project",
    )
    _validate_directory(component.path, require_empty=False)
    binding = _binding_for_mount(component)
    marker = component.path / ".ledger-project.toml"
    if marker.exists():
        existing = read_storage_binding(marker)
        if existing != binding:
            raise StorageBindingError(
                f"configuration binding marker {marker} belongs to another location"
            )
        return existing
    write_storage_binding(marker, binding)
    return binding


def validate_ledger_layout_storage(layout: Any) -> StorageValidationReport:
    """Validate configuration and every mount in a resolved layout."""
    results: list[StorageValidationResult] = []
    if layout.tool_config_path is not None:
        config = SimpleNamespace(
            path=layout.tool_config_path.parent,
            project_uuid=layout.project_uuid,
            tool=layout.ledger_name,
            name="config",
            storage="project",
        )
        results.append(
            validate_storage_binding(
                config,
                allow_missing=True,
                expected=_binding_for_mount(config),
            )
        )
    for mount in layout.mounts.values():
        result = validate_storage_binding(
            mount,
            allow_missing=True,
            expected=_expected_from_layout(layout, mount),
        )
        if mount.storage == "external":
            root = mount.root
            if root is not None:
                try:
                    validate_external_store(root)
                except StorageBindingError as exc:
                    result = StorageValidationResult(
                        False, mount.path, result.binding, str(exc)
                    )
        results.append(result)
    return StorageValidationReport(tuple(results))


def initialize_external_store(root: Path, *, legacy_compatible: bool = False) -> Path:
    """Create the structured external store marker explicitly."""
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise StorageBindingError(f"external store root {root} is not a real directory")
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".ledger-store.toml"
    doc = table()
    doc.add("schema_version", 1)
    doc.add("kind", "ledgerwerk-store")
    text = dumps(doc)
    if not text.endswith("\n"):
        text += "\n"
    atomic_write_text(marker, text)
    return marker


def validate_external_store(root: Path, *, allow_legacy: bool = True) -> Path:
    """Validate a structured external store marker."""
    marker = root / ".ledger-store.toml"
    if not marker.exists() and allow_legacy:
        legacy = root / ".ledger-store"
        if legacy.is_file() and not legacy.is_symlink():
            return legacy
    if marker.is_symlink() or not marker.is_file():
        raise StorageBindingError(
            f"external store marker {marker} is missing or invalid; "
            "initialize the external root explicitly"
        )
    try:
        document = parse(marker.read_text(encoding="utf-8"))
        if (
            document.get("schema_version") != 1
            or document.get("kind") != "ledgerwerk-store"
        ):
            raise StorageBindingError(
                f"external store marker {marker} has invalid identity"
            )
    except StorageBindingError:
        raise
    except Exception as exc:
        raise StorageBindingError(
            f"unable to read external store marker {marker}: {exc}"
        ) from exc
    return marker


__all__ = [
    "StorageBinding",
    "StorageValidationReport",
    "StorageValidationResult",
    "initialize_config_binding",
    "initialize_external_store",
    "initialize_storage_binding",
    "read_storage_binding",
    "validate_external_store",
    "validate_ledger_layout_storage",
    "validate_storage_binding",
    "write_storage_binding",
]
