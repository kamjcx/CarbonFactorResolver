"""Reference in-memory and null adapters.

The repository adapters are intentionally tiny: replacing them with a port
implementation backed by the future database/API does not change graph logic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.request import urlopen

from .catalog_policy import (
    CatalogDatasetPolicy,
    CatalogPolicyBundle,
    PolicySignatureVerifier,
)
from .integrity import (
    CATALOG_SCHEMA_VERSION,
    CatalogIntegrityError,
    PersistenceIntegrityError,
    ReviewStateConflictError,
    StaleReviewRevisionError,
    catalog_content_sha256,
    stable_sha256,
    verify_digest,
)
from .matching import normalize_text
from .material_registry import DEFAULT_MATERIAL_REGISTRY, MaterialSemanticRegistryPort
from .models import (
    ApprovalRecord,
    ApprovalStatus,
    DatabaseVersionAnchor,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    LinkAttempt,
    LinkOutcome,
    LinkStrategy,
    LockedResolution,
    LockedResolutionEvidenceSnapshot,
    MaterialCategory,
    MaterialClass,
    MaterialInterpretation,
    NormalizedActivity,
    ParameterEvidence,
    PipelineFunnel,
    Recommendation,
    RecordConversionDiagnostic,
    ReferenceFlowRecord,
    ResolutionRequest,
    ResolutionTrace,
    ResultTier,
    RetrievalDiagnostic,
    RetrievalIntent,
    RetrievalResult,
    SemanticAssessment,
    SourceQualityStatus,
    SourceRecord,
)
from .semantic_index import SemanticFactorIndex


def _norm(value: str | None) -> str:
    return normalize_text(value).value


def _record_aliases(record: SourceRecord) -> set[str]:
    raw = record.metadata.get("aliases", "")
    if not raw:
        return set()
    if isinstance(raw, (list, tuple)):
        parsed = list(raw)
    else:
        try:
            parsed = json.loads(str(raw))
        except json.JSONDecodeError:
            parsed = [part.strip() for part in str(raw).split(",")]
    if not isinstance(parsed, list):
        parsed = [parsed]
    return {_norm(str(value)) for value in parsed if _norm(str(value))}


def _with_match_strategy(record: SourceRecord, strategy: LinkStrategy) -> SourceRecord:
    return replace(record, metadata={**record.metadata, "match_strategy": strategy.value})


def _material_terms(value: str | None) -> set[str]:
    normalized = _norm(value)
    latin = {part for part in normalized.split() if len(part) >= 3}
    cjk = "".join(char for char in normalized if "\u4e00" <= char <= "\u9fff")
    grams = {cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))}
    process_terms = {
        "fused", "electrofused", "sintered", "calcined", "electric", "fusion",
        "电熔", "烧结", "煅烧",
    }
    return (latin | grams) - process_terms


def _related_material(
    activity: NormalizedActivity,
    source_name: str,
    registry: MaterialSemanticRegistryPort,
) -> bool:
    target = activity.material_identity
    observed = registry.resolve(source_name).identity
    if target and target.head_material and observed.head_material:
        if target.head_material == observed.head_material:
            return True
    if target and target.product_form and target.product_form == observed.product_form:
        return True
    return bool(_material_terms(activity.canonical_name) & _material_terms(source_name))


@dataclass(slots=True)
class InMemoryFactorRepository:
    records: list[SourceRecord]
    source_types: tuple[FactorSourceType, ...] | None = None
    anchor: DatabaseVersionAnchor | None = None
    material_registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY

    def _content_digest(self) -> str:
        return stable_sha256({
            "schema_version": CATALOG_SCHEMA_VERSION,
            "records": tuple(
                record.content_sha256
                for record in sorted(self.records, key=lambda item: item.source_id)
            ),
        })

    def __post_init__(self) -> None:
        content_digest = self._content_digest()
        if self.anchor is None:
            self.anchor = DatabaseVersionAnchor(
                catalog_name="in-memory-factor-catalog",
                catalog_version="test-v1",
                database_sha256=content_digest,
                locator="memory://factor-catalog",
                schema_version=CATALOG_SCHEMA_VERSION,
                publisher_id="in-memory",
                catalog_content_sha256=content_digest,
            )
        elif self.anchor.schema_version == CATALOG_SCHEMA_VERSION:
            if self.anchor.content_sha256 != content_digest:
                raise CatalogIntegrityError(
                    "in-memory catalog declared SHA-256 does not match actual record content"
                )
        else:
            self.anchor = replace(self.anchor, catalog_content_sha256=content_digest)

    async def search(self, intent: RetrievalIntent) -> RetrievalResult:
        if self.anchor is None:
            raise CatalogIntegrityError("in-memory catalog anchor is not configured")
        if self.anchor.content_sha256 != self._content_digest():
            raise CatalogIntegrityError(
                "in-memory catalog declared SHA-256 does not match actual record content"
            )
        allowed = self.source_types
        eligible = tuple(
            record for record in self.records
            if allowed is None or record.source_type in allowed
        )
        index = SemanticFactorIndex(eligible, self.anchor, self.material_registry)
        result = index.query(intent)
        return RetrievalResult(
            result.records, self.anchor, result.attempts, result.observations, result.anchor
        )


@dataclass(slots=True)
class InMemoryProxyRepository:
    records: list[SourceRecord]

    async def search(self, activity: NormalizedActivity, material_class: MaterialClass) -> Sequence[SourceRecord]:
        family = _norm(material_class.family or material_class.name)
        class_name = _norm(material_class.name)
        results: list[SourceRecord] = []
        for record in self.records:
            haystack = " ".join(
                [_norm(record.material_name), _norm(record.metadata.get("material_class", "")), _norm(record.metadata.get("family", ""))]
            )
            if class_name in haystack or family in haystack or not family:
                results.append(record)
        return tuple(results)


class NullFactorRepository:
    async def search(self, intent: RetrievalIntent) -> RetrievalResult:
        return RetrievalResult(
            (),
            DatabaseVersionAnchor(
                catalog_name="unconfigured-factor-catalog",
                catalog_version="none",
                database_sha256=None,
                locator="none://factor-catalog",
            ),
            (
                LinkAttempt(LinkStrategy.EXACT, LinkOutcome.NO_MATCH, reason="local factor repository is unconfigured"),
                LinkAttempt(LinkStrategy.SYNONYM, LinkOutcome.NO_MATCH, reason="local factor repository is unconfigured"),
                LinkAttempt(LinkStrategy.RELATED, LinkOutcome.NO_MATCH, reason="local factor repository is unconfigured"),
            ),
        )


@dataclass(slots=True)
class HttpCatalogFactorRepository:
    """Read-only adapter for the formal `/api/v2/factors/catalog` endpoint."""

    endpoint: str = "http://127.0.0.1:5004/api/v2/factors/catalog"
    expected_sha256: str | None = None
    timeout_seconds: float = 10.0
    fetch_json: Callable[[str], Mapping[str, Any]] | None = None
    signature_verifier: Callable[[Mapping[str, Any], bytes], bool] | None = None
    material_registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY
    policy_bundle: CatalogPolicyBundle | None = None
    policy_signature_verifier: PolicySignatureVerifier | None = None
    policy_effective_on: str | None = None
    dataset_policies: tuple[CatalogDatasetPolicy, ...] = ()
    _cached_index_key: str | None = field(default=None, init=False)
    _cached_index: SemanticFactorIndex | None = field(default=None, init=False)
    _cached_conversion_diagnostics: tuple[RecordConversionDiagnostic, ...] = field(
        default=(), init=False
    )

    async def search(self, intent: RetrievalIntent) -> RetrievalResult:
        if self.dataset_policies:
            raise CatalogIntegrityError(
                "legacy dataset_policies are disabled; inject a content-bound policy_bundle"
            )
        payload = await asyncio.to_thread(self._fetch)
        records = payload.get("records")
        if not isinstance(records, list):
            raise CatalogIntegrityError("factor catalog response lacks records")
        if not all(isinstance(item, Mapping) for item in records):
            raise CatalogIntegrityError("factor catalog records must be JSON objects")
        raw_records = tuple(item for item in records if isinstance(item, Mapping))
        actual_content_digest = catalog_content_sha256(raw_records)
        applied_bundle = self.policy_bundle
        bundle_signature_status = "not_configured"
        bundle_effective_on = ""
        dataset_policies: tuple[CatalogDatasetPolicy, ...] = ()
        if applied_bundle is not None:
            bundle_effective_on = applied_bundle.require_effective_on(
                self.policy_effective_on
            )
            if applied_bundle.approved_catalog_content_sha256 != actual_content_digest:
                raise CatalogIntegrityError(
                    "catalogue policy bundle does not match the observed catalog content"
                )
            bundle_signature_status = applied_bundle.signature_status(
                self.policy_signature_verifier
            )
            if (
                applied_bundle.authorizes_production_approval
                and bundle_signature_status != "verified"
            ):
                raise CatalogIntegrityError(
                    "production approval policy requires a verified bundle signature"
                )
            dataset_policies = applied_bundle.policies
        manifest = payload.get("manifest")
        schema_version = "legacy-catalog/v1"
        publisher_id = "unverified-legacy"
        publisher_identity_verified = False
        if manifest is not None:
            if not isinstance(manifest, Mapping):
                raise CatalogIntegrityError("catalog manifest must be a JSON object")
            schema_version = str(manifest.get("schema_version") or "").strip()
            if schema_version != CATALOG_SCHEMA_VERSION:
                raise CatalogIntegrityError("unsupported catalog manifest schema_version")
            declared_content_digest = verify_digest(
                manifest.get("catalog_content_sha256"),
                field_name="catalog_content_sha256",
            )
            if declared_content_digest != actual_content_digest:
                raise CatalogIntegrityError(
                    "catalog declared SHA-256 does not match actual record content"
                )
            publisher_id = str(manifest.get("publisher_id") or "").strip()
            if not publisher_id:
                raise CatalogIntegrityError("catalog manifest requires publisher_id")
            signature = manifest.get("signature")
            if signature is not None:
                if self.signature_verifier is None:
                    raise CatalogIntegrityError(
                        "signed catalog manifest has no configured signature verifier"
                    )
                publisher_identity_verified = bool(
                    self.signature_verifier(manifest, actual_content_digest.encode("ascii"))
                )
                if not publisher_identity_verified:
                    raise CatalogIntegrityError("catalog publisher signature verification failed")
        database = payload.get("database")
        if not isinstance(database, Mapping):
            raise CatalogIntegrityError("factor catalog response lacks database metadata")
        artifact_digest = str(database.get("sha256") or "").strip().lower()
        if self.expected_sha256 and artifact_digest != self.expected_sha256.strip().lower():
            raise CatalogIntegrityError(
                "formal factor database SHA-256 does not match the configured anchor"
            )
        anchor = DatabaseVersionAnchor(
            catalog_name=str(database.get("name") or "formal-factor-catalog"),
            catalog_version=str(payload.get("catalog_version") or "unknown"),
            database_sha256=artifact_digest or None,
            catalog_content_sha256=actual_content_digest,
            locator=self.endpoint,
            schema_version=schema_version,
            publisher_id=publisher_id,
            publisher_identity_verified=publisher_identity_verified,
        )
        policy_key = (
            stable_sha256({
                "content_sha256": applied_bundle.content_sha256,
                "effective_on": bundle_effective_on,
                "signature_sha256": stable_sha256(applied_bundle.signature or ""),
                "signature_status": bundle_signature_status,
            })
            if applied_bundle is not None
            else "none"
        )
        cache_key = (
            f"{anchor.identity}:{self.material_registry.sha256}:"
            f"{policy_key}:{actual_content_digest}"
        )
        if self._cached_index is None or self._cached_index_key != cache_key:
            converted_items: list[SourceRecord] = []
            conversion_diagnostics: list[RecordConversionDiagnostic] = []
            for position, item in enumerate(records):
                if not isinstance(item, Mapping):
                    conversion_diagnostics.append(RecordConversionDiagnostic(
                        source_id=f"catalog-position:{position}", raw_name="", success=False,
                        reason_codes=("record_not_object",),
                    ))
                    continue
                source_id = str(item.get("record_id") or item.get("code") or f"catalog-position:{position}").strip()
                raw_name = str(item.get("name") or "").strip()
                reasons: list[str] = []
                dropped_fields: list[str] = []
                try:
                    raw_value = item.get("primary_value")
                    value = float("" if raw_value is None else raw_value)
                    if not (value >= 0 and value < float("inf")):
                        reasons.append("primary_value_missing_or_invalid")
                except (TypeError, ValueError):
                    reasons.append("primary_value_missing_or_invalid")
                if not str(item.get("primary_unit") or "").strip():
                    reasons.append("primary_unit_missing")
                    dropped_fields.append("primary_unit")
                if not source_id or not raw_name:
                    reasons.append("record_identity_missing")
                source = None
                if not reasons:
                    try:
                        source = self._to_source_record(
                            item,
                            anchor,
                            dataset_policies,
                            actual_content_digest,
                            applied_bundle,
                            bundle_signature_status,
                            bundle_effective_on,
                        )
                    except (TypeError, ValueError) as exc:
                        reasons.append("record_validation_failed")
                        dropped_fields.append(type(exc).__name__)
                success = source is not None
                if source is not None:
                    converted_items.append(source)
                elif not reasons:
                    reasons.append("adapter_returned_none")
                conversion_diagnostics.append(RecordConversionDiagnostic(
                    source_id=source_id, raw_name=raw_name, success=success,
                    dropped_fields=tuple(dropped_fields), reason_codes=tuple(reasons),
                ))
            converted = tuple(converted_items)
            self._cached_index = SemanticFactorIndex(converted, anchor, self.material_registry)
            self._cached_index_key = cache_key
            self._cached_conversion_diagnostics = tuple(conversion_diagnostics)
        result = self._cached_index.query(intent)
        cached_conversion_diagnostics = self._cached_conversion_diagnostics
        retrieval_diagnostics = tuple(
            RetrievalDiagnostic(
                stage="semantic_index", strategy=attempt.strategy.value,
                query=intent.canonical_name, entity_id=intent.base_entity_id,
                outcome=attempt.outcome.value,
                reason_code=("retrieval_hit" if attempt.candidate_source_ids else "retrieval_miss"),
                details={"candidate_source_ids": attempt.candidate_source_ids, "reason": attempt.reason},
            )
            for attempt in result.attempts
        )
        return RetrievalResult(
            result.records, anchor, result.attempts, result.observations, result.anchor,
            retrieval_diagnostics, cached_conversion_diagnostics,
            PipelineFunnel(
                raw_catalog_records=len(records), retrieval_hits=len(result.records),
                converted_records=sum(item.success for item in cached_conversion_diagnostics),
            ),
        )

    def _fetch(self) -> Mapping[str, Any]:
        if self.fetch_json is not None:
            return self.fetch_json(self.endpoint)
        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("factor catalog endpoint must use HTTP or HTTPS")
        # Endpoint is deployment-configured and restricted to HTTP(S) above.
        with urlopen(  # noqa: S310  # nosec B310
            self.endpoint, timeout=self.timeout_seconds
        ) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("factor catalog response must be a JSON object")
        return value

    @staticmethod
    def _exact_match(item: Mapping[str, Any], query: str) -> bool:
        observed = {_norm(str(item.get("name") or "")), _norm(str(item.get("code") or ""))}
        return bool(query and query in observed)

    @staticmethod
    def _synonym_match(item: Mapping[str, Any], query: str, request_aliases: set[str]) -> bool:
        raw_aliases = item.get("aliases")
        item_aliases: list[Any] = raw_aliases if isinstance(raw_aliases, list) else []
        aliases = {_norm(str(alias)) for alias in item_aliases if _norm(str(alias))}
        name = _norm(str(item.get("name") or ""))
        return bool((name and name in request_aliases) or (query and query in aliases) or request_aliases & aliases)

    @classmethod
    def _convert_items(
        cls, items: Sequence[Mapping[str, Any]], anchor: DatabaseVersionAnchor, strategy: LinkStrategy
    ) -> tuple[SourceRecord, ...]:
        converted = (cls._to_source_record(item, anchor) for item in items)
        return tuple(_with_match_strategy(record, strategy) for record in converted if record is not None)

    @staticmethod
    def _to_source_record(
        item: Mapping[str, Any],
        anchor: DatabaseVersionAnchor,
        dataset_policies: Sequence[CatalogDatasetPolicy] = (),
        catalog_content_digest: str | None = None,
        policy_bundle: CatalogPolicyBundle | None = None,
        policy_bundle_signature_status: str = "not_configured",
        policy_bundle_effective_on: str = "",
    ) -> SourceRecord | None:
        try:
            raw_value = item.get("primary_value")
            value = float("" if raw_value is None else raw_value)
        except (TypeError, ValueError):
            return None
        unit = str(item.get("primary_unit") or "").strip()
        if not unit:
            return None
        source_id = str(item.get("record_id") or item.get("code") or "").strip()
        material_name = str(item.get("name") or "").strip()
        if not source_id or not material_name:
            return None
        applied_policies = tuple(
            policy for policy in dataset_policies
            if catalog_content_digest is not None
            and policy.applies(item, catalog_content_digest)
        )

        def inherited(field: str) -> object | None:
            explicit = item.get(field)
            if explicit not in (None, "", (), []):
                return explicit
            values = tuple(dict.fromkeys(
                value
                for policy in applied_policies
                for value in (getattr(policy, field),)
                if value not in (None, "", (), [])
            ))
            if len(values) > 1:
                raise ValueError(f"conflicting catalogue dataset policies for {field}")
            return values[0] if values else explicit

        year_value = inherited("year")
        try:
            year = int(str(year_value)) if year_value not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        raw_kind = str(item.get("factor_kind") or item.get("category") or "other").strip().lower()
        raw_subject_type = str(item.get("subject_type") or "unknown").strip().lower()
        try:
            subject_type = FactorSubjectType(raw_subject_type)
        except ValueError:
            subject_type = FactorSubjectType.UNKNOWN
        raw_quality_status = str(item.get("source_quality_status") or "NEEDS_REVIEW").strip().upper()
        try:
            source_quality_status = SourceQualityStatus(raw_quality_status)
        except ValueError:
            source_quality_status = SourceQualityStatus.NEEDS_REVIEW
        admission_value = item.get("admission_eligible", False)
        admission_eligible = admission_value if type(admission_value) is bool else False
        aliases = item.get("aliases")
        catalog_locator = f"{anchor.locator}#{source_id}"
        source_document_locator = str(
            item.get("source_document_locator")
            or item.get("document_url")
            or item.get("source_url")
            or item.get("source_path")
            or ""
        ).strip() or None
        source_document_sha256 = str(
            item.get("source_document_sha256") or item.get("source_sha256") or ""
        ).strip().lower() or None
        page = str(item.get("page") or "").strip() or None
        table = str(item.get("table") or "").strip() or None
        row = str(item.get("row") or "").strip() or None
        approved_dataset_ids = tuple(
            policy.production_approval_id
            for policy in applied_policies
            if policy.production_approval_id
        )
        def inferred_source_priority_rank() -> int:
            if applied_policies:
                return min(policy.source_priority_rank for policy in applied_policies)
            source_version = str(item.get("source_version") or "").casefold()
            source_name = str(item.get("source_name") or item.get("source") or "").casefold()
            source_identity = f"{source_name} {source_version}"
            if "ecoinvent" in source_identity and "3.10" in source_identity:
                return 10
            if "ecoinvent" in source_identity and "3.12" in source_identity:
                return 20
            return 100

        explicit_source_rank = item.get("source_priority_rank")
        source_priority_issue = ""
        if explicit_source_rank not in (None, ""):
            if (
                type(explicit_source_rank) is int
                and 0 <= explicit_source_rank <= 1000
            ):
                source_priority_rank = explicit_source_rank
            else:
                source_priority_rank = inferred_source_priority_rank()
                source_priority_issue = (
                    f"invalid source_priority_rank={explicit_source_rank!r}; "
                    f"fell back to inferred rank {source_priority_rank}"
                )
        else:
            source_priority_rank = inferred_source_priority_rank()
        governance_text = " ".join(str(item.get(field) or "") for field in (
            "document_status",
            "source_status",
            "upstream_source_status",
            "standard",
            "source_version",
        )).casefold()
        governance_markers = {
            "draft_or_consultation": ("draft", "consultation", "征求意见", "草案"),
            "aggregated_source": ("aggregated", "aggregate", "聚合"),
            "pending_review": ("pending review", "review-only", "待审核", "待审"),
        }
        governance_reasons = tuple(
            reason
            for reason, markers in governance_markers.items()
            if any(marker in governance_text for marker in markers)
        )
        result_tier_cap = (
            ResultTier.REFERENCE_ONLY.value
            if governance_reasons and not approved_dataset_ids
            else ""
        )
        metadata = {
            "catalog_version": anchor.catalog_version,
            "database_sha256": anchor.database_sha256 or "",
            "catalog_content_sha256": anchor.content_sha256 or "",
            "catalog_schema_version": anchor.schema_version,
            "catalog_publisher_id": anchor.publisher_id,
            "catalog_publisher_identity_verified": str(
                anchor.publisher_identity_verified
            ).lower(),
            "record_category": str(item.get("category") or ""),
            "document_status": str(item.get("document_status") or ""),
            "source_priority": str(item.get("source_priority") or ""),
            "source_priority_rank": str(source_priority_rank),
            "source_priority_policy": "catalog-explicit-or-version-fallback/v1",
            "source_priority_issue": source_priority_issue,
            "aliases": json.dumps(aliases, ensure_ascii=False) if isinstance(aliases, list) else "",
            "catalog_locator": catalog_locator,
            "source_document_locator": source_document_locator or "",
            "source_document_sha256": source_document_sha256 or "",
            "source_document_page": page or "",
            "source_document_table": table or "",
            "source_document_row": row or "",
            "subject_type": subject_type.value,
            "source_quality_status": source_quality_status.value,
            "admission_eligible": str(admission_eligible).lower(),
            "cross_format_verified": str(item.get("cross_format_verified") or ""),
            "parser_version": str(item.get("parser_version") or ""),
            "extraction_confidence": str(item.get("extraction_confidence") or ""),
            "license": str(item.get("license") or ""),
            "evidence_cell_bbox": json.dumps(item.get("evidence_cell_bbox"), ensure_ascii=False),
            "primary_label": str(item.get("primary_label") or ""),
            "scope": str(item.get("scope") or ""),
            "standard": str(item.get("standard") or ""),
            "source_version": str(item.get("source_version") or ""),
            "source_status": str(item.get("source_status") or ""),
            "upstream_source_status": str(item.get("upstream_source_status") or ""),
            "includes_process": str(item.get("includes_process") or ""),
            "catalog_dataset_policy_ids": json.dumps(
                tuple(policy.policy_id for policy in applied_policies), ensure_ascii=False
            ),
            "catalog_policy_bundle_id": policy_bundle.policy_id if policy_bundle else "",
            "catalog_policy_bundle_version": policy_bundle.version if policy_bundle else "",
            "catalog_policy_bundle_content_sha256": (
                policy_bundle.content_sha256 if policy_bundle else ""
            ),
            "catalog_policy_bundle_effective_from": (
                policy_bundle.effective_from if policy_bundle else ""
            ),
            "catalog_policy_bundle_effective_until": (
                policy_bundle.effective_until or "" if policy_bundle else ""
            ),
            "catalog_policy_bundle_approved_by": policy_bundle.approved_by if policy_bundle else "",
            "catalog_policy_bundle_signature_status": policy_bundle_signature_status,
            "catalog_policy_bundle_effective_on": policy_bundle_effective_on,
            "catalog_dataset_approval_ids": json.dumps(
                approved_dataset_ids, ensure_ascii=False
            ),
            "result_tier_cap": result_tier_cap,
            "result_tier_cap_reasons": json.dumps(
                governance_reasons, ensure_ascii=False
            ),
            "catalog_dataset_policy_evidence": json.dumps(
                tuple(policy.evidence_citation for policy in applied_policies),
                ensure_ascii=False,
            ),
            "catalog_inherited_fields": json.dumps(
                tuple(
                    field
                    for field in (
                        "indicator", "boundary", "boundary_modules", "geography", "year"
                    )
                    if item.get(field) in (None, "", (), [])
                    and inherited(field) not in (None, "", (), [])
                ) + (
                    ("declared_product",)
                    if not item.get("declared_product")
                    and any(policy.declared_product_from_name for policy in applied_policies)
                    else ()
                ),
                ensure_ascii=False,
            ),
        }
        kind_aliases = {
            "lifecycle": FactorKind.LIFECYCLE_FACTOR,
            "lifecycle_factor": FactorKind.LIFECYCLE_FACTOR,
            "epd": FactorKind.EPD_INDICATOR,
            "epd_indicator": FactorKind.EPD_INDICATOR,
            "emission_limit": FactorKind.EMISSION_LIMIT,
            "emission-limit": FactorKind.EMISSION_LIMIT,
            "energy_factor": FactorKind.ENERGY_FACTOR,
            "energy-factor": FactorKind.ENERGY_FACTOR,
            "combustion_factor": FactorKind.COMBUSTION_FACTOR,
            "combustion-factor": FactorKind.COMBUSTION_FACTOR,
            "transport_factor": FactorKind.TRANSPORT_FACTOR,
            "transport-factor": FactorKind.TRANSPORT_FACTOR,
            "derived_proxy": FactorKind.DERIVED_PROXY_FACTOR,
        }
        factor_kind = kind_aliases.get(raw_kind, FactorKind.OTHER)
        raw_source_type = str(item.get("source_type") or "").strip().lower()
        source_type = {
            "epd": FactorSourceType.EPD,
            "literature": FactorSourceType.LITERATURE,
            "supplier": FactorSourceType.SUPPLIER,
            "external_database": FactorSourceType.EXTERNAL_DATABASE,
        }.get(raw_source_type, FactorSourceType.EPD if factor_kind == FactorKind.EPD_INDICATOR else FactorSourceType.LOCAL_DATABASE)
        boundary_modules = inherited("boundary_modules")
        if isinstance(boundary_modules, str):
            boundary_modules = tuple(part.strip() for part in boundary_modules.split(",") if part.strip())
        elif isinstance(boundary_modules, list):
            boundary_modules = tuple(str(part) for part in boundary_modules)
        else:
            boundary_modules = ()
        return SourceRecord(
            source_id=source_id,
            source_type=source_type,
            provider=str(item.get("source_name") or item.get("source") or anchor.catalog_name),
            locator=source_document_locator or catalog_locator,
            material_name=material_name,
            factor_value=value,
            factor_unit=unit,
            geography=str(inherited("geography") or item.get("location") or "").strip() or None,
            year=year,
            product_form=str(item.get("product_form") or "").strip() or None,
            composition=str(item.get("composition") or "").strip() or None,
            production_process=str(item.get("production_process") or item.get("process") or "").strip() or None,
            boundary=str(inherited("boundary") or "").strip() or None,
            citation=str(item.get("source_citation") or item.get("source") or ""),
            excerpt=str(item.get("notes") or ""),
            metadata=metadata,
            factor_kind=factor_kind,
            subject_type=subject_type,
            source_quality_status=source_quality_status,
            admission_eligible=admission_eligible,
            indicator=str(inherited("indicator") or "").strip() or None,
            declared_product=(
                str(item.get("declared_product") or "").strip()
                or (
                    material_name
                    if any(policy.declared_product_from_name for policy in applied_policies)
                    else None
                )
            ),
            boundary_modules=boundary_modules,
            catalog_locator=catalog_locator,
            source_document_sha256=source_document_sha256,
            page=page,
            table=table,
            row=row,
        )


class NullProxyRepository:
    async def search(self, activity: NormalizedActivity, material_class: MaterialClass) -> Sequence[SourceRecord]:
        return ()


@dataclass(slots=True)
class InMemoryReferenceFlowRepository:
    records: list[ReferenceFlowRecord]

    async def search(self, activity: NormalizedActivity) -> Sequence[ReferenceFlowRecord]:
        target = _norm(activity.canonical_name)
        unit = _norm(activity.original_quantity_unit)
        return tuple(
            record for record in self.records
            if _norm(record.material_name) == target and _norm(record.reference_unit) == unit
        )


@dataclass(slots=True)
class InMemoryProcessParameterRepository:
    evidence: list[ParameterEvidence]

    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[ParameterEvidence]:
        target = _norm(activity.canonical_name)
        target_process = _norm(activity.production_process)
        return tuple(
            item for item in self.evidence
            if item.metadata.get("reference_source_id") == reference.source_id
            and _norm(item.metadata.get("target_material") or item.metadata.get("target_material_id")) == target
            and (
                not target_process
                or _norm(item.metadata.get("target_process") or item.metadata.get("target_process_id"))
                == target_process
            )
        )


@dataclass(slots=True)
class InMemoryGradeSeriesRepository:
    records: list[SourceRecord]

    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[SourceRecord]:
        series_id = _norm(reference.metadata.get("series_id") or reference.metadata.get("series"))
        if not series_id:
            return ()
        return tuple(
            record for record in self.records
            if record.source_id != reference.source_id
            and _norm(record.metadata.get("series_id") or record.metadata.get("series")) == series_id
        )


class NullReferenceFlowRepository:
    async def search(self, activity: NormalizedActivity) -> Sequence[ReferenceFlowRecord]:
        return ()


class NullProcessParameterRepository:
    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[ParameterEvidence]:
        return ()


class NullGradeSeriesRepository:
    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[SourceRecord]:
        return ()


class DeterministicMaterialUnderstanding:
    """Offline fallback; replace with an LLM adapter for richer semantics."""

    async def interpret(self, request: ResolutionRequest) -> MaterialInterpretation:
        return MaterialInterpretation(
            canonical_name=_norm(request.material_name),
            aliases=(),
            product_form=request.product_form,
            composition=request.composition,
            production_process=request.production_process,
        )

    async def classify(self, activity: NormalizedActivity) -> MaterialClass:
        # Classification is deliberately only called by the proxy branch.
        name = activity.canonical_name
        composition = _norm(activity.composition)
        process = _norm(activity.production_process)
        if any(token in composition or token in name for token in ("steel", "metal", "aluminium", "aluminum", "copper", "钢", "金属", "铝", "铜")):
            family = "metals"
            category = MaterialCategory.METAL
        elif any(token in composition or token in name for token in ("polymer", "plastic", "resin")):
            family = "polymers"
            category = MaterialCategory.SYNTHETIC_CHEMICAL
        elif any(token in process or token in name for token in ("fused", "sintered", "calcined", "电熔", "烧结", "煅烧")):
            family = "manufactured minerals"
            category = MaterialCategory.MANUFACTURED_MINERAL
        elif any(token in process or token in name for token in ("mining", "quarried", "ore", "矿", "开采")):
            family = "natural minerals"
            category = MaterialCategory.NATURAL_MINERAL
        elif any(token in composition or token in name for token in ("glass", "ceramic", "玻璃", "陶瓷", "硅酸铝")):
            family = "inorganics"
            category = MaterialCategory.MANUFACTURED_MINERAL
        else:
            family = composition or "unknown"
            category = MaterialCategory.UNKNOWN
        return MaterialClass(
            name=name, family=family, category=category,
            rationale="offline deterministic fallback", confidence=0.5,
        )

    async def assess_candidate(
        self,
        activity: NormalizedActivity,
        source: SourceRecord,
        origin: str,
        material_class: MaterialClass | None = None,
    ) -> SemanticAssessment:
        return SemanticAssessment()


class InMemoryResolutionStore:
    def __init__(self) -> None:
        self.recommendations: dict[str, Recommendation] = {}
        self.traces: dict[str, ResolutionTrace] = {}
        self.approvals: dict[tuple[str, str], ApprovalRecord] = {}
        self.locked: dict[str, LockedResolution] = {}
        self._run_lock = asyncio.Lock()
        self._approval_lock = asyncio.Lock()

    async def has_resolution_run(self, request_id: str) -> bool:
        return request_id in self.recommendations or request_id in self.traces

    async def save_resolution_run(
        self, recommendation: Recommendation, trace: ResolutionTrace
    ) -> None:
        if recommendation.request_id != trace.request_id:
            raise ValueError("recommendation and trace must belong to the same request")
        async with self._run_lock:
            if await self.has_resolution_run(recommendation.request_id):
                raise ValueError(f"duplicate request_id: {recommendation.request_id}")
            trace.verify_hash_chain()
            stored_trace = trace.clone()
            self.recommendations[recommendation.request_id] = replace(
                recommendation, trace=stored_trace
            )
            self.traces[trace.request_id] = stored_trace

    async def get_recommendation(self, request_id: str) -> Recommendation | None:
        return self.recommendations.get(request_id)

    async def save_trace(self, trace: ResolutionTrace) -> None:
        if trace.request_id not in self.recommendations:
            raise ValueError("trace updates require an existing atomic resolution run")
        trace.verify_hash_chain()
        current = self.traces[trace.request_id]
        if trace.revision < current.revision:
            raise ValueError("trace revision cannot move backwards")
        current_hashes = tuple(item.entry_hash for item in current.entries)
        incoming_prefix = tuple(
            item.entry_hash for item in trace.entries[:current.revision]
        )
        if incoming_prefix != current_hashes:
            raise ValueError("trace history is append-only and cannot be rewritten")
        stored_trace = trace.clone()
        self.traces[trace.request_id] = stored_trace
        self.recommendations[trace.request_id] = replace(
            self.recommendations[trace.request_id], trace=stored_trace
        )

    async def get_trace(self, request_id: str) -> ResolutionTrace | None:
        return self.traces.get(request_id)

    async def save_approval(
        self,
        approval: ApprovalRecord,
        trace: ResolutionTrace,
        *,
        expected_recommendation_sha256: str,
        expected_trace_revision: int,
    ) -> ApprovalRecord:
        key = (approval.request_id, approval.candidate_id)
        async with self._approval_lock:
            existing = self.approvals.get(key)
            if existing is not None:
                if existing.matches_decision(
                    status=approval.status,
                    reviewer=approval.reviewer,
                    note=approval.note,
                    mode=approval.mode,
                ):
                    stable_existing_bindings = (
                        existing.candidate_content_sha256,
                        existing.recommendation_content_sha256,
                        existing.recommendation_revision,
                        existing.database_anchor_sha256,
                        existing.registry_anchor_sha256,
                        existing.policy_anchor_sha256,
                    )
                    stable_incoming_bindings = (
                        approval.candidate_content_sha256,
                        approval.recommendation_content_sha256,
                        approval.recommendation_revision,
                        approval.database_anchor_sha256,
                        approval.registry_anchor_sha256,
                        approval.policy_anchor_sha256,
                    )
                    if stable_existing_bindings == stable_incoming_bindings:
                        return existing
                    raise PersistenceIntegrityError(
                        "replayed decision bindings do not match committed state"
                    )
                raise ReviewStateConflictError(
                    "candidate already has a different terminal human decision"
                )
            if approval.request_id in self.locked:
                raise ReviewStateConflictError("locked resolution cannot be changed")
            recommendation = self.recommendations.get(approval.request_id)
            current_trace = self.traces.get(approval.request_id)
            if recommendation is None or current_trace is None:
                raise ReviewStateConflictError("approval requires an existing resolution run")
            if recommendation.content_sha256 != expected_recommendation_sha256:
                raise ReviewStateConflictError("recommendation changed before approval commit")
            if current_trace.revision != expected_trace_revision:
                raise StaleReviewRevisionError("trace revision changed before approval commit")
            trace.verify_hash_chain()
            if trace.revision != expected_trace_revision + 1:
                raise PersistenceIntegrityError(
                    "approval commit must append exactly one trace event"
                )
            if tuple(item.entry_hash for item in trace.entries[:-1]) != tuple(
                item.entry_hash for item in current_trace.entries
            ):
                raise PersistenceIntegrityError(
                    "approval trace does not extend the stored trace"
                )
            if approval.status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
                raise ReviewStateConflictError(
                    "only approved or rejected terminal decisions can be persisted"
                )
            if approval.status == ApprovalStatus.APPROVED and any(
                item.request_id == approval.request_id
                and item.status == ApprovalStatus.APPROVED
                for item in self.approvals.values()
            ):
                raise ReviewStateConflictError("request already has an approved candidate")
            if not approval.is_integrity_bound:
                raise PersistenceIntegrityError(
                    "legacy approval without integrity digests cannot be persisted"
                )
            candidate = next((
                item for item in (
                    *recommendation.candidates, *recommendation.reviewable_candidates
                )
                if item.candidate_id == approval.candidate_id
            ), None)
            expected_bindings = (
                candidate.content_sha256 if candidate is not None else None,
                recommendation.content_sha256,
                recommendation.revision,
                recommendation.database_anchor_sha256,
                recommendation.registry_anchor_sha256,
                recommendation.policy_anchor_sha256,
                trace.revision,
                trace.chain_sha256,
            )
            observed_bindings = (
                approval.candidate_content_sha256,
                approval.recommendation_content_sha256,
                approval.recommendation_revision,
                approval.database_anchor_sha256,
                approval.registry_anchor_sha256,
                approval.policy_anchor_sha256,
                approval.trace_revision,
                approval.trace_chain_sha256,
            )
            if candidate is None or observed_bindings != expected_bindings:
                raise PersistenceIntegrityError(
                    "approval bindings do not match the committed candidate, recommendation, anchors or trace"
                )
            self.approvals[key] = approval
            stored_trace = trace.clone()
            self.traces[trace.request_id] = stored_trace
            self.recommendations[trace.request_id] = replace(
                recommendation, trace=stored_trace
            )
            return approval

    async def get_approval(self, request_id: str, candidate_id: str) -> ApprovalRecord | None:
        return self.approvals.get((request_id, candidate_id))

    async def save_locked(
        self,
        locked: LockedResolution,
        trace: ResolutionTrace,
        *,
        expected_recommendation_sha256: str,
        expected_trace_revision: int,
    ) -> LockedResolution:
        async with self._approval_lock:
            existing = self.locked.get(locked.request_id)
            if existing is not None:
                if existing.candidate.candidate_id == locked.candidate.candidate_id:
                    return existing
                raise ReviewStateConflictError("resolution is already locked and immutable")
            recommendation = self.recommendations.get(locked.request_id)
            current_trace = self.traces.get(locked.request_id)
            if recommendation is None or current_trace is None:
                raise ReviewStateConflictError("lock requires an existing resolution run")
            if recommendation.content_sha256 != expected_recommendation_sha256:
                raise ReviewStateConflictError("recommendation changed before lock commit")
            if current_trace.revision != expected_trace_revision:
                raise StaleReviewRevisionError("trace revision changed before lock commit")
            trace.verify_hash_chain()
            if trace.revision != expected_trace_revision + 1:
                raise PersistenceIntegrityError("lock commit must append exactly one trace event")
            if tuple(item.entry_hash for item in trace.entries[:-1]) != tuple(
                item.entry_hash for item in current_trace.entries
            ):
                raise PersistenceIntegrityError("lock trace does not extend the stored trace")
            approval = self.approvals.get((locked.request_id, locked.candidate.candidate_id))
            if approval is None or approval.content_sha256 != locked.approval_content_sha256:
                raise PersistenceIntegrityError("approval changed before lock commit")
            expected_snapshot = LockedResolutionEvidenceSnapshot.from_trace(
                trace,
                registry_anchor_sha256=recommendation.registry_anchor_sha256 or "",
                policy_anchor_sha256=recommendation.policy_anchor_sha256 or "",
            )
            if (
                locked.candidate_content_sha256 != locked.candidate.content_sha256
                or locked.recommendation_content_sha256 != recommendation.content_sha256
                or locked.evidence_snapshot != expected_snapshot
            ):
                raise PersistenceIntegrityError("lock bindings do not match committed state")
            self.locked[locked.request_id] = locked
            stored_trace = trace.clone()
            self.traces[trace.request_id] = stored_trace
            self.recommendations[trace.request_id] = replace(
                recommendation, trace=stored_trace
            )
            return locked

    async def get_locked(self, request_id: str) -> LockedResolution | None:
        return self.locked.get(request_id)
