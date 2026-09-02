from __future__ import annotations

import pytest

from tools.autonomous_evaluation.attacks import run_state_machine_attacks


@pytest.mark.asyncio
async def test_state_machine_attack_harness_covers_required_transitions() -> None:
    results = await run_state_machine_attacks()
    assert {item["attack_id"] for item in results} == {
        "APPROVE_UNRETURNED_CANDIDATE",
        "STANDARD_APPROVE_REFERENCE_ONLY",
        "APPROVE_HARD_BLOCKED_CANDIDATE",
        "MODIFY_LOCKED_RESULT",
        "OLD_CATALOG_REPLAY",
        "CATALOG_HASH_TAMPER",
        "REJECTED_CANDIDATE_REAPPROVAL",
        "CONCURRENT_DUPLICATE_APPROVAL_LOCK",
    }
    assert all("passed" in item and "observed" in item for item in results)
    assert all(item["passed"] for item in results)
