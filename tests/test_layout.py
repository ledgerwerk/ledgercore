"""Tests for ledgercore.layout."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from ledgercore.config import LedgerProjectLocator
from ledgercore.errors import LedgerLayoutError, PathValidationError
from ledgercore.ids import slugify_ref
from ledgercore.layout import (
    LedgerLocalConfig,
    LedgerMount,
    LedgerProjectManifest,
    LedgerRegistration,
    PlatformRoots,
    ToolConfigDefinition,
    derive_checkout_id,
    parse_ledger_local_config,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)


def _canonical_locator(project_root: Path) -> LedgerProjectLocator:
    config_root = project_root / ".ledger"
    return LedgerProjectLocator(
        project_root=project_root.resolve(),
        config_root=config_root.resolve(),
        manifest_path=(config_root / "ledger.toml").resolve(),
        local_config_path=(config_root / "ledger.local.toml").resolve(),
        source="canonical",
    )


def _manifest_document() -> dict[str, object]:
    return {
        "schema_version": 2,
        "project": {
            "uuid": "565C0312-B531-4D07-AA1F-32C796F58DAE",
            "name": "ledgercore",
        },
        "ledgers": {
            "taskledger": {
                "config": {"location": "project", "path": "task/config.toml"},
                "mounts": {
                    "data": {"storage": "workspace", "path": "task/data"},
                    "logs": {"storage": "workspace", "path": "task/logs"},
                    "records": {"storage": "repository", "path": "task/records"},
                    "cache": {
                        "storage": "cache",
                        "scope": "project",
                        "path": "task/cache",
                    },
                },
            }
        },
    }


class TestParseLedgerProjectManifest:
    def test_parses_minimal_valid_manifest(self) -> None:
        manifest = parse_ledger_project_manifest(
            {
                "schema_version": 2,
                "project": {"uuid": "565C0312-B531-4D07-AA1F-32C796F58DAE"},
                "ledgers": {
                    "taskledger": {
                        "mounts": {
                            "data": {"storage": "workspace", "path": "task/data"}
                        }
                    }
                },
            }
        )

        assert manifest.project_uuid == "565c0312-b531-4d07-aa1f-32c796f58dae"
        assert manifest.project_name is None
        assert manifest.workspace_default_provider == "user-data"
        assert manifest.cache_default_provider == "user-cache"
        assert manifest.workspace_namespace == "ledgerwerk"
        assert manifest.cache_namespace == "ledgerwerk"
        assert manifest.ledgers["taskledger"].mounts["data"].scope == "checkout"
        assert isinstance(manifest.ledgers, MappingProxyType)
        assert isinstance(manifest.ledgers["taskledger"].mounts, MappingProxyType)

    def test_parses_full_manifest(self) -> None:
        manifest = parse_ledger_project_manifest(_manifest_document())

        registration = manifest.ledgers["taskledger"]
        assert registration.config == ToolConfigDefinition(
            location="project",
            path="task/config.toml",
            scope=None,
        )
        assert registration.mounts["records"].storage == "repository"
        assert registration.mounts["cache"].scope == "project"

    @pytest.mark.parametrize(
        ("document", "message"),
        [
            ({}, "schema_version must be an integer"),
            (
                {
                    "schema_version": 3,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                },
                "schema_version must be 2",
            ),
            (
                {
                    "schema_version": True,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                },
                "schema_version must be an integer",
            ),
        ],
    )
    def test_rejects_invalid_schema_version(
        self, document: dict[str, object], message: str
    ) -> None:
        with pytest.raises(LedgerLayoutError, match=message):
            parse_ledger_project_manifest(document)

    def test_rejects_unknown_top_level_field(self) -> None:
        with pytest.raises(LedgerLayoutError, match="unsupported field"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "unexpected": {},
                }
            )

    def test_rejects_invalid_project_uuid(self) -> None:
        with pytest.raises(LedgerLayoutError, match="project.uuid"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "not-a-uuid"},
                }
            )

    def test_rejects_invalid_namespace_and_provider(self) -> None:
        with pytest.raises(
            LedgerLayoutError, match="storage.workspace.default_provider"
        ):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "storage": {"workspace": {"default_provider": "private-sibling"}},
                }
            )

        with pytest.raises(LedgerLayoutError, match="storage.cache.namespace"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "storage": {"cache": {"namespace": "Bad Namespace"}},
                }
            )

    def test_rejects_invalid_ledger_and_mount_names(self) -> None:
        with pytest.raises(LedgerLayoutError, match="ledgers key"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "ledgers": {"TaskLedger": {"mounts": {}}},
                }
            )

        with pytest.raises(LedgerLayoutError, match="mounts key"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "ledgers": {
                        "taskledger": {
                            "mounts": {
                                "BadName": {"storage": "workspace", "path": "task/data"}
                            }
                        }
                    },
                }
            )

    def test_rejects_workspace_tool_config_until_private_provider_phase(self) -> None:
        with pytest.raises(LedgerLayoutError, match="private-provider phase"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "ledgers": {
                        "taskledger": {
                            "config": {
                                "location": "workspace",
                                "scope": "project",
                                "path": "task/config.toml",
                            }
                        }
                    },
                }
            )

    def test_rejects_repository_scope_and_invalid_paths(self) -> None:
        with pytest.raises(LedgerLayoutError, match="repository mounts"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "ledgers": {
                        "taskledger": {
                            "mounts": {
                                "records": {
                                    "storage": "repository",
                                    "scope": "project",
                                    "path": "task/records",
                                }
                            }
                        }
                    },
                }
            )

        with pytest.raises(LedgerLayoutError, match="mounts.data.path") as exc_info:
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "ledgers": {
                        "taskledger": {
                            "mounts": {
                                "data": {"storage": "workspace", "path": "../escape"}
                            }
                        }
                    },
                }
            )
        assert isinstance(exc_info.value.__cause__, PathValidationError)

    def test_rejects_topology_collisions(self) -> None:
        with pytest.raises(LedgerLayoutError, match="topology collision"):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "ledgers": {
                        "taskledger": {
                            "config": {
                                "location": "project",
                                "path": "task/config.toml",
                            },
                            "mounts": {
                                "records": {"storage": "repository", "path": "task"}
                            },
                        }
                    },
                }
            )

    def test_accepts_same_relative_path_for_project_and_checkout_scopes(self) -> None:
        manifest = parse_ledger_project_manifest(
            {
                "schema_version": 2,
                "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                "ledgers": {
                    "taskledger": {
                        "mounts": {
                            "project-state": {
                                "storage": "workspace",
                                "scope": "project",
                                "path": "task/state",
                            },
                            "checkout-state": {
                                "storage": "workspace",
                                "scope": "checkout",
                                "path": "task/state",
                            },
                        }
                    }
                },
            }
        )

        assert set(manifest.ledgers["taskledger"].mounts) == {
            "project-state",
            "checkout-state",
        }


class TestParseLedgerLocalConfig:
    def test_accepts_empty_document(self, tmp_path: Path) -> None:
        local = parse_ledger_local_config({}, project_root=tmp_path)
        assert local == LedgerLocalConfig(
            schema_version=1,
            workspace_root=None,
            cache_root=None,
            workspace_provider=None,
            cache_provider=None,
            checkout_id=None,
        )

    def test_parses_relative_and_absolute_roots(self, tmp_path: Path) -> None:
        absolute_cache = (tmp_path / "cache-root").resolve()
        local = parse_ledger_local_config(
            {
                "storage": {
                    "workspace": {"root": "../workspace-root"},
                    "cache": {"root": str(absolute_cache)},
                }
            },
            project_root=tmp_path / "project",
        )

        assert local.workspace_root == (tmp_path / "workspace-root").resolve()
        assert local.cache_root == absolute_cache

    def test_expands_home_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        local = parse_ledger_local_config(
            {"storage": {"workspace": {"root": "~/ledger-work"}}},
            project_root=tmp_path,
        )

        assert local.workspace_root == (tmp_path / "home" / "ledger-work").resolve()

    def test_validates_checkout_id_and_provider_selection(self, tmp_path: Path) -> None:
        local = parse_ledger_local_config(
            {
                "checkout": {"id": "ledgercore-main"},
                "storage": {"workspace": {"provider": "private-sibling"}},
            },
            project_root=tmp_path,
        )
        assert local.checkout_id == "ledgercore-main"
        assert local.workspace_provider == "private-sibling"

        with pytest.raises(LedgerLayoutError, match="checkout.id"):
            parse_ledger_local_config(
                {"checkout": {"id": "../bad"}}, project_root=tmp_path
            )

        with pytest.raises(LedgerLayoutError, match="both root and provider"):
            parse_ledger_local_config(
                {
                    "storage": {
                        "workspace": {
                            "root": "../workspace",
                            "provider": "private-sibling",
                        }
                    }
                },
                project_root=tmp_path,
            )

    def test_rejects_unknown_fields_and_unsupported_version(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(LedgerLayoutError, match="unsupported field"):
            parse_ledger_local_config({"project": {}}, project_root=tmp_path)

        with pytest.raises(LedgerLayoutError, match="schema_version must be 1"):
            parse_ledger_local_config({"schema_version": 2}, project_root=tmp_path)


class TestDeriveCheckoutId:
    def test_is_deterministic_and_readable(self, tmp_path: Path) -> None:
        checkout_id = derive_checkout_id(tmp_path / "Ledger Core")
        expected_prefix = slugify_ref((tmp_path / "Ledger Core").name)
        assert checkout_id.startswith(f"{expected_prefix}-")
        assert len(checkout_id.rsplit("-", 1)[1]) == 12
        assert checkout_id == derive_checkout_id(tmp_path / "Ledger Core")

    def test_distinguishes_paths(self, tmp_path: Path) -> None:
        assert derive_checkout_id(tmp_path / "one") != derive_checkout_id(
            tmp_path / "two"
        )

    def test_uses_normcase(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, str] = {}

        def fake_normcase(value: str) -> str:
            captured["value"] = value
            return value.upper()

        monkeypatch.setattr(os.path, "normcase", fake_normcase)
        project_root = tmp_path / "mixedCase"
        checkout_id = derive_checkout_id(project_root)
        expected_digest = hashlib.sha256(
            captured["value"].upper().encode("utf-8")
        ).hexdigest()[:12]
        assert checkout_id == f"{slugify_ref(project_root.name)}-{expected_digest}"


class TestResolveLedgerLayout:
    def test_resolves_repository_workspace_and_cache_mounts(
        self, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(_manifest_document())
        roots = PlatformRoots(
            user_data=(tmp_path / "platform-data").resolve(),
            user_cache=(tmp_path / "platform-cache").resolve(),
        )

        layout = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            platform_roots=roots,
        )

        assert layout.project_root == project_root.resolve()
        assert layout.config_root == (project_root / ".ledger").resolve()
        assert (
            layout.mounts["records"].path
            == (project_root / ".ledger" / "task" / "records").resolve()
        )
        assert layout.mounts["records"].source == "repository"
        assert (
            layout.mounts["data"].path
            == (
                roots.user_data
                / "projects"
                / manifest.project_uuid
                / "checkouts"
                / layout.checkout_id
                / "task"
                / "data"
            ).resolve()
        )
        assert (
            layout.mounts["cache"].path
            == (
                roots.user_cache
                / "projects"
                / manifest.project_uuid
                / "project"
                / "task"
                / "cache"
            ).resolve()
        )
        assert (
            layout.tool_config_path
            == (project_root / ".ledger" / "task" / "config.toml").resolve()
        )

    def test_checkout_scope_uses_precedence(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(_manifest_document())
        local = LedgerLocalConfig(
            schema_version=1,
            workspace_root=None,
            cache_root=None,
            workspace_provider=None,
            cache_provider=None,
            checkout_id="local-checkout",
        )

        from_argument = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            local_config=local,
            checkout_id="explicit-checkout",
            environ={"LEDGER_CHECKOUT_ID": "env-checkout"},
            platform_roots=PlatformRoots(tmp_path / "d1", tmp_path / "c1"),
        )
        assert from_argument.checkout_id == "explicit-checkout"

        from_env = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            local_config=local,
            environ={"LEDGER_CHECKOUT_ID": "env-checkout"},
            platform_roots=PlatformRoots(tmp_path / "d2", tmp_path / "c2"),
        )
        assert from_env.checkout_id == "env-checkout"

        from_local = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            local_config=local,
            environ={},
            platform_roots=PlatformRoots(tmp_path / "d3", tmp_path / "c3"),
        )
        assert from_local.checkout_id == "local-checkout"

    def test_resolves_storage_root_precedence(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(_manifest_document())
        local = LedgerLocalConfig(
            schema_version=1,
            workspace_root=(tmp_path / "local-workspace").resolve(),
            cache_root=(tmp_path / "local-cache").resolve(),
            workspace_provider=None,
            cache_provider=None,
            checkout_id=None,
        )

        explicit = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            local_config=local,
            workspace_root=Path("explicit/workspace"),
            cache_root=Path("explicit/cache"),
            environ={
                "LEDGER_WORKSPACE_ROOT": "env/workspace",
                "LEDGER_CACHE_ROOT": "env/cache",
            },
            platform_roots=PlatformRoots(tmp_path / "pd", tmp_path / "pc"),
        )
        assert "explicit" in explicit.mounts["data"].path.as_posix()
        assert explicit.mounts["data"].source == "explicit"
        assert explicit.mounts["cache"].source == "explicit"

        from_env = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            local_config=local,
            environ={
                "LEDGER_WORKSPACE_ROOT": "env/workspace",
                "LEDGER_CACHE_ROOT": "env/cache",
            },
            platform_roots=PlatformRoots(tmp_path / "pd2", tmp_path / "pc2"),
        )
        assert "env/workspace" in from_env.mounts["data"].path.as_posix()
        assert from_env.mounts["data"].source == "environment"

        from_local = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            local_config=local,
            environ={"LEDGER_WORKSPACE_ROOT": "", "LEDGER_CACHE_ROOT": ""},
            platform_roots=PlatformRoots(tmp_path / "pd3", tmp_path / "pc3"),
        )
        assert "local-workspace" in from_local.mounts["data"].path.as_posix()
        assert from_local.mounts["data"].source == "local-root"

        from_default = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            environ={"LEDGER_WORKSPACE_ROOT": "", "LEDGER_CACHE_ROOT": ""},
            platform_roots=PlatformRoots(
                tmp_path / "platform-data", tmp_path / "platform-cache"
            ),
        )
        assert from_default.mounts["data"].source == "manifest-default"
        assert "platform-data" in from_default.mounts["data"].path.as_posix()

    def test_repository_mounts_cannot_be_redirected(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(_manifest_document())

        layout = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            workspace_root=tmp_path / "workspace-root",
            cache_root=tmp_path / "cache-root",
            platform_roots=PlatformRoots(tmp_path / "pd", tmp_path / "pc"),
        )

        assert (
            layout.mounts["records"].path
            == (project_root / ".ledger" / "task" / "records").resolve()
        )

    def test_rejects_workspace_tool_config_in_resolver(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = LedgerProjectManifest(
            schema_version=2,
            project_uuid="565c0312-b531-4d07-aa1f-32c796f58dae",
            project_name="ledgercore",
            workspace_namespace="ledgerwerk",
            cache_namespace="ledgerwerk",
            workspace_default_provider="user-data",
            cache_default_provider="user-cache",
            providers=MappingProxyType({}),
            ledgers=MappingProxyType(
                {
                    "taskledger": LedgerRegistration(
                        name="taskledger",
                        config=ToolConfigDefinition(
                            location="workspace",
                            path="task/config.toml",
                            scope="project",
                        ),
                        mounts=MappingProxyType(
                            {
                                "data": LedgerMount(
                                    name="data",
                                    storage="workspace",
                                    path="task/data",
                                    scope="checkout",
                                )
                            }
                        ),
                    )
                }
            ),
        )

        with pytest.raises(
            LedgerLayoutError, match="workspace tool config is not supported"
        ):
            resolve_ledger_layout(
                locator,
                manifest,
                "taskledger",
                checkout_id="checkout-a",
                platform_roots=PlatformRoots(
                    tmp_path / "platform-data", tmp_path / "platform-cache"
                ),
            )

    def test_resolver_rejects_workspace_tool_config_from_parsed_manifest(
        self, tmp_path: Path
    ) -> None:
        # The parser already rejects workspace tool config today; this guards
        # the same gate from the supported mapping path.
        with pytest.raises(
            LedgerLayoutError,
            match="not supported until the private-provider phase",
        ):
            parse_ledger_project_manifest(
                {
                    "schema_version": 2,
                    "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                    "ledgers": {
                        "taskledger": {
                            "config": {
                                "location": "workspace",
                                "path": "task/config.toml",
                            },
                            "mounts": {
                                "data": {"storage": "workspace", "path": "task/data"},
                            },
                        }
                    },
                }
            )

    def test_rejects_legacy_or_inconsistent_locators(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        manifest = parse_ledger_project_manifest(_manifest_document())

        legacy_locator = LedgerProjectLocator(
            project_root=project_root,
            config_root=project_root,
            manifest_path=project_root / ".taskledger.toml",
            local_config_path=project_root / ".ledger" / "ledger.local.toml",
            source="legacy-tool",
        )
        with pytest.raises(LedgerLayoutError, match="legacy project locators"):
            resolve_ledger_layout(
                legacy_locator,
                manifest,
                "taskledger",
                platform_roots=PlatformRoots(tmp_path / "pd", tmp_path / "pc"),
            )

        bad_locator = LedgerProjectLocator(
            project_root=project_root,
            config_root=project_root / "other",
            manifest_path=project_root / ".ledger" / "ledger.toml",
            local_config_path=project_root / ".ledger" / "ledger.local.toml",
            source="canonical",
        )
        with pytest.raises(LedgerLayoutError, match="config_root"):
            resolve_ledger_layout(
                bad_locator,
                manifest,
                "taskledger",
                platform_roots=PlatformRoots(tmp_path / "pd2", tmp_path / "pc2"),
            )

    def test_rejects_unknown_ledger_and_private_provider_override(
        self, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(_manifest_document())

        with pytest.raises(LedgerLayoutError, match="unknown ledger registration"):
            resolve_ledger_layout(
                locator,
                manifest,
                "missing",
                platform_roots=PlatformRoots(tmp_path / "pd", tmp_path / "pc"),
            )

        local = LedgerLocalConfig(
            schema_version=1,
            workspace_root=None,
            cache_root=None,
            workspace_provider="private-sibling",
            cache_provider=None,
            checkout_id=None,
        )
        with pytest.raises(LedgerLayoutError, match="private-provider phase"):
            resolve_ledger_layout(
                locator,
                manifest,
                "taskledger",
                local_config=local,
                platform_roots=PlatformRoots(tmp_path / "pd2", tmp_path / "pc2"),
            )

    def test_performs_no_writes(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(_manifest_document())

        layout = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            platform_roots=PlatformRoots(
                tmp_path / "platform-data", tmp_path / "platform-cache"
            ),
        )

        assert not layout.mounts["data"].path.exists()
        assert not layout.mounts["cache"].path.exists()
        assert (
            not layout.tool_config_path.exists()
            if layout.tool_config_path is not None
            else True
        )

    # LAY-001 regression tests: family roots are resolved lazily so that
    # repository-only ledgers are unaffected by irrelevant external settings
    # and a workspace-only ledger does not require cache configuration.

    def test_repository_only_unaffected_by_workspace_provider(
        self, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(
            {
                "schema_version": 2,
                "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                "ledgers": {
                    "archledger": {
                        "mounts": {
                            "records": {
                                "storage": "repository",
                                "path": "arch/records",
                            }
                        }
                    }
                },
            }
        )
        local = LedgerLocalConfig(
            schema_version=1,
            workspace_root=None,
            cache_root=None,
            workspace_provider="private-sibling",
            cache_provider="private-sibling",
            checkout_id=None,
        )

        layout = resolve_ledger_layout(
            locator,
            manifest,
            "archledger",
            local_config=local,
            platform_roots=PlatformRoots(tmp_path / "pd", tmp_path / "pc"),
        )

        assert "checkouts" not in layout.mounts["records"].path.parts
        assert layout.mounts["records"].source == "repository"
        assert (
            layout.mounts["records"].path
            == (project_root / ".ledger" / "arch" / "records").resolve()
        )

    def test_workspace_only_does_not_require_cache_configuration(
        self, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(
            {
                "schema_version": 2,
                "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                "ledgers": {
                    "taskledger": {
                        "mounts": {
                            "data": {
                                "storage": "workspace",
                                "scope": "checkout",
                                "path": "task/data",
                            }
                        }
                    }
                },
            }
        )

        layout = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            checkout_id="checkout-a",
            platform_roots=PlatformRoots(tmp_path / "pd", tmp_path / "pc"),
        )

        assert "checkouts" in layout.mounts["data"].path.parts
        assert layout.mounts["data"].source == "manifest-default"

    def test_cache_only_does_not_require_workspace_configuration(
        self, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project"
        (project_root / ".ledger").mkdir(parents=True)
        locator = _canonical_locator(project_root)
        manifest = parse_ledger_project_manifest(
            {
                "schema_version": 2,
                "project": {"uuid": "565c0312-b531-4d07-aa1f-32c796f58dae"},
                "ledgers": {
                    "taskledger": {
                        "mounts": {
                            "indexes": {
                                "storage": "cache",
                                "scope": "project",
                                "path": "task/indexes",
                            }
                        }
                    }
                },
            }
        )

        layout = resolve_ledger_layout(
            locator,
            manifest,
            "taskledger",
            platform_roots=PlatformRoots(tmp_path / "pd", tmp_path / "pc"),
        )

        assert layout.mounts["indexes"].source == "manifest-default"
        assert "project" in layout.mounts["indexes"].path.parts
