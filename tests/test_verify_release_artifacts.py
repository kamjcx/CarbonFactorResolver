from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from tools.verify_release_artifacts import verify_archive


def test_release_archive_verifier_accepts_code_and_rejects_private_members(tmp_path: Path) -> None:
    wheel = tmp_path / "safe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("a1_factor_engine/__init__.py", "")
        archive.writestr("share/carbon-factor-resolver/benchmarks/public.jsonl", "{}")
    assert verify_archive(wheel) == ()

    payload = tmp_path / "payload.txt"
    payload.write_text("secret", encoding="utf-8")
    sdist = tmp_path / "unsafe.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(payload, arcname="package/tests/private.db")
    assert verify_archive(sdist) == ("package/tests/private.db",)

