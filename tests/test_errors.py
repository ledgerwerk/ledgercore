"""Tests for ledgercore.errors."""

from __future__ import annotations

from ledgercore.errors import (
    AtomicWriteError,
    FrontMatterError,
    IdFormatError,
    JsonStoreError,
    LedgerConfigError,
    LedgerCoreError,
    LedgerLayoutError,
    PathValidationError,
    StorageError,
    YamlStoreError,
)


class TestLedgerCoreError:
    def test_default_code(self) -> None:
        err = LedgerCoreError("test")
        assert err.code == "LEDGERCORE_ERROR"
        assert str(err) == "test"

    def test_custom_code(self) -> None:
        err = LedgerCoreError("test", code="CUSTOM_ERROR")
        assert err.code == "CUSTOM_ERROR"

    def test_subclass_inherits_code(self) -> None:
        err = AtomicWriteError("write failed")
        assert isinstance(err, StorageError)
        assert isinstance(err, LedgerCoreError)

    def test_default_subclass_codes(self) -> None:
        cases = [
            (LedgerCoreError, "LEDGERCORE_ERROR"),
            (LedgerConfigError, "LEDGER_CONFIG_ERROR"),
            (LedgerLayoutError, "LEDGER_LAYOUT_ERROR"),
            (StorageError, "STORAGE_ERROR"),
            (AtomicWriteError, "ATOMIC_WRITE_ERROR"),
            (FrontMatterError, "FRONTMATTER_ERROR"),
            (JsonStoreError, "JSON_STORE_ERROR"),
            (YamlStoreError, "YAML_STORE_ERROR"),
            (PathValidationError, "PATH_VALIDATION_ERROR"),
            (IdFormatError, "ID_FORMAT_ERROR"),
        ]
        for cls, code in cases:
            assert cls("message").code == code

    def test_subclass_code_override(self) -> None:
        err = StorageError("boom", code="CUSTOM")
        assert err.code == "CUSTOM"

    def test_all_errors_are_ledgercore_errors(self) -> None:
        errors = [
            AtomicWriteError("a"),
            FrontMatterError("b"),
            JsonStoreError("c"),
            YamlStoreError("d"),
            PathValidationError("e"),
            IdFormatError("f"),
            StorageError("g"),
            LedgerConfigError("h"),
            LedgerLayoutError("i"),
        ]
        for err in errors:
            assert isinstance(err, LedgerCoreError)

    def test_layout_error_is_config_error(self) -> None:
        err = LedgerLayoutError("layout failed")
        assert isinstance(err, LedgerConfigError)
        assert err.code == "LEDGER_LAYOUT_ERROR"
