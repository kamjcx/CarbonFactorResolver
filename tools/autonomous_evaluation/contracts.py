"""Independent contracts for autonomous public-synthetic evaluation.

These tables are deliberately not imported from the runtime.  They are a
small, reviewable specification against which runtime behaviour can be
measured without making the implementation its own oracle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = "cfr-autonomous-evaluation/v1"

BOUNDARIES = ("A1", "A2", "A3", "A1-A3")
BOUNDARY_COMPATIBILITY: Mapping[str, Mapping[str, bool]] = {
    request: {record: request == record for record in BOUNDARIES} for request in BOUNDARIES
}

SUBJECTS = ("raw_material", "finished_product", "energy", "transport", "process", "waste")
SUBJECT_COMPATIBILITY: Mapping[str, Mapping[str, bool]] = {
    request: {record: request == record for record in SUBJECTS} for request in SUBJECTS
}

UNIT_DIMENSIONS: Mapping[str, str] = {
    "kgCO2e/kg": "mass_ratio",
    "kgCO2e/t": "mass_ratio",
    "kgCO2e/kWh": "energy_ratio",
    "kgCO2e/MWh": "energy_ratio",
    "kgCO2e/tkm": "transport_work",
    "kgCO2e/(t*km)": "transport_work",
    "kgCO2e/m3": "conditional_volume",
    "kgCO2e/Nm3": "conditional_volume",
}

SOURCE_PRIORITY: Mapping[str, int] = {
    "reviewed_formal": 400,
    "official_current": 300,
    "structured_current": 200,
    "historical": 100,
}

SOURCE_QUALITY_ADMISSION: Mapping[str, bool] = {
    "VERIFIED": True,
    "NEEDS_REVIEW": False,
    "REJECTED": False,
}

HIGH_RISK_NEIGHBOURS = (
    ("bauxite ore", "calcined bauxite clinker"),
    ("bauxite ore", "high alumina finished product"),
    ("primary aluminium ingot", "secondary aluminium ingot"),
    ("primary aluminium ingot", "alumina"),
    ("graphite electrode", "graphite powder"),
    ("unsorted iron turnings", "baled steel scrap"),
    ("road freight", "rail freight"),
    ("grid electricity 2024", "photovoltaic electricity"),
    ("grid electricity 2024", "grid electricity 2021"),
    ("purchased hard coal", "hard coal combustion"),
    ("electrofused spinel", "sintered spinel"),
)


def canonical_json(value: Any) -> bytes:
    """Return the sole byte representation used for fingerprints and manifests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ExpectedDecision:
    status: str
    acceptable_source_ids: tuple[str, ...] = ()
    forbidden_source_ids: tuple[str, ...] = ()
    reference_only_source_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    approval_allowed: bool = False
    expected_top_1: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CatalogVariant:
    variant_id: str = "baseline"
    operations: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"variant_id": self.variant_id, "operations": [dict(item) for item in self.operations]}


@dataclass(frozen=True, slots=True)
class GeneratedCase:
    case_id: str
    category: str
    request: Mapping[str, Any]
    expectation: ExpectedDecision
    catalog_variant: CatalogVariant = field(default_factory=CatalogVariant)
    metamorphic_group: str | None = None
    assertion_axis: str = "decision_contract"

    def semantic_payload(self) -> dict[str, Any]:
        request = {key: value for key, value in self.request.items() if key != "request_id"}
        return {
            "category": self.category,
            "request": request,
            "expectation": self.expectation.to_dict(),
            "catalog_variant": self.catalog_variant.to_dict(),
            "metamorphic_group": self.metamorphic_group,
            "assertion_axis": self.assertion_axis,
        }

    @property
    def semantic_fingerprint(self) -> str:
        return sha256_json(self.semantic_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            **self.semantic_payload(),
            "semantic_fingerprint": self.semantic_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class EvaluationBundle:
    seed: int
    records: tuple[Mapping[str, Any], ...]
    cases: tuple[GeneratedCase, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        case_ids = [case.case_id for case in self.cases]
        fingerprints = [case.semantic_fingerprint for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("duplicate autonomous evaluation case_id")
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("duplicate autonomous evaluation semantic fingerprint")

    @property
    def case_count(self) -> int:
        return len(self.cases)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "records": [dict(record) for record in self.records],
            "cases": [case.to_dict() for case in self.cases],
        }

    @property
    def sha256(self) -> str:
        return sha256_json(self._unsigned_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "case_count": self.case_count, "sha256": self.sha256}
