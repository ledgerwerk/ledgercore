"""UUIDv7 generation and validation helpers."""

from __future__ import annotations

import threading
import uuid

import uuid6

_UUID7_LOCK = threading.Lock()


def uuid7() -> uuid.UUID:
    """Generate an RFC 9562 UUID version 7.

    Generation is serialized for concurrent callers in the current process.
    """
    with _UUID7_LOCK:
        return uuid6.uuid7()


def parse_uuid7(value: str | uuid.UUID) -> uuid.UUID:
    """Normalize and validate a UUIDv7 value."""
    parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if parsed.version != 7:
        raise ValueError(f"Expected UUIDv7, got UUID version {parsed.version}")
    return parsed


def uuid7_timestamp_ms(value: str | uuid.UUID) -> int:
    """Return the UUIDv7 Unix timestamp in milliseconds."""
    parsed = parse_uuid7(value)
    return parsed.int >> 80
