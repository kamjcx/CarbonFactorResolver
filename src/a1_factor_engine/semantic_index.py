"""Version-anchored semantic index for entity-first factor retrieval."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Sequence

from .matching import normalize_text
from .material_registry import MaterialSemanticRegistryPort
from .models import (
    DatabaseVersionAnchor,
    IdentityOutcome,
    LinkAttempt,
    LinkOutcome,
    LinkStrategy,
    RecallObservation,
    RetrievalIntent,
    SemanticIndexAnchor,
    SourceRecord,
)


def _norm(value: str | None) -> str:
    return normalize_text(value).value


def _record_aliases(record: SourceRecord) -> set[str]:
    raw = record.metadata.get("aliases", "")
    if not raw:
        return set()
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        try:
            parsed = json.loads(str(raw))
            values = parsed if isinstance(parsed, list) else (parsed,)
        except json.JSONDecodeError:
            values = tuple(part.strip() for part in str(raw).split(","))
    return {_norm(str(value)) for value in values if _norm(str(value))}


def _with_strategy(record: SourceRecord, strategy: LinkStrategy, index_version: str) -> SourceRecord:
    return replace(record, metadata={
        **record.metadata,
        "match_strategy": strategy.value,
        "semantic_index_version": index_version,
    })


@dataclass(frozen=True, slots=True)
class SemanticIndexQueryResult:
    records: tuple[SourceRecord, ...]
    attempts: tuple[LinkAttempt, ...]
    observations: tuple[RecallObservation, ...]
    anchor: SemanticIndexAnchor


@dataclass(slots=True)
class SemanticFactorIndex:
    records: tuple[SourceRecord, ...]
    database_anchor: DatabaseVersionAnchor
    registry: MaterialSemanticRegistryPort
    anchor: SemanticIndexAnchor = field(init=False)

    def __post_init__(self) -> None:
        enriched = tuple(self.registry.enrich_source(record) for record in self.records)
        self.records = enriched
        digest_payload = "|".join(
            f"{record.source_id}:{record.metadata.get('base_entity_id', '')}:"
            f"{record.metadata.get('product_entity_id', '')}:"
            f"{record.metadata.get('grade_schema_id', '')}:"
            f"{record.metadata.get('grade', '')}"
            for record in sorted(enriched, key=lambda item: item.source_id)
        )
        content_digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()[:16]
        self.anchor = SemanticIndexAnchor(
            index_version=f"semantic-factor-index/1.1.0+{content_digest}",
            catalog_database_sha256=self.database_anchor.database_sha256,
            registry_version=self.registry.version,
            registry_sha256=self.registry.sha256,
            record_count=len(enriched),
        )

    @staticmethod
    def _attempt(
        strategy: LinkStrategy, records: Sequence[SourceRecord], found: str, absent: str
    ) -> LinkAttempt:
        return LinkAttempt(
            strategy=strategy,
            outcome=(
                LinkOutcome.NO_MATCH if not records
                else LinkOutcome.MATCHED if len(records) == 1
                else LinkOutcome.CANDIDATE_SET
            ),
            candidate_source_ids=tuple(record.source_id for record in records),
            reason=found if records else absent,
        )

    def query(self, intent: RetrievalIntent) -> SemanticIndexQueryResult:
        query = _norm(intent.canonical_name)
        request_aliases = {_norm(alias) for alias in intent.aliases if _norm(alias)}
        exact = tuple(
            _with_strategy(record, LinkStrategy.EXACT, self.anchor.index_version)
            for record in self.records
            if query and query == _norm(record.material_name)
        )
        used = {record.source_id for record in exact}
        synonym = tuple(
            _with_strategy(record, LinkStrategy.SYNONYM, self.anchor.index_version)
            for record in self.records
            if record.source_id not in used
            and (
                query in _record_aliases(record)
                or _norm(record.material_name) in request_aliases
                or bool(request_aliases & _record_aliases(record))
            )
        )
        used.update(record.source_id for record in synonym)

        related: tuple[SourceRecord, ...] = ()
        if intent.identity_outcome == IdentityOutcome.RESOLVED and intent.base_entity_id:
            related = tuple(
                _with_strategy(record, LinkStrategy.RELATED, self.anchor.index_version)
                for record in self.records
                if record.source_id not in used
                and record.metadata.get("identity_outcome") == IdentityOutcome.RESOLVED.value
                and record.metadata.get("base_entity_id") == intent.base_entity_id
            )

        attempts = (
            self._attempt(
                LinkStrategy.EXACT, exact,
                "catalogue primary name matched exactly",
                "no exact primary-name match in semantic index",
            ),
            self._attempt(
                LinkStrategy.SYNONYM, synonym,
                "reviewed/catalogue alias resolved to the request identity",
                "no reviewed alias match in semantic index",
            ),
            self._attempt(
                LinkStrategy.RELATED, related,
                "same base entity recalled with process/form/grade/route differences deferred to Gap Analysis",
                (
                    "request identity unresolved; lexical similarity is observation-only"
                    if intent.identity_outcome != IdentityOutcome.RESOLVED
                    else "no same-entity variants in semantic index"
                ),
            ),
        )
        observations = tuple(
            RecallObservation(
                source_id=record.source_id,
                material_name=record.material_name,
                retrieval_strategy=LinkStrategy.RELATED,
                retrieval_basis=(
                    f"base_entity_id={intent.base_entity_id}",
                    f"semantic_index={self.anchor.index_version}",
                ),
                identity_compatibility="pass",
                factor_kind=record.factor_kind,
                eligible_for_candidate_pool=True,
            )
            for record in related
        )
        return SemanticIndexQueryResult((*exact, *synonym, *related), attempts, observations, self.anchor)
