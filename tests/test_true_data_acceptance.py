from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

TOOL_PATH = Path(__file__).parents[1] / "tools" / "true_data_acceptance.py"
SPEC = importlib.util.spec_from_file_location("true_data_acceptance", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def factor(stage: str, value: float) -> object:
    return MODULE.ExtractedFactor(
        factor_id=f"TD-01-{stage}",
        report_id="01",
        factor_name_cn=f"示例耐火砖 {stage}",
        factor_name_en=(
            "Example Refractory Brick product carbon footprint"
            if stage == "TOTAL"
            else f"Example Refractory Brick {stage} lifecycle-stage carbon footprint"
        ),
        material_name_cn="示例耐火砖",
        category="product_carbon_footprint",
        stage=stage,
        value=value,
        unit="kgCO2e/t",
        source="issuer",
        source_version="certificate-v1",
        source_year=2025,
        boundary="cradle-to-gate" if stage == "TOTAL" else stage,
        boundary_modules=("A1", "A2", "A3") if stage == "TOTAL" else (stage,),
        applicability="per tonne",
        certificate_no="CERT-1",
        accounting_period="2025",
        docx_path="source.docx",
        docx_sha256="1" * 64,
        docx_evidence="Table 1",
        pdf_path="source.pdf",
        pdf_sha256="2" * 64,
        pdf_evidence="page 2",
        cross_format_verified=True,
    )


def test_catalog_snapshot_preserves_lifecycle_boundaries() -> None:
    payload = MODULE.catalog_payload((factor("A1", 10.0), factor("TOTAL", 12.0)))
    records = payload["records"]

    assert records[0]["boundary"] == "A1"
    assert records[0]["boundary_modules"] == ["A1"]
    assert records[1]["boundary"] == "cradle-to-gate"
    assert records[1]["boundary_modules"] == ["A1", "A2", "A3"]
    assert len(payload["database"]["sha256"]) == 64


def test_blind_cases_freeze_exact_candidate_and_add_controls() -> None:
    factors = (factor("A1", 10.0), factor("TOTAL", 12.0))
    cases = MODULE.blind_cases(factors)

    extracted = cases[:2]
    assert extracted[0]["acceptable_candidates"] == ["TD-01-A1"]
    assert extracted[0]["forbidden_candidates"] == ["TD-01-TOTAL"]
    assert extracted[1]["acceptable_candidates"] == ["TD-01-TOTAL"]
    assert len(cases) == 10
    assert sum(case["expected_more_input"] for case in cases) == 4
    assert sum(case["expected_abstention"] for case in cases) == 4


def test_number_parser_preserves_report_precision() -> None:
    assert MODULE.parse_number("3,624.70") == 3624.70


def test_product_name_is_derived_from_filename_without_case_registry() -> None:
    path = Path("20--示例组织--示例预制件产品碳足迹报告说明_证书边框.docx")
    assert MODULE.infer_product_name_cn(path) == "示例预制件"


def test_error_never_counts_as_correct_non_more_input() -> None:
    assert not MODULE.more_input_is_correct("error", False)
    assert MODULE.more_input_is_correct("recommendation_ready", False)
    assert MODULE.more_input_is_correct("more_input_needed", True)


def test_evidence_completeness_is_candidate_weighted() -> None:
    results = [
        {
            "recall_at_5": True,
            "candidate_count": 1,
            "wrong_candidate_count": 0,
            "abstention_correct": None,
            "more_input_correct": True,
            "evidence_coverage_sum": 1.0,
            "evidence_candidate_count": 1,
        },
        {
            "recall_at_5": True,
            "candidate_count": 3,
            "wrong_candidate_count": 2,
            "abstention_correct": None,
            "more_input_correct": True,
            "evidence_coverage_sum": 1.5,
            "evidence_candidate_count": 3,
        },
    ]
    metrics = MODULE.aggregate_acceptance_metrics(
        results,
        preset_sha_before="a",
        preset_sha_after="a",
        catalog_record_anchor="b",
    )

    assert metrics["evidence_completeness_rate"] == 0.625
    assert metrics["wrong_candidate_rate"] == 0.5
