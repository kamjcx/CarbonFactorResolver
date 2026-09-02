from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from a1_factor_engine.units import (
    CATALOG_FACTOR_UNIT_INVALID,
    UNIT_CONVERSION_EVIDENCE_REQUIRED,
    UNIT_DIMENSION_MISMATCH,
    UNIT_SYNTAX_UNSUPPORTED,
    ActivityDimension,
    CatalogFactorUnitError,
    UnitConversionEvidence,
    UnitConversionEvidenceRequiredError,
    UnitDimensionMismatchError,
    UnitSyntaxError,
    convert_activity_decimal,
    convert_factor,
    convert_factor_decimal,
    convert_mass,
    parse_activity_unit,
    parse_catalog_factor_unit,
    parse_factor_unit,
    plan_activity_conversion,
    plan_factor_conversion,
)


@pytest.mark.parametrize(
    ("raw", "canonical", "dimension", "ratio"),
    (
        ("g", "g", ActivityDimension.MASS, Decimal("0.001")),
        ("kg", "kg", ActivityDimension.MASS, Decimal("1")),
        ("tonne", "tonne", ActivityDimension.MASS, Decimal("1000")),
        ("MWh", "MWh", ActivityDimension.ENERGY, Decimal("1000")),
        ("MJ", "MJ", ActivityDimension.ENERGY, Decimal(1) / Decimal("3.6")),
        ("m³", "m3", ActivityDimension.VOLUME, Decimal("1")),
        ("Nm3", "Nm3", ActivityDimension.VOLUME, Decimal("1")),
        ("kgkm", "kgkm", ActivityDimension.TRANSPORT_WORK, Decimal("0.001")),
        ("piece", "item", ActivityDimension.COUNT, Decimal("1")),
    ),
)
def test_activity_registry_matrix(raw, canonical, dimension, ratio):
    parsed = parse_activity_unit(raw)
    assert parsed.canonical_unit == canonical
    assert parsed.dimension == dimension
    assert parsed.ratio_to_base == ratio


@pytest.mark.parametrize("impact", ("kgCO2e", "kg CO2e", "kgCO2eq", "kg CO2-eq"))
def test_controlled_impact_spellings_are_canonical(impact):
    parsed = parse_factor_unit(f"{impact}/MWh")
    assert parsed.impact_unit.canonical_unit == "kgCO2e"
    assert parsed.activity_unit.canonical_unit == "MWh"
    assert parsed.numerator == "kg"
    assert parsed.denominator_mass == "MWh"


def test_legacy_product_qualifier_is_retained():
    parsed = parse_factor_unit("kgCO2e/t产品")
    assert parsed.reference_product_qualifier == "产品"
    assert parsed.denominator_mass == "t"


def test_gco2e_compatibility_input_scales_impact():
    assert parse_factor_unit("gCO2e/kg").impact_unit.canonical_unit == "kgCO2e"
    result = plan_factor_conversion("gCO2e/kg", "kgCO2e/kg")
    assert result.multiplier == Decimal("0.001")
    assert result.convert("1000") == Decimal("1.000")


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    (
        ("kgCO2e/t", "kgCO2e/kg", Decimal("0.001")),
        ("kgCO2e/MWh", "kgCO2e/kWh", Decimal("0.001")),
        ("kgCO2e/tkm", "kgCO2e/kgkm", Decimal("0.001")),
    ),
)
def test_factor_denominator_direction(source, target, expected):
    plan = plan_factor_conversion(source, target)
    assert plan.multiplier == expected
    assert plan.reason_code is None


def test_activity_direction_is_inverse_of_factor_direction():
    activity = plan_activity_conversion("t", "kg")
    factor = plan_factor_conversion("kgCO2e/t", "kgCO2e/kg")
    assert activity.multiplier == Decimal("1000")
    assert factor.multiplier == Decimal("0.001")
    assert activity.multiplier * factor.multiplier == Decimal("1")


def test_quantity_times_factor_is_invariant():
    quantity = convert_activity_decimal("2.5", "t", "kg")
    factor = convert_factor_decimal("8", "kgCO2e/t", "kgCO2e/kg")
    assert Decimal("2.5") * Decimal("8") == quantity * factor


def test_m3_nm3_requires_versioned_directional_evidence():
    plan = plan_activity_conversion("m3", "Nm3")
    assert plan.evidence_required is True
    assert plan.reason_code == UNIT_CONVERSION_EVIDENCE_REQUIRED
    assert plan.multiplier is None
    with pytest.raises(UnitConversionEvidenceRequiredError) as raised:
        plan.convert("1")
    assert raised.value.reason_code == UNIT_CONVERSION_EVIDENCE_REQUIRED

    evidence = UnitConversionEvidence(
        evidence_id="volume-condition-1",
        version="v1",
        source_canonical_unit="m3",
        target_canonical_unit="Nm3",
        multiplier=Decimal("0.97"),
    )
    evidenced = plan_activity_conversion("m3", "Nm3", evidence=evidence)
    assert evidenced.convert("10") == Decimal("9.70")
    assert evidenced.evidence_id == "volume-condition-1"
    assert evidenced.evidence_version == "v1"


def test_nm3_identity_does_not_require_evidence():
    plan = plan_activity_conversion("Nm3", "Nm3")
    assert plan.multiplier == Decimal("1")
    assert plan.evidence_required is False


def test_factor_conditioned_volume_conversion_uses_inverse_evidence_direction():
    evidence = UnitConversionEvidence(
        evidence_id="volume-condition-2",
        version="2026-01",
        source_canonical_unit="m3",
        target_canonical_unit="Nm3",
        multiplier=Decimal("0.8"),
    )
    plan = plan_factor_conversion("kgCO2e/m3", "kgCO2e/Nm3", evidence=evidence)
    assert plan.multiplier == Decimal("1.25")


def test_conditioned_volume_gate_also_covers_scaled_ambient_volume_units():
    activity = plan_activity_conversion("L", "Nm3")
    factor = plan_factor_conversion("kgCO2e/L", "kgCO2e/Nm3")
    assert activity.evidence_required is True
    assert activity.reason_code == UNIT_CONVERSION_EVIDENCE_REQUIRED
    assert factor.evidence_required is True
    assert factor.reason_code == UNIT_CONVERSION_EVIDENCE_REQUIRED


def test_cross_dimension_plan_and_conversion_are_structured():
    plan = plan_activity_conversion("kg", "kWh")
    assert plan.reason_code == UNIT_DIMENSION_MISMATCH
    assert plan.convertible is False
    with pytest.raises(UnitDimensionMismatchError) as raised:
        plan.convert("1")
    assert raised.value.reason_code == UNIT_DIMENSION_MISMATCH

    factor_plan = plan_factor_conversion("kgCO2e/kg", "kgCO2e/kWh")
    assert factor_plan.reason_code == UNIT_DIMENSION_MISMATCH


def test_count_to_mass_is_never_inferred():
    with pytest.raises(UnitDimensionMismatchError):
        convert_activity_decimal("10", "piece", "kg")


def test_parse_errors_have_stable_context_specific_codes():
    with pytest.raises(UnitSyntaxError) as request_error:
        parse_factor_unit("points/kg")
    assert request_error.value.reason_code == UNIT_SYNTAX_UNSUPPORTED

    with pytest.raises(CatalogFactorUnitError) as catalog_error:
        parse_catalog_factor_unit("points/kg")
    assert catalog_error.value.reason_code == CATALOG_FACTOR_UNIT_INVALID


def test_legacy_float_wrappers_remain_compatible():
    mass = convert_mass(1, "t", "kg")
    factor = convert_factor(1000, "gCO2e/kg", "kgCO2e/kg")
    assert mass == 1000.0 and isinstance(mass, float)
    assert factor == 1.0 and isinstance(factor, float)


_POSITIVE_DECIMALS = st.decimals(
    min_value=Decimal("0.000001"),
    max_value=Decimal("1000000000"),
    allow_nan=False,
    allow_infinity=False,
    places=6,
)


@given(_POSITIVE_DECIMALS)
def test_decimal_mass_round_trip_is_exact(value):
    kilograms = convert_activity_decimal(value, "t", "kg")
    assert convert_activity_decimal(kilograms, "kg", "t") == value


@given(_POSITIVE_DECIMALS, _POSITIVE_DECIMALS)
def test_emissions_invariance_property(quantity, factor):
    converted_quantity = convert_activity_decimal(quantity, "MWh", "kWh")
    converted_factor = convert_factor_decimal(factor, "kgCO2e/MWh", "kgCO2e/kWh")
    assert quantity * factor == converted_quantity * converted_factor
