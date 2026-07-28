"""Generic error hierarchy for ledgercore."""


class LedgerCoreError(Exception):
    """Base exception for all ledgercore errors."""

    code: str = "LEDGERCORE_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class LedgerConfigError(LedgerCoreError):
    """Raised when a shared ledger config table is missing or invalid."""

    code: str = "LEDGER_CONFIG_ERROR"


class LedgerLayoutError(LedgerConfigError):
    """Raised when a Ledger-family project layout is invalid or unresolvable."""

    code: str = "LEDGER_LAYOUT_ERROR"


class TomlConfigError(LedgerConfigError):
    """Raised when Ledgercore TOML configuration cannot be read or written."""

    code: str = "TOML_CONFIG_ERROR"


class StorageBindingError(LedgerLayoutError):
    """Raised when a storage ownership marker is invalid."""

    code: str = "STORAGE_BINDING_ERROR"


class StorageError(LedgerCoreError):
    """Base exception for storage-related errors."""

    code: str = "STORAGE_ERROR"


class StorageMigrationError(StorageError):
    """Raised when an explicit storage migration cannot complete safely."""

    code: str = "STORAGE_MIGRATION_ERROR"


class StorageMigrationPlanError(StorageMigrationError):
    code = "STORAGE_MIGRATION_PLAN_INVALID"


class StorageMigrationJournalError(StorageMigrationError):
    code = "STORAGE_MIGRATION_JOURNAL_INVALID"


class StorageMigrationRecoveryError(StorageMigrationError):
    code = "STORAGE_MIGRATION_RECOVERY_FAILED"


class AtomicWriteError(StorageError):
    """Raised when an atomic write operation fails."""

    code: str = "ATOMIC_WRITE_ERROR"


class FrontMatterError(StorageError):
    """Raised when front matter parsing or writing fails."""

    code: str = "FRONTMATTER_ERROR"


class JsonStoreError(StorageError):
    """Raised when a JSON store operation fails."""

    code: str = "JSON_STORE_ERROR"


class YamlStoreError(StorageError):
    """Raised when a YAML store operation fails."""

    code: str = "YAML_STORE_ERROR"


class PathValidationError(StorageError):
    """Raised when a path fails validation."""

    code: str = "PATH_VALIDATION_ERROR"


class IdFormatError(LedgerCoreError):
    """Raised when an ID does not match the expected format."""

    code: str = "ID_FORMAT_ERROR"
