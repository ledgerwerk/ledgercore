"""Tests for ledgercore.ids."""

from __future__ import annotations

import uuid

import pytest

from ledgercore.ids import (
    LedgerIdFormat,
    NumericIdFormat,
    Uuid7IdFormat,
    next_prefixed_id,
    parse_prefixed_number,
    slugify_ref,
)


class TestLedgerIdFormat:
    def test_task_format(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert fmt.format(1) == "task-0001"

    def test_plan_format(self) -> None:
        fmt = LedgerIdFormat(prefix="plan")
        assert fmt.format(1) == "plan-0001"

    def test_al_underscore(self) -> None:
        fmt = LedgerIdFormat(prefix="al", separator="_")
        assert fmt.format(13) == "al_0013"

    def test_al_segmented(self) -> None:
        fmt = LedgerIdFormat(
            prefix="al",
            separator="_",
            segment_separator="_",
        )
        assert fmt.format(13, segment="content") == "al_content_0013"

    def test_parse(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert fmt.parse("task-0001") == 1

    def test_parse_underscore(self) -> None:
        fmt = LedgerIdFormat(prefix="al", separator="_")
        assert fmt.parse("al_0042") == 42

    def test_parse_parts_simple(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        parts = fmt.parse_parts("task-0003")
        assert parts.prefix == "task"
        assert parts.number == 3
        assert parts.segment is None

    def test_parse_parts_segmented(self) -> None:
        fmt = LedgerIdFormat(prefix="al", separator="_", segment_separator="_")
        parts = fmt.parse_parts("al_content_0013")
        assert parts.prefix == "al"
        assert parts.number == 13
        assert parts.segment == "content"

    def test_parse_wrong_prefix(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="does not match"):
            fmt.parse("run-0001")

    def test_parse_invalid_number(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="does not match"):
            fmt.parse("task-abc")

    def test_next_from_empty(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert fmt.next([]) == "task-0001"

    def test_next_from_existing(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert fmt.next(["task-0001", "task-0002"]) == "task-0003"

    def test_next_ignores_non_matching(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert fmt.next(["run-0001", "task-0001"]) == "task-0002"

    def test_next_segmented(self) -> None:
        fmt = LedgerIdFormat(prefix="al", separator="_", segment_separator="_")
        assert fmt.next([], segment="content") == "al_content_0001"
        assert fmt.next(["al_content_0001"], segment="content") == "al_content_0002"

    def test_next_separates_segments(self) -> None:
        fmt = LedgerIdFormat(prefix="al", separator="_", segment_separator="_")
        ids = ["al_content_0001", "al_0001"]
        # next without segment only considers non-segmented
        assert fmt.next(ids) == "al_0002"
        # next with segment only considers that segment
        assert fmt.next(ids, segment="content") == "al_content_0002"

    def test_is_valid(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert fmt.is_valid("task-0001")
        assert not fmt.is_valid("run-0001")
        assert not fmt.is_valid("")
        assert not fmt.is_valid(42)

    def test_is_valid_segmented(self) -> None:
        fmt = LedgerIdFormat(prefix="al", separator="_", segment_separator="_")
        assert fmt.is_valid("al_0013")
        assert fmt.is_valid("al_content_0013")
        assert not fmt.is_valid("task-0001")

    def test_filename(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert fmt.filename("task-0001", extension=".md") == "task-0001.md"

    def test_reject_zero(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="positive"):
            fmt.format(0)

    def test_reject_negative(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="positive"):
            fmt.format(-1)

    def test_reject_boolean(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="boolean"):
            fmt.format(True)  # type: ignore[arg-type]

    def test_parse_rejects_zero(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="positive"):
            fmt.parse("task-0000")

    def test_parse_parts_rejects_zero(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="positive"):
            fmt.parse_parts("task-0000")

    def test_is_valid_rejects_zero(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        assert not fmt.is_valid("task-0000")

    def test_custom_width(self) -> None:
        fmt = LedgerIdFormat(prefix="run", width=2)
        assert fmt.format(3) == "run-03"

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"prefix": ""}, "Prefix"),
            ({"prefix": "task", "separator": ""}, "Separator"),
            ({"prefix": "task", "width": 0}, "Width"),
            ({"prefix": "task", "segment_separator": ""}, "Segment separator"),
        ],
    )
    def test_rejects_invalid_configuration(
        self, kwargs: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            LedgerIdFormat(**kwargs)  # type: ignore[arg-type]

    def test_segment_required_needs_segment_support(self) -> None:
        with pytest.raises(ValueError, match="segment_separator"):
            LedgerIdFormat(prefix="task", segment_required=True)

    def test_rejects_empty_segment(self) -> None:
        fmt = LedgerIdFormat(prefix="al", segment_separator="_")
        with pytest.raises(ValueError, match="Segment"):
            fmt.format(1, segment="")

    def test_rejects_segment_when_not_enabled(self) -> None:
        fmt = LedgerIdFormat(prefix="task")
        with pytest.raises(ValueError, match="not enabled"):
            fmt.format(1, segment="content")

    def test_segment_required_applies_to_format_and_parse(self) -> None:
        fmt = LedgerIdFormat(
            prefix="al",
            separator="_",
            segment_separator="_",
            segment_required=True,
        )
        with pytest.raises(ValueError, match="required"):
            fmt.format(1)
        with pytest.raises(ValueError, match="requires a segment"):
            fmt.parse_parts("al_0001")
        assert fmt.parse_parts("al_content_0001").segment == "content"


class TestNumericIdFormat:
    def test_format_default(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        assert fmt.format(1) == "task-0001"

    def test_format_custom_separator(self) -> None:
        fmt = NumericIdFormat(prefix="al", separator="_")
        assert fmt.format(5) == "al_0005"

    def test_format_custom_width(self) -> None:
        fmt = NumericIdFormat(prefix="run", width=2)
        assert fmt.format(3) == "run-03"

    def test_parse(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        assert fmt.parse("task-0001") == 1

    def test_parse_custom(self) -> None:
        fmt = NumericIdFormat(prefix="al", separator="_")
        assert fmt.parse("al_0042") == 42

    def test_parse_wrong_prefix(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        with pytest.raises(ValueError, match="prefix"):
            fmt.parse("run-0001")

    def test_parse_non_numeric(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        with pytest.raises(ValueError, match="not a valid number"):
            fmt.parse("task-abc")

    def test_format_rejects_zero(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        with pytest.raises(ValueError, match="positive"):
            fmt.format(0)

    def test_format_rejects_negative(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        with pytest.raises(ValueError, match="positive"):
            fmt.format(-1)

    def test_format_rejects_boolean(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        with pytest.raises(ValueError, match="boolean"):
            fmt.format(True)  # type: ignore[arg-type]

    def test_parse_rejects_zero(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        with pytest.raises(ValueError, match="positive"):
            fmt.parse("task-0000")

    def test_next_from_empty(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        assert fmt.next([]) == "task-0001"

    def test_next_from_existing(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        assert fmt.next(["task-0001", "task-0002"]) == "task-0003"

    def test_next_ignores_non_matching(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        assert fmt.next(["run-0001", "task-0001"]) == "task-0002"

    def test_next_no_zero(self) -> None:
        fmt = NumericIdFormat(prefix="task")
        ids = ["task-0001", "task-0003"]
        assert fmt.next(ids) == "task-0004"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"prefix": ""},
            {"prefix": "task", "separator": ""},
            {"prefix": "task", "width": 0},
        ],
    )
    def test_rejects_invalid_configuration(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            NumericIdFormat(**kwargs)  # type: ignore[arg-type]


class TestParsePrefixedNumber:
    def test_default(self) -> None:
        assert parse_prefixed_number("task-0001", prefix="task") == 1

    def test_custom(self) -> None:
        assert parse_prefixed_number("al_0042", prefix="al", separator="_") == 42


class TestNextPrefixedId:
    def test_default(self) -> None:
        assert next_prefixed_id("task", []) == "task-0001"

    def test_with_existing(self) -> None:
        assert next_prefixed_id("task", ["task-0001"]) == "task-0002"


class TestSlugifyRef:
    def test_lowercases(self) -> None:
        assert slugify_ref("Hello World") == "hello-world"

    def test_collapses_non_alnum(self) -> None:
        assert slugify_ref("a   b!!!c") == "a-b-c"

    def test_trims(self) -> None:
        assert slugify_ref("  hello  ") == "hello"

    def test_empty_returns_default(self) -> None:
        assert slugify_ref("") == "item"

    def test_custom_empty(self) -> None:
        assert slugify_ref("!!!", empty="none") == "none"

    def test_only_dashes(self) -> None:
        assert slugify_ref("---") == "item"


class TestUuid7IdFormat:
    def test_new_format_and_parse(self) -> None:
        fmt = Uuid7IdFormat(prefix="task")
        value = fmt.new()
        assert value.startswith("task-")
        parsed = fmt.parse(value)
        assert parsed.version == 7
        assert fmt.format(str(parsed).upper()) == value

    def test_validity_and_filename(self) -> None:
        fmt = Uuid7IdFormat(prefix="task")
        value = fmt.new()
        assert fmt.is_valid(value)
        assert fmt.filename(value, extension=".md") == f"{value}.md"
        assert fmt.timestamp_ms(value) == fmt.parse(value).int >> 80

    def test_rejects_invalid_values(self) -> None:
        fmt = Uuid7IdFormat(prefix="task")
        assert not fmt.is_valid("task-0001")
        assert not fmt.is_valid("run-" + str(uuid.uuid4()))
        with pytest.raises(ValueError, match="Prefix"):
            Uuid7IdFormat(prefix="")
        with pytest.raises(ValueError, match="Separator"):
            Uuid7IdFormat(prefix="task", separator="")
        with pytest.raises(ValueError, match="filename-safe"):
            Uuid7IdFormat(prefix="task/name")

    def test_does_not_allocate_from_existing_ids(self) -> None:
        fmt = Uuid7IdFormat(prefix="task")
        first = fmt.new()
        second = fmt.new()
        assert first != second
