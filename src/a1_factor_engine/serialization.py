"""JSON-safe serializers for delivery surfaces.

The domain model deliberately uses enums, datetimes, immutable mappings and
tuples.  Keeping their conversion here prevents the HTTP and CLI layers from
depending on FastAPI/Pydantic serialization details.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


def to_jsonable(value: Any) -> Any:
    """Return a deterministic tree containing only JSON-compatible values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (Mapping, MappingProxyType)):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [to_jsonable(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, (tuple, list)):
        return [to_jsonable(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_jsonable(to_dict())
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def serialize_recommendation(recommendation: Any) -> dict[str, Any]:
    payload = to_jsonable(recommendation)
    if not isinstance(payload, dict):
        raise TypeError("recommendation serializer expected an object")
    digest = getattr(recommendation, "content_sha256", None)
    if isinstance(digest, str):
        payload["content_sha256"] = digest
    for field_name in (
        "candidates", "reviewable_candidates", "diagnostic_candidates"
    ):
        objects = getattr(recommendation, field_name, ())
        rows = payload.get(field_name, [])
        if isinstance(rows, list):
            for obj, row in zip(objects, rows, strict=True):
                if not isinstance(row, dict):
                    continue
                row["content_sha256"] = obj.content_sha256
                source = row.get("source")
                if isinstance(source, dict):
                    source["content_sha256"] = obj.source.content_sha256
    return payload


def serialize_trace(trace: Any) -> dict[str, Any]:
    """Serialize both the answer-oriented trace view and append-only entries."""

    to_dict = getattr(trace, "to_dict", None)
    payload = to_jsonable(to_dict() if callable(to_dict) else trace)
    if not isinstance(payload, dict):
        raise TypeError("trace serializer expected an object")
    return payload


def serialize_benchmark(value: Any) -> dict[str, Any]:
    payload = to_jsonable(value)
    if not isinstance(payload, dict):
        raise TypeError("benchmark serializer expected an object")
    return payload
