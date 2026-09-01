from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tools import true_data_acceptance as MODULE


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
        product_name_en="Example Refractory Brick",
        value_raw=f"{value:.2f}",
    )


def test_catalog_snapshot_preserves_lifecycle_boundaries() -> None:
    payload = MODULE.catalog_payload((factor("A1", 10.0), factor("TOTAL", 12.0)))
    records = payload["records"]

    assert records[0]["boundary"] == "A1"
    assert records[0]["boundary_modules"] == ["A1"]
    assert records[1]["boundary"] == "cradle-to-gate"
    assert records[1]["boundary_modules"] == ["A1", "A2", "A3"]
    assert records[0]["subject_type"] == "finished_product"
    assert records[0]["source_quality_status"] == "VERIFIED"
    assert records[0]["admission_eligible"] is True
    assert len(payload["database"]["sha256"]) == 64


def test_ingestion_cases_freeze_exact_candidate_and_add_controls() -> None:
    factors = (factor("A1", 10.0), factor("TOTAL", 12.0))
    cases = MODULE.ingestion_cases(factors)

    extracted = cases[:2]
    assert extracted[0]["acceptable_candidates"] == ["TD-01-A1"]
    assert extracted[0]["forbidden_candidates"] == ["TD-01-TOTAL"]
    assert extracted[1]["acceptable_candidates"] == ["TD-01-TOTAL"]
    assert len(cases) == 10
    assert sum(case["expected_more_input"] for case in cases) == 4
    assert sum(case["expected_abstention"] for case in cases) == 4


def test_number_parser_preserves_report_precision() -> None:
    assert MODULE.parse_number("3,624.70") == Decimal("3624.70")
    assert MODULE.parse_number("0.123400") == Decimal("0.123400")


def test_product_name_is_derived_from_filename_without_case_registry() -> None:
    path = Path("20--示例组织--示例预制件产品碳足迹报告说明_证书边框.docx")
    assert MODULE.infer_product_name_cn(path) == "示例预制件"


def test_product_name_is_not_reverse_parsed_or_truncated() -> None:
    original = factor("A1", 10.0)
    high_alumina = MODULE.replace(original, product_name_en="High Alumina Brick")

    catalog = MODULE.catalog_payload((high_alumina,))
    cases = MODULE.ingestion_cases((high_alumina,))

    assert catalog["records"][0]["name"] == "High Alumina Brick"
    assert cases[0]["request"]["material_name"] == "High Alumina Brick"


def test_report_pairing_rejects_duplicate_and_invalid_ids(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate"
    duplicate.mkdir()
    for name in ("01--a.docx", "01--b.docx", "01--a.pdf"):
        (duplicate / name).write_bytes(b"fixture")
    with pytest.raises(ValueError, match="duplicate DOCX report IDs"):
        MODULE.source_pairs(duplicate)

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    for name in ("A1--a.docx", "A1--a.pdf"):
        (invalid / name).write_bytes(b"fixture")
    with pytest.raises(ValueError, match="invalid DOCX report filename"):
        MODULE.source_pairs(invalid)


def test_pdf_cross_check_is_bound_to_stage_row_and_carbon_footprint_column() -> None:
    class Row:
        def __init__(self, marker: float):
            self.cells = ((0.0, 0.0, 1.0, 1.0),) * 4 + ((marker, 1.0, marker + 1.0, 2.0),)

    class Table:
        rows = [Row(float(index)) for index in range(5)]

        @staticmethod
        def extract():
            return [
                ["Life Cycle Process", "", "Sub-process", "Net Emissions", "Carbon Footprint"],
                ["A1", "", "", "100", "10.10"],
                ["A2", "", "", "200", "20.20"],
                ["A3", "", "", "300", "30.30"],
                ["Total", "", "", "600", "60.60"],
            ]

    class Page:
        @staticmethod
        def find_tables():
            return [Table()]

    cells = MODULE._pdf_lifecycle_cells(Page())

    assert cells["A2"][:3] == ("20.20", 0, 2)
    assert cells["A2"][3] == (2.0, 1.0, 3.0, 2.0)
    assert MODULE.parse_number(cells["A2"][0]) != MODULE.parse_number(cells["A1"][0])


def test_rejected_source_is_not_an_acceptable_ingestion_answer() -> None:
    rejected = MODULE.replace(
        factor("A1", 10.0), source_quality_status="REJECTED", admission_eligible=False
    )

    record = MODULE.catalog_payload((rejected,))["records"][0]
    case = MODULE.ingestion_cases((rejected,))[0]

    assert record["admission_eligible"] is False
    assert case["case_type"] == "source_quality_control"
    assert case["acceptable_candidates"] == []
    assert case["expected_abstention"] is True


def test_output_directory_cannot_overlap_source_or_overwrite_prior_run(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="must not equal or be inside"):
        MODULE.build_acceptance(source, source / "output")

    output = tmp_path / "output"
    output.mkdir()
    (output / "prior-run.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="must be new or empty"):
        MODULE.build_acceptance(source, output)


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
            "expected_more_input": False,
            "observed_status": "recommendation_ready",
            "evidence_coverage_sum": 1.0,
            "evidence_candidate_count": 1,
        },
        {
            "recall_at_5": True,
            "candidate_count": 3,
            "wrong_candidate_count": 2,
            "abstention_correct": None,
            "more_input_correct": True,
            "expected_more_input": False,
            "observed_status": "recommendation_ready",
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


def test_release_gate_requires_twenty_negative_holdout_cases() -> None:
    metrics = {
        "recall_at_5": 1.0,
        "wrong_candidate_rate": 0.0,
        "correct_abstention_rate": 1.0,
        "abstention_case_count": 20,
        "more_input_positive_recall": 1.0,
        "more_input_negative_specificity": 1.0,
        "evidence_completeness_rate": 1.0,
        "case_error_count": 0,
    }
    assert MODULE.release_gate(metrics, metrics)["passed"] is True

    undersized = dict(metrics, abstention_case_count=19)
    gate = MODULE.release_gate(metrics, undersized)
    assert gate["passed"] is False
    assert gate["checks"]["holdout_negative_sample_size"] is False

    missing = MODULE.release_gate(metrics, None)
    assert missing["passed"] is False
    assert missing["checks"]["holdout_present"] is False


def test_generated_report_uses_top_one_metric_and_methodology_labels(tmp_path: Path) -> None:
    metric = {
        "recall_at_5": 1.0,
        "top_1_accuracy": 0.875,
        "wrong_candidate_rate": 0.0,
        "correct_abstention_rate": 1.0,
        "more_input_positive_recall": 1.0,
        "more_input_negative_specificity": 1.0,
        "evidence_metadata_presence_rate": 1.0,
        "case_count": 32,
        "abstention_case_count": 20,
    }
    target = tmp_path / "report.md"
    MODULE.write_acceptance_report(
        target,
        pair_count=18,
        factor_count=72,
        case_count=80,
        finding_count=1,
        metrics=metric,
        holdout_metrics=metric,
        gate={"passed": True, "checks": {"holdout": True}},
    )

    report = target.read_text(encoding="utf-8")
    assert "Top-1 | 87.5%" in report
    assert "闭环摄取一致性验收" in report
    assert "独立真实查询 Holdout" in report
    assert "盲测" not in report
