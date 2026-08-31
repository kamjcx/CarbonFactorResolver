"""Reference in-memory and null adapters.

The repository adapters are intentionally tiny: replacing them with a port
implementation backed by the future database/API does not change graph logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen

from .matching import normalize_text
from .material_registry import DEFAULT_MATERIAL_REGISTRY, MaterialSemanticRegistryPort
from .models import (
    ApprovalRecord,
    DatabaseVersionAnchor,
    FactorKind,
    FactorSourceType,
    LinkAttempt,
    LinkOutcome,
    LinkStrategy,
    LockedResolution,
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

    def __post_init__(self) -> None:
        if self.anchor is None:
            payload = "|".join(
                f"{record.source_id}:{record.factor_value}:{record.factor_unit}"
                for record in sorted(self.records, key=lambda item: item.source_id)
            )
            self.anchor = DatabaseVersionAnchor(
                catalog_name="in-memory-factor-catalog",
                catalog_version="test-v1",
                database_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                locator="memory://factor-catalog",
            )

    async def search(self, intent: RetrievalIntent) -> RetrievalResult:
        allowed = self.source_types
        eligible = tuple(
            record for record in self.records
            if allowed is None or record.source_type in allowed
        )
        assert self.anchor is not None
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

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("catalogue dataset policy requires a policy_id")

    def applies(self, item: Mapping[str, Any]) -> bool:
        def matches(field: str, allowed: tuple[str, ...]) -> bool:
            if not allowed:
                return True
            observed = str(item.get(field) or "").strip().casefold()
            return observed in {value.strip().casefold() for value in allowed}

        return (
            matches("category", self.record_categories)
            and matches("standard", self.standards)
            and matches("primary_label", self.primary_labels)
        )


REFRACTORY_A1_STANDARD_POLICY = CatalogDatasetPolicy(
    policy_id="catalog.refractory-a1-product-carbon-footprint/v1",
    record_categories=("lifecycle_factor",),
    standards=("GB/T XXXX-202X 征求意见稿",),
    primary_labels=("产品碳足迹因子",),
    indicator="GWP-total",
    boundary="cradle-to-gate",
    declared_product_from_name=True,
    evidence_citation=(
        "《温室气体 产品碳足迹量化方法与要求 耐火材料》征求意见稿，"
        "5.2声明单位、5.3.1系统边界、7.1全球变暖潜势"
    ),
    production_approval_id="customer.refractory-draft-first/v1",
    source_priority_rank=0,
)


@dataclass(slots=True)
class HttpCatalogFactorRepository:
    """Read-only adapter for the formal `/api/v2/factors/catalog` endpoint."""

    endpoint: str = "http://127.0.0.1:5004/api/v2/factors/catalog"
    expected_sha256: str | None = None
    timeout_seconds: float = 10.0
    fetch_json: Callable[[str], Mapping[str, Any]] | None = None
    material_registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY
    dataset_policies: tuple[CatalogDatasetPolicy, ...] = (
        REFRACTORY_A1_STANDARD_POLICY,
    )
    _cached_index_key: str | None = field(default=None, init=False)
    _cached_index: SemanticFactorIndex | None = field(default=None, init=False)
    _cached_conversion_diagnostics: tuple[RecordConversionDiagnostic, ...] = field(
        default=(), init=False
    )

    async def search(self, intent: RetrievalIntent) -> RetrievalResult:
        payload = await asyncio.to_thread(self._fetch)
        database = payload.get("database")
        if not isinstance(database, Mapping):
            raise ValueError("factor catalog response lacks database metadata")
        digest = str(database.get("sha256") or "").strip().lower()
        if self.expected_sha256 and digest != self.expected_sha256.strip().lower():
            raise ValueError("formal factor database SHA-256 does not match the configured anchor")
        anchor = DatabaseVersionAnchor(
            catalog_name=str(database.get("name") or "formal-factor-catalog"),
            catalog_version=str(payload.get("catalog_version") or "unknown"),
            database_sha256=digest or None,
            locator=self.endpoint,
        )
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("factor catalog response lacks records")
        policy_key = ",".join(
            f"{policy.policy_id}:{policy.production_approval_id or ''}"
            for policy in self.dataset_policies
        )
        cache_key = f"{anchor.identity}:{self.material_registry.sha256}:{policy_key}"
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
                    value = float(item.get("primary_value"))
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
                        source = self._to_source_record(item, anchor, self.dataset_policies)
                    except (TypeError, ValueError) as exc:
                        reasons.append("record_validation_failed")
                        dropped_fields.append(type(exc).__name__)
                success = source is not None
                if success:
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
        conversion_diagnostics = getattr(self, "_cached_conversion_diagnostics", ())
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
            retrieval_diagnostics, conversion_diagnostics,
            PipelineFunnel(
                raw_catalog_records=len(records), retrieval_hits=len(result.records),
                converted_records=sum(item.success for item in conversion_diagnostics),
            ),
        )

    def _fetch(self) -> Mapping[str, Any]:
        if self.fetch_json is not None:
            return self.fetch_json(self.endpoint)
        with urlopen(self.endpoint, timeout=self.timeout_seconds) as response:  # nosec B310 - configured local API
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
        item_aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
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
    ) -> SourceRecord | None:
        try:
            value = float(item.get("primary_value"))
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
            policy for policy in dataset_policies if policy.applies(item)
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
            year = int(year_value) if year_value not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        raw_kind = str(item.get("factor_kind") or item.get("category") or "other").strip().lower()
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
            "record_category": str(item.get("category") or ""),
            "document_status": str(item.get("document_status") or ""),
            "source_priority": str(item.get("source_priority") or ""),
            "source_priority_rank": str(source_priority_rank),
            "source_priority_policy": "customer.draft-ecoinvent310-ecoinvent312/v1",
            "source_priority_issue": source_priority_issue,
            "aliases": json.dumps(aliases, ensure_ascii=False) if isinstance(aliases, list) else "",
            "catalog_locator": catalog_locator,
            "source_document_locator": source_document_locator or "",
            "source_document_sha256": source_document_sha256 or "",
            "source_document_page": page or "",
            "source_document_table": table or "",
            "source_document_row": row or "",
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
            self.recommendations[recommendation.request_id] = recommendation
            self.traces[trace.request_id] = trace

    async def get_recommendation(self, request_id: str) -> Recommendation | None:
        return self.recommendations.get(request_id)

    async def save_trace(self, trace: ResolutionTrace) -> None:
        # Trace is intentionally mutable and replaceable; it is not a snapshot.
        if trace.request_id not in self.recommendations:
            raise ValueError("trace updates require an existing atomic resolution run")
        self.traces[trace.request_id] = trace

    async def get_trace(self, request_id: str) -> ResolutionTrace | None:
        return self.traces.get(request_id)

    async def save_approval(self, approval: ApprovalRecord) -> None:
        if approval.request_id in self.locked:
            raise ValueError("locked resolution cannot be changed")
        self.approvals[(approval.request_id, approval.candidate_id)] = approval

    async def get_approval(self, request_id: str, candidate_id: str) -> ApprovalRecord | None:
        return self.approvals.get((request_id, candidate_id))

    async def save_locked(self, locked: LockedResolution) -> None:
        existing = self.locked.get(locked.request_id)
        if existing is not None and existing != locked:
            raise ValueError("resolution is already locked and immutable")
        self.locked.setdefault(locked.request_id, locked)

    async def get_locked(self, request_id: str) -> LockedResolution | None:
        return self.locked.get(request_id)
