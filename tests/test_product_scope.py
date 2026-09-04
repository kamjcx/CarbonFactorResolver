from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from a1_factor_engine.api import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPOSITORY_ROOT / "src" / "a1_factor_engine"
FILE_PARSING_MODULES = {
    "camelot",
    "docx",
    "easyocr",
    "fitz",
    "odf",
    "ocrmypdf",
    "openpyxl",
    "paddleocr",
    "pandas",
    "pdfplumber",
    "pil",
    "pymupdf",
    "pypdf",
    "pypdf2",
    "pytesseract",
    "tabula",
    "tesseract",
    "textract",
    "tika",
    "unstructured",
    "xlrd",
}
FILE_PARSING_DISTRIBUTIONS = {
    "camelot-py",
    "easyocr",
    "ocrmypdf",
    "odfpy",
    "openpyxl",
    "paddleocr",
    "pandas",
    "pdfplumber",
    "pillow",
    "pymupdf",
    "pypdf",
    "pypdf2",
    "pytesseract",
    "python-docx",
    "tabula-py",
    "textract",
    "tika",
    "unstructured",
    "xlrd",
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0].casefold() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0].casefold())
    return imports


def dependency_name(requirement: str) -> str:
    return requirement.split("[", 1)[0].split(";", 1)[0].split(">", 1)[0].split("<", 1)[0].split("=", 1)[0].strip().casefold()


def test_production_runtime_does_not_import_document_or_ocr_libraries() -> None:
    violations = {
        str(path.relative_to(REPOSITORY_ROOT)): sorted(imported_roots(path) & FILE_PARSING_MODULES)
        for path in RUNTIME_ROOT.rglob("*.py")
        if imported_roots(path) & FILE_PARSING_MODULES
    }

    assert violations == {}


def test_default_and_api_installs_exclude_file_parsing_dependencies() -> None:
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    base = {dependency_name(item) for item in project["dependencies"]}
    api = {dependency_name(item) for item in project["optional-dependencies"]["api"]}

    assert not (base | api) & FILE_PARSING_DISTRIBUTIONS
    assert {dependency_name(item) for item in project["optional-dependencies"]["acceptance-tools"]} == {
        "pdfplumber",
        "python-docx",
    }
    assert {dependency_name(item) for item in project["optional-dependencies"]["energy-db-build"]} == {
        "pdfplumber",
        "openpyxl",
    }
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert '".[api]"' in dockerfile
    assert "acceptance-tools" not in dockerfile
    assert "energy-db-build" not in dockerfile
    assert "tools" in dockerignore
    assert "tests" in dockerignore


def test_resolve_api_is_json_only_and_openapi_has_no_upload_surface() -> None:
    class Resolver:
        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        async def resolve(self, payload: dict[str, object]) -> dict[str, object]:
            self.requests.append(payload)
            return {"request_id": "scope-test", "status": "unresolved"}

    resolver = Resolver()
    app = create_app(engine=resolver)
    schema = app.openapi()
    resolve_content = schema["paths"]["/api/v1/resolve"]["post"]["requestBody"]["content"]

    assert set(resolve_content) == {"application/json"}
    serialized = json.dumps(schema).casefold()
    assert "uploadfile" not in serialized
    assert "multipart/form-data" not in serialized
    assert "application/octet-stream" not in serialized

    with TestClient(app) as client:
        accepted = client.post(
            "/api/v1/resolve",
            json={"material_name": "steel", "quantity": 1},
        )
        rejected = client.post(
            "/api/v1/resolve",
            files={"file": ("evidence.pdf", b"not-a-real-pdf", "application/pdf")},
        )
        rejected_array = client.post("/api/v1/resolve", json=["steel", 1])
        rejected_text = client.post(
            "/api/v1/resolve",
            content='{"material_name":"steel","quantity":1}',
            headers={"content-type": "text/plain"},
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 415
    assert rejected_array.status_code == 422
    assert rejected_text.status_code == 415
    assert len(resolver.requests) == 1
    assert resolver.requests[0]["material_name"] == "steel"
    assert resolver.requests[0]["quantity"] == 1
    assert resolver.requests[0]["request_id"]
