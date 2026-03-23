from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, TypeAlias, cast

from src.io.files import ensure_directory

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = object
JsonObject: TypeAlias = dict[str, object]
JsonArray: TypeAlias = list[object]


def to_jsonable(value: object) -> JsonValue:
    if is_dataclass(value):
        return cast(JsonObject, {key: to_jsonable(item) for key, item in asdict(cast(Any, value)).items()})
    if isinstance(value, dict):
        return cast(JsonObject, {str(key): to_jsonable(item) for key, item in value.items()})
    if isinstance(value, list):
        return cast(JsonArray, [to_jsonable(item) for item in value])
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def as_json_object(value: object) -> JsonObject:
    jsonable = to_jsonable(value)
    return cast(JsonObject, jsonable) if isinstance(jsonable, dict) else {}


def merge_dicts(base: JsonObject, patch: JsonObject) -> JsonObject:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(cast(JsonObject, merged[key]), value)
        else:
            merged[key] = value
    return merged


def write_json(path: Path, payload: object) -> Path:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(to_jsonable(payload), handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    return path
