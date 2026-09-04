"""Deployment-owned resolver policy.

Formal callers cannot lower safety or ranking thresholds in their JSON request.
"""

from __future__ import annotations

from dataclasses import dataclass

from .integrity import stable_sha256


@dataclass(frozen=True, slots=True)
class DeploymentPolicy:
    min_score: float = 0.65

    def __post_init__(self) -> None:
        if not 0 <= self.min_score <= 1:
            raise ValueError("deployment min_score must be between 0 and 1")

    @property
    def anchor_sha256(self) -> str:
        return stable_sha256({
            "schema_version": "cfr.deployment-policy/v1",
            "min_score": self.min_score,
        })
