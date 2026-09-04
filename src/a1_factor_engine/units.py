"""Deterministic Decimal unit parsing and conversion.

The conversion core implements ``cfr-unit-system/v1``. Existing float helpers
remain compatibility boundaries; registry ratios and plans are Decimal-based.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType

UNIT_SYNTAX_UNSUPPORTED = "UNIT_SYNTAX_UNSUPPORTED"
CATALOG_FACTOR_UNIT_INVALID = "CATALOG_FACTOR_UNIT_INVALID"
UNIT_DIMENSION_MISMATCH = "UNIT_DIMENSION_MISMATCH"
UNIT_CONVERSION_EVIDENCE_REQUIRED = "UNIT_CONVERSION_EVIDENCE_REQUIRED"


class UnitConversionError(ValueError):
    """Base error carrying the stable Unit System Contract reason code."""

    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class UnitSyntaxError(UnitConversionError):
    def __init__(self, message: str, reason_code: str = UNIT_SYNTAX_UNSUPPORTED) -> None:
        super().__init__(message, reason_code)


class CatalogFactorUnitError(UnitSyntaxError):
    def __init__(self, message: str) -> None:
        super().__init__(message, CATALOG_FACTOR_UNIT_INVALID)


class UnitDimensionMismatchError(UnitConversionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, UNIT_DIMENSION_MISMATCH)


class UnitConversionEvidenceRequiredError(UnitConversionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, UNIT_CONVERSION_EVIDENCE_REQUIRED)


class ActivityDimension(str, Enum):
    MASS = "MASS"
    ENERGY = "ENERGY"
    VOLUME = "VOLUME"
    TRANSPORT_WORK = "TRANSPORT_WORK"
    COUNT = "COUNT"
    AREA = "AREA"


@dataclass(frozen=True, slots=True)
class ActivityUnitSpec:
    canonical_unit: str
    dimension: ActivityDimension
    ratio_to_base: Decimal
    requires_external_evidence: bool = False


@dataclass(frozen=True, slots=True)
class ImpactUnitSpec:
    canonical_unit: str
    ratio_to_kgco2e: Decimal
    legacy_numerator: str


@dataclass(frozen=True, slots=True)
class ParsedFactorUnit:
    raw_unit: str
    impact_unit: ImpactUnitSpec
    activity_unit: ActivityUnitSpec
    reference_product_qualifier: str | None = None

    @property
    def numerator(self) -> str:
        return self.impact_unit.legacy_numerator

    @property
    def denominator_mass(self) -> str:
        """Compatibility name; v1 may return any controlled activity unit."""

        return self.activity_unit.canonical_unit


@dataclass(frozen=True, slots=True)
class UnitConversionEvidence:
    evidence_id: str
    version: str
    source_canonical_unit: str
    target_canonical_unit: str
    multiplier: Decimal

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.version.strip():
            raise ValueError("unit conversion evidence requires an id and version")
        if not self.multiplier.is_finite() or self.multiplier <= 0:
            raise ValueError("unit conversion evidence multiplier must be finite and positive")


@dataclass(frozen=True, slots=True)
class UnitConversionResult:
    source_raw_unit: str
    target_raw_unit: str
    source_canonical_unit: str
    target_canonical_unit: str
    conversion_direction: str
    multiplier: Decimal | None
    formula_id: str
    evidence_required: bool = False
    reason_code: str | None = None
    evidence_id: str | None = None
    evidence_version: str | None = None

    @property
    def convertible(self) -> bool:
        return self.multiplier is not None and self.reason_code is None

    def convert(self, value: Decimal | str | int | float) -> Decimal:
        if self.reason_code == UNIT_DIMENSION_MISMATCH:
            raise UnitDimensionMismatchError(
                f"cannot convert {self.source_raw_unit!r} to {self.target_raw_unit!r}"
            )
        if self.evidence_required:
            raise UnitConversionEvidenceRequiredError(
                f"conversion {self.source_raw_unit!r} to {self.target_raw_unit!r} requires evidence"
            )
        if self.multiplier is None:
            raise UnitConversionError(
                "conversion plan has no multiplier", self.reason_code or UNIT_SYNTAX_UNSUPPORTED
            )
        return _decimal(value) * self.multiplier


def _spec(
    canonical: str,
    dimension: ActivityDimension,
    ratio: Decimal,
    *,
    evidence: bool = False,
) -> ActivityUnitSpec:
    return ActivityUnitSpec(canonical, dimension, ratio, evidence)


_ONE = Decimal("1")
_ACTIVITY_ALIASES: Mapping[str, ActivityUnitSpec] = MappingProxyType({
    "g": _spec("g", ActivityDimension.MASS, Decimal("0.001")),
    "kg": _spec("kg", ActivityDimension.MASS, _ONE),
    "t": _spec("t", ActivityDimension.MASS, Decimal("1000")),
    "tonne": _spec("tonne", ActivityDimension.MASS, Decimal("1000")),
    "lb": _spec("lb", ActivityDimension.MASS, Decimal("0.45359237")),
    "kwh": _spec("kWh", ActivityDimension.ENERGY, _ONE),
    "mwh": _spec("MWh", ActivityDimension.ENERGY, Decimal("1000")),
    "mj": _spec("MJ", ActivityDimension.ENERGY, _ONE / Decimal("3.6")),
    "gj": _spec("GJ", ActivityDimension.ENERGY, Decimal("1000") / Decimal("3.6")),
    "m3": _spec("m3", ActivityDimension.VOLUME, _ONE),
    "m³": _spec("m3", ActivityDimension.VOLUME, _ONE),
    "l": _spec("L", ActivityDimension.VOLUME, Decimal("0.001")),
    "nm3": _spec("Nm3", ActivityDimension.VOLUME, _ONE, evidence=True),
    "nm³": _spec("Nm3", ActivityDimension.VOLUME, _ONE, evidence=True),
    "m2": _spec("m2", ActivityDimension.AREA, _ONE),
    "m²": _spec("m2", ActivityDimension.AREA, _ONE),
    "tkm": _spec("tkm", ActivityDimension.TRANSPORT_WORK, _ONE),
    "kgkm": _spec("kgkm", ActivityDimension.TRANSPORT_WORK, Decimal("0.001")),
    "item": _spec("item", ActivityDimension.COUNT, _ONE),
    "count": _spec("item", ActivityDimension.COUNT, _ONE),
    "piece": _spec("item", ActivityDimension.COUNT, _ONE),
    "pcs": _spec("item", ActivityDimension.COUNT, _ONE),
    "bag": _spec("item", ActivityDimension.COUNT, _ONE),
    "roll": _spec("item", ActivityDimension.COUNT, _ONE),
})

_IMPACT_ALIASES: Mapping[str, ImpactUnitSpec] = MappingProxyType({
    "kgco2e": ImpactUnitSpec("kgCO2e", _ONE, "kg"),
    "kgco2eq": ImpactUnitSpec("kgCO2e", _ONE, "kg"),
    "gco2e": ImpactUnitSpec("kgCO2e", Decimal("0.001"), "g"),
    "tco2e": ImpactUnitSpec("kgCO2e", Decimal("1000"), "t"),
})

# Compatibility export. Values are authoritative Decimals in v1.
MASS_TO_KG: Mapping[str, Decimal] = MappingProxyType({
    key: spec.ratio_to_base
    for key, spec in _ACTIVITY_ALIASES.items()
    if spec.dimension == ActivityDimension.MASS
})

_QUALIFIERS = ("product", "produit", "产品")


def _decimal(value: Decimal | str | int | float) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, float):
        result = Decimal(str(value))
    else:
        result = Decimal(value)
    if not result.is_finite():
        raise ValueError("unit conversion value must be finite")
    return result


def _activity_key(value: str) -> str:
    key = "".join(value.strip().casefold().split())
    while len(key) >= 2 and key[0] == "(" and key[-1] == ")":
        key = key[1:-1]
    return key.replace("*", "").replace("·", "").replace(".", "")


def _impact_key(value: str) -> str:
    return "".join(value.strip().casefold().replace("₂", "2").replace("-", "").split())


def parse_activity_unit(value: str) -> ActivityUnitSpec:
    if not isinstance(value, str) or not value.strip():
        raise UnitSyntaxError("activity unit is required")
    key = _activity_key(value)
    try:
        return _ACTIVITY_ALIASES[key]
    except KeyError as exc:
        raise UnitSyntaxError(f"unsupported activity unit: {value!r}") from exc


def is_mass_unit(value: str) -> bool:
    try:
        return parse_activity_unit(value).dimension == ActivityDimension.MASS
    except UnitSyntaxError:
        return False


def _split_factor_unit(value: str) -> tuple[str, str]:
    slash = re.fullmatch(r"\s*(.+?)\s*/\s*(.+?)\s*", value)
    if slash:
        return slash.group(1), slash.group(2)
    per = re.fullmatch(r"\s*(.+?)\s+per\s+(.+?)\s*", value, flags=re.IGNORECASE)
    if per:
        return per.group(1), per.group(2)
    compact = re.fullmatch(
        r"\s*(.+?co(?:2|₂)(?:e|eq|-eq))per(.+?)\s*", value, flags=re.IGNORECASE
    )
    if compact:
        return compact.group(1), compact.group(2)
    raise UnitSyntaxError(f"unsupported factor unit: {value!r}")


def parse_factor_unit(value: str) -> ParsedFactorUnit:
    if not isinstance(value, str) or not value.strip():
        raise UnitSyntaxError("factor unit is required")
    impact_text, activity_text = _split_factor_unit(value)
    try:
        impact = _IMPACT_ALIASES[_impact_key(impact_text)]
    except KeyError as exc:
        raise UnitSyntaxError(f"unsupported impact unit: {impact_text!r}") from exc

    qualifier = None
    compact_activity = "".join(activity_text.strip().split())
    folded_activity = compact_activity.casefold()
    for candidate in _QUALIFIERS:
        if folded_activity.endswith(candidate.casefold()):
            qualifier = candidate
            compact_activity = compact_activity[: -len(candidate)]
            break
    activity = parse_activity_unit(compact_activity)
    return ParsedFactorUnit(value, impact, activity, qualifier)


def parse_catalog_factor_unit(value: str) -> ParsedFactorUnit:
    try:
        return parse_factor_unit(value)
    except UnitSyntaxError as exc:
        raise CatalogFactorUnitError(str(exc)) from exc


def _is_conditioned_volume_pair(source: ActivityUnitSpec, target: ActivityUnitSpec) -> bool:
    return (
        source.dimension == ActivityDimension.VOLUME
        and target.dimension == ActivityDimension.VOLUME
        and source.requires_external_evidence != target.requires_external_evidence
    )


def _matching_evidence(
    evidence: UnitConversionEvidence | None,
    source: ActivityUnitSpec,
    target: ActivityUnitSpec,
) -> UnitConversionEvidence | None:
    if evidence is None:
        return None
    if (
        evidence.source_canonical_unit != source.canonical_unit
        or evidence.target_canonical_unit != target.canonical_unit
    ):
        raise ValueError("unit conversion evidence direction does not match the conversion plan")
    return evidence


def plan_activity_conversion(
    source_unit: str,
    target_unit: str,
    *,
    evidence: UnitConversionEvidence | None = None,
) -> UnitConversionResult:
    source = parse_activity_unit(source_unit)
    target = parse_activity_unit(target_unit)
    direction = f"{source.canonical_unit}->{target.canonical_unit}"
    if source.dimension != target.dimension:
        return UnitConversionResult(
            source_unit, target_unit, source.canonical_unit, target.canonical_unit,
            direction, None, "unit.activity_scale/v1", reason_code=UNIT_DIMENSION_MISMATCH,
        )
    if source.canonical_unit == target.canonical_unit:
        multiplier = _ONE
        matched = None
    elif _is_conditioned_volume_pair(source, target):
        matched = _matching_evidence(evidence, source, target)
        if matched is None:
            return UnitConversionResult(
                source_unit, target_unit, source.canonical_unit, target.canonical_unit,
                direction, None, "unit.activity_scale/v1", evidence_required=True,
                reason_code=UNIT_CONVERSION_EVIDENCE_REQUIRED,
            )
        multiplier = matched.multiplier
    else:
        multiplier = source.ratio_to_base / target.ratio_to_base
        matched = None
    return UnitConversionResult(
        source_unit, target_unit, source.canonical_unit, target.canonical_unit,
        direction, multiplier, "unit.activity_scale/v1",
        evidence_id=matched.evidence_id if matched else None,
        evidence_version=matched.version if matched else None,
    )


def plan_factor_conversion(
    source_unit: str,
    target_unit: str,
    *,
    evidence: UnitConversionEvidence | None = None,
) -> UnitConversionResult:
    source = parse_factor_unit(source_unit)
    target = parse_factor_unit(target_unit)
    source_canonical = f"{source.impact_unit.canonical_unit}/{source.activity_unit.canonical_unit}"
    target_canonical = f"{target.impact_unit.canonical_unit}/{target.activity_unit.canonical_unit}"
    direction = f"{source_canonical}->{target_canonical}"
    if source.activity_unit.dimension != target.activity_unit.dimension:
        return UnitConversionResult(
            source_unit, target_unit, source_canonical, target_canonical, direction,
            None, "unit.factor_scale/v1", reason_code=UNIT_DIMENSION_MISMATCH,
        )
    activity_plan = plan_activity_conversion(
        source.activity_unit.canonical_unit,
        target.activity_unit.canonical_unit,
        evidence=evidence,
    )
    if activity_plan.evidence_required:
        return UnitConversionResult(
            source_unit, target_unit, source_canonical, target_canonical, direction,
            None, "unit.factor_scale/v1", evidence_required=True,
            reason_code=UNIT_CONVERSION_EVIDENCE_REQUIRED,
        )
    if activity_plan.multiplier is None:
        raise ValueError("activity conversion plan lacks a multiplier")
    multiplier = (
        source.impact_unit.ratio_to_kgco2e
        / target.impact_unit.ratio_to_kgco2e
        / activity_plan.multiplier
    )
    return UnitConversionResult(
        source_unit, target_unit, source_canonical, target_canonical, direction,
        multiplier, "unit.factor_scale/v1", evidence_id=activity_plan.evidence_id,
        evidence_version=activity_plan.evidence_version,
    )


def convert_activity_decimal(
    value: Decimal | str | int | float,
    from_unit: str,
    to_unit: str,
    *,
    evidence: UnitConversionEvidence | None = None,
) -> Decimal:
    return plan_activity_conversion(from_unit, to_unit, evidence=evidence).convert(value)


def convert_factor_decimal(
    value: Decimal | str | int | float,
    from_unit: str,
    to_unit: str = "kgCO2e/kg",
    *,
    evidence: UnitConversionEvidence | None = None,
) -> Decimal:
    return plan_factor_conversion(from_unit, to_unit, evidence=evidence).convert(value)


def convert_mass(value: float, from_unit: str, to_unit: str = "kg") -> float:
    source = parse_activity_unit(from_unit)
    target = parse_activity_unit(to_unit)
    if source.dimension != ActivityDimension.MASS or target.dimension != ActivityDimension.MASS:
        raise UnitDimensionMismatchError(f"unsupported mass unit: {from_unit!r} -> {to_unit!r}")
    if isinstance(value, float):
        # Preserve the legacy float boundary exactly while the authoritative
        # registry and Decimal APIs remain Decimal-based.
        return value * float(source.ratio_to_base) / float(target.ratio_to_base)
    return float(convert_activity_decimal(value, from_unit, to_unit))


def convert_factor(value: float, from_unit: str, to_unit: str = "kgCO2e/kg") -> float:
    return float(convert_factor_decimal(value, from_unit, to_unit))
