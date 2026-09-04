"""Deployment-injected, content-bound catalogue policy contracts."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .integrity import CatalogIntegrityError, canonical_json_bytes, stable_sha256, verify_digest

POLICY_BUNDLE_SCHEMA_VERSION = "cfr.catalog-policy-bundle/v1"
POLICY_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_policy_date(value: str, *, field_name: str) -> date:
    """Parse a canonical calendar date without consulting the wall clock."""

    if not POLICY_DATE_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid calendar date") from exc


@dataclass(frozen=True, slots=True)
class CatalogDatasetPolicy:
    """Reviewed defaults inherited by matching catalogue records only."""

    policy_id: str
    record_categories: tuple[str, ...] = ()
    standards: tuple[str, ...] = ()
    primary_labels: tuple[str, ...] = ()
    indicator: str | None = None
    boundary: str | None = None
    boundary_modules: tuple[str, ...] = ()
    geography: str | None = None
    year: int | None = None
    declared_product_from_name: bool = False
    evidence_citation: str = ""
    production_approval_id: str | None = None
    source_priority_rank: int = 100
    catalog_content_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("catalogue dataset policy requires a policy_id")
        if self.catalog_content_sha256 is not None:
            object.__setattr__(
                self,
                "catalog_content_sha256",
                verify_digest(self.catalog_content_sha256, field_name="catalog_content_sha256"),
            )

    def applies(self, item: Mapping[str, Any], catalog_content_digest: str) -> bool:
        def matches(field: str, allowed: tuple[str, ...]) -> bool:
            if not allowed:
                return True
            observed = str(item.get(field) or "").strip().casefold()
            return observed in {value.strip().casefold() for value in allowed}

        return (
            self.catalog_content_sha256 == catalog_content_digest
            and matches("category", self.record_categories)
            and matches("standard", self.standards)
            and matches("primary_label", self.primary_labels)
        )


PolicySignatureVerifier = Callable[[bytes, str], bool]


@dataclass(frozen=True, slots=True)
class CatalogPolicyBundle:
    """An explicit deployment policy bound to one approved catalogue snapshot."""

    policy_id: str
    version: str
    approved_catalog_content_sha256: str
    effective_from: str
    approved_by: str
    policies: tuple[CatalogDatasetPolicy, ...] = ()
    effective_until: str | None = None
    signature: str | None = None
    schema_version: str = POLICY_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != POLICY_BUNDLE_SCHEMA_VERSION:
            raise ValueError("unsupported catalogue policy bundle schema_version")
        for field_name in ("policy_id", "version", "effective_from", "approved_by"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"catalogue policy bundle requires {field_name}")
        digest = verify_digest(
            self.approved_catalog_content_sha256,
            field_name="approved_catalog_content_sha256",
        )
        object.__setattr__(self, "approved_catalog_content_sha256", digest)
        if any(policy.catalog_content_sha256 != digest for policy in self.policies):
            raise ValueError("every dataset policy must bind to the bundle catalogue digest")
        effective_from = parse_policy_date(self.effective_from, field_name="effective_from")
        if self.effective_until is not None:
            effective_until = parse_policy_date(
                self.effective_until, field_name="effective_until"
            )
            if effective_until < effective_from:
                raise ValueError("effective_until must be on or after effective_from")

    @property
    def content_sha256(self) -> str:
        return stable_sha256(self.signable_payload)

    @property
    def signable_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "version": self.version,
            "approved_catalog_content_sha256": self.approved_catalog_content_sha256,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "approved_by": self.approved_by,
            "policies": self.policies,
        }

    def signature_status(self, verifier: PolicySignatureVerifier | None) -> str:
        if not self.signature:
            return "unsigned"
        if verifier is None:
            return "unverified"
        try:
            verified = verifier(canonical_json_bytes(self.signable_payload), self.signature)
        except Exception as exc:
            raise CatalogIntegrityError("catalogue policy signature verification failed") from exc
        if not verified:
            raise CatalogIntegrityError("catalogue policy signature verification failed")
        return "verified"

    def require_effective_on(self, value: str | None) -> str:
        """Return the audited evaluation date or reject a non-replayable policy use."""

        if value is None:
            raise CatalogIntegrityError(
                "catalogue policy bundle requires explicit policy_effective_on"
            )
        try:
            observed = parse_policy_date(value, field_name="policy_effective_on")
            effective_from = parse_policy_date(
                self.effective_from, field_name="effective_from"
            )
            effective_until = (
                parse_policy_date(self.effective_until, field_name="effective_until")
                if self.effective_until is not None
                else None
            )
        except ValueError as exc:
            raise CatalogIntegrityError(str(exc)) from exc
        if observed < effective_from or (
            effective_until is not None and observed > effective_until
        ):
            raise CatalogIntegrityError(
                "catalogue policy bundle is not effective on policy_effective_on"
            )
        return observed.isoformat()

    @property
    def authorizes_production_approval(self) -> bool:
        return any(policy.production_approval_id for policy in self.policies)
