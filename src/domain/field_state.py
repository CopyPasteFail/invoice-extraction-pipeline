from __future__ import annotations

from collections.abc import Iterable


INVALID_SENTINELS = {"", "---", "n/a", "na", "none", "null", "unknown", "tbd"}


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_invalid_scalar(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in INVALID_SENTINELS
    return False


def has_meaningful_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return not is_invalid_scalar(value)
    if isinstance(value, dict):
        return any(has_meaningful_value(item) for item in value.values())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, dict)):
        return any(has_meaningful_value(item) for item in value)
    return True
