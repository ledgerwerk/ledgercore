"""Tests for ledgercore.refs."""

from __future__ import annotations

import uuid

import pytest

from ledgercore.errors import IdFormatError
from ledgercore.refs import (
    LedgerResourceRef,
    LedgerUuidResourceRef,
    is_resource_ref,
    is_uuid_resource_ref,
    normalize_kind,
    normalize_ref_token,
    parse_global_ref,
    parse_local_ref,
    parse_resource_ref,
    parse_uuid_global_ref,
    parse_uuid_local_ref,
    parse_uuid_resource_ref,
)


class TestParseCanonicalGlobalRef:
    def test_basic(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        assert ref.ledger == "tl"
        assert ref.kind == "task"
        assert ref.number == 1
        assert ref.width == 4
        assert ref.local_id == "task-0001"
        assert ref.global_ref == "tl:task-0001"
        assert ref.file_ref == "tl-task-0001"


class TestCanonicalizesCase:
    def test_uppercase_canonical(self) -> None:
        ref = parse_resource_ref("TL:TASK-0001")
        assert ref.global_ref == "tl:task-0001"


class TestParseFileSafeAlias:
    def test_basic(self) -> None:
        ref = parse_resource_ref("al-adr-0002")
        assert ref.global_ref == "al:adr-0002"
        assert ref.file_ref == "al-adr-0002"

    def test_uppercase_file_alias(self) -> None:
        ref = parse_resource_ref("AL-ADR-0002")
        assert ref.global_ref == "al:adr-0002"


class TestParseLegacyUnderscoreAlias:
    def test_basic(self) -> None:
        ref = parse_resource_ref("al_adr_0046")
        assert ref.global_ref == "al:adr-0046"

    def test_segmented_legacy(self) -> None:
        ref = parse_resource_ref("al_content_0013")
        assert ref.global_ref == "al:content-0013"


class TestParseLocalRef:
    def test_without_default_ledger(self) -> None:
        ref = parse_resource_ref("task-0001")
        assert ref.ledger is None
        assert ref.local_id == "task-0001"

    def test_with_default_ledger(self) -> None:
        ref = parse_resource_ref("task-0001", default_ledger="tl")
        assert ref.global_ref == "tl:task-0001"


class TestParseGlobalRefRejectsLocal:
    def test_rejects(self) -> None:
        with pytest.raises(IdFormatError):
            parse_global_ref("task-0001")


class TestGlobalRefRequiresLedger:
    def test_raises(self) -> None:
        ref = parse_local_ref("task-0001")
        with pytest.raises(IdFormatError):
            _ = ref.global_ref


class TestFileRefRequiresLedger:
    def test_raises(self) -> None:
        ref = parse_local_ref("task-0001")
        with pytest.raises(IdFormatError):
            _ = ref.file_ref


class TestHyphenatedKindCanonical:
    def test_basic(self) -> None:
        ref = parse_resource_ref("al:quality-requirement-0001")
        assert ref.kind == "quality-requirement"
        assert ref.global_ref == "al:quality-requirement-0001"


class TestHyphenatedKindFileAlias:
    def test_basic(self) -> None:
        ref = parse_resource_ref("al-quality-requirement-0001")
        assert ref.ledger == "al"
        assert ref.kind == "quality-requirement"
        assert ref.global_ref == "al:quality-requirement-0001"


class TestShortNumberPaddedToDefaultWidth:
    def test_basic(self) -> None:
        ref = parse_resource_ref("tl:task-1")
        assert ref.global_ref == "tl:task-0001"


class TestWideNumberPreservesWidth:
    def test_basic(self) -> None:
        ref = parse_resource_ref("tl:task-000001")
        assert ref.width == 6
        assert ref.global_ref == "tl:task-000001"


class TestAllowedLedgersAcceptsKnown:
    def test_basic(self) -> None:
        ref = parse_resource_ref("tl:task-0001", allowed_ledgers={"tl"})
        assert ref.global_ref == "tl:task-0001"


class TestAllowedLedgersRejectsUnknown:
    def test_basic(self) -> None:
        with pytest.raises(IdFormatError):
            parse_resource_ref("xx:task-0001", allowed_ledgers={"tl"})


class TestAllowedKindsAcceptsKnown:
    def test_basic(self) -> None:
        ref = parse_resource_ref("tl:task-0001", allowed_kinds={"task"})
        assert ref.global_ref == "tl:task-0001"


class TestAllowedKindsRejectsUnknown:
    def test_basic(self) -> None:
        with pytest.raises(IdFormatError):
            parse_resource_ref("tl:run-0001", allowed_kinds={"task"})


class TestRejectsInvalidRefs:
    @pytest.mark.parametrize(
        "value",
        [
            "",
            "tl:",
            ":task-0001",
            "tl:task-0000",
            "tl:task--0001",
            "tl:task-abc",
            "t-l:task-0001",
            "tl:Task Name-0001",
            "task",
            "0001",
        ],
    )
    def test_rejects(self, value: str) -> None:
        with pytest.raises(IdFormatError):
            parse_resource_ref(value)


class TestIsResourceRefRejectsNonString:
    def test_int(self) -> None:
        assert not is_resource_ref(123)

    def test_none(self) -> None:
        assert not is_resource_ref(None)

    def test_bool(self) -> None:
        assert not is_resource_ref(True)

    def test_valid_string(self) -> None:
        assert is_resource_ref("tl:task-0001")

    def test_invalid_string(self) -> None:
        assert not is_resource_ref("")


class TestNormalizeRefToken:
    def test_lowercases(self) -> None:
        assert normalize_ref_token("TL", label="ledger") == "tl"

    def test_strips(self) -> None:
        assert normalize_ref_token(" tl ", label="ledger") == "tl"

    def test_rejects_hyphen(self) -> None:
        with pytest.raises(IdFormatError):
            normalize_ref_token("t-l", label="ledger")


class TestNormalizeKind:
    def test_lowercases(self) -> None:
        assert normalize_kind("TASK") == "task"

    def test_underscores_to_hyphens(self) -> None:
        assert normalize_kind("quality_requirement") == "quality-requirement"

    def test_rejects_leading_digit(self) -> None:
        with pytest.raises(IdFormatError):
            normalize_kind("1task")


class TestLedgerResourceRefIsGlobal:
    def test_global(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        assert ref.is_global

    def test_local(self) -> None:
        ref = parse_local_ref("task-0001")
        assert not ref.is_global


class TestLedgerResourceRefFormat:
    def test_canonical(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        assert ref.format("canonical") == "tl:task-0001"

    def test_file(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        assert ref.format("file") == "tl-task-0001"

    def test_local(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        assert ref.format("local") == "task-0001"

    def test_unsupported_style(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        with pytest.raises(IdFormatError):
            ref.format("other")  # type: ignore[arg-type]


class TestWithLedger:
    def test_adds_ledger(self) -> None:
        ref = parse_local_ref("task-0001")
        global_ref = ref.with_ledger("tl")
        assert global_ref.global_ref == "tl:task-0001"

    def test_replaces_ledger(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        changed = ref.with_ledger("al")
        assert changed.global_ref == "al:task-0001"


class TestParseLocalRefRejectsGlobal:
    def test_rejects(self) -> None:
        with pytest.raises(IdFormatError):
            parse_local_ref("tl:task-0001")


class TestWidthNotPositive:
    def test_rejects_zero(self) -> None:
        with pytest.raises(IdFormatError):
            LedgerResourceRef(ledger="tl", kind="task", number=1, width=0)


class TestBooleanNumber:
    def test_rejects_true(self) -> None:
        with pytest.raises(IdFormatError):
            LedgerResourceRef(ledger="tl", kind="task", number=True)  # type: ignore[arg-type]

    def test_rejects_false(self) -> None:
        with pytest.raises(IdFormatError):
            LedgerResourceRef(ledger="tl", kind="task", number=False)  # type: ignore[arg-type]


class TestZeroNumber:
    def test_rejects(self) -> None:
        with pytest.raises(IdFormatError):
            LedgerResourceRef(ledger="tl", kind="task", number=0)


class TestNegativeNumber:
    def test_rejects(self) -> None:
        with pytest.raises(IdFormatError):
            LedgerResourceRef(ledger="tl", kind="task", number=-1)


class TestFrozenDataclass:
    def test_immutable(self) -> None:
        ref = parse_resource_ref("tl:task-0001")
        with pytest.raises(AttributeError):
            ref.number = 2  # type: ignore[misc]


UUID7_TEXT = "0199a1b2-3c4d-7e5f-8a90-123456789abc"


class TestUuid7ResourceRefs:
    def test_local_global_and_file_forms(self) -> None:
        local = parse_uuid_local_ref(f"task-{UUID7_TEXT}")
        assert local.ledger is None
        assert local.local_id == f"task-{UUID7_TEXT}"

        ref = parse_uuid_resource_ref(f"tl:task-{UUID7_TEXT}")
        assert ref.ledger == "tl"
        assert ref.kind == "task"
        assert ref.resource_uuid.version == 7
        assert ref.global_ref == f"tl:task-{UUID7_TEXT}"
        assert ref.file_ref == f"tl-task-{UUID7_TEXT}"
        assert parse_uuid_global_ref(ref.file_ref).global_ref == ref.global_ref

    def test_normalizes_case_and_default_ledger(self) -> None:
        ref = parse_uuid_resource_ref(f"task-{UUID7_TEXT.upper()}", default_ledger="TL")
        assert ref.global_ref == f"tl:task-{UUID7_TEXT}"
        direct = LedgerUuidResourceRef(
            ledger="TL", kind="TASK", resource_uuid=uuid.UUID(UUID7_TEXT)
        )
        assert direct.global_ref == ref.global_ref

    def test_allowed_values_and_rejections(self) -> None:
        assert is_uuid_resource_ref(f"tl:task-{UUID7_TEXT}", allowed_ledgers={"tl"})
        assert is_uuid_resource_ref(f"tl:task-{UUID7_TEXT}", allowed_kinds={"task"})
        assert not is_uuid_resource_ref(f"tl:task-{UUID7_TEXT}", allowed_ledgers={"al"})
        assert not is_uuid_resource_ref(f"tl:task-{UUID7_TEXT}", allowed_kinds={"adr"})
        assert not is_uuid_resource_ref("tl:task-0001")
        assert not is_uuid_resource_ref(f"tl:task-{uuid.uuid4()}")
        with pytest.raises(IdFormatError):
            parse_uuid_resource_ref(f"tl:task-{uuid.uuid4()}")

    def test_numeric_parser_remains_separate(self) -> None:
        numeric = parse_resource_ref("tl:task-0001")
        assert numeric.number == 1
        assert not is_uuid_resource_ref("tl:task-0001")
