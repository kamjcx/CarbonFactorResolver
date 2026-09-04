from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from tools.public_delivery_scan import scan_public_data
from tools.release_manifest import build_manifest
from tools.verify_release_artifacts import verify_archive

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_is_digest_locked_frozen_and_minimal() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith(
        "# syntax=docker/dockerfile:1.7@sha256:"
        "a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e"
    )
    assert "python:3.11.16-slim-trixie@sha256:9534e5a8" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85a" in dockerfile
    assert "uv sync --frozen --no-dev --extra api" in dockerfile
    assert "COPY . " not in dockerfile
    assert "COPY src/ ./src/" in dockerfile
    assert "COPY data/benchmarks/*.jsonl ./data/benchmarks/" in dockerfile
    assert "COPY data/fixtures/catalog/ ./data/fixtures/catalog/" in dockerfile
    assert "COPY data/fixtures/external/ ./data/fixtures/external/" in dockerfile
    assert "COPY tests" not in dockerfile
    assert "COPY evidence" not in dockerfile
    assert "/usr/local/bin/python -m pip uninstall --yes pip setuptools wheel" in dockerfile
    assert "find_spec('jaraco') is None" in dockerfile
    assert "USER cfr" in dockerfile


def test_ci_uses_immutable_actions_and_runs_delivery_gates_before_final_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, flags=re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", value) for value in uses)
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d" in workflow
    assert "ubuntu-latest" not in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    for required in (
        "pip-audit", "bandit", "gitleaks", "cyclonedx-py", "trivy",
        "SHA256SUMS", "release-manifest.json", "public_delivery_scan.py",
    ):
        assert required in workflow
    final_gate = workflow.index("name: Fail CI when evaluation quality gates fail")
    for preceding in (
        "name: Build package", "name: Audit locked Python dependencies",
        "name: Scan Python source", "name: Scan Git history for secrets",
        "name: Build locked runtime image", "name: Scan runtime image",
        "name: Generate dependency SBOM", "name: Generate release checksums",
        "name: Generate release manifest", "name: Upload release and supply-chain evidence",
    ):
        assert workflow.index(preceding) < final_gate


def test_public_data_scanner_accepts_reviewable_synthetic_json(tmp_path: Path) -> None:
    data = tmp_path / "data" / "fixtures"
    data.mkdir(parents=True)
    (data / "public.json").write_text(
        json.dumps({"license": "MIT synthetic fixture", "source": "https://example.invalid/data"}),
        encoding="utf-8",
    )
    report = scan_public_data(tmp_path)
    assert report["passed"] is True
    assert report["violations"] == []


def test_public_data_scanner_redacts_restricted_secret_and_local_path_values(tmp_path: Path) -> None:
    data = tmp_path / "data" / "customer"
    data.mkdir(parents=True)
    secret = "do-not-echo-this-token"
    local_path = "C:/private/customer.xlsx"
    (data / "payload.json").write_text(
        json.dumps({"classification": "restricted", "api_key": secret, "source": local_path}),
        encoding="utf-8",
    )
    report = scan_public_data(tmp_path)
    encoded = json.dumps(report)
    assert report["passed"] is False
    assert {item["reason"] for item in report["violations"]} >= {
        "RESTRICTED_PATH", "RESTRICTED_CONTENT", "SECRET_VALUE", "ABSOLUTE_LOCAL_PATH",
    }
    assert secret not in encoded
    assert local_path not in encoded


def test_public_data_scanner_rejects_compound_paths_and_camelcase_secrets(tmp_path: Path) -> None:
    data = tmp_path / "data" / "customer-data"
    data.mkdir(parents=True)
    (data / "payload.json").write_text(
        json.dumps({"accessKey": "redacted-by-report", "aws_secret_access_key": "also-redacted"}),
        encoding="utf-8",
    )

    report = scan_public_data(tmp_path)

    assert report["passed"] is False
    assert {item["reason"] for item in report["violations"]} >= {
        "RESTRICTED_PATH",
        "SECRET_VALUE",
    }


def test_archive_scanner_rejects_case_variants_secrets_and_unsafe_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.whl"
    members = (
        "package/Tests/test_module.py",
        "package/.env.production",
        "package/Customer/export.json",
        "C:/private/key.txt",
        "../escape.txt",
        "package/archive.ZIP",
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        for member in members:
            archive.writestr(member, "placeholder")
    assert verify_archive(archive_path) == members


def test_archive_scanner_reports_secret_member_without_echoing_value(tmp_path: Path) -> None:
    archive_path = tmp_path / "secret.whl"
    secret = "do-not-echo-this-secret"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("package/config.json", json.dumps({"api_key": secret}))
    violations = verify_archive(archive_path)
    assert violations == ("package/config.json",)
    assert secret not in json.dumps(violations)


def test_archive_scanner_rejects_compound_customer_path_and_access_key(tmp_path: Path) -> None:
    archive_path = tmp_path / "compound.whl"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("package/customer-data/catalog.json", "placeholder")
        archive.writestr("package/config.json", json.dumps({"accessKey": "hidden-value"}))

    assert verify_archive(archive_path) == (
        "package/customer-data/catalog.json",
        "package/config.json",
    )


def test_release_manifest_is_source_timestamped_and_validates_image_digest(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    manifest = build_manifest(
        ROOT,
        [Path("README.md")],
        image_digest="sha256:" + "a" * 64,
        toolchain={"uv": "0.11.7"},
    )
    assert manifest["created_at"] == "1970-01-01T00:00:00+00:00"
    assert len(manifest["git_tree"]) == 40
    assert manifest["toolchain"] == {"uv": "0.11.7"}
    assert {"Dockerfile", "pyproject.toml", "uv.lock", ".github/workflows/ci.yml"} <= set(
        manifest["source_inputs"]
    )


def test_release_manifest_rejects_non_digest_image_identifier() -> None:
    try:
        build_manifest(ROOT, [Path("README.md")], image_digest="latest")
    except ValueError as exc:
        assert "image digest" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("non-digest image identifier was accepted")
