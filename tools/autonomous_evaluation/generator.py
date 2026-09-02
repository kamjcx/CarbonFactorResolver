"""Contract-driven autonomous evaluation generator using only synthetic data."""

from __future__ import annotations

import copy
import hashlib
import random
from typing import Any, Mapping, Sequence

from .contracts import CatalogVariant, EvaluationBundle, GeneratedCase
from .oracle import derive_expectation

DEFAULT_SEED = 20260902


def _digest(label: str) -> str:
    return hashlib.sha256(f"cfr-public-synthetic:{label}".encode()).hexdigest()


def _record(
    slug: str,
    name: str,
    aliases: Sequence[str],
    *,
    subject: str,
    boundary: str,
    unit: str,
    value: float,
    process: str | None = None,
    form: str | None = None,
    geography: str | None = None,
    year: int | None = None,
    tier: str = "structured_current",
) -> dict[str, Any]:
    source_id = f"AUTO-SYN-{slug.upper().replace('-', '_')}"
    record: dict[str, Any] = {
        "record_id": f"auto-syn:{slug}",
        "source_id": source_id,
        "code": source_id,
        "name": name,
        "aliases": list(aliases),
        "category": "public_synthetic_factor",
        "primary_value": value,
        "primary_unit": unit,
        "source": "CFR autonomous public-synthetic contract fixture",
        "source_tier": tier,
        "subject_type": subject,
        "boundary": boundary,
        "boundary_modules": [boundary] if boundary != "A1-A3" else ["A1", "A2", "A3"],
        "source_quality_status": "VERIFIED",
        "admission_eligible": True,
        "document_status": "PUBLISHED",
        "indicator": "GWP-total",
        "declared_product": name,
        "source_document_locator": f"https://example.invalid/autonomous/{slug}",
        "source_document_sha256": _digest(slug),
    }
    optional = {
        "production_process": process,
        "product_form": form,
        "geography": geography,
        "year": year,
    }
    record.update({key: value for key, value in optional.items() if value is not None})
    return record


def _base_records() -> tuple[Mapping[str, Any], ...]:
    specs = (
        ("bauxite-ore", "bauxite ore", ("铝土矿原矿", "raw bauxite"), "raw_material", "A1", "kgCO2e/kg", 0.31, None, "ore", None, None),
        ("bauxite-clinker", "calcined bauxite clinker", ("高铝矾土熟料", "calcined bauxite"), "raw_material", "A1", "kgCO2e/kg", 0.83, "calcined", "clinker", None, None),
        ("high-alumina-product", "high alumina finished product", ("高铝耐火制品",), "finished_product", "A1-A3", "kgCO2e/kg", 1.21, None, "finished", None, None),
        ("primary-aluminium", "primary aluminium ingot", ("原铝锭", "primary aluminum"), "raw_material", "A1", "kgCO2e/kg", 12.1, "primary", "ingot", None, None),
        ("secondary-aluminium", "secondary aluminium ingot", ("再生铝锭", "recycled aluminum"), "raw_material", "A1", "kgCO2e/kg", 1.8, "secondary", "ingot", None, None),
        ("alumina", "alumina", ("氧化铝", "aluminium oxide"), "raw_material", "A1", "kgCO2e/kg", 2.4, None, "powder", None, None),
        ("graphite-electrode", "graphite electrode", ("石墨电极", "graphite-electrode"), "raw_material", "A1", "kgCO2e/kg", 7.4, None, "electrode", None, None),
        ("graphite-powder", "graphite powder", ("普通石墨粉", "graphite"), "raw_material", "A1", "kgCO2e/kg", 2.2, None, "powder", None, None),
        ("iron-turnings", "unsorted iron turnings", ("未分选铁屑", "iron swarf"), "waste", "A1", "kgCO2e/kg", 0.08, None, "loose", None, None),
        ("baled-scrap", "baled steel scrap", ("压块废钢", "sorted scrap bale"), "waste", "A1", "kgCO2e/kg", 0.16, None, "bale", None, None),
        ("road-freight", "road freight", ("公路运输", "road freight transport"), "transport", "A2", "kgCO2e/tkm", 0.078, None, None, None, None),
        ("rail-freight", "rail freight", ("铁路运输", "rail freight transport"), "transport", "A2", "kgCO2e/tkm", 0.0495, None, None, None, None),
        ("grid-2024", "grid electricity 2024", ("2024全国平均电力", "外购电力"), "energy", "A3", "kgCO2e/kWh", 0.5777, None, None, "CN", 2024),
        ("photovoltaic", "photovoltaic electricity", ("光伏电力", "solar electricity"), "energy", "A3", "kgCO2e/kWh", 0.055, None, None, "CN", 2024),
        ("grid-2021", "grid electricity 2021", ("2021历史电力",), "energy", "A3", "kgCO2e/kWh", 0.581, None, None, "CN", 2021),
        ("coal-market", "purchased hard coal", ("采购煤炭", "hard coal market"), "raw_material", "A1", "kgCO2e/kg", 0.31, "market_supply", None, "CN", 2024),
        ("coal-combustion", "hard coal combustion", ("煤炭现场燃烧", "coal burning"), "energy", "A3", "kgCO2e/kg", 2.52, "combustion", None, "CN", 2024),
        ("spinel-fused", "electrofused spinel", ("电熔尖晶石", "fused spinel"), "raw_material", "A1", "kgCO2e/kg", 4.6, "electrofused", "aggregate", None, None),
        ("spinel-sintered", "sintered spinel", ("烧结尖晶石",), "raw_material", "A1", "kgCO2e/kg", 3.8, "sintered", "aggregate", None, None),
        ("steel-fiber", "steel fiber", ("钢纤维", "steel fibre"), "raw_material", "A1", "kgCO2e/kg", 2.1, None, "fiber", None, None),
    )
    return tuple(
        _record(
            slug,
            name,
            aliases,
            subject=subject,
            boundary=boundary,
            unit=unit,
            value=value,
            process=process,
            form=form,
            geography=geography,
            year=year,
        )
        for slug, name, aliases, subject, boundary, unit, value, process, form, geography, year in specs
    )


def _apply_operations(
    records: Sequence[Mapping[str, Any]], operations: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result = [copy.deepcopy(dict(record)) for record in records]
    for operation in operations:
        kind = operation["kind"]
        if kind == "shuffle":
            random.Random(int(operation["seed"])).shuffle(result)
        elif kind == "noise":
            result.append(copy.deepcopy(dict(operation["record"])))
        elif kind == "duplicate":
            source = next(record for record in result if record["source_id"] == operation["source_id"])
            duplicate = copy.deepcopy(source)
            duplicate["record_id"] = str(operation["record_id"])
            duplicate["source_id"] = str(operation["new_source_id"])
            duplicate["source_tier"] = str(operation.get("source_tier", "historical"))
            result.append(duplicate)
        elif kind == "patch":
            target = next(record for record in result if record["source_id"] == operation["source_id"])
            for key, value in dict(operation["changes"]).items():
                if value == "__DELETE__":
                    target.pop(key, None)
                else:
                    target[key] = value
            if "boundary" in operation["changes"] and "boundary_modules" not in operation["changes"]:
                boundary = str(target["boundary"])
                target["boundary_modules"] = (
                    ["A1", "A2", "A3"] if boundary == "A1-A3" else [boundary]
                )
        else:
            raise ValueError(f"unknown catalog operation: {kind}")
    return result


def materialize_catalog(case: GeneratedCase) -> Mapping[str, Any]:
    records = _apply_operations(_base_records(), case.catalog_variant.operations)
    # The public HTTP catalog contract treats ``record_id`` as the canonical
    # source identifier. Keep it aligned with the Oracle's synthetic source ID
    # and translate the Oracle's readable source tier into the runtime's
    # lower-is-better priority rank.
    runtime_priority = {
        "reviewed_formal": 0,
        "official_current": 10,
        "structured_current": 20,
        "historical": 100,
    }
    for record in records:
        record["record_id"] = record["source_id"]
        record["factor_kind"] = "lifecycle_factor"
        record["source_priority_rank"] = runtime_priority[str(record["source_tier"])]
    return {
        "catalog_version": "cfr-autonomous-public-synthetic/v1",
        "database": {
            "name": "cfr-autonomous-public-synthetic",
            "sha256": _digest(case.catalog_variant.variant_id),
        },
        "records": records,
    }


def _request(record: Mapping[str, Any], name: str | None = None) -> dict[str, Any]:
    quantity_unit = {
        "kgCO2e/kg": "kg",
        "kgCO2e/kWh": "kWh",
        "kgCO2e/tkm": "tkm",
    }[str(record["primary_unit"])]
    request: dict[str, Any] = {
        "material_name": name or record["name"],
        "quantity": 1.0,
        "quantity_unit": quantity_unit,
        "target_factor_unit": record["primary_unit"],
        "subject_type": record["subject_type"],
        "boundary": record["boundary"],
        "top_k": 5,
    }
    for key in ("production_process", "product_form", "geography", "year"):
        if key in record:
            request[key] = record[key]
    return request


def _variant(variant_id: str, *operations: Mapping[str, Any]) -> CatalogVariant:
    return CatalogVariant(variant_id, tuple(operations))


def _noise_record(index: int) -> Mapping[str, Any]:
    return _record(
        f"noise-{index}",
        f"unrelated synthetic mineral {index}",
        (f"无关合成矿物{index}",),
        subject="raw_material",
        boundary="A1",
        unit="kgCO2e/kg",
        value=0.1 + index / 1000,
    )


def _make_case(
    case_id: str,
    category: str,
    request: Mapping[str, Any],
    variant: CatalogVariant,
    *,
    group: str | None = None,
    axis: str = "decision_contract",
) -> GeneratedCase:
    catalog = _apply_operations(_base_records(), variant.operations)
    return GeneratedCase(
        case_id=case_id,
        category=category,
        request=dict(request),
        expectation=derive_expectation(request, catalog),
        catalog_variant=variant,
        metamorphic_group=group,
        assertion_axis=axis,
    )


def generate_bundle(seed: int = DEFAULT_SEED) -> EvaluationBundle:
    """Generate 300-500 unique cases with deterministic content and ordering."""

    records = _base_records()
    cases: list[GeneratedCase] = []
    baseline = _variant("baseline")
    wrong_subject = {
        "raw_material": "finished_product",
        "finished_product": "raw_material",
        "energy": "transport",
        "transport": "energy",
        "waste": "raw_material",
    }
    wrong_unit = {
        "kgCO2e/kg": "kgCO2e/kWh",
        "kgCO2e/kWh": "kgCO2e/tkm",
        "kgCO2e/tkm": "kgCO2e/kg",
    }
    equivalent_unit = {
        "kgCO2e/kg": "kgCO2e/t",
        "kgCO2e/kWh": "kgCO2e/MWh",
        "kgCO2e/tkm": "kgCO2e/(t*km)",
    }

    for index, record in enumerate(records, 1):
        base = _request(record)
        slug = str(record["record_id"]).split(":", 1)[1]
        aliases = list(record["aliases"])
        typo = str(record["name"]).replace("i", "l", 1)
        if typo == record["name"]:
            typo = f"{record['name']} synthetic typo"
        typo_variant = _variant(
            f"typo-{slug}",
            {
                "kind": "patch",
                "source_id": record["source_id"],
                "changes": {"aliases": [*aliases, typo]},
            },
        )
        forms = (
            ("canonical", record["name"], baseline, "alias_or_entity"),
            ("reviewed-alias", aliases[0], baseline, "alias_or_entity"),
            ("casefold", str(record["name"]).upper(), baseline, "alias_or_entity"),
            ("symbol", f" {record['name'].replace(' ', ' - ')} ", baseline, "alias_or_entity"),
            ("reviewed-typo", typo, typo_variant, "alias_or_entity"),
        )
        for label, name, variant, axis in forms:
            request = {**base, "material_name": name}
            cases.append(
                _make_case(
                    f"AUTO-{index:02d}-POS-{label}",
                    f"positive_{label}",
                    request,
                    variant,
                    axis=axis,
                )
            )

        for multiplier in (0.001, 10.0, 1_000_000.0):
            request = {**base, "quantity": multiplier}
            cases.append(
                _make_case(
                    f"AUTO-{index:02d}-Q-{str(multiplier).replace('.', '_')}",
                    "metamorphic_quantity",
                    request,
                    baseline,
                    group=f"quantity:{slug}",
                    axis="ranking_invariance",
                )
            )

        shuffled = _variant(f"shuffle-{slug}-{seed}", {"kind": "shuffle", "seed": seed + index})
        cases.append(
            _make_case(
                f"AUTO-{index:02d}-ORDER",
                "metamorphic_catalog_order",
                base,
                shuffled,
                group=f"order:{slug}",
                axis="deterministic_replay",
            )
        )
        noise = _variant(f"noise-{slug}", {"kind": "noise", "record": _noise_record(index)})
        cases.append(
            _make_case(
                f"AUTO-{index:02d}-NOISE",
                "metamorphic_irrelevant_noise",
                base,
                noise,
                group=f"noise:{slug}",
                axis="top_1_stability",
            )
        )
        duplicate = _variant(
            f"duplicate-{slug}",
            {
                "kind": "duplicate",
                "source_id": record["source_id"],
                "record_id": f"auto-syn:{slug}-historical-copy",
                "new_source_id": f"AUTO-SYN-{slug.upper()}-HISTORICAL",
                "source_tier": "historical",
            },
        )
        cases.append(
            _make_case(
                f"AUTO-{index:02d}-DUP",
                "source_priority_duplicate",
                base,
                duplicate,
                group=f"priority:{slug}",
                axis="source_priority",
            )
        )

        bad_boundary = "A2" if record["boundary"] != "A2" else "A1"
        cases.append(
            _make_case(
                f"AUTO-{index:02d}-BOUNDARY",
                "boundary_conflict",
                {**base, "boundary": bad_boundary},
                baseline,
                axis="boundary",
            )
        )
        subject = str(record["subject_type"])
        cases.append(
            _make_case(
                f"AUTO-{index:02d}-SUBJECT",
                "subject_conflict",
                {**base, "subject_type": wrong_subject.get(subject, "process")},
                baseline,
                axis="subject",
            )
        )
        unit = str(record["primary_unit"])
        cases.append(
            _make_case(
                f"AUTO-{index:02d}-UNIT-X",
                "unit_dimension_conflict",
                {**base, "target_factor_unit": wrong_unit[unit]},
                baseline,
                axis="unit",
            )
        )
        cases.append(
            _make_case(
                f"AUTO-{index:02d}-UNIT-EQ",
                "unit_same_dimension",
                {**base, "target_factor_unit": equivalent_unit[unit]},
                baseline,
                group=f"unit:{slug}",
                axis="unit_math_equivalence",
            )
        )

        for label, changes in (
            ("HASH", {"source_document_sha256": "__DELETE__"}),
            ("QUALITY", {"source_quality_status": "NEEDS_REVIEW"}),
            ("ELIGIBLE", {"admission_eligible": False}),
        ):
            variant = _variant(
                f"provenance-{label.lower()}-{slug}",
                {"kind": "patch", "source_id": record["source_id"], "changes": changes},
            )
            cases.append(
                _make_case(
                    f"AUTO-{index:02d}-PROV-{label}",
                    "provenance_degradation",
                    base,
                    variant,
                    axis="provenance",
                )
            )

    # Matrix is explicit and complete: aggregated values are never stage candidates.
    matrix_record = next(record for record in records if record["record_id"] == "auto-syn:grid-2024")
    for request_boundary in ("A1", "A2", "A3", "A1-A3"):
        for record_boundary in ("A1", "A2", "A3", "A1-A3"):
            variant = _variant(
                f"matrix-{request_boundary}-{record_boundary}",
                {
                    "kind": "patch",
                    "source_id": matrix_record["source_id"],
                    "changes": {"boundary": record_boundary},
                },
            )
            request = {**_request(matrix_record), "boundary": request_boundary}
            cases.append(
                _make_case(
                    f"AUTO-MATRIX-{request_boundary}-{record_boundary}",
                    "boundary_matrix",
                    request,
                    variant,
                    axis="boundary",
                )
            )

    # Unknown and malformed queries exercise coverage and unsupported-unit refusal.
    for index in range(12):
        unknown_request = {
            "material_name": f"unknown public synthetic material {index}",
            "quantity": 1,
            "quantity_unit": "kg",
            "target_factor_unit": "kgCO2e/kg",
            "subject_type": "raw_material",
            "boundary": "A1",
        }
        cases.append(
            _make_case(
                f"AUTO-UNKNOWN-{index:02d}",
                "catalog_coverage_gap",
                unknown_request,
                baseline,
                axis="abstention",
            )
        )

    # Decisive attributes are tested against deliberately shared reviewed aliases.
    ambiguity_specs = (
        ("ALUMINIUM", "aluminium ingot", ("AUTO-SYN-PRIMARY_ALUMINIUM", "AUTO-SYN-SECONDARY_ALUMINIUM"), "production_process"),
        ("SPINEL", "spinel aggregate", ("AUTO-SYN-SPINEL_FUSED", "AUTO-SYN-SPINEL_SINTERED"), "production_process"),
        ("GRID", "CN grid electricity", ("AUTO-SYN-GRID_2024", "AUTO-SYN-GRID_2021"), "year"),
        ("BAUXITE", "bauxite feed", ("AUTO-SYN-BAUXITE_ORE", "AUTO-SYN-BAUXITE_CLINKER"), "product_form"),
        ("GRAPHITE", "graphite material", ("AUTO-SYN-GRAPHITE_ELECTRODE", "AUTO-SYN-GRAPHITE_POWDER"), "product_form"),
    )
    record_by_source = {str(record["source_id"]): record for record in records}
    for label, shared_alias, source_ids, decisive_field in ambiguity_specs:
        operations = tuple(
            {
                "kind": "patch",
                "source_id": source_id,
                "changes": {
                    "aliases": [*record_by_source[source_id]["aliases"], shared_alias],
                },
            }
            for source_id in source_ids
        )
        reference = record_by_source[source_ids[0]]
        request = _request(reference, shared_alias)
        request.pop(decisive_field, None)
        variant = _variant(f"missing-decisive-{label.casefold()}", *operations)
        cases.append(
            _make_case(
                f"AUTO-MISSING-{label}",
                "missing_decisive_attribute",
                request,
                variant,
                group=f"missing:{label.casefold()}",
                axis="more_input",
            )
        )

    # Geography and year mismatches are hard qualification failures.
    for source_id in ("AUTO-SYN-GRID_2024", "AUTO-SYN-COAL_MARKET", "AUTO-SYN-COAL_COMBUSTION"):
        record = record_by_source[source_id]
        for field, value in (("geography", "US"), ("year", 2019)):
            cases.append(
                _make_case(
                    f"AUTO-{source_id.removeprefix('AUTO-SYN-')}-{field.upper()}-X",
                    f"{field}_conflict",
                    {**_request(record), field: value},
                    baseline,
                    axis=field,
                )
            )

    # A higher-priority record never overrides an incompatible qualification dimension.
    priority_targets = tuple(records[:5])
    for index, record in enumerate(priority_targets, 1):
        duplicate_id = f"AUTO-SYN-HIGH-CONFLICT-{index}"
        for axis, changes in (
            ("boundary", {"boundary": "A2" if record["boundary"] != "A2" else "A1"}),
            ("subject", {"subject_type": "energy"}),
            ("unit", {"primary_unit": "kgCO2e/kWh"}),
        ):
            variant = _variant(
                f"high-priority-{axis}-{index}",
                {
                    "kind": "duplicate",
                    "source_id": record["source_id"],
                    "record_id": f"auto-syn:high-conflict-{axis}-{index}",
                    "new_source_id": duplicate_id,
                    "source_tier": "reviewed_formal",
                },
                {"kind": "patch", "source_id": duplicate_id, "changes": changes},
            )
            cases.append(
                _make_case(
                    f"AUTO-HIGH-PRIORITY-{index}-{axis.upper()}",
                    "ineligible_high_priority",
                    _request(record),
                    variant,
                    axis=axis,
                )
            )

    return EvaluationBundle(seed=seed, records=records, cases=tuple(cases))
