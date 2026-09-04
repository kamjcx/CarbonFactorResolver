"""Reproducible JSON/Markdown output and immutable first-run persistence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .metrics import bad_cases


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _rate(value: Mapping[str, Any]) -> str:
    denominator = int(value.get("denominator", 0))
    if not denominator:
        return "N/A (0/0)"
    return f"{float(value.get('rate', 0.0)):.2%} ({value.get('numerator')}/{denominator})"


def render_markdown(payload: Mapping[str, Any]) -> str:
    metrics = payload.get("metrics", {})
    rows = payload.get("results", ())
    attacks = payload.get("state_machine_attacks", ())
    failures = payload.get("bad_cases", ())
    gate = payload.get("quality_gate", {})
    lines = [
        "# CFR Autonomous Public-Synthetic Contract Evaluation",
        "",
        "> Developer-only offline evaluation. This is not real-world accuracy or production-readiness evidence.",
        "",
        "## Decision",
        "",
        f"- Generated cases: **{len(rows)}**",
        f"- Passed cases: **{sum(bool(row.get('passed')) for row in rows)} / {len(rows)}**",
        f"- Bad Cases: **{len(failures)}**",
        f"- State-machine attacks passed: **{sum(bool(row.get('passed')) for row in attacks)} / {len(attacks)}**",
        f"- Evaluation execution: **{gate.get('execution_status', 'completed')}**",
        f"- Quality gate: **{gate.get('quality_status', 'PASS' if metrics.get('hard_gates_pass') else 'FAIL')}**",
        f"- Unresolved Bad Cases: **{gate.get('unresolved_bad_case_count', len(failures))}**",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
    ]
    labels = {
        "direct_recommendation_top1": "Direct Recommendation Top-1",
        "recall_at_5": "Recall@5",
        "forbidden_candidate_escape": "Forbidden Candidate Escape",
        "abstention_correctness": "Abstention Correctness",
        "more_input_recall": "MORE_INPUT Recall",
        "unnecessary_question_rate": "Unnecessary Question Rate",
        "boundary_violation": "Boundary Violation",
        "subject_violation": "Subject Violation",
        "unit_violation": "Unit Violation",
        "proxy_disclosure": "Proxy Disclosure",
        "evidence_metadata_completeness": "Evidence Metadata Completeness",
        "deterministic_replay": "Deterministic Replay",
        "unhandled_http_500": "Unhandled HTTP 500",
    }
    for key, label in labels.items():
        value = metrics.get(key)
        if isinstance(value, Mapping):
            lines.append(f"| {label} | {_rate(value)} |")
    lines.extend((
        "",
        "## Bad Case Attribution",
        "",
        "| Category | Count |",
        "|---|---:|",
    ))
    counts: dict[str, int] = {}
    for row in failures:
        category = str(row.get("bad_case_category") or "UNKNOWN")
        counts[category] = counts.get(category, 0) + 1
    for category in sorted(counts):
        lines.append(f"| `{category}` | {counts[category]} |")
    if not counts:
        lines.append("| none | 0 |")
    lines.extend((
        "",
        "## Interpretation",
        "",
        "Accuracy comes from hybrid recall that finds plausible records, deterministic gates that prevent",
        "incompatible records from admission, and explicit `MORE_INPUT` or safe refusal when evidence is",
        "insufficient. It is not attributed to an embedding swap or similarity-score increase alone.",
        "",
        "The catalogue and queries are project-authored public-synthetic contracts. Results do not claim",
        "general accuracy on enterprise queries, licensed databases, or unseen real-world materials.",
        "",
    ))
    return "\n".join(lines)


def write_first_run(
    output_dir: Path,
    payload: Mapping[str, Any],
    *,
    root: Path,
    generated_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write first-run evidence once; any existing entry blocks overwrite."""

    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"first-run output is immutable and already exists: {output_dir}")
    # Capture repository state before creating the evidence directory. Otherwise
    # the first generated artifact makes a clean run appear dirty by definition.
    pre_run_commit = _git(root, "rev-parse", "HEAD")
    pre_run_dirty = bool(_git(root, "status", "--porcelain"))
    output_dir.mkdir(parents=True, exist_ok=True)

    failures = list(payload.get("bad_cases") or bad_cases(payload.get("results", ())))
    complete = {**dict(payload), "bad_cases": failures}
    result_path = output_dir / "first_run.json"
    bad_case_path = output_dir / "bad_cases.json"
    report_path = output_dir / "REPORT.md"
    contract_path = output_dir / "generated_contract.json"
    result_path.write_text(json.dumps(complete, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    bad_case_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(render_markdown(complete), encoding="utf-8")
    artifacts = [result_path, bad_case_path, report_path]
    if generated_contract is not None:
        contract_path.write_text(
            json.dumps(generated_contract, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        artifacts.append(contract_path)

    manifest = {
        "schema_version": "cfr-autonomous-evaluation-manifest/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": pre_run_commit,
        "git_dirty": pre_run_dirty,
        "git_state_captured_before_output": True,
        "evaluation_schema": complete.get("schema_version"),
        "contract_sha256": sha256_value(generated_contract) if generated_contract is not None else None,
        "artifacts": [
            {
                "path": path.name,
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
            for path in artifacts
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def verify_manifest(output_dir: Path) -> tuple[str, ...]:
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    failures = []
    for item in manifest.get("artifacts", ()):
        path = output_dir / str(item["path"])
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            failures.append(str(item["path"]))
    return tuple(failures)
