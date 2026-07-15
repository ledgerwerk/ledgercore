"""Typed Ledger-family project layout parsing and resolution."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, TypeVar, cast

from platformdirs import user_cache_path, user_data_path

from ledgercore.config import LedgerProjectLocator
from ledgercore.errors import LedgerLayoutError, PathValidationError
from ledgercore.ids import slugify_ref
from ledgercore.paths import resolve_relative_child, validate_relative_posix_path

StorageClass = Literal["repository", "workspace", "cache"]
StorageScope = Literal["project", "checkout"]
ConfigLocation = Literal["project", "workspace"]
StorageResolutionSource = Literal[
    "repository",
    "explicit",
    "environment",
    "local-root",
    "local-provider",
    "manifest-default",
]

_SIBLING_LEDGER_PROVIDER = "sibling-ledger"
_SIBLING_LEDGER_DIRNAME = "ledger"
_SIBLING_LEDGER_MARKER = ".ledger-store"

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "project", "storage", "ledgers"})
_PROJECT_FIELDS = frozenset({"uuid", "name"})
_STORAGE_FIELDS = frozenset({"workspace", "cache"})
_STORAGE_CLASS_FIELDS = frozenset({"default_provider", "namespace"})
_LEDGER_FIELDS = frozenset({"config", "mounts"})
_TOOL_CONFIG_FIELDS = frozenset({"location", "path", "scope"})
_MOUNT_FIELDS = frozenset({"storage", "path", "scope"})
_LOCAL_TOP_LEVEL_FIELDS = frozenset({"schema_version", "checkout", "storage"})
_LOCAL_CHECKOUT_FIELDS = frozenset({"id"})
_LOCAL_STORAGE_FIELDS = frozenset({"workspace", "cache"})
_LOCAL_STORAGE_CLASS_FIELDS = frozenset({"root", "provider"})


@dataclass(frozen=True)
class PlatformRoots:
    user_data: Path
    user_cache: Path


@dataclass(frozen=True)
class _SelectedStorageBackend:
    root: Path
    source: StorageResolutionSource
    namespaced: bool
    provider: str | None


@dataclass(frozen=True)
class LedgerMount:
    name: str
    storage: StorageClass
    path: str
    scope: StorageScope | None


@dataclass(frozen=True)
class ToolConfigDefinition:
    location: ConfigLocation
    path: str
    scope: StorageScope | None


@dataclass(frozen=True)
class LedgerRegistration:
    name: str
    config: ToolConfigDefinition | None
    mounts: Mapping[str, LedgerMount]


@dataclass(frozen=True)
class LedgerProjectManifest:
    schema_version: int
    project_uuid: str
    project_name: str | None
    workspace_namespace: str
    cache_namespace: str
    workspace_default_provider: str
    cache_default_provider: str
    ledgers: Mapping[str, LedgerRegistration]


@dataclass(frozen=True)
class LedgerLocalConfig:
    schema_version: int
    workspace_root: Path | None
    cache_root: Path | None
    workspace_provider: str | None
    cache_provider: str | None
    checkout_id: str | None


@dataclass(frozen=True)
class ResolvedMount:
    name: str
    storage: StorageClass
    scope: StorageScope | None
    scoped_root: Path
    path: Path
    source: StorageResolutionSource


@dataclass(frozen=True)
class ResolvedLedgerLayout:
    ledger_name: str
    project_uuid: str
    project_root: Path
    config_root: Path
    manifest_path: Path
    local_config_path: Path
    tool_config_path: Path | None
    checkout_id: str | None
    mounts: Mapping[str, ResolvedMount]


@dataclass(frozen=True)
class _OwnedPath:
    owner: str
    path: str
    segments: tuple[str, ...]


T = TypeVar("T")


def _freeze_mapping(values: Mapping[str, T] | dict[str, T]) -> Mapping[str, T]:
    return cast(Mapping[str, T], MappingProxyType(dict(values)))


def _expect_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LedgerLayoutError(f"{field_name} must be a table")
    return cast(Mapping[str, Any], value)


def _check_unknown_fields(
    mapping: Mapping[str, Any], field_name: str, allowed: frozenset[str]
) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise LedgerLayoutError(
            f"{field_name} contains unsupported field(s): {', '.join(unknown)}"
        )


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LedgerLayoutError(f"{field_name} must be an integer")
    return value


def _require_string(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise LedgerLayoutError(f"{field_name} must be a string")
    if not allow_empty and value == "":
        raise LedgerLayoutError(f"{field_name} must not be empty")
    return value


def _require_token(value: Any, field_name: str) -> str:
    token = _require_string(value, field_name)
    if not _TOKEN_RE.fullmatch(token):
        raise LedgerLayoutError(
            f"{field_name} must match {_TOKEN_RE.pattern!r}: {token!r}"
        )
    return token


def _require_safe_segment(value: Any, field_name: str) -> str:
    segment = _require_string(value, field_name)
    if segment in {".", ".."}:
        raise LedgerLayoutError(f"{field_name} must not be '.' or '..'")
    if "/" in segment or "\\" in segment:
        raise LedgerLayoutError(f"{field_name} must not contain path separators")
    if "\x00" in segment or any(ord(char) < 32 for char in segment):
        raise LedgerLayoutError(f"{field_name} must not contain control characters")
    return segment


def _validate_relative_layout_path(value: Any, field_name: str) -> str:
    text = _require_string(value, field_name)
    try:
        return validate_relative_posix_path(text, field_name=field_name)
    except PathValidationError as exc:
        raise LedgerLayoutError(f"{field_name} is invalid: {exc}") from exc


def _resolve_layout_child(base_dir: Path, relative_path: str, field_name: str) -> Path:
    try:
        return resolve_relative_child(base_dir, relative_path, field_name=field_name)
    except PathValidationError as exc:
        raise LedgerLayoutError(f"{field_name} is invalid: {exc}") from exc


def _normalize_uuid(value: Any, field_name: str) -> str:
    text = _require_string(value, field_name)
    try:
        return str(uuid.UUID(text))
    except ValueError as exc:
        raise LedgerLayoutError(f"{field_name} must be a valid UUID") from exc


def _parse_storage_class(value: Any, field_name: str) -> StorageClass:
    storage = _require_string(value, field_name)
    if storage not in {"repository", "workspace", "cache"}:
        raise LedgerLayoutError(
            f"{field_name} must be one of repository, workspace, or cache"
        )
    return cast(StorageClass, storage)


def _parse_storage_scope(value: Any, field_name: str) -> StorageScope:
    scope = _require_string(value, field_name)
    if scope not in {"project", "checkout"}:
        raise LedgerLayoutError(f"{field_name} must be 'project' or 'checkout'")
    return cast(StorageScope, scope)


def _parse_config_location(value: Any, field_name: str) -> ConfigLocation:
    location = _require_string(value, field_name)
    if location not in {"project", "workspace"}:
        raise LedgerLayoutError(f"{field_name} must be 'project' or 'workspace'")
    return cast(ConfigLocation, location)


def _resolve_trusted_root(value: Path | str, *, project_root: Path) -> Path:
    raw = os.fspath(value)
    # $HOME is consulted explicitly so that local configs can target a
    # user-chosen directory on every platform. On Windows, neither
    # os.path.expanduser nor Path.expanduser honors $HOME; they only look at
    # USERPROFILE / HOMEDRIVE / HOMEPATH and would silently fall back to the
    # runner's user profile otherwise.
    if raw.startswith("~"):
        home = os.environ.get("HOME")
        if home and (raw == "~" or raw[1] in ("/", "\\")):
            raw = home if raw == "~" else os.path.join(home, raw[2:])
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def _default_platform_roots(manifest: LedgerProjectManifest) -> PlatformRoots:
    return PlatformRoots(
        user_data=Path(user_data_path(manifest.workspace_namespace, appauthor=False)),
        user_cache=Path(user_cache_path(manifest.cache_namespace, appauthor=False)),
    )


def _parse_storage_defaults(
    storage: Mapping[str, Any] | None,
    *,
    storage_class: Literal["workspace", "cache"],
) -> tuple[str, str]:
    if storage is None:
        return (
            ("user-data", "ledgerwerk")
            if storage_class == "workspace"
            else ("user-cache", "ledgerwerk")
        )

    field_name = f"storage.{storage_class}"
    _check_unknown_fields(storage, field_name, _STORAGE_CLASS_FIELDS)

    default_provider_name = (
        "user-data" if storage_class == "workspace" else "user-cache"
    )
    default_provider = storage.get("default_provider", default_provider_name)
    provider = _require_string(default_provider, f"{field_name}.default_provider")
    if provider != default_provider_name:
        raise LedgerLayoutError(
            f"{field_name}.default_provider must be {default_provider_name!r}"
        )

    namespace = storage.get("namespace", "ledgerwerk")
    normalized_namespace = _require_token(namespace, f"{field_name}.namespace")
    return provider, normalized_namespace


def _parse_tool_config(value: Any, field_name: str) -> ToolConfigDefinition:
    config = _expect_mapping(value, field_name)
    _check_unknown_fields(config, field_name, _TOOL_CONFIG_FIELDS)
    location = _parse_config_location(config.get("location"), f"{field_name}.location")
    path = _validate_relative_layout_path(config.get("path"), f"{field_name}.path")

    if location == "project":
        if "scope" in config:
            raise LedgerLayoutError(
                f"{field_name}.scope is not allowed for project config"
            )
        return ToolConfigDefinition(location="project", path=path, scope=None)

    raise LedgerLayoutError(f"{field_name}.location='workspace' is not supported")


def _parse_mount(value: Any, field_name: str, mount_name: str) -> LedgerMount:
    mount = _expect_mapping(value, field_name)
    _check_unknown_fields(mount, field_name, _MOUNT_FIELDS)
    storage = _parse_storage_class(mount.get("storage"), f"{field_name}.storage")
    path = _validate_relative_layout_path(mount.get("path"), f"{field_name}.path")

    if storage == "repository":
        if "scope" in mount:
            raise LedgerLayoutError(
                f"{field_name}.scope is not allowed for repository mounts"
            )
        return LedgerMount(name=mount_name, storage=storage, path=path, scope=None)

    scope = _parse_storage_scope(mount.get("scope", "checkout"), f"{field_name}.scope")
    return LedgerMount(name=mount_name, storage=storage, path=path, scope=scope)


def _validate_owned_paths(manifest: LedgerProjectManifest) -> None:
    grouped_paths: dict[tuple[StorageClass, StorageScope | None], list[_OwnedPath]] = {}

    def add_path(
        group: tuple[StorageClass, StorageScope | None], owner: str, path: str
    ) -> None:
        entry = _OwnedPath(owner=owner, path=path, segments=tuple(path.split("/")))
        for existing in grouped_paths.setdefault(group, []):
            existing_is_prefix = (
                existing.segments[: len(entry.segments)] == entry.segments
            )
            entry_is_prefix = (
                entry.segments[: len(existing.segments)] == existing.segments
            )
            if existing_is_prefix or entry_is_prefix:
                group_label = group[0] if group[1] is None else f"{group[0]}/{group[1]}"
                raise LedgerLayoutError(
                    "topology collision for "
                    f"{group_label}: {existing.owner} ({existing.path}) conflicts with "
                    f"{entry.owner} ({entry.path})"
                )
        grouped_paths[group].append(entry)

    for ledger_name, registration in manifest.ledgers.items():
        if registration.config is not None:
            if registration.config.location == "project":
                add_path(
                    ("repository", None),
                    f"ledgers.{ledger_name}.config",
                    registration.config.path,
                )
            else:
                add_path(
                    ("workspace", registration.config.scope or "project"),
                    f"ledgers.{ledger_name}.config",
                    registration.config.path,
                )
        for mount_name, mount in registration.mounts.items():
            group: tuple[StorageClass, StorageScope | None]
            if mount.storage == "repository":
                group = ("repository", None)
            else:
                group = (mount.storage, mount.scope)
            add_path(group, f"ledgers.{ledger_name}.mounts.{mount_name}", mount.path)


def parse_ledger_project_manifest(document: Mapping[str, Any]) -> LedgerProjectManifest:
    """Parse a schema-version-2 Ledger project manifest from a mapping."""
    _check_unknown_fields(document, "manifest", _TOP_LEVEL_FIELDS)

    schema_version = _require_int(document.get("schema_version"), "schema_version")
    if schema_version != 2:
        raise LedgerLayoutError(f"schema_version must be 2, got {schema_version}")

    project = _expect_mapping(document.get("project"), "project")
    _check_unknown_fields(project, "project", _PROJECT_FIELDS)
    project_uuid = _normalize_uuid(project.get("uuid"), "project.uuid")
    project_name: str | None = None
    if "name" in project:
        project_name = _require_string(project.get("name"), "project.name")

    storage = document.get("storage")
    if storage is not None:
        storage = _expect_mapping(storage, "storage")
        _check_unknown_fields(storage, "storage", _STORAGE_FIELDS)

    workspace_storage: Mapping[str, Any] | None = None
    if storage is not None and "workspace" in storage:
        workspace_storage = _expect_mapping(
            storage.get("workspace"), "storage.workspace"
        )
    workspace_defaults = _parse_storage_defaults(
        workspace_storage, storage_class="workspace"
    )

    cache_storage: Mapping[str, Any] | None = None
    if storage is not None and "cache" in storage:
        cache_storage = _expect_mapping(storage.get("cache"), "storage.cache")
    cache_defaults = _parse_storage_defaults(cache_storage, storage_class="cache")

    raw_ledgers = document.get("ledgers", {})
    ledgers_table = _expect_mapping(raw_ledgers, "ledgers")
    ledgers: dict[str, LedgerRegistration] = {}
    for ledger_name, raw_registration in ledgers_table.items():
        normalized_ledger_name = _require_token(ledger_name, "ledgers key")
        registration = _expect_mapping(raw_registration, f"ledgers.{ledger_name}")
        _check_unknown_fields(registration, f"ledgers.{ledger_name}", _LEDGER_FIELDS)

        config = None
        if "config" in registration:
            config = _parse_tool_config(
                registration.get("config"), f"ledgers.{ledger_name}.config"
            )

        mounts: dict[str, LedgerMount] = {}
        if "mounts" in registration:
            mounts_table = _expect_mapping(
                registration.get("mounts"), f"ledgers.{ledger_name}.mounts"
            )
            for mount_name, raw_mount in mounts_table.items():
                normalized_mount_name = _require_token(
                    mount_name, f"ledgers.{ledger_name}.mounts key"
                )
                mounts[normalized_mount_name] = _parse_mount(
                    raw_mount,
                    f"ledgers.{ledger_name}.mounts.{mount_name}",
                    normalized_mount_name,
                )

        if config is None and not mounts:
            raise LedgerLayoutError(
                f"ledgers.{ledger_name} must define at least one config or mount"
            )

        ledgers[normalized_ledger_name] = LedgerRegistration(
            name=normalized_ledger_name,
            config=config,
            mounts=_freeze_mapping(mounts),
        )

    manifest = LedgerProjectManifest(
        schema_version=schema_version,
        project_uuid=project_uuid,
        project_name=project_name,
        workspace_namespace=workspace_defaults[1],
        cache_namespace=cache_defaults[1],
        workspace_default_provider=workspace_defaults[0],
        cache_default_provider=cache_defaults[0],
        ledgers=_freeze_mapping(ledgers),
    )
    _validate_owned_paths(manifest)
    return manifest


def _parse_local_storage_class(
    value: Any,
    field_name: str,
    *,
    project_root: Path,
) -> tuple[Path | None, str | None]:
    storage = _expect_mapping(value, field_name)
    _check_unknown_fields(storage, field_name, _LOCAL_STORAGE_CLASS_FIELDS)

    root: Path | None = None
    provider: str | None = None

    if "root" in storage:
        root_value = _require_string(storage.get("root"), f"{field_name}.root")
        root = _resolve_trusted_root(root_value, project_root=project_root)

    if "provider" in storage:
        provider = _require_token(storage.get("provider"), f"{field_name}.provider")

    if root is not None and provider is not None:
        raise LedgerLayoutError(
            f"{field_name} cannot define both root and provider at the same time"
        )

    return root, provider


def parse_ledger_local_config(
    document: Mapping[str, Any],
    *,
    project_root: Path,
) -> LedgerLocalConfig:
    """Parse the optional machine-local Ledger layout config mapping."""
    _check_unknown_fields(document, "local config", _LOCAL_TOP_LEVEL_FIELDS)

    schema_version = 1
    if "schema_version" in document:
        schema_version = _require_int(document.get("schema_version"), "schema_version")
        if schema_version != 1:
            raise LedgerLayoutError(f"schema_version must be 1, got {schema_version}")

    checkout_id: str | None = None
    if "checkout" in document:
        checkout = _expect_mapping(document.get("checkout"), "checkout")
        _check_unknown_fields(checkout, "checkout", _LOCAL_CHECKOUT_FIELDS)
        if "id" in checkout:
            checkout_id = _require_safe_segment(checkout.get("id"), "checkout.id")

    workspace_root: Path | None = None
    cache_root: Path | None = None
    workspace_provider: str | None = None
    cache_provider: str | None = None
    if "storage" in document:
        storage = _expect_mapping(document.get("storage"), "storage")
        _check_unknown_fields(storage, "storage", _LOCAL_STORAGE_FIELDS)
        if "workspace" in storage:
            workspace_root, workspace_provider = _parse_local_storage_class(
                storage.get("workspace"),
                "storage.workspace",
                project_root=project_root,
            )
        if "cache" in storage:
            cache_root, cache_provider = _parse_local_storage_class(
                storage.get("cache"),
                "storage.cache",
                project_root=project_root,
            )

    return LedgerLocalConfig(
        schema_version=schema_version,
        workspace_root=workspace_root,
        cache_root=cache_root,
        workspace_provider=workspace_provider,
        cache_provider=cache_provider,
        checkout_id=checkout_id,
    )


def derive_checkout_id(project_root: Path) -> str:
    """Derive a deterministic checkout ID from the project path."""
    resolved = project_root.resolve(strict=False)
    normalized = os.path.normcase(os.fspath(resolved))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    prefix = slugify_ref(resolved.name)
    return f"{prefix}-{digest}"


def _check_locator_consistency(locator: LedgerProjectLocator) -> None:
    expected_project_root = locator.project_root.resolve(strict=False)
    expected_config_root = (expected_project_root / ".ledger").resolve(strict=False)
    expected_manifest_path = (expected_config_root / "ledger.toml").resolve(
        strict=False
    )
    expected_local_config = (expected_config_root / "ledger.local.toml").resolve(
        strict=False
    )

    if locator.config_root.resolve(strict=False) != expected_config_root:
        raise LedgerLayoutError(
            "locator.config_root is inconsistent with locator.project_root"
        )
    if locator.manifest_path.resolve(strict=False) != expected_manifest_path:
        raise LedgerLayoutError(
            "locator.manifest_path is inconsistent with locator.project_root"
        )
    if locator.local_config_path.resolve(strict=False) != expected_local_config:
        raise LedgerLayoutError(
            "locator.local_config_path is inconsistent with locator.project_root"
        )


def _selected_checkout_id(
    project_root: Path,
    *,
    local_config: LedgerLocalConfig | None,
    explicit_checkout_id: str | None,
    environ: Mapping[str, str],
) -> str:
    if explicit_checkout_id is not None:
        return _require_safe_segment(explicit_checkout_id, "checkout_id")

    env_checkout = environ.get("LEDGER_CHECKOUT_ID")
    if env_checkout:
        return _require_safe_segment(env_checkout, "LEDGER_CHECKOUT_ID")

    if local_config is not None and local_config.checkout_id is not None:
        return _require_safe_segment(
            local_config.checkout_id,
            "local_config.checkout_id",
        )

    return derive_checkout_id(project_root)


def _resolve_sibling_ledger_root(project_root: Path) -> Path:
    candidate = project_root.parent / _SIBLING_LEDGER_DIRNAME
    root = candidate.resolve(strict=False)
    provider = _SIBLING_LEDGER_PROVIDER
    if not root.exists():
        raise LedgerLayoutError(
            f"workspace provider {provider!r} is selected, but {root!s} does not "
            "exist. Restore or initialize the sibling store, or remove the local "
            "provider selection. No fallback was used."
        )
    if not root.is_dir():
        raise LedgerLayoutError(
            f"workspace provider {provider!r} is selected, but {root!s} is not a "
            "directory. Restore the sibling store or remove the local provider "
            "selection. No fallback was used."
        )
    marker = root / _SIBLING_LEDGER_MARKER
    if not marker.exists():
        raise LedgerLayoutError(
            f"workspace provider {provider!r} is selected, but {marker!s} is "
            "missing. Create the store marker during explicit initialization or "
            "remove the local provider selection. No fallback was used."
        )
    if not marker.is_file():
        raise LedgerLayoutError(
            f"workspace provider {provider!r} is selected, but {marker!s} is not "
            "a regular file. Restore the store marker or remove the local provider "
            "selection. No fallback was used."
        )
    return root


def _selected_family_root(
    storage_class: Literal["workspace", "cache"],
    manifest: LedgerProjectManifest,
    *,
    project_root: Path,
    local_config: LedgerLocalConfig | None,
    explicit_root: Path | None,
    environ: Mapping[str, str],
    platform_roots: PlatformRoots,
) -> _SelectedStorageBackend:
    if explicit_root is not None:
        return _SelectedStorageBackend(
            root=_resolve_trusted_root(explicit_root, project_root=project_root),
            source="explicit",
            namespaced=True,
            provider=None,
        )

    env_var = (
        "LEDGER_WORKSPACE_ROOT" if storage_class == "workspace" else "LEDGER_CACHE_ROOT"
    )
    env_root = environ.get(env_var)
    if env_root:
        return _SelectedStorageBackend(
            root=_resolve_trusted_root(env_root, project_root=project_root),
            source="environment",
            namespaced=True,
            provider=None,
        )

    local_root = (
        None
        if local_config is None
        else local_config.workspace_root
        if storage_class == "workspace"
        else local_config.cache_root
    )
    if local_root is not None:
        return _SelectedStorageBackend(
            root=local_root,
            source="local-root",
            namespaced=True,
            provider=None,
        )

    local_provider = (
        None
        if local_config is None
        else local_config.workspace_provider
        if storage_class == "workspace"
        else local_config.cache_provider
    )
    if local_provider is not None:
        if storage_class == "workspace" and local_provider == _SIBLING_LEDGER_PROVIDER:
            return _SelectedStorageBackend(
                root=_resolve_sibling_ledger_root(project_root),
                source="local-provider",
                namespaced=False,
                provider=local_provider,
            )
        raise LedgerLayoutError(
            f"{storage_class} provider {local_provider!r} is not supported; "
            "only workspace provider 'sibling-ledger' is available, and it "
            "supports direct project-scoped mounts. No fallback was used."
        )

    if storage_class == "workspace":
        if manifest.workspace_default_provider != "user-data":
            raise LedgerLayoutError("workspace default provider must be 'user-data'")
        return _SelectedStorageBackend(
            root=platform_roots.user_data.resolve(strict=False),
            source="manifest-default",
            namespaced=True,
            provider="user-data",
        )

    if manifest.cache_default_provider != "user-cache":
        raise LedgerLayoutError("cache default provider must be 'user-cache'")
    return _SelectedStorageBackend(
        root=platform_roots.user_cache.resolve(strict=False),
        source="manifest-default",
        namespaced=True,
        provider="user-cache",
    )


def _scoped_root(
    base_root: Path,
    project_uuid: str,
    scope: StorageScope,
    checkout_id: str,
) -> Path:
    project_base = base_root / "projects" / project_uuid
    if scope == "project":
        return (project_base / "project").resolve(strict=False)
    return (project_base / "checkouts" / checkout_id).resolve(strict=False)


def resolve_ledger_layout(
    locator: LedgerProjectLocator,
    manifest: LedgerProjectManifest,
    ledger_name: str,
    *,
    local_config: LedgerLocalConfig | None = None,
    workspace_root: Path | None = None,
    cache_root: Path | None = None,
    checkout_id: str | None = None,
    environ: Mapping[str, str] | None = None,
    platform_roots: PlatformRoots | None = None,
) -> ResolvedLedgerLayout:
    """Resolve layout paths for one registered ledger."""
    if locator.is_legacy:
        raise LedgerLayoutError(
            "legacy project locators support discovery only; resolve from "
            "canonical .ledger/ledger.toml"
        )
    if locator.source not in {"canonical", "default"}:
        raise LedgerLayoutError(f"unsupported project locator source: {locator.source}")

    _check_locator_consistency(locator)
    registration = manifest.ledgers.get(ledger_name)
    if registration is None:
        raise LedgerLayoutError(f"unknown ledger registration: {ledger_name}")

    # Workspace tool configuration remains unsupported in 0.4.0. The parser
    # rejects it through the supported mapping path; repeat the gate here so
    # manually constructed manifests cannot bypass it.
    if registration.config is not None and registration.config.location == "workspace":
        raise LedgerLayoutError("workspace tool config is not supported")

    env = os.environ if environ is None else environ
    roots = platform_roots or _default_platform_roots(manifest)
    project_root = locator.project_root.resolve(strict=False)
    config_root = locator.config_root.resolve(strict=False)

    workspace_needed = any(
        mount.storage == "workspace" for mount in registration.mounts.values()
    ) or (
        registration.config is not None and registration.config.location == "workspace"
    )
    cache_needed = any(
        mount.storage == "cache" for mount in registration.mounts.values()
    )
    checkout_needed = any(
        mount.scope == "checkout"
        for mount in registration.mounts.values()
        if mount.scope
    )
    if registration.config is not None and registration.config.scope == "checkout":
        checkout_needed = True

    selected_checkout_id = (
        _selected_checkout_id(
            project_root,
            local_config=local_config,
            explicit_checkout_id=checkout_id,
            environ=env,
        )
        if checkout_needed
        else None
    )

    # LAY-001: only resolve the family roots that this registration actually
    # needs. A repository-only ledger must not require any external storage
    # config; a workspace-only ledger must not require a cache root.
    workspace_backend: _SelectedStorageBackend | None = None
    if workspace_needed:
        workspace_backend = _selected_family_root(
            "workspace",
            manifest,
            project_root=project_root,
            local_config=local_config,
            explicit_root=workspace_root,
            environ=env,
            platform_roots=roots,
        )
    cache_backend: _SelectedStorageBackend | None = None
    if cache_needed:
        cache_backend = _selected_family_root(
            "cache",
            manifest,
            project_root=project_root,
            local_config=local_config,
            explicit_root=cache_root,
            environ=env,
            platform_roots=roots,
        )

    resolved_mounts: dict[str, ResolvedMount] = {}
    for mount_name, mount in registration.mounts.items():
        if mount.storage == "repository":
            scoped_root = config_root
            resolved_path = _resolve_layout_child(
                scoped_root,
                mount.path,
                f"mounts.{mount_name}.path",
            )
            source: StorageResolutionSource = "repository"
        else:
            if mount.scope is None:
                raise LedgerLayoutError(f"mounts.{mount_name}.scope is required")
            if mount.scope == "checkout" and selected_checkout_id is None:
                raise LedgerLayoutError(
                    "checkout-scoped resolution requires a checkout ID"
                )
            if mount.storage == "workspace":
                assert workspace_backend is not None
                backend = workspace_backend
            else:
                assert cache_backend is not None
                backend = cache_backend
            source = backend.source
            if not backend.namespaced:
                if mount.storage != "workspace" or mount.scope != "project":
                    raise LedgerLayoutError(
                        "workspace provider 'sibling-ledger' supports only "
                        "project-scoped workspace mounts"
                    )
                scoped_root = backend.root
            else:
                scoped_root = _scoped_root(
                    backend.root,
                    manifest.project_uuid,
                    mount.scope,
                    selected_checkout_id or "",
                )
            resolved_path = _resolve_layout_child(
                scoped_root,
                mount.path,
                f"mounts.{mount_name}.path",
            )

        resolved_mounts[mount_name] = ResolvedMount(
            name=mount_name,
            storage=mount.storage,
            scope=mount.scope,
            scoped_root=scoped_root,
            path=resolved_path,
            source=source,
        )

    tool_config_path: Path | None = None
    if registration.config is not None:
        if registration.config.location == "project":
            tool_config_path = _resolve_layout_child(
                config_root,
                registration.config.path,
                "config.path",
            )
        else:
            config_scope = registration.config.scope or "project"
            if config_scope == "checkout" and selected_checkout_id is None:
                raise LedgerLayoutError("checkout-scoped config requires a checkout ID")
            assert workspace_backend is not None
            scoped_root = _scoped_root(
                workspace_backend.root,
                manifest.project_uuid,
                config_scope,
                selected_checkout_id or "",
            )
            tool_config_path = _resolve_layout_child(
                scoped_root,
                registration.config.path,
                "config.path",
            )

    return ResolvedLedgerLayout(
        ledger_name=ledger_name,
        project_uuid=manifest.project_uuid,
        project_root=project_root,
        config_root=config_root,
        manifest_path=locator.manifest_path.resolve(strict=False),
        local_config_path=locator.local_config_path.resolve(strict=False),
        tool_config_path=tool_config_path,
        checkout_id=selected_checkout_id,
        mounts=_freeze_mapping(resolved_mounts),
    )


__all__ = [
    "ConfigLocation",
    "LedgerLocalConfig",
    "LedgerMount",
    "LedgerProjectManifest",
    "LedgerRegistration",
    "PlatformRoots",
    "ResolvedLedgerLayout",
    "ResolvedMount",
    "StorageClass",
    "StorageResolutionSource",
    "StorageScope",
    "ToolConfigDefinition",
    "derive_checkout_id",
    "parse_ledger_local_config",
    "parse_ledger_project_manifest",
    "resolve_ledger_layout",
]
