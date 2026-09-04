"""Canonical integrity contracts for catalogues and persisted decisions.

The functions in this module deliberately avoid domain-specific ranking logic.
They provide one byte-level representation for content that must remain stable
across adapters, stores and Python processes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence

CATALOG_SCHEMA_VERSION = "cfr.catalog/v2"
DECISION_SCHEMA_VERSION = "cfr.decision/v1"
LOCK_SCHEMA_VERSION = "cfr.lock/v1"
TRACE_SCHEMA_VERSION = "cfr.trace/v1"


class CatalogIntegrityError(ValueError):
    """The bytes observed from a catalogue do not match its content contract."""


class PersistenceIntegrityError(ValueError):
    """A persisted approval, lock or audit object failed a binding check."""


# Full input schema consumed by HttpCatalogFactorRepository. Unknown fields are
# rejected under cfr.catalog/v2 so a result-driving field cannot silently sit
# outside the digest contract. Legacy payloads remain readable only through the
# explicit migration path in the adapter and never gain verified-publisher status.
CATALOG_RECORD_FIELDS = frozenset({
    "record_id", "source_id", "code", "name", "aliases", "primary_value",
    "primary_unit", "geography", "year", "product_form", "composition",
    "production_process", "boundary", "boundary_modules", "category",
    "factor_kind", "subject_type", "source_quality_status", "admission_eligible",
    "indicator", "declared_product", "citation", "excerpt", "provider", "source",
    "source_name", "source_type", "source_tier", "source_version", "source_status",
    "upstream_source_status",
    "source_priority", "source_priority_rank", "document_status", "standard",
    "primary_label", "scope", "includes_process", "license", "parser_version",
    "extraction_confidence", "cross_format_verified", "evidence_cell_bbox",
    "location", "notes", "process", "source_citation",
    "source_document_locator", "source_document_sha256", "source_sha256",
    "document_url", "source_url", "source_path", "page", "table", "row",
})


def _number(value: int | float | Decimal) -> Mapping[str, str]:
    if isinstance(value, bool):  # bool is an int subclass
        raise TypeError("booleans are not numeric values in canonical JSON")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("canonical values cannot contain NaN or infinity")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid canonical numeric value") from exc
    normalized = decimal.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    return {"$number": text}


def canonical_value(value: Any) -> Any:
    """Return a JSON-safe, type-preserving and recursively stable value."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float, Decimal)):
        return _number(value)
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, MappingProxyType):
        value = dict(value)
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [canonical_value(item) for item in value]
        return sorted(normalized, key=canonical_json_bytes)
    if is_dataclass(value):
        return {
            item.name: canonical_value(getattr(value, item.name))
            for item in fields(value)
        }
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        canonical_value(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_catalog_records(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Validate and canonicalize the complete v2 catalogue record schema."""

    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for position, raw in enumerate(records):
        unknown = set(raw) - CATALOG_RECORD_FIELDS
        if unknown:
            raise CatalogIntegrityError(
                f"catalog record {position} contains fields outside cfr.catalog/v2: "
                + ", ".join(sorted(unknown))
            )
        record = {field: raw.get(field) for field in sorted(CATALOG_RECORD_FIELDS)}
        for unordered in ("aliases", "boundary_modules"):
            values = record.get(unordered)
            if isinstance(values, (list, tuple)):
                record[unordered] = sorted(values, key=lambda item: canonical_json_bytes(item))
        identity = str(raw.get("record_id") or raw.get("source_id") or raw.get("code") or "").strip()
        if not identity:
            raise CatalogIntegrityError(f"catalog record {position} has no stable identity")
        if identity in identities:
            raise CatalogIntegrityError(f"duplicate catalog record identity: {identity}")
        identities.add(identity)
        record["$record_identity"] = identity
        normalized.append(record)
    normalized.sort(key=lambda item: (str(item["$record_identity"]), canonical_json_bytes(item)))
    return tuple(normalized)


def catalog_content_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    return stable_sha256({
        "schema_version": CATALOG_SCHEMA_VERSION,
        "records": canonical_catalog_records(records),
    })


def legacy_catalog_content_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    """Migration-only digest for pre-v2 manifests; never implies publisher identity."""

    raw = json.dumps(
        list(records), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_digest(value: str | None, *, field_name: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise CatalogIntegrityError(f"{field_name} must be a lowercase SHA-256")
    return digest
