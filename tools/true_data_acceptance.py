"""Build and run a read-only acceptance benchmark from paired DOCX/PDF reports.

The command deliberately writes only to an explicit output directory. It does
not update a catalogue, approval store, or any source report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.engine import A1FactorResolutionEngine
from a1_factor_engine.models import ResolutionStatus

EXPECTED_STAGES = ("A1", "A2", "A3", "TOTAL")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def parse_number(value: str) -> float:
    return float(value.replace(",", "").strip())


def label_value(paragraphs: Iterable[str], label: str) -> str:
    for paragraph in paragraphs:
        for line in paragraph.splitlines():
            if label in line:
                return line.split(label, 1)[1].strip()
    raise ValueError(f"required label not found: {label}")


def normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def first_year(value: str) -> int:
    match = re.search(r"\b(20\d{2})\b", value)
    if not match:
        raise ValueError(f"year not found: {value}")
    return int(match.group(1))


def infer_product_name_cn(path: Path) -> str:
    """Extract the product label from the report filename without a case registry."""
    tail = re.sub(r"^\d+--", "", path.stem)
    if "--" in tail:
        tail = tail.rsplit("--", 1)[1]
    elif "_" in tail:
        tail = tail.split("_", 1)[1]
    tail = tail.lstrip("_-")
    suffixes = (
        "产品碳足迹报告说明_证书边框",
        "_中英双语_证书边框_new",
        "中英双语_证书边框_new",
        "_中英双语_证书边框",
        "中英双语_证书边框",
        "报告说明_证书边框",
        "_证书边框",
    )
    for suffix in suffixes:
        if tail.endswith(suffix):
            tail = tail[: -len(suffix)]
            break
    return re.sub(r"\s+", "", tail).strip("_-")


@dataclass(frozen=True)
class SourcePair:
    report_id: str
    product_name_cn: str
    docx_path: str
    pdf_path: str
    docx_sha256: str
    pdf_sha256: str
    docx_size: int
    pdf_size: int


@dataclass(frozen=True)
class ExtractedFactor:
    factor_id: str
    report_id: str
    factor_name_cn: str
    factor_name_en: str
    material_name_cn: str
    category: str
    stage: str
    value: float
    unit: str
    source: str
    source_version: str
    source_year: int
    boundary: str
    boundary_modules: tuple[str, ...]
    applicability: str
    certificate_no: str
    accounting_period: str
    docx_path: str
    docx_sha256: str
    docx_evidence: str
    pdf_path: str
    pdf_sha256: str
    pdf_evidence: str
    cross_format_verified: bool


@dataclass(frozen=True)
class QualityFinding:
    report_id: str
    severity: str
    code: str
    message: str
    evidence: str


def source_pairs(source_dir: Path) -> tuple[SourcePair, ...]:
    docx_by_id = {path.name[:2]: path for path in source_dir.glob("*.docx")}
    pdf_by_id = {path.name[:2]: path for path in source_dir.glob("*.pdf")}
    if set(docx_by_id) != set(pdf_by_id):
        raise ValueError(
            "DOCX/PDF report IDs differ: "
            f"docx_only={sorted(set(docx_by_id) - set(pdf_by_id))}, "
            f"pdf_only={sorted(set(pdf_by_id) - set(docx_by_id))}"
        )
    if len(docx_by_id) != 18:
        raise ValueError(f"expected 18 paired reports, found {len(docx_by_id)}")

    return tuple(
        SourcePair(
            report_id=report_id,
            product_name_cn=infer_product_name_cn(docx_by_id[report_id]),
            docx_path=str(docx_by_id[report_id].resolve()),
            pdf_path=str(pdf_by_id[report_id].resolve()),
            docx_sha256=sha256_file(docx_by_id[report_id]),
            pdf_sha256=sha256_file(pdf_by_id[report_id]),
            docx_size=docx_by_id[report_id].stat().st_size,
            pdf_size=pdf_by_id[report_id].stat().st_size,
        )
        for report_id in sorted(docx_by_id)
    )


def extract_pair(pair: SourcePair) -> tuple[tuple[ExtractedFactor, ...], tuple[QualityFinding, ...]]:
    try:
        import pdfplumber
        from docx import Document
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        raise RuntimeError(
            "true-data extraction requires the optional energy-import dependencies "
            "plus python-docx"
        ) from exc

    document = Document(pair.docx_path)
    paragraphs = tuple(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
    product_en = label_value(paragraphs, "Product Name:")
    specification = label_value(paragraphs, "Specification/Model:")
    certificate_no = label_value(paragraphs, "Certificate No.:")
    accounting_period = label_value(paragraphs, "Accounting Period:")
    boundary_text = label_value(paragraphs, "System Boundary:")
    total_label = label_value(paragraphs, "Product Carbon Footprint per Unit:")
    total_value = parse_number(re.search(r"[\d,.]+", total_label).group(0))  # type: ignore[union-attr]
    year = first_year(accounting_period)
    issue_date = label_value(paragraphs, "Issue Date:")
    source_version = f"{certificate_no}; issued {issue_date}"
    source = label_value(paragraphs, "Evaluation and Reporting Organization:")

    if len(document.tables) != 1 or len(document.tables[0].rows) != 5:
        raise ValueError(
            f"{pair.report_id}: expected one five-row lifecycle table, "
            f"found {len(document.tables)} tables"
        )
    rows = [
        tuple(cell.text.replace("\n", " ").strip() for cell in row.cells)
        for row in document.tables[0].rows[1:]
    ]
    observed_stages = tuple(row[0].split()[0] if row[0].startswith("A") else "TOTAL" for row in rows)
    if observed_stages != EXPECTED_STAGES:
        raise ValueError(f"{pair.report_id}: unexpected lifecycle rows {observed_stages!r}")

    with pdfplumber.open(pair.pdf_path) as pdf:
        pdf_pages = tuple(page.extract_text() or "" for page in pdf.pages)
    if len(pdf_pages) != 2:
        raise ValueError(f"{pair.report_id}: expected two PDF pages, found {len(pdf_pages)}")
    compact_pdf = normalized_token("\n".join(pdf_pages))
    product_verified = normalized_token(product_en) in compact_pdf

    factors: list[ExtractedFactor] = []
    findings: list[QualityFinding] = []
    stage_values: list[Decimal] = []
    stage_net_emissions: list[Decimal] = []
    for row_number, (stage, row) in enumerate(zip(EXPECTED_STAGES, rows, strict=True), 2):
        net_emissions = Decimal(row[3].replace(",", ""))
        value = Decimal(row[4].replace(",", ""))
        if stage != "TOTAL":
            stage_values.append(value)
            stage_net_emissions.append(net_emissions)
        page = 2
        if stage == "TOTAL":
            category = "product_carbon_footprint"
            boundary = "cradle-to-gate"
            modules = ("A1", "A2", "A3")
            applicability = (
                f"{product_en}; specification {specification}; per tonne of product; "
                f"{boundary_text}; accounting period {accounting_period}"
            )
            name_cn = f"{pair.product_name_cn}产品碳足迹"
            name_en = f"{product_en} product carbon footprint"
        else:
            category = "lifecycle_stage_carbon_footprint"
            boundary = stage
            modules = (stage,)
            subprocess = row[2]
            applicability = (
                f"{product_en}; lifecycle stage {stage}; {subprocess}; per tonne of product; "
                f"accounting period {accounting_period}"
            )
            name_cn = f"{pair.product_name_cn} {stage}阶段碳足迹"
            name_en = f"{product_en} {stage} lifecycle-stage carbon footprint"
        numeric_verified = normalized_token(f"{float(value):,.2f}") in compact_pdf
        factors.append(
            ExtractedFactor(
                factor_id=f"TD-{pair.report_id}-{stage}",
                report_id=pair.report_id,
                factor_name_cn=name_cn,
                factor_name_en=name_en,
                material_name_cn=pair.product_name_cn,
                category=category,
                stage=stage,
                value=float(value),
                unit="kgCO2e/t",
                source=source,
                source_version=source_version,
                source_year=year,
                boundary=boundary,
                boundary_modules=modules,
                applicability=applicability,
                certificate_no=certificate_no,
                accounting_period=accounting_period,
                docx_path=pair.docx_path,
                docx_sha256=pair.docx_sha256,
                docx_evidence=(
                    "paragraph containing Product Carbon Footprint per Unit; "
                    f"Table 1 row {row_number}, Carbon Footprint column"
                    if stage == "TOTAL"
                    else f"Table 1 row {row_number}, Carbon Footprint column"
                ),
                pdf_path=pair.pdf_path,
                pdf_sha256=pair.pdf_sha256,
                pdf_evidence=f"page {page}, lifecycle table row {stage}",
                cross_format_verified=bool(product_verified and numeric_verified),
            )
        )

    total_row_value = Decimal(str(factors[-1].value))
    if abs(sum(stage_values) - total_row_value) > Decimal("0.02"):
        findings.append(
            QualityFinding(
                pair.report_id,
                "error",
                "FOOTPRINT_STAGE_SUM_MISMATCH",
                f"A1+A2+A3={sum(stage_values)} but total={total_row_value}",
                "DOCX Table 1 rows 2-5; PDF page 2 lifecycle table",
            )
        )
    total_net = Decimal(rows[-1][3].replace(",", ""))
    if abs(sum(stage_net_emissions) - total_net) > Decimal("0.02"):
        findings.append(
            QualityFinding(
                pair.report_id,
                "error",
                "NET_EMISSIONS_SUM_MISMATCH",
                f"A1+A2+A3={sum(stage_net_emissions)} tCO2 but total={total_net} tCO2",
                "DOCX Table 1 rows 2-5; PDF page 2 lifecycle table",
            )
        )
    if abs(total_value - float(total_row_value)) > 0.02:
        findings.append(
            QualityFinding(
                pair.report_id,
                "error",
                "PAGE_TOTAL_MISMATCH",
                f"page 1 total={total_value} but page 2 total={total_row_value}",
                "DOCX page-1 total paragraph and Table 1 total row; PDF pages 1-2",
            )
        )
    for factor in factors:
        if not factor.cross_format_verified:
            findings.append(
                QualityFinding(
                    pair.report_id,
                    "warning",
                    "CROSS_FORMAT_TEXT_CHECK_FAILED",
                    f"DOCX factor {factor.factor_id} was not found verbatim in normalized PDF text",
                    factor.pdf_evidence,
                )
            )
    return tuple(factors), tuple(findings)


def catalog_payload(factors: tuple[ExtractedFactor, ...]) -> dict[str, Any]:
    records = []
    for factor in factors:
        base_name = factor.factor_name_en.split(" product carbon footprint", 1)[0]
        base_name = base_name.split(" A", 1)[0]
        records.append(
            {
                "record_id": factor.factor_id,
                "category": "epd_indicator",
                "code": factor.factor_id,
                "name": base_name,
                "aliases": [factor.material_name_cn],
                "primary_value": factor.value,
                "primary_unit": factor.unit,
                "source": factor.source,
                "source_id": factor.certificate_no,
                "source_version": factor.source_version,
                "document_status": "PUBLISHED",
                "source_type": "epd",
                "year": factor.source_year,
                "boundary": factor.boundary,
                "boundary_modules": list(factor.boundary_modules),
                "indicator": "GWP-total",
                "declared_product": base_name,
                "scope": factor.applicability,
                "source_document_locator": factor.pdf_path,
                "source_document_sha256": factor.pdf_sha256,
                "page": "2",
                "table": "Lifecycle Process",
                "row": factor.stage,
                "notes": factor.pdf_evidence,
            }
        )
    record_sha = hashlib.sha256(canonical_json_bytes(records)).hexdigest()
    return {
        "catalog_version": "true-data-read-only-snapshot/v1",
        "database": {"name": "read-only-report-extract", "sha256": record_sha},
        "records": records,
    }


def blind_cases(factors: tuple[ExtractedFactor, ...]) -> list[dict[str, Any]]:
    all_ids = {factor.factor_id for factor in factors}
    cases: list[dict[str, Any]] = []
    for factor in factors:
        base_name = factor.factor_name_en.split(" product carbon footprint", 1)[0]
        base_name = base_name.split(" A", 1)[0]
        cases.append(
            {
                "schema_version": "cfr-true-data-acceptance/v1",
                "case_id": f"CASE-{factor.factor_id}",
                "case_type": "extracted_factor",
                "factor_id": factor.factor_id,
                "correct_material_entity": base_name,
                "request": {
                    "material_name": base_name,
                    "quantity": 1.0,
                    "quantity_unit": "t",
                    "year": factor.source_year,
                    "boundary": factor.boundary,
                    "target_factor_unit": factor.unit,
                    "top_k": 5,
                },
                "acceptable_candidates": [factor.factor_id],
                "forbidden_candidates": sorted(all_ids - {factor.factor_id}),
                "expected_more_input": False,
                "expected_abstention": False,
                "answer_basis": (
                    "Exact declared product, accounting year, lifecycle boundary, unit, "
                    "and paired DOCX/PDF evidence must agree."
                ),
            }
        )

    controls = (
        ("CTRL-SLIDING-GATE", "Sliding Gate", True),
        ("CTRL-SILICA-BRICK", "Silica Brick", True),
        ("CTRL-PRECAST", "Precast Shape", True),
        ("CTRL-WEAR-CASTABLE", "Wear-Resistant Castable", True),
        ("CTRL-ALUMINA-RAW", "Alumina raw material", False),
        ("CTRL-ALUMINIUM-METAL", "Primary aluminium metal", False),
        ("CTRL-STEEL-FIBRE-RAW", "Steel fibre raw material", False),
        ("CTRL-NATURAL-GAS", "Natural gas", False),
    )
    for case_id, material_name, more_input in controls:
        cases.append(
            {
                "schema_version": "cfr-true-data-acceptance/v1",
                "case_id": case_id,
                "case_type": "ambiguity_control" if more_input else "abstention_control",
                "factor_id": None,
                "correct_material_entity": material_name,
                "request": {
                    "material_name": material_name,
                    "quantity": 1.0,
                    "quantity_unit": "t",
                    "boundary": "cradle-to-gate",
                    "target_factor_unit": "kgCO2e/t",
                    "top_k": 5,
                },
                "acceptable_candidates": [],
                "forbidden_candidates": sorted(all_ids),
                "expected_more_input": more_input,
                "expected_abstention": not more_input,
                "answer_basis": (
                    "Ambiguous family label requires clarification."
                    if more_input
                    else "The extracted report snapshot contains no exact raw-material factor."
                ),
            }
        )
    return cases


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def write_factor_csvs(output_dir: Path, factors: tuple[ExtractedFactor, ...], cases: list[dict[str, Any]]) -> None:
    import csv

    cases_by_factor = {case["factor_id"]: case for case in cases if case["factor_id"]}
    target = output_dir / "factor_test_tables"
    target.mkdir(parents=True, exist_ok=True)
    for factor in factors:
        case = cases_by_factor[factor.factor_id]
        rows = [
            ("factor_id", factor.factor_id),
            ("factor_name_cn", factor.factor_name_cn),
            ("factor_name_en", factor.factor_name_en),
            ("category", factor.category),
            ("value", factor.value),
            ("unit", factor.unit),
            ("source", factor.source),
            ("source_version", factor.source_version),
            ("source_year", factor.source_year),
            ("boundary", factor.boundary),
            ("applicability", factor.applicability),
            ("correct_material_entity", case["correct_material_entity"]),
            ("acceptable_candidates", "|".join(case["acceptable_candidates"])),
            ("forbidden_candidate_rule", "any candidate not listed as acceptable"),
            ("expected_more_input", case["expected_more_input"]),
            ("expected_abstention", case["expected_abstention"]),
            ("docx_evidence", f"{factor.docx_path} :: {factor.docx_evidence}"),
            ("pdf_evidence", f"{factor.pdf_path} :: {factor.pdf_evidence}"),
        ]
        with (target / f"{factor.factor_id}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("field", "value"))
            writer.writerows(rows)


def evidence_coverage(candidate: object) -> float:
    source = candidate.source
    fields = (
        source.source_id,
        source.provider,
        source.locator,
        source.factor_unit,
        source.factor_kind.value,
        source.indicator,
        source.declared_product,
        source.boundary,
        source.source_document_sha256,
        source.page,
        source.table,
        source.row,
    )
    return sum(value is not None and str(value).strip() != "" for value in fields) / len(fields)


def more_input_is_correct(status: str, expected_more_input: bool) -> bool:
    if status == ResolutionStatus.ERROR.value:
        return False
    return (status == ResolutionStatus.MORE_INPUT_NEEDED.value) == expected_more_input


def aggregate_acceptance_metrics(
    results: list[dict[str, Any]],
    *,
    preset_sha_before: str,
    preset_sha_after: str,
    catalog_record_anchor: str,
) -> dict[str, Any]:
    retrieval = [result for result in results if result["recall_at_5"] is not None]
    candidate_count = sum(int(result["candidate_count"]) for result in results)
    wrong_count = sum(int(result["wrong_candidate_count"]) for result in results)
    abstentions = [result for result in results if result["abstention_correct"] is not None]
    evidence_sum = sum(float(result["evidence_coverage_sum"]) for result in results)
    evidence_count = sum(int(result["evidence_candidate_count"]) for result in results)
    return {
        "case_count": len(results),
        "extracted_factor_case_count": len(retrieval),
        "recall_at_5": (
            sum(bool(result["recall_at_5"]) for result in retrieval) / len(retrieval)
            if retrieval
            else None
        ),
        "wrong_candidate_rate": wrong_count / candidate_count if candidate_count else 0.0,
        "correct_abstention_rate": (
            sum(bool(result["abstention_correct"]) for result in abstentions) / len(abstentions)
            if abstentions
            else None
        ),
        "more_input_reasonableness_rate": (
            sum(bool(result["more_input_correct"]) for result in results) / len(results)
            if results
            else None
        ),
        "evidence_completeness_rate": evidence_sum / evidence_count if evidence_count else None,
        "wrong_candidate_count": wrong_count,
        "returned_candidate_count": candidate_count,
        "preset_sha256_before": preset_sha_before,
        "preset_sha256_after": preset_sha_after,
        "catalog_snapshot_sha256": catalog_record_anchor,
    }


async def run_cases(
    catalog: Mapping[str, Any], cases: list[dict[str, Any]], preset_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before_sha = sha256_file(preset_path)
    database = catalog["database"]

    def fetch_json(_endpoint: str) -> Mapping[str, Any]:
        return catalog

    repository = HttpCatalogFactorRepository(
        endpoint="fixture://true-data-read-only-snapshot",
        expected_sha256=str(database["sha256"]),
        fetch_json=fetch_json,
    )
    engine = A1FactorResolutionEngine(local_retrieval=repository)
    results: list[dict[str, Any]] = []
    for case in cases:
        request = dict(case["request"])
        request["request_id"] = f"true-data:{case['case_id']}"
        started = datetime.now(UTC)
        try:
            recommendation = await engine.resolve(request)
            candidates = (*recommendation.candidates, *recommendation.reviewable_candidates)
            observed = list(dict.fromkeys(candidate.source.source_id for candidate in candidates))
            coverages = [evidence_coverage(candidate) for candidate in candidates[:5]]
            trace = recommendation.trace.explain() if recommendation.trace else None
            error = None
            status = recommendation.status.value
        except Exception as exc:  # a complete acceptance run must retain case failures
            observed, coverages, trace = [], [], None
            error = f"{type(exc).__name__}: {exc}"
            status = ResolutionStatus.ERROR.value
        acceptable = set(case["acceptable_candidates"])
        forbidden = set(case["forbidden_candidates"])
        results.append(
            {
                "case_id": case["case_id"],
                "case_type": case["case_type"],
                "factor_id": case["factor_id"],
                "expected_more_input": case["expected_more_input"],
                "expected_abstention": case["expected_abstention"],
                "observed_status": status,
                "observed_top_ids": observed[:5],
                "recall_at_5": bool(acceptable & set(observed[:5])) if acceptable else None,
                "wrong_candidate_count": len(forbidden & set(observed[:5])),
                "candidate_count": len(observed[:5]),
                "more_input_correct": more_input_is_correct(
                    status, bool(case["expected_more_input"])
                ),
                "abstention_correct": (
                    not observed
                    and status
                    in {
                        ResolutionStatus.UNRESOLVED.value,
                        ResolutionStatus.SUPPLIER_DATA_REQUIRED.value,
                        ResolutionStatus.PROCESS_MODEL_REQUIRED.value,
                    }
                    if case["expected_abstention"]
                    else None
                ),
                "evidence_completeness": sum(coverages) / len(coverages) if coverages else None,
                "evidence_coverage_sum": sum(coverages),
                "evidence_candidate_count": len(coverages),
                "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "error": error,
                "trace": trace,
            }
        )
    after_sha = sha256_file(preset_path)
    if before_sha != after_sha:
        raise RuntimeError("blind-test preset changed during execution")

    metrics = aggregate_acceptance_metrics(
        results,
        preset_sha_before=before_sha,
        preset_sha_after=after_sha,
        catalog_record_anchor=str(database["sha256"]),
    )
    return results, metrics


def build_acceptance(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs = source_pairs(source_dir)
    all_factors: list[ExtractedFactor] = []
    all_findings: list[QualityFinding] = []
    for pair in pairs:
        factors, findings = extract_pair(pair)
        all_factors.extend(factors)
        all_findings.extend(findings)
    factors_tuple = tuple(all_factors)
    if len(factors_tuple) != 72:
        raise ValueError(f"expected 72 extracted factors, found {len(factors_tuple)}")

    catalog = catalog_payload(factors_tuple)
    cases = blind_cases(factors_tuple)
    manifest_path = output_dir / "blind_test_manifest.jsonl"
    write_json(output_dir / "source_manifest.json", [asdict(pair) for pair in pairs])
    write_json(output_dir / "extracted_factors.json", [asdict(factor) for factor in factors_tuple])
    write_json(output_dir / "source_quality_findings.json", [asdict(item) for item in all_findings])
    write_json(output_dir / "isolated_catalog_snapshot.json", catalog)
    write_jsonl(manifest_path, cases)
    write_factor_csvs(output_dir, factors_tuple, cases)
    frozen_sha = sha256_file(manifest_path)
    (output_dir / "blind_test_manifest.sha256").write_text(
        f"{frozen_sha}  {manifest_path.name}\n", encoding="ascii"
    )
    results, metrics = asyncio.run(run_cases(catalog, cases, manifest_path))
    write_json(output_dir / "cfr_results.json", results)
    write_json(output_dir / "metrics.json", metrics)
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = None
    try:
        package_version = importlib.metadata.version("carbon-factor-resolver")
    except importlib.metadata.PackageNotFoundError:
        package_version = "unknown"
    run_manifest = {
        "schema_version": "cfr-true-data-acceptance-run/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "package_version": package_version,
        "source_directory": str(source_dir),
        "source_manifest_sha256": sha256_file(output_dir / "source_manifest.json"),
        "extracted_factors_sha256": sha256_file(output_dir / "extracted_factors.json"),
        "catalog_snapshot_sha256": sha256_file(output_dir / "isolated_catalog_snapshot.json"),
        "catalog_record_anchor": metrics["catalog_snapshot_sha256"],
        "blind_test_manifest_sha256": frozen_sha,
        "blind_test_manifest_verified_unchanged": (
            metrics["preset_sha256_before"] == metrics["preset_sha256_after"]
        ),
        "formal_factor_database_written": False,
        "source_files_written": False,
    }
    write_json(output_dir / "run_manifest.json", run_manifest)
    return {
        "source_pair_count": len(pairs),
        "factor_count": len(factors_tuple),
        "case_count": len(cases),
        "finding_count": len(all_findings),
        "metrics": metrics,
        "preset_sha256": frozen_sha,
        "output_dir": str(output_dir.resolve()),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("source_dir", type=Path)
    value.add_argument("output_dir", type=Path)
    return value


def main() -> None:
    args = parser().parse_args()
    summary = build_acceptance(args.source_dir.resolve(), args.output_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
