"""Generate a reproducible CFR release-candidate evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def build_manifest(
    root: Path,
    evidence_paths: Sequence[Path],
    *,
    image_digest: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    commit = git_output(root, "rev-parse", "HEAD")
    status = git_output(root, "status", "--porcelain", "--untracked-files=no")
    files = []
    for path in evidence_paths:
        target = path if path.is_absolute() else root / path
        resolved = target.resolve()
        relative = resolved.relative_to(root).as_posix()
        files.append({"path": relative, "sha256": sha256_file(resolved), "size": resolved.stat().st_size})
    return {
        "schema_version": "cfr-release-candidate-manifest/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "tracked_worktree_clean": status == "",
        "dependency_lock": {
            "path": "uv.lock",
            "sha256": sha256_file(root / "uv.lock"),
        },
        "docker_image_digest": image_digest,
        "evidence": sorted(files, key=lambda item: item["path"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-digest")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    payload = build_manifest(args.root, args.paths, image_digest=args.image_digest)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"git_commit": payload["git_commit"], "output": output.name}))
    return 0 if payload["tracked_worktree_clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

