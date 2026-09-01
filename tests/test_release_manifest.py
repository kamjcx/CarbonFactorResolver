from __future__ import annotations

from pathlib import Path

from tools.release_manifest import build_manifest, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def test_release_manifest_uses_relative_paths_hashes_and_frozen_commit() -> None:
    manifest = build_manifest(ROOT, [Path("README.md"), Path("uv.lock")])
    assert len(manifest["git_commit"]) == 40
    assert manifest["dependency_lock"]["sha256"] == sha256_file(ROOT / "uv.lock")
    assert [item["path"] for item in manifest["evidence"]] == ["README.md", "uv.lock"]
    assert all(len(item["sha256"]) == 64 for item in manifest["evidence"])
    assert all(not Path(item["path"]).is_absolute() for item in manifest["evidence"])

