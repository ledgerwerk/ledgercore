"""Cross-ledger resource reference parsing and formatting."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from ledgercore.errors import IdFormatError
from ledgercore.uuids import parse_uuid7

RefStyle = Literal["canonical", "file", "local"]

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9]*$")
_KIND_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_UUID_TEXT = (
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_UUID_CANONICAL_RE = re.compile(
    rf"^(?P<ledger>[A-Za-z][A-Za-z0-9]*):"
    rf"(?P<kind>[A-Za-z][A-Za-z0-9_-]*)-(?P<resource_uuid>{_UUID_TEXT})$"
)
_UUID_LOCAL_RE = re.compile(
    rf"^(?P<kind>[A-Za-z][A-Za-z0-9_-]*)-(?P<resource_uuid>{_UUID_TEXT})$"
)
_UUID_FILE_RE = re.compile(
    rf"^(?P<ledger>[A-Za-z][A-Za-z0-9]*)-"
    rf"(?P<kind>[A-Za-z][A-Za-z0-9_-]*)-(?P<resource_uuid>{_UUID_TEXT})$"
)
_CANONICAL_RE = re.compile(
    r"^(?P<ledger>[A-Za-z][A-Za-z0-9]*):"
    r"(?P<kind>[A-Za-z][A-Za-z0-9_-]*)-"
    r"(?P<number>\d+)$"
)
_LOCAL_RE = re.compile(r"^(?P<kind>[A-Za-z][A-Za-z0-9_-]*)-(?P<number>\d+)$")
_LEGACY_RE = re.compile(
    r"^(?P<ledger>[A-Za-z][A-Za-z0-9]*)_"
    r"(?P<kind>[A-Za-z][A-Za-z0-9_-]*)_"
    r"(?P<number>\d+)$"
)


@dataclass(frozen=True)
class LedgerResourceRef:
    """A ledger-neutral reference to a numeric resource record.

    Canonical global form:
        tl:task-0001

    File-safe global form:
        tl-task-0001

    Local form:
        task-0001
    """

    ledger: str | None
    kind: str
    number: int
    width: int = 4

    def __post_init__(self) -> None:
        if self.ledger is not None:
            object.__setattr__(
                self,
                "ledger",
                normalize_ref_token(self.ledger, label="ledger"),
            )
        object.__setattr__(self, "kind", normalize_kind(self.kind))
        _validate_number(self.number)
        if self.width <= 0:
            raise IdFormatError("Width must be positive")

    @property
    def local_id(self) -> str:
        """The local ID without ledger namespace, e.g. ``task-0001``."""
        return f"{self.kind}-{self.number:0{self.width}d}"

    @property
    def is_global(self) -> bool:
        """True when a ledger namespace is attached."""
        return self.ledger is not None

    @property
    def global_ref(self) -> str:
        """Canonical global ref, e.g. ``tl:task-0001``.

        Raises IdFormatError when ledger is None.
        """
        if self.ledger is None:
            raise IdFormatError("Cannot format a global ref without a ledger code")
        return f"{self.ledger}:{self.local_id}"

    @property
    def file_ref(self) -> str:
        """File-safe global ref using ``-`` instead of ``:``, e.g. ``tl-task-0001``.

        Raises IdFormatError when ledger is None.
        """
        if self.ledger is None:
            raise IdFormatError("Cannot format a file ref without a ledger code")
        return f"{self.ledger}-{self.local_id}"

    def format(self, style: RefStyle = "canonical") -> str:
        """Format the ref in the requested style.

        Styles: ``canonical`` (``tl:task-0001``), ``file`` (``tl-task-0001``),
        ``local`` (``task-0001``).
        """
        if style == "canonical":
            return self.global_ref
        if style == "file":
            return self.file_ref
        if style == "local":
            return self.local_id
        raise IdFormatError(f"Unsupported ref style: {style}")

    def with_ledger(self, ledger: str) -> LedgerResourceRef:
        """Return a copy of this ref with the given ledger namespace."""
        return LedgerResourceRef(
            ledger=ledger,
            kind=self.kind,
            number=self.number,
            width=self.width,
        )


def normalize_ref_token(value: str, *, label: str) -> str:
    """Lowercase and validate a short token such as a ledger code.

    The token must start with a letter and contain only lowercase
    alphanumeric characters. Raises IdFormatError on invalid input.
    """
    normalized = value.strip().lower()
    if not _TOKEN_RE.fullmatch(normalized):
        raise IdFormatError(f"Invalid {label}: {value!r}")
    return normalized


def normalize_kind(value: str) -> str:
    """Lowercase, replace underscores with hyphens, and validate a resource kind.

    The kind must start with a letter and may contain hyphens.
    Raises IdFormatError on invalid input.
    """
    normalized = value.strip().lower().replace("_", "-")
    if not _KIND_RE.fullmatch(normalized):
        raise IdFormatError(f"Invalid resource kind: {value!r}")
    return normalized


def parse_resource_ref(
    value: str,
    *,
    default_ledger: str | None = None,
    width: int = 4,
    allow_file_alias: bool = True,
    allow_legacy_alias: bool = True,
    allowed_ledgers: set[str] | None = None,
    allowed_kinds: set[str] | None = None,
) -> LedgerResourceRef:
    """Parse a canonical, file-safe, legacy, or local resource reference.

    Accepted input examples:
        tl:task-0001      canonical global ref
        tl-task-0001      file-safe alias
        TL-TASK-0001      uppercase file-safe alias
        al_adr_0046       legacy underscore alias
        task-0001         local ref, only globalized if default_ledger is provided

    Canonical output is always available through `.global_ref` when ledger is set.
    """
    if not isinstance(value, str):
        raise IdFormatError("Resource ref must be a string")
    raw = value.strip()
    if not raw:
        raise IdFormatError("Resource ref must not be empty")

    ref: LedgerResourceRef | None = None

    m = _CANONICAL_RE.fullmatch(raw)
    if m is not None:
        ref = _build_ref(
            m.group("ledger"),
            m.group("kind"),
            m.group("number"),
            width=width,
        )

    if ref is None and allow_legacy_alias:
        m = _LEGACY_RE.fullmatch(raw)
        if m is not None:
            ref = _build_ref(
                m.group("ledger"),
                m.group("kind"),
                m.group("number"),
                width=width,
            )

    if ref is None and allow_file_alias:
        ref = _parse_file_alias(raw, width=width)

    if ref is None:
        m = _LOCAL_RE.fullmatch(raw)
        if m is not None:
            ledger = default_ledger
            ref = _build_ref(ledger, m.group("kind"), m.group("number"), width=width)

    if ref is None:
        raise IdFormatError(f"Invalid resource ref: {value!r}")

    _check_allowed(ref, allowed_ledgers=allowed_ledgers, allowed_kinds=allowed_kinds)
    return ref


def parse_global_ref(value: str, **kwargs: object) -> LedgerResourceRef:
    """Parse and require a ledger namespace."""
    ref = parse_resource_ref(value, **kwargs)  # type: ignore[arg-type]
    if ref.ledger is None:
        raise IdFormatError(f"Resource ref is local, not global: {value!r}")
    return ref


def parse_local_ref(value: str, *, width: int = 4) -> LedgerResourceRef:
    """Parse a local kind-number ID without assigning a ledger."""
    ref = parse_resource_ref(
        value,
        width=width,
        allow_file_alias=False,
        allow_legacy_alias=False,
    )
    if ref.ledger is not None:
        raise IdFormatError(f"Resource ref is global, not local: {value!r}")
    return ref


def is_resource_ref(value: object, **kwargs: object) -> bool:
    """Return True if value is a valid resource ref."""
    if not isinstance(value, str):
        return False
    try:
        parse_resource_ref(value, **kwargs)  # type: ignore[arg-type]
    except IdFormatError:
        return False
    return True


@dataclass(frozen=True)
class LedgerUuidResourceRef:
    """A ledger-neutral reference to a UUIDv7 resource record."""

    ledger: str | None
    kind: str
    resource_uuid: uuid.UUID

    def __post_init__(self) -> None:
        if self.ledger is not None:
            object.__setattr__(
                self, "ledger", normalize_ref_token(self.ledger, label="ledger")
            )
        object.__setattr__(self, "kind", normalize_kind(self.kind))
        try:
            normalized_uuid = parse_uuid7(self.resource_uuid)
        except (TypeError, ValueError) as exc:
            raise IdFormatError(
                f"Invalid UUIDv7 resource ID: {self.resource_uuid!r}"
            ) from exc
        object.__setattr__(self, "resource_uuid", normalized_uuid)

    @property
    def local_id(self) -> str:
        """The local ID without a ledger namespace."""
        return f"{self.kind}-{self.resource_uuid}"

    @property
    def is_global(self) -> bool:
        """True when a ledger namespace is attached."""
        return self.ledger is not None

    @property
    def global_ref(self) -> str:
        """The canonical global reference."""
        if self.ledger is None:
            raise IdFormatError("Cannot format a global ref without a ledger code")
        return f"{self.ledger}:{self.local_id}"

    @property
    def file_ref(self) -> str:
        """The file-safe global reference."""
        if self.ledger is None:
            raise IdFormatError("Cannot format a file ref without a ledger code")
        return f"{self.ledger}-{self.local_id}"

    def format(self, style: RefStyle = "canonical") -> str:
        """Format the reference in canonical, file-safe, or local style."""
        if style == "canonical":
            return self.global_ref
        if style == "file":
            return self.file_ref
        if style == "local":
            return self.local_id
        raise IdFormatError(f"Unsupported ref style: {style}")


def parse_uuid_resource_ref(
    value: str,
    *,
    default_ledger: str | None = None,
    allow_file_alias: bool = True,
    allowed_ledgers: set[str] | None = None,
    allowed_kinds: set[str] | None = None,
) -> LedgerUuidResourceRef:
    """Parse a UUIDv7 local, canonical, or file-safe resource reference."""
    if not isinstance(value, str):
        raise IdFormatError("Resource ref must be a string")
    raw = value.strip()
    if not raw:
        raise IdFormatError("Resource ref must not be empty")

    match = _UUID_CANONICAL_RE.fullmatch(raw)
    ledger: str | None
    if match is not None:
        ledger = match.group("ledger")
    elif allow_file_alias and (file_match := _UUID_FILE_RE.fullmatch(raw)) is not None:
        match = file_match
        ledger = match.group("ledger")
    elif (local_match := _UUID_LOCAL_RE.fullmatch(raw)) is not None:
        match = local_match
        ledger = default_ledger
    else:
        match = None
        ledger = None

    if match is None:
        raise IdFormatError(f"Invalid UUID resource ref: {value!r}")
    ref = _build_uuid_ref(ledger, match.group("kind"), match.group("resource_uuid"))
    _check_uuid_allowed(
        ref, allowed_ledgers=allowed_ledgers, allowed_kinds=allowed_kinds
    )
    return ref


def parse_uuid_global_ref(value: str, **kwargs: object) -> LedgerUuidResourceRef:
    """Parse a UUIDv7 reference and require a ledger namespace."""
    ref = parse_uuid_resource_ref(value, **kwargs)  # type: ignore[arg-type]
    if ref.ledger is None:
        raise IdFormatError(f"Resource ref is local, not global: {value!r}")
    return ref


def parse_uuid_local_ref(value: str) -> LedgerUuidResourceRef:
    """Parse a local UUIDv7 kind-ID without assigning a ledger."""
    ref = parse_uuid_resource_ref(value, allow_file_alias=False)
    if ref.ledger is not None:
        raise IdFormatError(f"Resource ref is global, not local: {value!r}")
    return ref


def is_uuid_resource_ref(value: object, **kwargs: object) -> bool:
    """Return whether value is a valid UUIDv7 resource reference."""
    if not isinstance(value, str):
        return False
    try:
        parse_uuid_resource_ref(value, **kwargs)  # type: ignore[arg-type]
    except IdFormatError:
        return False
    return True


def _build_uuid_ref(
    ledger: str | None, kind: str, uuid_text: str
) -> LedgerUuidResourceRef:
    try:
        resource_uuid = parse_uuid7(uuid_text)
        return LedgerUuidResourceRef(
            ledger=ledger, kind=kind, resource_uuid=resource_uuid
        )
    except (TypeError, ValueError, IdFormatError) as exc:
        raise IdFormatError(f"Invalid UUID resource ref UUID: {uuid_text!r}") from exc


def _check_uuid_allowed(
    ref: LedgerUuidResourceRef,
    *,
    allowed_ledgers: set[str] | None,
    allowed_kinds: set[str] | None,
) -> None:
    if allowed_ledgers is not None:
        normalized_ledgers = {
            normalize_ref_token(item, label="ledger") for item in allowed_ledgers
        }
        if ref.ledger is not None and ref.ledger not in normalized_ledgers:
            raise IdFormatError(f"Ledger code is not allowed: {ref.ledger}")
    if allowed_kinds is not None:
        normalized_kinds = {normalize_kind(item) for item in allowed_kinds}
        if ref.kind not in normalized_kinds:
            raise IdFormatError(f"Resource kind is not allowed: {ref.kind}")


def _parse_file_alias(value: str, *, width: int) -> LedgerResourceRef | None:
    parts = value.split("-")
    if len(parts) < 3:
        return None
    ledger = parts[0]
    number_text = parts[-1]
    kind = "-".join(parts[1:-1])
    if not number_text.isdigit():
        return None
    try:
        return _build_ref(ledger, kind, number_text, width=width)
    except IdFormatError:
        return None


def _build_ref(
    ledger: str | None,
    kind: str,
    number_text: str,
    *,
    width: int,
) -> LedgerResourceRef:
    if not number_text.isdigit():
        raise IdFormatError(f"Invalid resource number: {number_text!r}")
    number = int(number_text)
    resolved_width = max(width, len(number_text))
    return LedgerResourceRef(
        ledger=ledger,
        kind=kind,
        number=number,
        width=resolved_width,
    )


def _validate_number(number: int) -> None:
    if isinstance(number, bool):
        raise IdFormatError("Number must not be a boolean")
    if number <= 0:
        raise IdFormatError(f"Number must be positive, got {number}")


def _check_allowed(
    ref: LedgerResourceRef,
    *,
    allowed_ledgers: set[str] | None,
    allowed_kinds: set[str] | None,
) -> None:
    if allowed_ledgers is not None:
        normalized_ledgers = {
            normalize_ref_token(item, label="ledger") for item in allowed_ledgers
        }
        if ref.ledger is not None and ref.ledger not in normalized_ledgers:
            raise IdFormatError(f"Ledger code is not allowed: {ref.ledger}")
    if allowed_kinds is not None:
        normalized_kinds = {normalize_kind(item) for item in allowed_kinds}
        if ref.kind not in normalized_kinds:
            raise IdFormatError(f"Resource kind is not allowed: {ref.kind}")
