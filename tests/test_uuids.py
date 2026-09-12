"""Tests for UUIDv7 helpers."""

from __future__ import annotations

import concurrent.futures
import time
import uuid

import pytest

from ledgercore.uuids import parse_uuid7, uuid7, uuid7_timestamp_ms


def test_uuid7_generation() -> None:
    value = uuid7()
    assert isinstance(value, uuid.UUID)
    assert value.version == 7


def test_parse_uuid7_normalizes_text() -> None:
    value = uuid7()
    assert parse_uuid7(str(value).upper()) == value
    assert parse_uuid7(value) is value


def test_parse_uuid7_rejects_non_v7() -> None:
    with pytest.raises(ValueError, match="Expected UUIDv7"):
        parse_uuid7(str(uuid.uuid4()))


def test_uuid7_timestamp() -> None:
    value = uuid7()
    timestamp_ms = uuid7_timestamp_ms(value)
    now_ms = int(time.time() * 1000)
    assert timestamp_ms == value.int >> 80
    assert abs(timestamp_ms - now_ms) < 10_000


def test_uuid7_threaded_uniqueness() -> None:
    def generate_many() -> list[uuid.UUID]:
        return [uuid7() for _ in range(100)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        values = [
            value
            for batch in executor.map(lambda _: generate_many(), range(8))
            for value in batch
        ]

    assert all(value.version == 7 for value in values)
    assert len(set(values)) == len(values)
