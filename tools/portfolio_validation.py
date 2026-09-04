"""Developer-only portfolio evaluator for CFR Challenge Set V1.

The evaluator is deliberately outside the production runtime.  It compares two
simple retrieval baselines with the unmodified CarbonFactorResolver pipeline and
writes only to an explicit output directory.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Mapping, Sequence

from a1_factor_engine import A1FactorResolutionEngine, ResolutionStatus
from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.serialization import serialize_trace
from a1_factor_engine.units import UnitConversionError, parse_factor_unit

SCHEMA_VERSION = "portfolio-challenge/v1"
ABSTENTION_STATUSES = {
    ResolutionStatus.UNRESOLVED.value,
    ResolutionStatus.SUPPLIER_DATA_REQUIRED.value,
    ResolutionStatus.PROCESS_MODEL_REQUIRED.value,
}


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^0-9a-z\u3400-\u9fff]+", " ", text).split())


def sha256_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def sha256_text_file(path: Path) -> str:
    """Hash UTF-8 text with canonical LF endings for cross-platform evidence."""

    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ChallengeCase:
    case_id: str
    category: str
    request: Mapping[str, Any]
    acceptable_ids: tuple[str, ...]
    forbidden_ids: tuple[str, ...]
    expected_decision: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ChallengeCase":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported portfolio challenge schema")
        decision = str(value.get("expected_decision", ""))
        if decision not in {"retrieve", "more_input", "abstain"}:
            raise ValueError(f"invalid expected_decision: {decision}")
        return cls(
            case_id=str(value["case_id"]), category=str(value["category"]),
            request=dict(value["request"]),
            acceptable_ids=tuple(map(str, value.get("acceptable_ids", ()))),
            forbidden_ids=tuple(map(str, value.get("forbidden_ids", ()))),
            expected_decision=decision,
        )


def load_cases(path: Path) -> tuple[ChallengeCase, ...]:
    cases = tuple(
        ChallengeCase.from_mapping(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("portfolio case IDs must be unique")
    return cases


def combined_catalog(paths: Sequence[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records.extend(dict(item) for item in payload["records"])
    ids = [str(record["record_id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("portfolio catalogue record IDs must be unique")
    digest = sha256_json(records)
    return {
        "catalog_version": "portfolio-combined-public-synthetic/v1",
        "database": {"name": "portfolio-combined-public-synthetic", "sha256": digest},
        "records": records,
    }


def record_terms(record: Mapping[str, Any]) -> tuple[str, ...]:
    values = [record.get("name", ""), *(record.get("aliases") or ())]
    return tuple(dict.fromkeys(term for value in values if (term := normalized(value))))


def exact_alias(record: Mapping[str, Any], query: str) -> float:
    return 1.0 if query in record_terms(record) else 0.0


def lexical(record: Mapping[str, Any], query: str) -> float:
    query_tokens = set(query.split())
    scores: list[float] = []
    for term in record_terms(record):
        term_tokens = set(term.split())
        overlap = len(query_tokens & term_tokens) / max(1, len(query_tokens | term_tokens))
        scores.append(0.75 * SequenceMatcher(None, query, term).ratio() + 0.25 * overlap)
    return max(scores, default=0.0)


def baseline_candidates(
    case: ChallengeCase, records: Sequence[Mapping[str, Any]], method: str, top_k: int = 5
) -> tuple[str, ...]:
    query = normalized(case.request.get("material_name"))
    scorer = exact_alias if method == "exact_alias" else lexical
    scored = [(scorer(record, query), str(record["record_id"])) for record in records]
    if method == "exact_alias":
        scored = [item for item in scored if item[0] == 1.0]
    else:
        scored = [item for item in scored if item[0] > 0.0]
    return tuple(item[1] for item in sorted(scored, key=lambda item: (-item[0], item[1]))[:top_k])


def predicted_decision(candidate_ids: Sequence[str], observed_status: str | None = None) -> str:
    if observed_status == ResolutionStatus.ERROR.value:
        return "error"
    if observed_status == ResolutionStatus.MORE_INPUT_NEEDED.value:
        return "more_input"
    if not candidate_ids:
        return "abstain"
    return "retrieve"


def _rate(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def metric_prf(expected: Sequence[bool], predicted: Sequence[bool]) -> dict[str, float | int | None]:
    tp = sum(e and p for e, p in zip(expected, predicted, strict=True))
    fp = sum(not e and p for e, p in zip(expected, predicted, strict=True))
    fn = sum(e and not p for e, p in zip(expected, predicted, strict=True))
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "true_positive": tp, "false_positive": fp, "false_negative": fn,
        "expected_positive": sum(expected), "predicted_positive": sum(predicted),
        "precision": precision, "recall": recall, "f1": f1,
    }


def aggregate(results: Sequence[Mapping[str, Any]], records_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    retrieval = [row for row in results if row["expected_decision"] == "retrieve"]
    returned = [(row, candidate) for row in results for candidate in row["observed_ids"]]
    correct_returned = sum(
        row["expected_decision"] == "retrieve" and candidate in row["acceptable_ids"]
        for row, candidate in returned
    )
    forbidden_returned = sum(candidate in row["forbidden_ids"] for row, candidate in returned)
    unlisted_returned = len(returned) - correct_returned - forbidden_returned
    ranks = []
    for row in retrieval:
        acceptable = set(row["acceptable_ids"])
        rank = next((index for index, item in enumerate(row["observed_ids"], 1) if item in acceptable), None)
        ranks.append(rank)
    boundary_violations = 0
    subject_violations = 0
    unit_violations = 0
    for row in results:
        request = row["request"]
        for candidate_id in row["observed_ids"]:
            if candidate_id not in records_by_id:
                raise ValueError(f"unknown candidate ID in evaluation output: {candidate_id}")
            record = records_by_id[candidate_id]
            if request.get("subject_type") and record.get("subject_type") != request.get("subject_type"):
                subject_violations += 1
            requested_boundary = str(request.get("boundary") or "")
            observed_boundary = str(record.get("boundary") or "")
            if requested_boundary and observed_boundary != requested_boundary:
                boundary_violations += 1
            requested_factor_unit = str(request.get("target_factor_unit") or "")
            observed_factor_unit = str(record.get("factor_unit") or "")
            if requested_factor_unit and observed_factor_unit:
                try:
                    requested_dimension = parse_factor_unit(requested_factor_unit).activity_unit.dimension
                    observed_dimension = parse_factor_unit(observed_factor_unit).activity_unit.dimension
                    unit_violations += requested_dimension != observed_dimension
                except UnitConversionError:
                    unit_violations += 1
    abstain = metric_prf(
        [row["expected_decision"] == "abstain" for row in results],
        [row["observed_decision"] == "abstain" for row in results],
    )
    more_input = metric_prf(
        [row["expected_decision"] == "more_input" for row in results],
        [row["observed_decision"] == "more_input" for row in results],
    )
    latencies = sorted(float(row["latency_ms"]) for row in results)

    def percentile(q: float) -> float:
        if not latencies:
            return 0.0
        return latencies[min(len(latencies) - 1, math.ceil(q * len(latencies)) - 1)]

    errors = sum(row["observed_decision"] == "error" for row in results)
    decision_correct = sum(
        row["observed_decision"] == row["expected_decision"] for row in results
    )
    returned_count = len(returned)
    retrieval_count = len(retrieval)
    return {
        "case_count": len(results),
        "retrieval_case_count": retrieval_count,
        "returned_candidate_count": returned_count,
        "correct_candidate_count": correct_returned,
        "wrong_candidate_count": returned_count - correct_returned,
        "forbidden_candidate_count": forbidden_returned,
        "unlisted_candidate_count": unlisted_returned,
        "top_1_correct_count": sum(rank == 1 for rank in ranks),
        "recall_at_5_correct_count": sum(rank is not None and rank <= 5 for rank in ranks),
        "top_1_accuracy": _rate(sum(rank == 1 for rank in ranks), retrieval_count),
        "recall_at_5": _rate(sum(rank is not None and rank <= 5 for rank in ranks), retrieval_count),
        "mrr": _rate(sum((1 / rank for rank in ranks if rank), 0.0), retrieval_count),
        "wrong_candidate_rate": _rate(returned_count - correct_returned, returned_count),
        "boundary_violation_count": boundary_violations,
        "boundary_violation_rate": _rate(boundary_violations, returned_count),
        "subject_violation_count": subject_violations,
        "subject_violation_rate": _rate(subject_violations, returned_count),
        "unit_violation_count": unit_violations,
        "unit_violation_rate": _rate(unit_violations, returned_count),
        "error_count": errors,
        "error_rate": _rate(errors, len(results)),
        "decision_correct_count": decision_correct,
        "decision_accuracy": _rate(decision_correct, len(results)),
        "abstention": abstain,
        "more_input": more_input,
        "p50_latency_ms": median(latencies) if latencies else 0.0,
        "p95_latency_ms": percentile(0.95),
        "p99_latency_ms": percentile(0.99),
    }


def portfolio_quality_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fail-closed release gate separately from execution success."""

    more_input = metrics.get("more_input", {})
    more_input_recall = more_input.get("recall") if isinstance(more_input, Mapping) else None
    checks = {
        "decision_accuracy_at_least_95_percent": bool(
            metrics.get("decision_accuracy") is not None and metrics["decision_accuracy"] >= 0.95
        ),
        "top_1_at_least_90_percent": bool(
            metrics.get("top_1_accuracy") is not None and metrics["top_1_accuracy"] >= 0.90
        ),
        "recall_at_5_at_least_95_percent": bool(
            metrics.get("recall_at_5") is not None and metrics["recall_at_5"] >= 0.95
        ),
        "more_input_positive_recall_at_least_90_percent": bool(
            more_input_recall is not None and more_input_recall >= 0.90
        ),
        "wrong_candidate_rate_at_most_5_percent": bool(
            metrics.get("wrong_candidate_rate") is not None
            and metrics["wrong_candidate_rate"] <= 0.05
        ),
        "zero_forbidden_candidate_escape": metrics.get("forbidden_candidate_count") == 0,
        "zero_boundary_violation": metrics.get("boundary_violation_count") == 0,
        "zero_subject_violation": metrics.get("subject_violation_count") == 0,
        "zero_unit_dimension_violation": metrics.get("unit_violation_count") == 0,
        "zero_errors": metrics.get("error_count") == 0,
    }
    return {
        "execution_status": "completed",
        "quality_status": "PASS" if all(checks.values()) else "FAIL",
        "hard_gates_pass": all(checks.values()),
        "checks": checks,
    }


def dynamic_findings(gate: Mapping[str, Any]) -> list[dict[str, str]]:
    """Create findings from this run's failed checks; never carry stale prose."""

    checks = gate.get("checks", {})
    if not isinstance(checks, Mapping):
        return [{
            "id": "CFR-PV-GATE-MISSING",
            "severity": "CRITICAL",
            "status": "OPEN",
            "summary": "Portfolio quality-gate checks are missing from this run.",
        }]
    severity = {
        "decision_accuracy_at_least_95_percent": "HIGH",
        "top_1_at_least_90_percent": "HIGH",
        "recall_at_5_at_least_95_percent": "HIGH",
        "more_input_positive_recall_at_least_90_percent": "HIGH",
        "wrong_candidate_rate_at_most_5_percent": "HIGH",
        "zero_forbidden_candidate_escape": "CRITICAL",
        "zero_boundary_violation": "CRITICAL",
        "zero_subject_violation": "CRITICAL",
        "zero_unit_dimension_violation": "CRITICAL",
        "zero_errors": "CRITICAL",
    }
    return [
        {
            "id": f"CFR-PV-{name.upper()}",
            "severity": severity[name],
            "status": "OPEN",
            "summary": f"Current run failed quality check: {name}.",
        }
        for name, passed in checks.items()
        if passed is not True
    ]


async def run_full_cfr(cases: Sequence[ChallengeCase], catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    repository = HttpCatalogFactorRepository(
        endpoint="fixture://portfolio-combined",
        expected_sha256=str(catalog["database"]["sha256"]),
        fetch_json=lambda _endpoint: catalog,
    )
    engine = A1FactorResolutionEngine(local_retrieval=repository)
    results: list[dict[str, Any]] = []
    for case in cases:
        request = dict(case.request)
        request["request_id"] = f"portfolio:{case.case_id}"
        request.setdefault("top_k", 5)
        started = perf_counter()
        try:
            recommendation = await engine.resolve(request)
            candidates = (*recommendation.candidates, *recommendation.reviewable_candidates)
            ids = tuple(dict.fromkeys(item.source.source_id for item in candidates))[:5]
            status = recommendation.status.value
            error = None
            trace = serialize_trace(recommendation.trace) if recommendation.trace else None
        except Exception as exc:  # retain failures in an auditable offline run
            ids, status, error, trace = (
                (), ResolutionStatus.ERROR.value, f"{type(exc).__name__}: {exc}", None
            )
        results.append({
            "case_id": case.case_id, "category": case.category, "request": dict(case.request),
            "acceptable_ids": list(case.acceptable_ids), "forbidden_ids": list(case.forbidden_ids),
            "expected_decision": case.expected_decision, "observed_ids": list(ids),
            "observed_status": status, "observed_decision": predicted_decision(ids, status),
            "latency_ms": (perf_counter() - started) * 1000, "error": error, "trace": trace,
        })
    return results


def run_baseline(cases: Sequence[ChallengeCase], records: Sequence[Mapping[str, Any]], method: str) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        started = perf_counter()
        ids = baseline_candidates(case, records, method)
        results.append({
            "case_id": case.case_id, "category": case.category, "request": dict(case.request),
            "acceptable_ids": list(case.acceptable_ids), "forbidden_ids": list(case.forbidden_ids),
            "expected_decision": case.expected_decision, "observed_ids": list(ids),
            "observed_status": None, "observed_decision": predicted_decision(ids),
            "latency_ms": (perf_counter() - started) * 1000, "error": None, "trace": None,
        })
    return results


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.run(
            ("git", *args), check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _candidate_classification(row: Mapping[str, Any], candidate_id: str) -> str:
    if row["expected_decision"] == "retrieve" and candidate_id in row["acceptable_ids"]:
        return "acceptable"
    if candidate_id in row["forbidden_ids"]:
        return "forbidden"
    return "unlisted"


def _svg_bar_chart(title: str, values: Sequence[tuple[str, float]], *, percent: bool = True) -> str:
    width, height = 760, 100 + 52 * len(values)
    rows = []
    for index, (label, value) in enumerate(values):
        y = 70 + index * 52
        normalized_value = max(0.0, min(1.0, value)) if percent else max(0.0, value)
        bar_width = normalized_value * 470 if percent else min(normalized_value, 470)
        display = f"{value:.1%}" if percent else f"{value:.2f}"
        rows.append(
            f'<text x="20" y="{y + 17}" font-size="14">{label}</text>'
            f'<rect x="220" y="{y}" width="470" height="24" rx="4" fill="#e8edf4"/>'
            f'<rect x="220" y="{y}" width="{bar_width:.2f}" height="24" rx="4" fill="#246bce"/>'
            f'<text x="700" y="{y + 17}" font-size="13">{display}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>'
        f'<text x="20" y="34" font-size="22" font-weight="700">{title}</text>{"".join(rows)}</svg>'
    )


def _format_rate(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def _report(payload: Mapping[str, Any], *, chinese: bool) -> str:
    runs = payload["runs"]
    gate = payload["quality_gate"]
    lines = [
        "# CFR 作品集验证报告" if chinese else "# CFR Portfolio Validation Report",
        "",
        (
            "本报告来自开发期离线 QA，不批准任何正式因子，也不代表生产准入。"
            if chinese else
            "This developer-only offline QA run approves no formal factor and is not a production-admission decision."
        ),
        "",
        (
            f"评测进程：**{gate['execution_status']}**；质量门禁：**{gate['quality_status']}**。"
            if chinese else
            f"Evaluation execution: **{gate['execution_status']}**; quality gate: **{gate['quality_status']}**."
        ),
        "",
        "| Method | Decision | Top-1 | Recall@5 | Wrong candidates | Boundary | Subject | Unit | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, run in runs.items():
        metric = run["metrics"]
        lines.append(
            f"| {name} | {_format_rate(metric['decision_accuracy'])} | "
            f"{_format_rate(metric['top_1_accuracy'])} | {_format_rate(metric['recall_at_5'])} | "
            f"{_format_rate(metric['wrong_candidate_rate'])} "
            f"({metric['wrong_candidate_count']}/{metric['returned_candidate_count']}) | "
            f"{_format_rate(metric['boundary_violation_rate'])} | "
            f"{_format_rate(metric['subject_violation_rate'])} | "
            f"{_format_rate(metric['unit_violation_rate'])} | "
            f"{metric['error_count']}/{metric['case_count']} |"
        )
    lines.extend([
        "",
        "## " + ("数据限制" if chinese else "Dataset limitations"),
        "",
        (
            f"挑战集含 {payload['case_count']} 个 case、{payload['unique_request_count']} 个唯一查询；"
            f"它是公开合成目录上的作品集回归集，不是未知业务查询泛化证明。"
            if chinese else
            f"The challenge contains {payload['case_count']} cases and {payload['unique_request_count']} unique queries. "
            "It is a portfolio regression set over a public synthetic catalogue, not proof of unseen-query generalization."
        ),
        "",
        (
            "Full CFR 的安全指标按全部返回候选计算；MORE_INPUT/拒答样例返回的未列候选也计错。"
            if chinese else
            "Full-CFR safety metrics score every returned candidate; unlisted candidates on MORE_INPUT or abstention cases count as wrong."
        ),
        "",
        "## " + ("本次动态发现" if chinese else "Current-run findings"),
        "",
    ])
    findings = payload.get("known_findings", ())
    if findings:
        for finding in findings:
            lines.append(f"- **{finding['severity']}** `{finding['id']}`: {finding['summary']}")
    else:
        lines.append("- " + ("本次门禁没有未解决发现。" if chinese else "No unresolved gate finding in this run."))
    lines.extend((
        "",
        (
            "脚本完成不等于质量通过；发布流程必须使用质量门禁退出码。"
            if chinese else
            "Successful script execution is not a quality PASS; release automation must enforce the quality-gate exit code."
        ),
    ))
    return "\n".join(lines) + "\n"


def write_outputs(output_dir: Path, payload: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "portfolio_validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "portfolio_validation.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "method", "case_id", "category", "expected_decision", "observed_decision",
            "observed_status", "candidate_id", "candidate_rank", "classification", "error", "latency_ms",
        ))
        writer.writeheader()
        for method, run in payload["runs"].items():
            for row in run["results"]:
                candidate_ids = row["observed_ids"] or (None,)
                for rank, candidate_id in enumerate(candidate_ids, 1):
                    writer.writerow({
                        "method": method, "case_id": row["case_id"], "category": row["category"],
                        "expected_decision": row["expected_decision"],
                        "observed_decision": row["observed_decision"], "observed_status": row["observed_status"],
                        "candidate_id": candidate_id or "", "candidate_rank": rank if candidate_id else "",
                        "classification": _candidate_classification(row, candidate_id) if candidate_id else "none",
                        "error": row["error"], "latency_ms": f"{row['latency_ms']:.6f}",
                    })
    with (output_dir / "portfolio_traces.jsonl").open("w", encoding="utf-8") as handle:
        for row in payload["runs"]["full_cfr"]["results"]:
            handle.write(json.dumps({"case_id": row["case_id"], "trace": row["trace"]}, ensure_ascii=False) + "\n")
    (output_dir / "REPORT_EN.md").write_text(_report(payload, chinese=False), encoding="utf-8")
    (output_dir / "REPORT_ZH.md").write_text(_report(payload, chinese=True), encoding="utf-8")
    metrics = {name: run["metrics"] for name, run in payload["runs"].items()}
    (output_dir / "retrieval_quality.svg").write_text(_svg_bar_chart(
        "Retrieval quality",
        [(f"{name} Top-1", metric["top_1_accuracy"] or 0.0) for name, metric in metrics.items()] +
        [(f"{name} Recall@5", metric["recall_at_5"] or 0.0) for name, metric in metrics.items()],
    ), encoding="utf-8")
    (output_dir / "safety_rates.svg").write_text(_svg_bar_chart(
        "Safety and error rates",
        [(f"{name} wrong", metric["wrong_candidate_rate"] or 0.0) for name, metric in metrics.items()] +
        [(f"{name} boundary", metric["boundary_violation_rate"] or 0.0) for name, metric in metrics.items()] +
        [(f"{name} subject", metric["subject_violation_rate"] or 0.0) for name, metric in metrics.items()] +
        [(f"{name} unit", metric["unit_violation_rate"] or 0.0) for name, metric in metrics.items()],
    ), encoding="utf-8")
    latency_max = max(metric["p99_latency_ms"] for metric in metrics.values()) or 1.0
    (output_dir / "latency_percentiles.svg").write_text(_svg_bar_chart(
        "Latency percentiles (relative to max p99)",
        [(f"{name} p{percentile}", metric[f"p{percentile}_latency_ms"] / latency_max)
         for name, metric in metrics.items() for percentile in (50, 95, 99)],
    ), encoding="utf-8")


async def evaluate(challenge_path: Path, catalog_paths: Sequence[Path], output_dir: Path) -> dict[str, Any]:
    cases = load_cases(challenge_path)
    catalog = combined_catalog(catalog_paths)
    records = catalog["records"]
    records_by_id = {str(record["record_id"]): record for record in records}
    catalog_ids = set(records_by_id)
    for case in cases:
        if set(case.acceptable_ids) & set(case.forbidden_ids):
            raise ValueError(f"case {case.case_id} has overlapping acceptable/forbidden labels")
        unknown = (set(case.acceptable_ids) | set(case.forbidden_ids)) - catalog_ids
        if unknown:
            raise ValueError(f"case {case.case_id} references unknown catalogue IDs: {sorted(unknown)}")
    runs: dict[str, Any] = {}
    for method in ("exact_alias", "lexical"):
        results = run_baseline(cases, records, method)
        runs[method] = {"metrics": aggregate(results, records_by_id), "results": results}
    full_results = await run_full_cfr(cases, catalog)
    runs["full_cfr"] = {"metrics": aggregate(full_results, records_by_id), "results": full_results}
    quality_gate = portfolio_quality_gate(runs["full_cfr"]["metrics"])
    payload = {
        "schema_version": "portfolio-validation-run/v1",
        "challenge_sha256": sha256_text_file(challenge_path),
        "catalog_sha256": catalog["database"]["sha256"],
        "case_count": len(cases),
        "unique_request_count": len({sha256_json(case.request) for case in cases}),
        "category_counts": {
            category: sum(case.category == category for case in cases)
            for category in sorted({case.category for case in cases})
        },
        "execution_status": "completed",
        "quality_gate": quality_gate,
        "known_findings": dynamic_findings(quality_gate),
        "runs": runs,
    }
    git_status = _git_value("status", "--porcelain")
    manifest = {
        "schema_version": "portfolio-validation-manifest/v1",
        "evaluator_version": "1.1.0",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "commit": _git_value("rev-parse", "HEAD"),
        "git_dirty": bool(git_status),
        "python": sys.version,
        "platform": platform.platform(),
        "argv": sys.argv,
        "working_directory_name": Path.cwd().name,
        "top_k": 5,
        "challenge": {"name": challenge_path.name, "sha256": payload["challenge_sha256"]},
        "catalog_inputs": [
            {"name": path.name, "sha256": sha256_text_file(path)}
            for path in catalog_paths
        ],
        "combined_catalog_sha256": payload["catalog_sha256"],
    }
    write_outputs(output_dir, payload, manifest)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--challenge", type=Path, default=Path("data/benchmarks/portfolio_challenge_v1.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("outputs/portfolio_validation"))
    args = parser.parse_args(argv)
    catalog_paths = (
        Path("data/fixtures/catalog/factorbench_catalog.json"),
        Path("data/fixtures/catalog/factorbench_extended_catalog.json"),
        Path("data/fixtures/catalog/portfolio_catalog_additions.json"),
    )
    result = asyncio.run(evaluate(args.challenge, catalog_paths, args.output))
    print(json.dumps({
        "execution_status": result["execution_status"],
        "quality_gate": result["quality_gate"],
        "metrics": {name: run["metrics"] for name, run in result["runs"].items()},
    }, indent=2))
    return 0 if result["quality_gate"]["hard_gates_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
