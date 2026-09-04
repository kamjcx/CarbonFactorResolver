"""Scan public data for delivery-policy violations without echoing sensitive values."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ALLOWED_SUFFIXES = {".json", ".jsonl"}
MAX_PUBLIC_FILE_BYTES = 1_000_000
RESTRICTED_MARKERS = {"confidential", "customer", "internal", "licensed", "private", "proprietary", "restricted"}
SECRET_KEYS = {
    "access_key", "access_token", "api_key", "client_secret", "credential", "credentials",
    "password", "private_key", "secret", "token",
}
WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")


def _pointer(parts: Iterable[str]) -> str:
    escaped = (part.replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped)


def _is_absolute_locator(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith("/")
        or stripped.casefold().startswith("file://")
        or WINDOWS_ABSOLUTE.match(stripped) is not None
    )


def _walk(value: Any, parts: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            yield from _walk(child, (*parts, key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*parts, str(index)))
    else:
        yield parts, parts[-1] if parts else None, value


def _parse_documents(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def scan_public_data(root: Path) -> dict[str, Any]:
    root = root.resolve()
    data_root = root / "data"
    violations: list[dict[str, str]] = []
    scanned = 0
    if not data_root.is_dir():
        violations.append({"path": "data", "location": "/", "reason": "PUBLIC_DATA_MISSING"})
    else:
        for path in sorted(candidate for candidate in data_root.rglob("*") if candidate.is_file()):
            relative = path.relative_to(root).as_posix()
            scanned += 1
            lowered_parts = {part.casefold() for part in path.relative_to(data_root).parts}
            if lowered_parts.intersection(RESTRICTED_MARKERS):
                violations.append({"path": relative, "location": "/", "reason": "RESTRICTED_PATH"})
            if path.suffix.casefold() not in ALLOWED_SUFFIXES:
                violations.append({"path": relative, "location": "/", "reason": "NON_REVIEWABLE_FORMAT"})
                continue
            if path.stat().st_size >= MAX_PUBLIC_FILE_BYTES:
                violations.append({"path": relative, "location": "/", "reason": "PUBLIC_FILE_TOO_LARGE"})
                continue
            try:
                documents = _parse_documents(path)
            except (UnicodeDecodeError, json.JSONDecodeError):
                violations.append({"path": relative, "location": "/", "reason": "INVALID_PUBLIC_JSON"})
                continue
            for document_index, document in enumerate(documents):
                prefix = (str(document_index),) if len(documents) > 1 else ()
                for parts, key, value in _walk(document, prefix):
                    normalized_key = (key or "").casefold().replace("-", "_")
                    location = _pointer(parts)
                    if normalized_key in SECRET_KEYS and value not in (None, "", "REDACTED"):
                        violations.append({"path": relative, "location": location, "reason": "SECRET_VALUE"})
                    if isinstance(value, str) and _is_absolute_locator(value):
                        violations.append({"path": relative, "location": location, "reason": "ABSOLUTE_LOCAL_PATH"})
                    if normalized_key in {"classification", "confidentiality", "license", "visibility"}:
                        words = set(re.findall(r"[a-z]+", str(value).casefold()))
                        if words.intersection(RESTRICTED_MARKERS):
                            violations.append({"path": relative, "location": location, "reason": "RESTRICTED_CONTENT"})
    ordered = sorted(violations, key=lambda item: (item["path"], item["location"], item["reason"]))
    return {
        "schema_version": "cfr-public-delivery-scan/v1",
        "passed": not ordered,
        "scanned_files": scanned,
        "violations": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = scan_public_data(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "scanned_files": report["scanned_files"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
