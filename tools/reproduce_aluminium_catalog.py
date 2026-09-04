"""Reproduce aluminium resolution through the real HTTP catalogue adapter.

The script never embeds catalogue content. Runtime traces and matching raw
records are written only to the caller-selected output directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from a1_factor_engine import A1FactorResolutionEngine, ResolutionRequest
from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.matching import normalize_text
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY
from a1_factor_engine.models import DatabaseVersionAnchor

QUERIES = (
    "金属铝",
    "铝",
    "aluminum",
    "aluminium",
    "原铝",
    "电解铝",
    "primary aluminium",
    "再生铝",
    "secondary aluminium",
    "aluminium ingot",
    "氧化铝",
    "alumina",
    "硅酸铝",
    "铝合金",
    "6061 aluminium alloy",
)


def _fetch(endpoint: str) -> Mapping[str, Any]:
    # Developer diagnostic endpoint; production connector validation lives in runtime code.
    with urlopen(endpoint, timeout=30) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("catalogue response must be an object")
    return payload


def _text_matches(item: Mapping[str, Any], terms: set[str]) -> bool:
    values = [item.get("name"), item.get("code")]
    aliases = item.get("aliases")
    if isinstance(aliases, list):
        values.extend(aliases)
    normalized = {normalize_text(str(value or "")).value for value in values}
    return bool(normalized & terms)


async def reproduce(endpoint: str, output: Path) -> dict[str, Any]:
    payload = _fetch(endpoint)
    database = payload.get("database")
    records = payload.get("records")
    if not isinstance(database, Mapping) or not isinstance(records, list):
        raise ValueError("catalogue response lacks database metadata or records")
    anchor = DatabaseVersionAnchor(
        catalog_name=str(database.get("name") or "formal-factor-catalog"),
        catalog_version=str(payload.get("catalog_version") or "unknown"),
        database_sha256=str(database.get("sha256") or "").strip().lower() or None,
        locator=endpoint,
    )
    converted = []
    dropped = []
    for position, item in enumerate(records):
        if not isinstance(item, Mapping):
            dropped.append({"position": position, "reason": "not_an_object"})
            continue
        source = HttpCatalogFactorRepository._to_source_record(item, anchor)
        if source is None:
            dropped.append({
                "position": position,
                "source_id": str(item.get("record_id") or item.get("code") or ""),
                "raw_name": str(item.get("name") or ""),
                "reason": "adapter_returned_none",
            })
        else:
            converted.append(source)

    query_terms: set[str] = set()
    for query in QUERIES:
        resolution = DEFAULT_MATERIAL_REGISTRY.resolve(query)
        query_terms.add(normalize_text(query).value)
        query_terms.update(normalize_text(alias).value for alias in resolution.retrieval_intent.aliases)
    matching_raw = [item for item in records if isinstance(item, Mapping) and _text_matches(item, query_terms)]

    output.mkdir(parents=True, exist_ok=True)
    (output / "raw-matching-records.json").write_text(
        json.dumps(matching_raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    repository = HttpCatalogFactorRepository(endpoint=endpoint, fetch_json=lambda _: payload)
    engine = A1FactorResolutionEngine(local_retrieval=repository)
    cases = []
    for index, query in enumerate(QUERIES, start=1):
        request = ResolutionRequest(
            request_id=f"aluminium-baseline-{index:02d}",
            material_name=query,
            quantity=1,
            quantity_unit="kg",
        )
        recommendation = await engine.resolve(request)
        trace = await engine.trace(request.request_id)
        if trace is None:
            raise RuntimeError(f"trace missing for {query}")
        trace_payload = trace.to_dict()
        (output / f"{index:02d}-{request.request_id}.json").write_text(
            json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        explanation = trace.explain()
        cases.append({
            "query": query,
            "request_id": request.request_id,
            "status": recommendation.status.value,
            "base_entity_id": (explanation.get("material_identity") or {}).get("base_entity_id"),
            "required_choice": explanation.get("required_choice"),
            "retrieved_record_count": (explanation.get("local_retrieval") or {}).get("record_count", 0),
            "selected_candidate_ids": explanation.get("selected_candidate_ids", ()),
            "raw_related_hit_count": len(explanation.get("raw_related_hits", ())),
        })
    summary = {
        "endpoint": endpoint,
        "catalog_version": anchor.catalog_version,
        "database_sha256": anchor.database_sha256,
        "raw_record_count": len(records),
        "records_matching_text": len(matching_raw),
        "conversion_success_count": len(converted),
        "conversion_drop_count": len(dropped),
        "conversion_drops": dropped,
        "cases": cases,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:5004/api/v2/factors/catalog",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = asyncio.run(reproduce(args.endpoint, args.output))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
