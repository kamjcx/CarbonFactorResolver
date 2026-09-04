"""Fail closed when release archives contain private or out-of-scope material."""

from __future__ import annotations

import argparse
import re
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

FORBIDDEN_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".duckdb", ".doc", ".docx", ".xls", ".xlsx",
    ".pdf", ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".bak", ".backup",
    ".dump", ".mdb", ".accdb", ".log", ".zip", ".7z", ".tar", ".gz",
}
FORBIDDEN_PARTS = {
    "outputs", "datasets", "exports", ".env", "tests", "restricted", "customer", "customers",
    "private", "licensed", "task_plan.md", "findings.md", "progress.md",
}
WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")
SECRET_ASSIGNMENT = re.compile(
    rb'''(?ix)["']?(?:api[_-]?key|access[_-]?(?:key|token)|aws[_-]?secret[_-]?access[_-]?key|client[_-]?secret|password|private[_-]?key)'''
    rb'''["']?\s*[:=]\s*["'][^"']{4,}["']'''
)
MAX_INSPECTED_MEMBER_BYTES = 1_000_000


def _path_words(value: str) -> set[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return set(re.findall(r"[a-z0-9]+", separated.casefold()))


def members(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return tuple(archive.namelist())
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return tuple(archive.getnames())
    raise ValueError(f"unsupported release archive: {path.name}")


def content_violations(path: Path) -> tuple[str, ...]:
    violations: list[str] = []
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir() or info.file_size > MAX_INSPECTED_MEMBER_BYTES:
                    continue
                payload = archive.read(info)
                if SECRET_ASSIGNMENT.search(payload):
                    violations.append(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    target = payload.decode("utf-8", errors="ignore")
                    if _unsafe_member_path(target):
                        violations.append(info.filename)
        return tuple(dict.fromkeys(violations))
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for info in archive.getmembers():
                if info.issym() or info.islnk():
                    if _unsafe_member_path(info.linkname):
                        violations.append(info.name)
                    continue
                if not info.isfile() or info.size > MAX_INSPECTED_MEMBER_BYTES:
                    continue
                extracted = archive.extractfile(info)
                if extracted is not None and SECRET_ASSIGNMENT.search(extracted.read()):
                    violations.append(info.name)
        return tuple(dict.fromkeys(violations))
    raise ValueError(f"unsupported release archive: {path.name}")


def _unsafe_member_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parsed = PurePosixPath(normalized)
    return (
        normalized.startswith("/")
        or WINDOWS_ABSOLUTE.match(normalized) is not None
        or ".." in parsed.parts
    )


def verify_archive(path: Path) -> tuple[str, ...]:
    violations: list[str] = []
    for name in members(path):
        normalized = name.replace("\\", "/")
        parsed = PurePosixPath(normalized)
        parts = set().union(*(_path_words(part) for part in parsed.parts))
        filename = parsed.name.casefold()
        suffix = parsed.suffix.casefold()
        unsafe_path = _unsafe_member_path(normalized)
        environment_file = filename == ".env" or filename.startswith(".env.")
        database_sidecar = ".db-" in filename or ".sqlite-" in filename
        if (
            unsafe_path
            or environment_file
            or database_sidecar
            or suffix in FORBIDDEN_SUFFIXES
            or parts.intersection(FORBIDDEN_PARTS)
        ):
            violations.append(normalized)
    violations.extend(content_violations(path))
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

