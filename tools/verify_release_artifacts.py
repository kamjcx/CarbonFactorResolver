"""Fail closed when release archives contain private or out-of-scope material."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".duckdb", ".doc", ".docx", ".xls", ".xlsx",
    ".pdf", ".pem", ".key", ".p12", ".pfx", ".bak", ".backup", ".dump",
}
FORBIDDEN_PARTS = {"outputs", "datasets", "exports", ".env", "task_plan.md", "findings.md", "progress.md"}


def members(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return tuple(archive.namelist())
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return tuple(archive.getnames())
    raise ValueError(f"unsupported release archive: {path.name}")


def verify_archive(path: Path) -> tuple[str, ...]:
    violations: list[str] = []
    for name in members(path):
        normalized = name.replace("\\", "/")
        parts = set(Path(normalized).parts)
        suffix = Path(normalized).suffix.casefold()
        if suffix in FORBIDDEN_SUFFIXES or parts.intersection(FORBIDDEN_PARTS):
            violations.append(normalized)
        if path.name.endswith(".tar.gz") and "/tests/" in f"/{normalized}/":
            violations.append(normalized)
    return tuple(dict.fromkeys(violations))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()
    violations = {path.name: verify_archive(path) for path in args.archives}
    failed = {name: rows for name, rows in violations.items() if rows}
    if failed:
        for name, rows in failed.items():
            print(f"{name}: {len(rows)} forbidden member(s)")
        return 1
    print(f"verified {len(args.archives)} release archive(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

