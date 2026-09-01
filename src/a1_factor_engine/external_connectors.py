"""Deterministic, evidence-first connectors for external factor sources.

The connectors in this module never turn search-result snippets into factors.
Only fetched structured documents whose content hash can be reproduced are
accepted by :class:`StructuredEPDEvidenceExtractor`.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import quote

from .models import (
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    RetrievalIntent,
    SourceQualityStatus,
    SourceRecord,
)
from .units import parse_factor_unit

PARSER_VERSION = "structured-epd/v1"


def _fixture_root() -> Path:
    """Find fixtures in a source checkout or an installed wheel."""

    source_root = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "external"
    if source_root.is_dir():
        return source_root
    return Path(sys.prefix) / "share" / "carbon-factor-resolver" / "fixtures" / "external"


class InvalidExternalEvidence(ValueError):
    """Raised when fetched evidence is incomplete, malformed, or unverified."""


class ExternalSourceUnavailable(RuntimeError):
    """Raised when an explicitly requested live operation is unavailable."""


@dataclass(frozen=True, slots=True)
class ConnectorHealth(Mapping[str, Any]):
    available: bool
    status: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "status": self.status, "reason": self.reason}

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return 3


@dataclass(frozen=True, slots=True)
class ExternalDiscoveryRef(Mapping[str, Any]):
    source_id: str
    provider: str
    locator: str
    document_kind: str
    expected_content_sha256: str | None = None
    snapshot_sha256: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "provider": self.provider,
            "locator": self.locator,
            "document_kind": self.document_kind,
            "expected_content_sha256": self.expected_content_sha256,
            "snapshot_sha256": self.snapshot_sha256,
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return 7


@dataclass(frozen=True, slots=True)
class ExternalDocument(Mapping[str, Any]):
    ref: ExternalDiscoveryRef
    content: bytes
    content_sha256: str
    retrieved_at: datetime
    snapshot_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "content": self.content,
            "content_sha256": self.content_sha256,
            "retrieved_at": self.retrieved_at,
            "snapshot_sha256": self.snapshot_sha256,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return 5


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str | None) -> bool:
    return bool(
        value
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _normalise(value: str | None) -> str:
    return " ".join((value or "").casefold().replace("-", " ").replace("_", " ").split())


def _intent_terms(intent: RetrievalIntent) -> set[str]:
    return {_normalise(intent.canonical_name), *(_normalise(item) for item in intent.aliases)} - {""}


def _terms_overlap(left: set[str], right: set[str]) -> bool:
    """Conservative phrase overlap for discovery recall, never identity authority."""

    return bool(left.intersection(right)) or any(
        len(shorter.split()) >= 2 and shorter in longer
        for shorter in left
        for longer in right
    ) or any(
        len(shorter.split()) >= 2 and shorter in longer
        for shorter in right
        for longer in left
    )


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _as_ref(value: ExternalDiscoveryRef | Mapping[str, Any]) -> ExternalDiscoveryRef:
    if isinstance(value, ExternalDiscoveryRef):
        return value
    return ExternalDiscoveryRef(
        source_id=str(value["source_id"]),
        provider=str(value["provider"]),
        locator=str(value["locator"]),
        document_kind=str(value["document_kind"]),
        expected_content_sha256=value.get("expected_content_sha256"),
        snapshot_sha256=value.get("snapshot_sha256"),
        metadata=value.get("metadata", {}),
    )


def _as_document(value: ExternalDocument | Mapping[str, Any]) -> ExternalDocument:
    if isinstance(value, ExternalDocument):
        return value
    retrieved_at = value.get("retrieved_at")
    if isinstance(retrieved_at, str):
        retrieved_at = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    if not isinstance(retrieved_at, datetime):
        raise InvalidExternalEvidence("document retrieved_at is required")
    content = value["content"]
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, bytes):
        raise InvalidExternalEvidence("document content must be bytes or text")
    return ExternalDocument(
        ref=_as_ref(value["ref"]),
        content=content,
        content_sha256=str(value["content_sha256"]),
        retrieved_at=retrieved_at,
        snapshot_sha256=value.get("snapshot_sha256"),
    )


class InMemoryExternalCache:
    """Small deterministic cache implementing the frozen async get/put shape."""

    def __init__(self) -> None:
        self._values: dict[str, Mapping[str, Any]] = {}

    async def get(self, key: str) -> Mapping[str, Any] | None:
        return self._values.get(key)

    async def put(self, key: str, document: Mapping[str, Any]) -> None:
        self._values[key] = document


class SnapshotExternalConnector:
    """Discovers and fetches records from a fixed, local JSON snapshot."""

    def __init__(self, snapshot_path: str | Path, *, provider: str) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.provider = provider

    def health(self) -> ConnectorHealth:
        if not self.snapshot_path.is_file():
            return ConnectorHealth(False, "unavailable", "snapshot file is missing")
        return ConnectorHealth(True, "available")

    def _load(self) -> tuple[dict[str, Any], bytes, str]:
        try:
            raw = self.snapshot_path.read_bytes()
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ExternalSourceUnavailable(f"snapshot cannot be read: {self.snapshot_path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise InvalidExternalEvidence("snapshot must contain a records array")
        return payload, raw, _sha256(raw)

    async def discover(self, intent: RetrievalIntent) -> tuple[ExternalDiscoveryRef, ...]:
        payload, _, snapshot_sha256 = self._load()
        terms = _intent_terms(intent)
        refs: list[ExternalDiscoveryRef] = []
        for item in payload["records"]:
            if not isinstance(item, dict):
                continue
            names = {_normalise(str(item.get("material_name", "")))}
            names.update(_normalise(str(alias)) for alias in item.get("aliases", ()))
            if not _terms_overlap(terms, names):
                continue
            content = _canonical_json(item)
            source_id = str(item.get("source_id", "")).strip()
            if not source_id:
                continue
            refs.append(
                ExternalDiscoveryRef(
                    source_id=source_id,
                    provider=self.provider,
                    locator=f"{self.snapshot_path.resolve().as_uri()}#record={quote(source_id)}",
                    document_kind=str(item.get("document_kind", "structured_epd")),
                    expected_content_sha256=_sha256(content),
                    snapshot_sha256=snapshot_sha256,
                    metadata={"snapshot_version": str(payload.get("snapshot_version", ""))},
                )
            )
        return tuple(sorted(refs, key=lambda ref: ref.source_id))

    async def fetch(self, ref: ExternalDiscoveryRef | Mapping[str, Any]) -> ExternalDocument:
        ref = _as_ref(ref)
        payload, _, snapshot_sha256 = self._load()
        if ref.snapshot_sha256 and snapshot_sha256 != ref.snapshot_sha256:
            raise InvalidExternalEvidence("snapshot SHA-256 changed after discovery")
        item = next(
            (row for row in payload["records"] if isinstance(row, dict) and row.get("source_id") == ref.source_id),
            None,
        )
        if item is None:
            raise InvalidExternalEvidence(f"snapshot record disappeared: {ref.source_id}")
        content = _canonical_json(item)
        digest = _sha256(content)
        if ref.expected_content_sha256 and digest != ref.expected_content_sha256:
            raise InvalidExternalEvidence("document SHA-256 does not match discovery reference")
        return ExternalDocument(
            ref=ref,
            content=content,
            content_sha256=digest,
            retrieved_at=datetime.now(timezone.utc),
            snapshot_sha256=snapshot_sha256,
        )


class FixtureExternalConnector(SnapshotExternalConnector):
    """Offline connector with synthetic records for deterministic tests/demos."""

    def __init__(self, snapshot_path: str | Path | None = None) -> None:
        super().__init__(snapshot_path or _fixture_root() / "fixture_external.json", provider="FactorBench fixture")


class PublicStructuredEPDConnector(SnapshotExternalConnector):
    """Connector for a pinned public structured-EPD snapshot.

    ``fetcher`` is optional and injectable. It may return bytes, a mapping, or
    an :class:`ExternalDocument`; no network implementation is bundled.
    """

    def __init__(
        self,
        snapshot_path: str | Path | None = None,
        *,
        fetcher: Callable[[ExternalDiscoveryRef], Any | Awaitable[Any]] | None = None,
    ) -> None:
        super().__init__(
            snapshot_path or _fixture_root() / "public_epd_snapshot.json",
            provider="Public EPD snapshot",
        )
        self.fetcher = fetcher

    async def fetch(self, ref: ExternalDiscoveryRef | Mapping[str, Any]) -> ExternalDocument:
        ref = _as_ref(ref)
        if self.fetcher is None:
            return await super().fetch(ref)
        fetched = await _resolve(self.fetcher(ref))
        if isinstance(fetched, ExternalDocument):
            document = fetched
        else:
            content = fetched if isinstance(fetched, bytes) else _canonical_json(fetched)
            document = ExternalDocument(
                ref=ref,
                content=content,
                content_sha256=_sha256(content),
                retrieved_at=datetime.now(timezone.utc),
                snapshot_sha256=ref.snapshot_sha256,
            )
        if _sha256(document.content) != document.content_sha256:
            raise InvalidExternalEvidence("fetcher returned an invalid content SHA-256")
        if ref.expected_content_sha256 and document.content_sha256 != ref.expected_content_sha256:
            raise InvalidExternalEvidence("fetched document differs from pinned snapshot record")
        if ref.snapshot_sha256 and document.snapshot_sha256 != ref.snapshot_sha256:
            raise InvalidExternalEvidence("fetched document lacks the pinned snapshot SHA-256")
        return document


class OpenEPDConnector:
    """Credential-gated OpenEPD-compatible adapter using injected I/O.

    Absence of credentials is an expected, non-blocking state: health reports
    ``unavailable`` and discovery returns no references without invoking I/O.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        discovery_fetcher: Callable[[str, Mapping[str, str]], Any | Awaitable[Any]] | None = None,
        document_fetcher: Callable[[str, Mapping[str, str]], Any | Awaitable[Any]] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENEPD_API_KEY", "")
        self.base_url = (base_url if base_url is not None else os.getenv("OPENEPD_BASE_URL", "")).rstrip("/")
        self.discovery_fetcher = discovery_fetcher
        self.document_fetcher = document_fetcher

    def health(self) -> ConnectorHealth:
        if not self.api_key.strip():
            return ConnectorHealth(False, "unavailable", "OPENEPD_API_KEY is not configured")
        if not self.base_url.strip():
            return ConnectorHealth(False, "unavailable", "OPENEPD_BASE_URL is not configured")
        if self.discovery_fetcher is None or self.document_fetcher is None:
            return ConnectorHealth(False, "unavailable", "OpenEPD I/O fetchers are not configured")
        return ConnectorHealth(True, "available")

    @property
    def _headers(self) -> Mapping[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    async def discover(self, intent: RetrievalIntent) -> tuple[ExternalDiscoveryRef, ...]:
        if not self.health().available:
            return ()
        url = f"{self.base_url}/epds?query={quote(intent.canonical_name)}"
        response = await _resolve(self.discovery_fetcher(url, self._headers))  # type: ignore[misc]
        rows = response.get("results", ()) if isinstance(response, Mapping) else response
        refs: list[ExternalDiscoveryRef] = []
        for row in rows or ():
            if not isinstance(row, Mapping):
                continue
            source_id = str(row.get("id", "")).strip()
            document_url = str(row.get("url", "")).strip()
            if source_id and document_url:
                refs.append(
                    ExternalDiscoveryRef(
                        source_id=source_id,
                        provider="OpenEPD",
                        locator=document_url,
                        document_kind="openepd",
                        expected_content_sha256=str(row.get("sha256", "")).strip().lower() or None,
                    )
                )
        return tuple(sorted(refs, key=lambda ref: ref.source_id))

    async def fetch(self, ref: ExternalDiscoveryRef | Mapping[str, Any]) -> ExternalDocument:
        ref = _as_ref(ref)
        if not self.health().available:
            raise ExternalSourceUnavailable(self.health().reason)
        fetched = await _resolve(self.document_fetcher(ref.locator, self._headers))  # type: ignore[misc]
        content = fetched if isinstance(fetched, bytes) else _canonical_json(fetched)
        digest = _sha256(content)
        if ref.expected_content_sha256 and digest != ref.expected_content_sha256:
            raise InvalidExternalEvidence("OpenEPD document SHA-256 mismatch")
        return ExternalDocument(ref, content, digest, datetime.now(timezone.utc))


class StructuredEPDEvidenceExtractor:
    """Strictly validate a fetched structured document before factor ingress."""

    parser_version = PARSER_VERSION
    _accepted_kinds = {"fixture_factor", "structured_epd", "openepd"}

    async def extract(
        self, document: ExternalDocument | Mapping[str, Any], intent: RetrievalIntent
    ) -> tuple[SourceRecord, ...]:
        document = _as_document(document)
        if document.ref.document_kind not in self._accepted_kinds:
            raise InvalidExternalEvidence("search summaries and unstructured documents cannot supply factors")
        actual_sha256 = _sha256(document.content)
        if not _is_sha256(document.content_sha256):
            raise InvalidExternalEvidence("document content SHA-256 is malformed")
        if actual_sha256 != document.content_sha256:
            raise InvalidExternalEvidence("document content SHA-256 is invalid")
        if document.ref.expected_content_sha256 and actual_sha256 != document.ref.expected_content_sha256:
            raise InvalidExternalEvidence("document content does not match its discovery hash")
        if document.ref.snapshot_sha256:
            if not _is_sha256(document.ref.snapshot_sha256):
                raise InvalidExternalEvidence("snapshot SHA-256 is malformed")
            if document.snapshot_sha256 != document.ref.snapshot_sha256:
                raise InvalidExternalEvidence("snapshot SHA-256 was not preserved during fetch")
        try:
            item = json.loads(document.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidExternalEvidence("document is not valid JSON") from exc
        if not isinstance(item, dict):
            raise InvalidExternalEvidence("document root must be an object")

        source_id = str(item.get("source_id", document.ref.source_id)).strip()
        material_name = str(item.get("material_name", "")).strip()
        if not source_id or not material_name:
            raise InvalidExternalEvidence("source_id and material_name are required")

        value = item.get("factor_value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidExternalEvidence("factor_value must be numeric")
        factor_value = float(value)
        if not (factor_value >= 0 and factor_value < float("inf")):
            raise InvalidExternalEvidence("factor_value must be finite and non-negative")
        factor_unit = str(item.get("factor_unit", "")).strip()
        try:
            parse_factor_unit(factor_unit)
        except ValueError as exc:
            raise InvalidExternalEvidence("factor_unit is not parseable") from exc
        indicator = str(item.get("indicator", "")).strip()
        if not indicator.casefold().startswith("gwp"):
            raise InvalidExternalEvidence("a GWP indicator is required")
        declared_product = str(item.get("declared_product", "")).strip()
        if not declared_product:
            raise InvalidExternalEvidence("declared_product is required")
        modules = tuple(str(value).strip().upper() for value in item.get("boundary_modules", ()) if str(value).strip())
        boundary = str(item.get("boundary", "")).strip()
        if not boundary or not modules:
            raise InvalidExternalEvidence("boundary and boundary_modules are required")
        evidence_locator = str(item.get("evidence_locator", "")).strip()
        source_locator = str(item.get("source_locator", document.ref.locator)).strip()
        if not evidence_locator or not source_locator:
            raise InvalidExternalEvidence("source and evidence locators are required")
        try:
            subject_type = FactorSubjectType(str(item.get("subject_type", "")))
        except ValueError as exc:
            raise InvalidExternalEvidence("subject_type is required and must be supported") from exc
        try:
            quality_status = SourceQualityStatus(str(item.get("source_quality_status", "")).upper())
        except ValueError as exc:
            raise InvalidExternalEvidence("source_quality_status is required and must be supported") from exc
        admission_eligible = item.get("admission_eligible")
        if type(admission_eligible) is not bool:
            raise InvalidExternalEvidence("admission_eligible is required and must be boolean")

        terms = _intent_terms(intent)
        names = {_normalise(str(item.get("material_name", "")))}
        aliases = tuple(str(alias).strip() for alias in item.get("aliases", ()) if str(alias).strip())
        alias_names = {_normalise(alias) for alias in aliases}
        names.update(alias_names)
        if not _terms_overlap(terms, names):
            return ()
        try:
            source_type = FactorSourceType(str(item.get("source_type", FactorSourceType.EPD.value)))
        except ValueError as exc:
            raise InvalidExternalEvidence("source_type is not supported") from exc
        request_name = _normalise(intent.canonical_name)
        declared_product_match = bool(
            request_name and request_name in _normalise(declared_product)
        )
        reviewed_aliases = tuple(dict.fromkeys((
            *aliases,
            *((intent.canonical_name,) if declared_product_match else ()),
        )))
        metadata = {
            "parser_version": self.parser_version,
            "evidence_locator": evidence_locator,
            "snapshot_sha256": document.snapshot_sha256 or "",
            "license": str(item.get("license", "public-or-synthetic")),
            "aliases": json.dumps(reviewed_aliases, ensure_ascii=False),
            "match_proof": "declared_product" if declared_product_match else "catalogue_name_or_alias",
            "match_strategy": (
                "exact_link"
                if request_name == _normalise(material_name)
                else "synonym_link"
                if request_name in alias_names or declared_product_match
                else "related_candidate_recall"
            ),
        }
        try:
            factor_kind = FactorKind(str(item.get("factor_kind", FactorKind.EPD_INDICATOR.value)))
        except ValueError as exc:
            raise InvalidExternalEvidence("factor_kind is not supported") from exc
        return (
            SourceRecord(
                source_id=source_id,
                source_type=source_type,
                provider=document.ref.provider,
                locator=source_locator,
                material_name=material_name,
                factor_value=factor_value,
                factor_unit=factor_unit,
                geography=str(item.get("geography", "")).strip() or None,
                year=int(item["year"]) if item.get("year") is not None else None,
                product_form=str(item.get("product_form", "")).strip() or None,
                composition=str(item.get("composition", "")).strip() or None,
                production_process=str(item.get("production_process", "")).strip() or None,
                boundary=boundary,
                citation=str(item.get("citation", "")).strip(),
                excerpt=str(item.get("excerpt", "")).strip(),
                retrieved_at=document.retrieved_at,
                metadata=metadata,
                factor_kind=factor_kind,
                subject_type=subject_type,
                source_quality_status=quality_status,
                admission_eligible=admission_eligible,
                indicator=indicator,
                declared_product=declared_product,
                boundary_modules=modules,
                catalog_locator=document.ref.locator,
                source_document_sha256=actual_sha256,
                page=str(item.get("page", "")).strip() or None,
                table=str(item.get("table", "")).strip() or None,
                row=str(item.get("row", "")).strip() or None,
            ),
        )
