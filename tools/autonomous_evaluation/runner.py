"""Execute generated contracts against the real Resolver and preserve observations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Mapping, Sequence

from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.api import create_app
from a1_factor_engine.engine import A1FactorResolutionEngine
from a1_factor_engine.models import Candidate, Recommendation, ResolutionRequest

from .attacks import run_state_machine_attacks
from .contracts import ExpectedDecision, GeneratedCase
from .generator import generate_bundle, materialize_catalog
from .metrics import aggregate_metrics, bad_cases

SCHEMA_VERSION = "cfr-autonomous-evaluation-run/v1"


def _source_ids(candidates: Sequence[Candidate]) -> tuple[str, ...]:
    return tuple(candidate.source.source_id for candidate in candidates)


def _candidate_evidence_complete(candidate: Candidate) -> bool:
    return bool(
        candidate.source.locator
        and candidate.source.source_document_sha256
        and len(candidate.source.source_document_sha256) == 64
    )


def _decision_signature(recommendation: Recommendation) -> str:
    payload = {
        "status": recommendation.status.value,
        "primary": _source_ids(recommendation.candidates),
        "reviewable": _source_ids(recommendation.reviewable_candidates),
        "diagnostic": _source_ids(recommendation.diagnostic_candidates),
        "reason_codes": recommendation.reason_codes,
        "questions": recommendation.questions,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _metric_expectation(expected: ExpectedDecision, axis: str) -> dict[str, Any]:
    decision = (
        "direct" if expected.status == "recommendation_ready"
        else "more_input" if expected.status == "more_input_needed"
        else "reference_review" if expected.status == "reference_review_required"
        else "abstain"
    )
    reference_ids = set(expected.reference_only_source_ids)
    return {
        "decision": decision,
        "status": expected.status,
        "acceptable_ids": list(expected.acceptable_source_ids),
        "forbidden_ids": [
            source_id for source_id in expected.forbidden_source_ids
            if source_id not in reference_ids
        ],
        "reference_only_ids": list(expected.reference_only_source_ids),
        "reason_codes": list(expected.reason_codes),
        "expected_top_1": expected.expected_top_1,
        "approval_allowed": expected.approval_allowed,
        "safety_axis": axis if axis in {"boundary", "subject", "unit", "provenance"} else None,
    }


def _observe(recommendation: Recommendation) -> dict[str, Any]:
    selectable = (*recommendation.candidates, *recommendation.reviewable_candidates)
    trace = recommendation.trace
    stages = tuple(entry.stage for entry in trace.entries) if trace else ()
    proxy_disclosed = all(
        not candidate.proxy_material
        or bool(candidate.limitations or candidate.warnings or candidate.proxy_class)
        for candidate in selectable
    )
    return {
        "status": recommendation.status.value,
        "primary_ids": list(_source_ids(recommendation.candidates)),
        "reviewable_ids": list(_source_ids(recommendation.reviewable_candidates)),
        "diagnostic_ids": list(_source_ids(recommendation.diagnostic_candidates)),
        "reason_codes": list(recommendation.reason_codes),
        "questions": list(recommendation.questions),
        "evidence_complete": bool(selectable) and all(
            _candidate_evidence_complete(candidate) for candidate in selectable
        ),
        "proxy_disclosed": proxy_disclosed,
        "trace_complete": bool(trace and {"normalize", "local_retrieval", "top_k"} <= set(stages)),
        "trace_revision": trace.revision if trace else 0,
        "trace_stages": list(stages),
        "decision_signature": _decision_signature(recommendation),
        "error": False,
    }


def _case_passed(expectation: Mapping[str, Any], observation: Mapping[str, Any]) -> bool:
    primary = tuple(str(item) for item in observation.get("primary_ids", ()))
    reviewable = tuple(str(item) for item in observation.get("reviewable_ids", ()))
    selectable = set((*primary, *reviewable))
    forbidden = set(str(item) for item in expectation.get("forbidden_ids", ()))
    references = set(str(item) for item in expectation.get("reference_only_ids", ()))
    acceptable = set(str(item) for item in expectation.get("acceptable_ids", ()))
    if observation.get("status") != expectation.get("status"):
        return False
    if forbidden & selectable:
        return False
    if references and not references <= set(reviewable):
        return False
    expected_top = expectation.get("expected_top_1")
    if expected_top is not None and (not primary or primary[0] != expected_top):
        return False
    if acceptable and not (acceptable & selectable):
        return False
    return bool(observation.get("trace_complete"))


async def _run_case(case: GeneratedCase) -> tuple[dict[str, Any], bool]:
    payload = materialize_catalog(case)
    repository = HttpCatalogFactorRepository(
        endpoint=f"synthetic://autonomous/{case.case_id}",
        fetch_json=lambda _endpoint: payload,
    )
    engine = A1FactorResolutionEngine(local_retrieval=repository)
    request_payload = {**dict(case.request), "request_id": f"autoeval-{case.case_id}"}
    expected = _metric_expectation(case.expectation, case.assertion_axis)
    try:
        first = await engine.resolve(ResolutionRequest.from_mapping(request_payload))
        observation = _observe(first)
        replay_engine = A1FactorResolutionEngine(local_retrieval=repository)
        replay_payload = {**request_payload, "request_id": f"autoeval-replay-{case.case_id}"}
        replay = await replay_engine.resolve(ResolutionRequest.from_mapping(replay_payload))
        replay_equal = _decision_signature(first) == _decision_signature(replay)
    except Exception as exc:  # Evaluation records runtime failures instead of hiding them.
        observation = {
            "status": "error",
            "primary_ids": [],
            "reviewable_ids": [],
            "diagnostic_ids": [],
            "reason_codes": [],
            "trace_complete": False,
            "evidence_complete": False,
            "proxy_disclosed": False,
            "decision_signature": None,
            "error": True,
            "exception_type": type(exc).__name__,
            "sanitized_message": "resolver execution failed",
        }
        replay_equal = False
    row: dict[str, Any] = {
        "case_id": case.case_id,
        "category": case.category,
        "assertion_axis": case.assertion_axis,
        "metamorphic_group": case.metamorphic_group,
        "semantic_fingerprint": case.semantic_fingerprint,
        "request": dict(case.request),
        "expectation": expected,
        "observation": observation,
    }
    row["passed"] = _case_passed(expected, observation)
    return row, replay_equal


def _api_safety_rows() -> list[dict[str, Any]]:
    try:
        from fastapi.testclient import TestClient
    except ImportError as exc:
        raise RuntimeError(
            "autonomous evaluation requires the 'api' dependency extra; "
            "dependency availability must not change the benchmark case inventory"
        ) from exc

    bundle = generate_bundle()
    case = bundle.cases[0]
    payload = materialize_catalog(case)
    repository = HttpCatalogFactorRepository(
        endpoint="synthetic://autonomous/api",
        fetch_json=lambda _endpoint: payload,
    )
    app = create_app(engine=A1FactorResolutionEngine(local_retrieval=repository))
    requests = (
        dict(case.request),
        {**dict(case.request), "quantity": 0},
        {**dict(case.request), "subject_type": "not-a-subject"},
        {"material_name": "unknown", "quantity": 1, "quantity_unit": "kg"},
    )
    rows = []
    with TestClient(app, raise_server_exceptions=False) as client:
        for index, request in enumerate(requests, 1):
            response = client.post("/api/v1/resolve", json=request)
            rows.append({
                "case_id": f"AUTO-HTTP-{index}",
                "category": "api_safety",
                "expectation": {"decision": "http_contract"},
                "observation": {"http_status": response.status_code},
                "passed": response.status_code < 500,
            })
    return rows


async def run_evaluation(*, seed: int = 20260902) -> dict[str, Any]:
    """Run all generated cases, replay checks, API probes, and workflow attacks."""

    bundle = generate_bundle(seed)
    executed = await asyncio.gather(*(_run_case(case) for case in bundle.cases))
    rows = [item[0] for item in executed]
    relation_results = {
        f"replay:{case.case_id}": executed[index][1]
        for index, case in enumerate(bundle.cases)
    }
    http_rows = _api_safety_rows()
    all_rows = [*rows, *http_rows]
    attacks = await run_state_machine_attacks()
    metrics = aggregate_metrics(all_rows, relation_results=relation_results)
    metrics["state_machine_attacks"] = {
        "numerator": sum(bool(item["passed"]) for item in attacks),
        "denominator": len(attacks),
        "rate": sum(bool(item["passed"]) for item in attacks) / len(attacks),
    }
    metrics["hard_gates_pass"] = bool(
        metrics["hard_gates_pass"] and all(item["passed"] for item in attacks)
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generator": {
            "schema_version": bundle.schema_version,
            "seed": bundle.seed,
            "case_count": bundle.case_count,
            "sha256": bundle.sha256,
            "data_classification": "PUBLIC_SYNTHETIC",
            "contains_licensed_or_customer_data": False,
        },
        "results": all_rows,
        "relation_results": relation_results,
        "state_machine_attacks": attacks,
        "metrics": metrics,
    }
    payload["bad_cases"] = bad_cases(all_rows)
    return payload


def generated_contract_payload(seed: int = 20260902) -> dict[str, Any]:
    return generate_bundle(seed).to_dict()
