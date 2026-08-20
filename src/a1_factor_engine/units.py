"""Deterministic mass and emission-factor unit conversion."""

from __future__ import annotations

import re
from dataclasses import dataclass

MASS_TO_KG = {
    "g": 1e-3,
    "kg": 1.0,
    "t": 1000.0,
    "tonne": 1000.0,
    "lb": 0.45359237,
}


@dataclass(frozen=True, slots=True)
class ParsedFactorUnit:
    numerator: str
    denominator_mass: str
    reference_product_qualifier: str | None = None


def is_mass_unit(value: str) -> bool:
    return value.strip().lower().replace(" ", "") in MASS_TO_KG


def _mass_unit(value: str) -> str:
    parsed = parse_factor_unit(value)
    return parsed.numerator, parsed.denominator_mass


def parse_factor_unit(value: str) -> ParsedFactorUnit:
    value = value.lower().replace("₂", "2").replace(" ", "")
    # Accept kgCO2e/kg, kgCO2/kg and kgCO2eq/kg forms.
    match = re.fullmatch(r"([a-z]+)(?:co2e?|co2eq|co2)(?:/|per)([a-z]+)(.*)", value)
    if not match:
        raise ValueError(f"unsupported factor unit: {value!r}")
    numerator, denominator, qualifier = match.groups()
    if numerator not in MASS_TO_KG or denominator not in MASS_TO_KG:
        raise ValueError(f"unsupported mass unit in factor unit: {value!r}")
    qualifier = qualifier or None
    if qualifier and qualifier not in {"product", "produit", "产品"}:
        raise ValueError(f"unsupported reference product qualifier: {qualifier!r}")
    return ParsedFactorUnit(numerator, denominator, qualifier)


def convert_mass(value: float, from_unit: str, to_unit: str = "kg") -> float:
    source = from_unit.strip().lower().replace(" ", "")
    target = to_unit.strip().lower().replace(" ", "")
    if source not in MASS_TO_KG or target not in MASS_TO_KG:
        raise ValueError(f"unsupported mass unit: {from_unit!r} -> {to_unit!r}")
    return value * MASS_TO_KG[source] / MASS_TO_KG[target]


def convert_factor(value: float, from_unit: str, to_unit: str = "kgCO2e/kg") -> float:
    source_num, source_den = _mass_unit(from_unit)
    target_num, target_den = _mass_unit(to_unit)
    # A factor is numerator emissions mass / denominator activity mass.
    value_in_kg_per_kg = value * MASS_TO_KG[source_num] / MASS_TO_KG[source_den]
    return value_in_kg_per_kg / (MASS_TO_KG[target_num] / MASS_TO_KG[target_den])
