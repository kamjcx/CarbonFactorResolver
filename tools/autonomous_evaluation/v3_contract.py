"""Build the frozen Autonomous V3 adjudication and input manifest.

This developer-only module applies explicit benchmark-governance rules. It does
not import or execute the Resolver, and therefore cannot copy runtime outcomes
into the Oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import GeneratedCase, sha256_json
from .generator import DEFAULT_SEED, generate_bundle

BASELINE_COMMIT = "1d0956d7ea7697ed65c0dee1565a991bfef92b46"
EFFECTIVE_VERSION = "0.14.2+autonomous-contract-v3"
AUTHORITY = "CFR_AUTONOMOUS_QUALITY_GATE_V3_ADJUDICATION"
REVIEWER = "CarbonFactorResolver benchmark governance review"

V2_STEEL_FIBRE_CASES = frozenset({
    "AUTO-20-POS-canonical",
    "AUTO-20-POS-reviewed-alias",
    "AUTO-20-POS-casefold",
    "AUTO-20-POS-symbol",
    "AUTO-20-POS-reviewed-typo",
    "AUTO-20-Q-0_001",
    "AUTO-20-Q-10_0",
    "AUTO-20-Q-1000000_0",
    "AUTO-20-ORDER",
    "AUTO-20-NOISE",
    "AUTO-20-DUP",
    "AUTO-20-BOUNDARY",
    "AUTO-20-UNIT-EQ",
})

REFERENCE_ALIAS_CASES = frozenset({
    "AUTO-01-POS-reviewed-typo",
    "AUTO-03-POS-reviewed-alias",
    "AUTO-06-POS-reviewed-typo",
    "AUTO-07-POS-reviewed-alias",
    "AUTO-07-POS-reviewed-typo",
    "AUTO-08-POS-reviewed-alias",
    "AUTO-08-POS-reviewed-typo",
    "AUTO-09-POS-reviewed-alias",
    "AUTO-10-POS-reviewed-alias",
    "AUTO-11-POS-reviewed-alias",
    "AUTO-11-POS-reviewed-typo",
    "AUTO-12-POS-reviewed-alias",
    "AUTO-12-POS-reviewed-typo",
    "AUTO-16-POS-reviewed-alias",
    "AUTO-17-POS-reviewed-alias",
    "AUTO-18-POS-reviewed-typo",
})

MORE_INPUT_ALIAS_CASES = frozenset({"AUTO-04-POS-reviewed-typo"})
SUBJECT_STATUS_CASES = frozenset({"AUTO-20-SUBJECT"})
CATALOGUE_COVERAGE_CASES = frozenset(
    f"AUTO-UNKNOWN-{index:02d}" for index in range(12)
)
PROVENANCE_CASES = frozenset(
    f"AUTO-{index:02d}-PROV-{kind}"
    for index in range(1, 21)
    for kind in ("HASH", "QUALITY", "ELIGIBLE")
)


def _decision(status: str) -> str:
    if status == "recommendation_ready":
        return "direct"
    if status == "more_input_needed":
        return "more_input"
    if status == "reference_review_required":
        return "reference_review"
    return "abstain"


def _metric_expectation(case: GeneratedCase) -> dict[str, Any]:
    expected = case.expectation
    references = set(expected.reference_only_source_ids)
    return {
        "decision": _decision(expected.status),
        "status": expected.status,
        "acceptable_ids": list(expected.acceptable_source_ids),
        "forbidden_ids": [
            source_id
            for source_id in expected.forbidden_source_ids
            if source_id not in references
        ],
        "reference_only_ids": list(expected.reference_only_source_ids),
        "reason_codes": list(expected.reason_codes),
        "expected_top_1": expected.expected_top_1,
        "approval_allowed": expected.approval_allowed,
        "safety_axis": (
            case.assertion_axis
            if case.assertion_axis in {"boundary", "subject", "unit", "provenance"}
            else None
        ),
    }


def _non_selectable_expectation(
    case: GeneratedCase,
    *,
    status: str,
    references: tuple[str, ...] = (),
    reason_codes: tuple[str, ...] = (),
) -> dict[str, Any]:
    raw = _metric_expectation(case)
    forbidden = {str(value) for value in raw["forbidden_ids"]}
    forbidden.update(str(value) for value in raw["acceptable_ids"])
    forbidden.update(str(value) for value in raw["reference_only_ids"])
    forbidden.difference_update(references)
    return {
        "decision": _decision(status),
        "status": status,
        "acceptable_ids": [],
        "forbidden_ids": sorted(forbidden),
        "reference_only_ids": list(references),
        "reason_codes": list(reason_codes),
        "expected_top_1": None,
        "approval_allowed": False,
        "safety_axis": raw["safety_axis"],
    }


def _provenance_expectation(case: GeneratedCase) -> dict[str, Any]:
    index = int(case.case_id.split("-", 2)[1])
    if index == 20:
        status = "more_input_needed"
    elif index in {18, 19}:
        status = "process_model_required"
    else:
        status = "unresolved"
    reasons: tuple[str, ...]
    if case.case_id.endswith("-HASH"):
        reasons = ("SOURCE_DOCUMENT_HASH_REQUIRED",)
    elif index <= 17:
        reasons = ("ADMISSION_REJECTED",)
    else:
        reasons = ()
    return _non_selectable_expectation(case, status=status, reason_codes=reasons)


def _entry(case: GeneratedCase) -> dict[str, Any] | None:
    case_id = case.case_id
    raw = _metric_expectation(case)
    if case_id in V2_STEEL_FIBRE_CASES:
        references = tuple(str(value) for value in raw["acceptable_ids"])
        effective = _non_selectable_expectation(
            case,
            status="more_input_needed",
            references=references,
        )
        root_cause = "steel_fibre_decisive_attribute"
        reason = (
            "The V1 Oracle treated generic steel fibre as directly selectable. The reviewed "
            "safety contract requires steel_fiber_type before selection and keeps any otherwise "
            "compatible records non-selectable."
        )
    elif case_id in REFERENCE_ALIAS_CASES:
        effective = _non_selectable_expectation(
            case,
            status="reference_review_required",
            references=tuple(str(value) for value in raw["acceptable_ids"]),
        )
        root_cause = "catalogue_alias_identity_authority"
        reason = (
            "The V1 Oracle promoted a catalogue alias or generated typo to direct selection. "
            "Without independently resolved identity authority it is limited to REFERENCE_ONLY "
            "and requires explicit review."
        )
    elif case_id in MORE_INPUT_ALIAS_CASES:
        effective = _non_selectable_expectation(
            case,
            status="more_input_needed",
            references=tuple(str(value) for value in raw["acceptable_ids"]),
        )
        root_cause = "unresolved_alias_decisive_identity"
        reason = (
            "The misspelled aluminium name is only a catalogue alias observation. Its material "
            "identity is not independently resolved, so the route/form context cannot make it a "
            "formal recommendation and a decisive clarification remains required."
        )
    elif case_id in PROVENANCE_CASES:
        effective = _provenance_expectation(case)
        root_cause = "provenance_fail_closed_status"
        reason = (
            "V1 exposed evidence-degraded records as reviewable. The hardened evidence contract "
            "forbids HASH, QUALITY, or ELIGIBLE failures from every selectable lane; the terminal "
            "status follows the already-versioned request/process follow-up precedence."
        )
    elif case_id in CATALOGUE_COVERAGE_CASES:
        effective = _non_selectable_expectation(case, status="supplier_data_required")
        root_cause = "catalogue_coverage_status_vocabulary"
        reason = (
            "A true zero-hit structured factor query uses supplier_data_required in the public "
            "runtime contract. V1 used the generic unresolved label despite returning no candidate."
        )
    elif case_id in SUBJECT_STATUS_CASES:
        effective = _non_selectable_expectation(case, status="more_input_needed")
        root_cause = "input_gap_before_subject_terminal_status"
        reason = (
            "The steel-fibre request has an independent required subtype gap. The runtime asks for "
            "that input while retaining zero selectable candidates; the incompatible subject record "
            "remains excluded and subject escape stays zero."
        )
    else:
        return None
    return {
        "case_id": case_id,
        "case_sha256": case.semantic_fingerprint,
        "input_sha256": sha256_json(dict(case.request)),
        "disposition": "oracle_preset_error",
        "root_cause": root_cause,
        "previous_expectation": raw,
        "effective_expectation": effective,
        "reason": reason,
        "reviewer": REVIEWER,
        "authority": AUTHORITY,
        "effective_version": EFFECTIVE_VERSION,
    }


def build_adjudications() -> dict[str, Any]:
    bundle = generate_bundle(DEFAULT_SEED)
    entries = [entry for case in bundle.cases if (entry := _entry(case)) is not None]
    expected_ids = (
        V2_STEEL_FIBRE_CASES
        | REFERENCE_ALIAS_CASES
        | MORE_INPUT_ALIAS_CASES
        | SUBJECT_STATUS_CASES
        | CATALOGUE_COVERAGE_CASES
        | PROVENANCE_CASES
    )
    if {entry["case_id"] for entry in entries} != expected_ids or len(entries) != 103:
        raise ValueError("V3 adjudication inventory must bind exactly 103 unique cases")
    return {
        "schema_version": "cfr-autonomous-adjudications/v1",
        "evaluator_contract_sha256": bundle.sha256,
        "version": "3.0.0",
        "supersedes": "autonomous_evaluation_v2_adjudications/2.0.0",
        "historical_results_rewritten": False,
        "entries": entries,
    }


def _api_cases(bundle_case: GeneratedCase) -> list[dict[str, Any]]:
    requests = (
        dict(bundle_case.request),
        {**dict(bundle_case.request), "quantity": 0},
        {**dict(bundle_case.request), "subject_type": "not-a-subject"},
        {"material_name": "unknown", "quantity": 1, "quantity_unit": "kg"},
    )
    cases = []
    for index, request in enumerate(requests, 1):
        payload = {
            "case_id": f"AUTO-HTTP-{index}",
            "category": "api_safety",
            "request": request,
            "expectation": {"http_status_class": "non_5xx"},
        }
        cases.append({
            "case_id": payload["case_id"],
            "case_sha256": sha256_json(payload),
            "input_sha256": sha256_json(request),
        })
    return cases


def _file_sha(path: Path) -> str:
    canonical = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def build_freeze_manifest(root: Path) -> dict[str, Any]:
    bundle = generate_bundle(DEFAULT_SEED)
    generated = [
        {
            "case_id": case.case_id,
            "case_sha256": case.semantic_fingerprint,
            "input_sha256": sha256_json(dict(case.request)),
        }
        for case in bundle.cases
    ]
    api_cases = _api_cases(bundle.cases[0])
    unsigned: dict[str, Any] = {
        "schema_version": "cfr-autonomous-quality-gate-freeze/v1",
        "baseline_commit": BASELINE_COMMIT,
        "seed": bundle.seed,
        "generator_sha256": bundle.sha256,
        "generated_case_count": len(generated),
        "api_case_count": len(api_cases),
        "total_case_count": len(generated) + len(api_cases),
        "source_sha256": {
            path: _file_sha(root / path)
            for path in (
                "tools/autonomous_evaluation/contracts.py",
                "tools/autonomous_evaluation/generator.py",
                "tools/autonomous_evaluation/oracle.py",
                "tools/autonomous_evaluation/v3_contract.py",
            )
        },
        "baseline_inventory": {
            "raw_bad_case_count": 103,
            "prior_adjudicated_count": 13,
            "unresolved_bad_case_count": 90,
            "forbidden_candidate_escape_count": 0,
            "root_causes": {
                "provenance": 60,
                "generic_exact_ambiguity": 16,
                "catalog_coverage": 12,
                "subject": 1,
                "expected_recommendation_but_asked": 1,
                "prior_oracle_preset_error": 13,
            },
        },
        "generated_cases": generated,
        "api_cases": api_cases,
    }
    return {**unsigned, "manifest_sha256": sha256_json(unsigned)}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    outputs = {
        root / "data/benchmarks/autonomous_evaluation_v3_adjudications.json": build_adjudications(),
        root / "data/benchmarks/autonomous_evaluation_v3_freeze.json": build_freeze_manifest(root),
    }
    if args.check:
        for path, expected in outputs.items():
            if json.loads(path.read_text(encoding="utf-8")) != expected:
                raise SystemExit(f"frozen V3 artifact drift: {path}")
        return 0
    for path, payload in outputs.items():
        _write_json(path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
