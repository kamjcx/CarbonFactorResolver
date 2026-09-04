"""Generate a reproducible CFR release-candidate evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def source_timestamp(root: Path) -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH") or git_output(root, "log", "-1", "--format=%ct")
    try:
        value = int(epoch)
    except ValueError as exc:
        raise ValueError("SOURCE_DATE_EPOCH must be an integer") from exc
    return datetime.fromtimestamp(value, UTC).isoformat()


def build_manifest(
    root: Path,
    evidence_paths: Sequence[Path],
    *,
    image_digest: str | None = None,
    toolchain: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if image_digest is not None and not SHA256_PATTERN.fullmatch(image_digest):
        raise ValueError("image digest must be sha256:<64 lowercase hex characters>")
    commit = git_output(root, "rev-parse", "HEAD")
    status = git_output(root, "status", "--porcelain", "--untracked-files=no")
    files = []
    observed_paths: set[str] = set()
    for path in evidence_paths:
        target = path if path.is_absolute() else root / path
        resolved = target.resolve()
        relative = resolved.relative_to(root).as_posix()
        if relative in observed_paths:
            raise ValueError(f"duplicate evidence path: {relative}")
        if not resolved.is_file():
            raise ValueError(f"evidence path is not a regular file: {relative}")
        observed_paths.add(relative)
        files.append({"path": relative, "sha256": sha256_file(resolved), "size": resolved.stat().st_size})
    source_inputs = {}
    for relative in ("pyproject.toml", "uv.lock", "Dockerfile", ".github/workflows/ci.yml"):
        source = root / relative
        if source.is_file():
            source_inputs[relative] = {"sha256": sha256_file(source), "size": source.stat().st_size}
    return {
        "schema_version": "cfr-release-candidate-manifest/v2",
        "created_at": source_timestamp(root),
        "git_commit": commit,
        "git_tree": git_output(root, "rev-parse", "HEAD^{tree}"),
        "tracked_worktree_clean": status == "",
        "dependency_lock": {
            "path": "uv.lock",
            "sha256": sha256_file(root / "uv.lock"),
        },
        "docker_image_digest": image_digest,
        "source_inputs": source_inputs,
        "toolchain": dict(sorted((toolchain or {}).items())),
        "evidence": sorted(files, key=lambda item: item["path"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-digest")
    parser.add_argument("--runner-image")
    parser.add_argument("--python-version")
    parser.add_argument("--uv-version")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    toolchain = {
        key: value
        for key, value in {
            "runner_image": args.runner_image,
            "python": args.python_version,
            "uv": args.uv_version,
        }.items()
        if value
    }
    payload = build_manifest(
        args.root, args.paths, image_digest=args.image_digest, toolchain=toolchain
    )
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"git_commit": payload["git_commit"], "output": output.name}))
    return 0 if payload["tracked_worktree_clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

