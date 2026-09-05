from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_public_release_documents_exist() -> None:
    required = {
        "README.md",
        "ARCHITECTURE.md",
        "EVALUATION.md",
        "LIMITATIONS.md",
        "DATA_LICENSE.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "LICENSE",
    }
    assert all((ROOT / name).is_file() for name in required)
    assert "CarbonFactorResolver contributors" in (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_v0143_release_documents_preserve_raw_and_effective_metric_scope() -> None:
    notes = (ROOT / "docs" / "RELEASE_NOTES_V0.14.3.md").read_text(encoding="utf-8")
    readiness = (ROOT / "docs" / "RELEASE_READINESS_V0.14.3.md").read_text(encoding="utf-8")
    for document in (notes, readiness):
        assert "230/259" in document
        assert "103" in document
        assert "418/418" in document
        assert "0 unresolved" in document
        assert "0 forbidden" in document
        assert "public-synthetic" in document
        assert "not an independent Holdout" in document
        assert "not a real-world accuracy" in document


def test_v0144_release_documents_define_alignment_scope_and_limits() -> None:
    notes = (ROOT / "docs" / "RELEASE_NOTES_V0.14.4.md").read_text(encoding="utf-8")
    readiness = (ROOT / "docs" / "RELEASE_READINESS_V0.14.4.md").read_text(encoding="utf-8")
    for document in (notes, readiness):
        assert "API safety" in document
        assert "unit field" in document.casefold()
        assert "review state" in document.casefold()
        assert "in-memory" in document.casefold()
        assert "three structured electricity records" in document.casefold()
        assert "formal admission" in document.casefold()
        assert "public-synthetic" in document
        assert "not a real-world accuracy" in document
        assert "v0.14.3" in document
        assert "v0.14.4" in document


def test_runtime_dependency_groups_exclude_file_parsers() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    parser_packages = {"pdfplumber", "python-docx", "openpyxl"}

    def names(requirements: list[str]) -> set[str]:
        return {
            re.split(r"[<>=!~ ]", item, maxsplit=1)[0].casefold()
            for item in requirements
        }

    assert names(project["dependencies"]).isdisjoint(parser_packages)
    assert names(project["optional-dependencies"]["api"]).isdisjoint(parser_packages)
    assert {"pdfplumber", "python-docx"} <= names(
        project["optional-dependencies"]["acceptance-tools"]
    )
    assert {"pdfplumber", "openpyxl"} <= names(
        project["optional-dependencies"]["energy-db-build"]
    )


def test_docker_context_excludes_private_and_developer_artifacts() -> None:
    patterns = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required = {
        ".env.*",
        "*.db",
        "*.duckdb",
        "*.docx",
        "*.xlsx",
        "*.pdf",
        "*.pem",
        "outputs",
        "datasets",
        "exports",
        "dist",
        "task_plan.md",
        "findings.md",
        "progress.md",
    }
    assert required <= patterns
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert '".[api]"' in dockerfile
    assert "acceptance-tools" not in dockerfile
    assert "energy-db-build" not in dockerfile


def test_public_data_tree_contains_only_reviewable_text_fixtures() -> None:
    allowed = {".json", ".jsonl"}
    files = [path for path in (ROOT / "data").rglob("*") if path.is_file()]
    assert files
    assert all(path.suffix.casefold() in allowed for path in files)
    assert not any(path.stat().st_size >= 1_000_000 for path in files)
    assert not any(path.suffix.casefold() in {".db", ".sqlite", ".duckdb", ".zip"} for path in files)


def test_source_distribution_manifest_excludes_tests_and_local_state() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "prune tests" in manifest
    assert "prune outputs" in manifest
    assert "exclude task_plan.md" in manifest
    assert "global-exclude .env" in manifest


def test_reachable_git_history_has_no_database_archive_or_private_key_blob() -> None:
    objects = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    forbidden_suffixes = {
        ".db", ".sqlite", ".sqlite3", ".duckdb", ".zip", ".7z", ".p12", ".pfx", ".pem", ".key"
    }
    paths = [line.split(" ", 1)[1] for line in objects if " " in line]
    assert not [path for path in paths if Path(path).suffix.casefold() in forbidden_suffixes]

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    for relative in tracked:
        path = ROOT / relative
        if path.is_file() and path.stat().st_size < 1_000_000:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            assert private_key_marker not in text
