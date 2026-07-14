"""Pin the exact curated `ledgercore` package-root layout facade.

This test prevents accidental drift between the public facade and the detailed
layout dataclasses that intentionally remain under `ledgercore.layout`. The
curated surface is the only contract smoke scripts, READMEs, and downstream
docs may rely on without a deeper import.
"""

from __future__ import annotations

import ledgercore

CURATED_LAYOUT_FACADE = frozenset(
    {
        "LedgerProjectLocator",
        "ResolvedLedgerLayout",
        "derive_checkout_id",
        "locate_ledger_project",
        "parse_ledger_local_config",
        "parse_ledger_project_manifest",
        "resolve_ledger_layout",
    }
)

DETAILED_LAYOUT_DATACLASSES = frozenset(
    {
        "LedgerLocalConfig",
        "LedgerMount",
        "LedgerProjectManifest",
        "LedgerRegistration",
        "PlatformRoots",
        "ResolvedMount",
        "StorageProviderDefinition",
        "ToolConfigDefinition",
    }
)


def test_root_layout_facade_exports_curated_symbols() -> None:
    package_all = set(getattr(ledgercore, "__all__", ()))
    assert package_all, "ledgercore.__all__ must be defined and non-empty"

    missing = CURATED_LAYOUT_FACADE - package_all
    assert not missing, (
        f"curated layout facade missing from ledgercore.__all__: {sorted(missing)}"
    )


def test_root_layout_facade_does_not_leak_detailed_dataclasses() -> None:
    package_all = set(getattr(ledgercore, "__all__", ()))
    leaked = DETAILED_LAYOUT_DATACLASSES & package_all
    assert not leaked, (
        f"detailed layout dataclasses must stay under ledgercore.layout, "
        f"but {sorted(leaked)} appear in ledgercore.__all__"
    )


def test_root_layout_facade_keeps_derive_checkout_id_for_backcompat() -> None:
    assert hasattr(ledgercore, "derive_checkout_id"), (
        "derive_checkout_id must remain importable from the package root "
        "for 0.2.x backward compatibility"
    )
    assert "derive_checkout_id" in ledgercore.__all__


def test_root_layout_facade_exposes_layout_helpers() -> None:
    for name in CURATED_LAYOUT_FACADE:
        assert hasattr(ledgercore, name), f"missing public layout symbol: {name}"


def test_detailed_layout_dataclasses_only_under_layout_module() -> None:
    from ledgercore import layout as layout_module

    for name in DETAILED_LAYOUT_DATACLASSES:
        assert hasattr(layout_module, name), f"layout module missing dataclass: {name}"
        assert not hasattr(ledgercore, name), (
            f"{name} must NOT be exposed at the package root; "
            "import it from ledgercore.layout"
        )
