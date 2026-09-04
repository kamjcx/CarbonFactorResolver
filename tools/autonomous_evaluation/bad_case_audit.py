"""Machine-readable and human-readable summaries derived from evaluator JSON."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .gates import forbidden_escape_ids

ROOT_CAUSES = (
    "geography",
    "year_temporal",
    "boundary",
    "declared_product",
    "subject",
    "unit",
    "generic_exact_ambiguity",
    "expected_more_input_but_recommended",
    "expected_recommendation_but_asked",
    "oracle_preset_error",
    "stale_report",
    "accepted_limitation",
    "provenance",
    "catalog_coverage",
    "other",
)

RISK = {
    "geography": "HIGH",
    "year_temporal": "HIGH",
    "boundary": "CRITICAL",
    "declared_product": "CRITICAL",
    "subject": "CRITICAL",
    "unit": "CRITICAL",
    "generic_exact_ambiguity": "HIGH",
    "expected_more_input_but_recommended": "CRITICAL",
    "expected_recommendation_but_asked": "MEDIUM",
    "oracle_preset_error": "MEDIUM",
    "stale_report": "MEDIUM",
    "accepted_limitation": "ACCEPTED",
    "provenance": "HIGH",
    "catalog_coverage": "MEDIUM",
    "other": "MEDIUM",
}

NEXT_PR = {
    "geography": "temporal-geography-contract-v2",
    "year_temporal": "temporal-geography-contract-v2",
    "boundary": "boundary-reference-only-contract",
    "declared_product": "declared-product-admission-hardening",
    "subject": "subject-decision-contract-alignment",
    "unit": "unit-syntax-contract-alignment",
    "generic_exact_ambiguity": "review-tier-and-alias-contract-alignment",
    "expected_more_input_but_recommended": "ambiguity-decision-hardening",
    "expected_recommendation_but_asked": "ambiguity-question-regression",
    "oracle_preset_error": "versioned-oracle-adjudication",
    "stale_report": "dynamic-evaluation-reporting",
    "accepted_limitation": "no-runtime-change; retain versioned adjudication",
    "provenance": "provenance-reference-only-contract-alignment",
    "catalog_coverage": "abstention-status-contract-alignment",
    "other": "bad-case-triage-follow-up",
}


def root_cause(row: Mapping[str, Any]) -> str:
    adjudication = row.get("adjudication")
    if isinstance(adjudication, Mapping):
        disposition = str(adjudication.get("disposition") or "")
        if disposition == "oracle_preset_error":
            return disposition
    expectation = row.get("expectation", {})
    observation = row.get("observation", {})
    expected = expectation if isinstance(expectation, Mapping) else {}
    observed = observation if isinstance(observation, Mapping) else {}
    axis = str(row.get("assertion_axis") or expected.get("safety_axis") or "").casefold()
    category = str(row.get("category") or "").casefold()
    expected_decision = str(expected.get("decision") or "")
    observed_status = str(observed.get("status") or "")
    if "geography" in axis or "geography" in category:
        return "geography"
    if axis == "year" or "year_" in category or "temporal" in category:
        return "year_temporal"
    if "boundary" in axis or "boundary" in category:
        return "boundary"
    if "declared_product" in axis or "declared_product" in category:
        return "declared_product"
    if "subject" in axis or "subject" in category:
        return "subject"
    if "unit" in axis or "unit" in category:
        return "unit"
    if expected_decision == "more_input" and observed_status in {
        "recommendation_ready", "reference_review_required"
    }:
        return "expected_more_input_but_recommended"
    if expected_decision == "direct" and observed_status == "more_input_needed":
        return "expected_recommendation_but_asked"
    if "alias" in category or "typo" in category or "exact" in category:
        return "generic_exact_ambiguity"
    if "provenance" in axis or "provenance" in category:
        return "provenance"
    if "catalog_coverage" in category:
        return "catalog_coverage"
    return "other"


def build_inventory(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for raw in payload.get("bad_cases", ()):
        row = dict(raw)
        expected = row.get("expectation", {})
        observed = row.get("observation", {})
        cause = root_cause(row)
        escaped = forbidden_escape_ids(row)
        rows.append({
            "case_id": row.get("case_id"),
            "root_cause": cause,
            "risk": RISK[cause],
            "legacy_category": row.get("bad_case_category"),
            "expected": {
                "decision": expected.get("decision") if isinstance(expected, Mapping) else None,
                "status": expected.get("status") if isinstance(expected, Mapping) else None,
                "top_1": expected.get("expected_top_1") if isinstance(expected, Mapping) else None,
            },
            "actual": {
                "status": observed.get("status") if isinstance(observed, Mapping) else None,
                "primary_ids": list(observed.get("primary_ids", ())) if isinstance(observed, Mapping) else [],
                "reviewable_ids": list(observed.get("reviewable_ids", ())) if isinstance(observed, Mapping) else [],
                "reason_codes": list(observed.get("reason_codes", ())) if isinstance(observed, Mapping) else [],
            },
            "forbidden_candidate_escape_ids": list(escaped),
            "adjudication": row.get("adjudication"),
            "suggested_follow_up_pr": NEXT_PR[cause],
        })
    counts = Counter(str(row["root_cause"]) for row in rows)
    summaries = []

    def accepted_limitation(row: Mapping[str, Any]) -> bool:
        adjudication = row.get("adjudication")
        return (
            isinstance(adjudication, Mapping)
            and adjudication.get("disposition") == "accepted_limitation"
        )

    for cause in ROOT_CAUSES:
        matching = [row for row in rows if row["root_cause"] == cause]
        if cause == "accepted_limitation":
            matching = [row for row in rows if accepted_limitation(row)]
        summaries.append({
            "root_cause": cause,
            "count": len(matching) if cause == "accepted_limitation" else counts.get(cause, 0),
            "risk": RISK[cause],
            "representative_case_ids": [str(row["case_id"]) for row in matching[:5]],
            "suggested_follow_up_pr": NEXT_PR[cause],
        })
    gate = payload.get("quality_gate", {})
    generator = payload.get("generator", {})
    return {
        "schema_version": "cfr-bad-case-inventory/v1",
        "evaluation_schema_version": payload.get("schema_version"),
        "generator_sha256": generator.get("sha256") if isinstance(generator, Mapping) else None,
        "quality_gate": gate,
        "bad_case_count": len(rows),
        "root_cause_summary": summaries,
        "forbidden_candidate_escape_cases": [
            {"case_id": row["case_id"], "candidate_ids": row["forbidden_candidate_escape_ids"]}
            for row in rows if row["forbidden_candidate_escape_ids"]
        ],
        "cases": rows,
    }


def render_inventory(inventory: Mapping[str, Any]) -> str:
    gate = inventory.get("quality_gate", {})
    lines = [
        "# CFR Current Bad Case Audit",
        "",
        "> Generated from the current evaluation JSON. No frozen answer or Resolver behavior was changed.",
        "",
        "## Decision",
        "",
        f"- Evaluation execution: **{gate.get('execution_status', 'unknown')}**",
        f"- Quality gate: **{gate.get('quality_status', 'unknown')}**",
        f"- Raw Bad Cases: **{inventory.get('bad_case_count', 0)}**",
        f"- Unresolved Bad Cases: **{gate.get('unresolved_bad_case_count', 0)}**",
        f"- Raw forbidden escapes: **{gate.get('raw_forbidden_escape_count', 0)}**",
        f"- Unadjudicated forbidden escapes: **{gate.get('unadjudicated_forbidden_escape_count', 0)}**",
        "",
        "## Root-cause and adjudication inventory",
        "",
        "| Root cause / disposition | Count | Risk | Representative cases | Suggested follow-up PR |",
        "|---|---:|---|---|---|",
    ]
    for item in inventory.get("root_cause_summary", ()):
        examples = ", ".join(f"`{case_id}`" for case_id in item.get("representative_case_ids", ())) or "—"
        lines.append(
            f"| `{item['root_cause']}` | {item['count']} | {item['risk']} | {examples} | "
            f"`{item['suggested_follow_up_pr']}` |"
        )
    lines.extend(("", "## Forbidden candidate escapes", ""))
    escapes = inventory.get("forbidden_candidate_escape_cases", ())
    if escapes:
        for item in escapes:
            candidates = ", ".join(f"`{value}`" for value in item.get("candidate_ids", ()))
            lines.append(f"- `{item['case_id']}`: {candidates}")
    else:
        lines.append("None.")
    lines.extend((
        "",
        "## Interpretation",
        "",
        "A completed process only proves that the evaluator ran and wrote its evidence. A PASS quality",
        "decision additionally requires every enforced metric and every unresolved Bad Case gate to pass.",
        "Versioned adjudications remain visible in raw counts and may only be excluded after their case,",
        "input, authority, reason, reviewer, and effective version bindings are verified.",
        "",
    ))
    return "\n".join(lines)


def write_inventory(output_dir: Path, payload: Mapping[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory(payload)
    json_path = output_dir / "bad_case_inventory.json"
    report_path = output_dir / "BAD_CASE_REPORT.md"
    json_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(render_inventory(inventory), encoding="utf-8")
    return json_path, report_path
