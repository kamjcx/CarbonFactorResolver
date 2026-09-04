"""Deterministic public-synthetic scale benchmark for CarbonFactorResolver.

This developer-only harness deliberately contains no production or licensed
factor data.  It measures the existing resolver through its public Python
request contract while keeping the generated catalogue reproducible.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from a1_factor_engine import (
    A1FactorResolutionEngine,
    DatabaseVersionAnchor,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    ResolutionRequest,
    SourceRecord,
)
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY
from a1_factor_engine.models import RetrievalIntent, RetrievalResult
from a1_factor_engine.semantic_index import SemanticFactorIndex

SCHEMA_VERSION = "cfr-public-synthetic-performance/1.0"
GENERATOR_VERSION = "public-synthetic-catalog/1.0"
GENERATOR_CONTRACT_SHA256 = hashlib.sha256(
    b"CFR public synthetic records; fixed UTC timestamp; no external values; v1"
).hexdigest()
TARGET_NAME = "public synthetic anchor material"
TARGET_SOURCE_ID = "public-synthetic-00000000"
FIXED_TIME = datetime(2025, 1, 1, tzinfo=UTC)


def _record(index: int) -> SourceRecord:
    is_target = index == 0
    name = TARGET_NAME if is_target else f"fixture compound {index:08x}"
    source_id = f"public-synthetic-{index:08d}"
    return SourceRecord(
        source_id=source_id,
        source_type=FactorSourceType.EPD,
        provider="CFR public synthetic generator",
        locator=f"synthetic://performance/{source_id}",
        material_name=name,
        factor_value=1.0 + (index % 997) / 1000,
        factor_unit="kgCO2e/kg",
        geography="CN",
        year=2025,
        product_form="bulk",
        production_process="synthetic reference process",
        boundary="cradle-to-gate",
        citation="Public-synthetic benchmark fixture; not a measured factor.",
        excerpt="Generated deterministically for software performance evaluation.",
        retrieved_at=FIXED_TIME,
        metadata={"data_class": "PUBLIC_SYNTHETIC", "generator": GENERATOR_VERSION},
        factor_kind=FactorKind.LIFECYCLE_FACTOR,
        subject_type=FactorSubjectType.UNKNOWN,
        indicator="GWP-total",
        declared_product=name,
        boundary_modules=("A1", "A2", "A3"),
        catalog_locator="synthetic://performance/catalog",
        source_document_sha256=hashlib.sha256(source_id.encode()).hexdigest(),
        page="synthetic-1",
        table="synthetic-1",
        row=str(index + 1),
    )


def generate_public_synthetic_catalog(count: int, *, seed: int = 20260902) -> tuple[SourceRecord, ...]:
    """Generate an ordered, deterministic catalogue with exactly one target."""

    if count < 1:
        raise ValueError("catalogue size must be positive")
    # The seed is part of the contract even though v1 intentionally emits a
    # canonical order.  Perturbation uses it independently below.
    if seed < 0:
        raise ValueError("seed must be non-negative")
    return tuple(_record(index) for index in range(count))


def catalog_sha256(records: Sequence[SourceRecord]) -> str:
    """Hash stable generated fields without timestamps or object reprs."""

    payload = [
        {
            "source_id": item.source_id,
            "name": item.material_name,
            "value": item.factor_value,
            "unit": item.factor_unit,
            "locator": item.locator,
            "document_sha256": item.source_document_sha256,
        }
        for item in sorted(records, key=lambda record: record.source_id)
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _anchor(records: Sequence[SourceRecord]) -> DatabaseVersionAnchor:
    digest = catalog_sha256(records)
    return DatabaseVersionAnchor(
        catalog_name="CFR public synthetic performance catalogue",
        catalog_version=GENERATOR_VERSION,
        database_sha256=digest,
        locator=f"synthetic://performance/catalog/{digest}",
        observed_at=FIXED_TIME,
    )


@dataclass(slots=True)
class _PrebuiltSemanticRepository:
    index: SemanticFactorIndex
    database_anchor: DatabaseVersionAnchor

    async def search(self, intent: RetrievalIntent) -> RetrievalResult:
        result = self.index.query(intent)
        return RetrievalResult(
            result.records,
            self.database_anchor,
            result.attempts,
            result.observations,
            result.anchor,
        )


def _request(request_id: str) -> ResolutionRequest:
    return ResolutionRequest(
        request_id=request_id,
        material_name=TARGET_NAME,
        quantity=1,
        quantity_unit="kg",
        geography="CN",
        year=2025,
        product_form="bulk",
        production_process="synthetic reference process",
        subject_type=FactorSubjectType.UNKNOWN,
        boundary="cradle-to-gate",
        target_factor_unit="kgCO2e/kg",
        top_k=5,
    )


def _intent() -> RetrievalIntent:
    intent = DEFAULT_MATERIAL_REGISTRY.resolve(TARGET_NAME).retrieval_intent
    if intent is None:  # defensive: registry implementations promise an intent
        raise RuntimeError("material registry did not produce a retrieval intent")
    return intent


def _top_ids(result: Any) -> tuple[str, ...]:
    return tuple(candidate.source.source_id for candidate in result.candidates)


def _retrieved_ids(result: Any) -> tuple[str, ...]:
    return tuple(record.source_id for record in result.records)


def _percentiles(samples_ms: Sequence[float]) -> dict[str, float | int]:
    ordered = sorted(samples_ms)
    if not ordered:
        return {"samples": 0, "min_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0}

    def percentile(fraction: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        "samples": len(ordered),
        "min_ms": round(ordered[0], 6),
        "p50_ms": round(percentile(0.50), 6),
        "p95_ms": round(percentile(0.95), 6),
        "p99_ms": round(percentile(0.99), 6),
        "max_ms": round(ordered[-1], 6),
    }


def peak_rss_bytes() -> int | None:
    """Return process peak RSS using only platform stdlib facilities."""

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            ok = psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            )
            return int(counters.PeakWorkingSetSize) if ok else None
        except (AttributeError, OSError):
            return None
    try:
        import resource

        getrusage = resource.getrusage
        rusage_self = resource.RUSAGE_SELF
        value = int(getrusage(rusage_self).ru_maxrss)
        return value if platform.system() == "Darwin" else value * 1024
    except (ImportError, OSError, ValueError):
        return None


async def _timed_resolve(engine: A1FactorResolutionEngine, request_id: str) -> tuple[float, tuple[str, ...]]:
    start = time.perf_counter_ns()
    result = await engine.resolve(_request(request_id))
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return elapsed_ms, _top_ids(result)


async def _benchmark_size(
    count: int,
    *,
    concurrency_levels: Sequence[int],
    warm_queries: int,
    seed: int,
) -> dict[str, Any]:
    generation_start = time.perf_counter_ns()
    records = generate_public_synthetic_catalog(count, seed=seed)
    digest = catalog_sha256(records)
    generation_ms = (time.perf_counter_ns() - generation_start) / 1_000_000
    anchor = _anchor(records)

    index_start = time.perf_counter_ns()
    index = SemanticFactorIndex(records, anchor, DEFAULT_MATERIAL_REGISTRY)
    index_build_ms = (time.perf_counter_ns() - index_start) / 1_000_000
    repository = _PrebuiltSemanticRepository(index, anchor)
    intent = _intent()

    repository_samples: list[float] = []
    repository_ids: list[tuple[str, ...]] = []
    for _ in range(warm_queries):
        start = time.perf_counter_ns()
        retrieved = await repository.search(intent)
        repository_samples.append((time.perf_counter_ns() - start) / 1_000_000)
        repository_ids.append(_retrieved_ids(retrieved))

    engine = A1FactorResolutionEngine(local_retrieval=repository)
    cold_ms, cold_ids = await _timed_resolve(engine, f"perf-{count}-cold")
    warm_samples: list[float] = []
    warm_ids: list[tuple[str, ...]] = []
    for index_number in range(warm_queries):
        elapsed, ids = await _timed_resolve(engine, f"perf-{count}-warm-{index_number}")
        warm_samples.append(elapsed)
        warm_ids.append(ids)

    concurrency: dict[str, Any] = {}
    for level in concurrency_levels:
        concurrent_engine = A1FactorResolutionEngine(local_retrieval=repository)
        started = time.perf_counter_ns()
        outcomes = await asyncio.gather(*(
            _timed_resolve(concurrent_engine, f"perf-{count}-c{level}-{number}")
            for number in range(level)
        ))
        wall_ms = (time.perf_counter_ns() - started) / 1_000_000
        samples = [item[0] for item in outcomes]
        signatures = [item[1] for item in outcomes]
        concurrency[str(level)] = {
            "requests": level,
            "wall_ms": round(wall_ms, 6),
            "throughput_requests_per_second": round(level / max(wall_ms / 1000, 1e-12), 6),
            "latency": _percentiles(samples),
            "top_k_stable": len(set(signatures)) == 1 and signatures[0] == cold_ids,
        }

    shuffled = list(records)
    random.Random(seed + count).shuffle(shuffled)
    shuffled_anchor = _anchor(shuffled)
    shuffled_index = SemanticFactorIndex(tuple(shuffled), shuffled_anchor, DEFAULT_MATERIAL_REGISTRY)
    shuffled_ids = _retrieved_ids(shuffled_index.query(intent))
    del shuffled_index, shuffled

    baseline_count = max(1, count // 2)
    baseline_records = records[:baseline_count]
    baseline_index = SemanticFactorIndex(
        baseline_records, _anchor(baseline_records), DEFAULT_MATERIAL_REGISTRY
    )
    baseline_ids = _retrieved_ids(baseline_index.query(intent))
    expanded_ids = _retrieved_ids(index.query(intent))

    replay_signatures = repository_ids + warm_ids
    deterministic = bool(replay_signatures) and len(set(replay_signatures)) == 1
    return {
        "catalog": {
            "record_count": count,
            "sha256": digest,
            "data_class": "PUBLIC_SYNTHETIC",
            "licensed_data_included": False,
            "generator_version": GENERATOR_VERSION,
            "generator_contract_sha256": GENERATOR_CONTRACT_SHA256,
        },
        "timings": {
            "catalog_generation_ms": round(generation_ms, 6),
            "semantic_index_build_ms": round(index_build_ms, 6),
            "cold_resolver_ms": round(cold_ms, 6),
            "cold_start_total_ms": round(generation_ms + index_build_ms + cold_ms, 6),
            "repository_query": _percentiles(repository_samples),
            "warm_resolver": _percentiles(warm_samples),
        },
        "concurrency": concurrency,
        "robustness": {
            "target_source_id": TARGET_SOURCE_ID,
            "cold_top_k": cold_ids,
            "deterministic_replay": {
                "passed": deterministic,
                "repetitions": len(replay_signatures),
                "signature_sha256": hashlib.sha256(
                    json.dumps(replay_signatures, separators=(",", ":")).encode()
                ).hexdigest(),
            },
            "catalog_order_perturbation": {
                "passed": shuffled_ids == expanded_ids,
                "catalog_sha_stable": catalog_sha256(records) == catalog_sha256(tuple(reversed(records))),
                "baseline_top_k": expanded_ids,
                "perturbed_top_k": shuffled_ids,
            },
            "noise_expansion_top_k": {
                "passed": baseline_ids == expanded_ids,
                "baseline_record_count": baseline_count,
                "expanded_record_count": count,
                "baseline_top_k": baseline_ids,
                "expanded_top_k": expanded_ids,
            },
        },
        "peak_rss_bytes": peak_rss_bytes(),
    }


async def run_scale_benchmark(
    sizes: Sequence[int] = (10_000, 50_000),
    concurrency_levels: Sequence[int] = (10, 25, 50),
    warm_queries: int = 7,
    *,
    seed: int = 20260902,
) -> Mapping[str, Any]:
    """Run scale benchmarks; callers may pass tiny sizes for CI smoke tests."""

    normalized_sizes = tuple(int(value) for value in sizes)
    normalized_concurrency = tuple(int(value) for value in concurrency_levels)
    if not normalized_sizes or any(value < 1 for value in normalized_sizes):
        raise ValueError("sizes must contain positive integers")
    if not normalized_concurrency or any(value < 1 for value in normalized_concurrency):
        raise ValueError("concurrency levels must contain positive integers")
    if warm_queries < 1:
        raise ValueError("warm_queries must be positive")

    results = []
    started = time.perf_counter_ns()
    for size in normalized_sizes:
        results.append(await _benchmark_size(
            size,
            concurrency_levels=normalized_concurrency,
            warm_queries=warm_queries,
            seed=seed,
        ))
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    hard_gates = {
        "deterministic_replay_100_percent": all(
            item["robustness"]["deterministic_replay"]["passed"]
            and all(load["top_k_stable"] for load in item["concurrency"].values())
            for item in results
        ),
        "catalog_order_invariant": all(
            item["robustness"]["catalog_order_perturbation"]["passed"] for item in results
        ),
        "noise_expansion_top_k_stable": all(
            item["robustness"]["noise_expansion_top_k"]["passed"] for item in results
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_kind": "developer-only public-synthetic performance and robustness",
        "production_performance_claim": False,
        "licensed_or_customer_data_included": False,
        "configuration": {
            "sizes": normalized_sizes,
            "concurrency_levels": normalized_concurrency,
            "warm_queries": warm_queries,
            "seed": seed,
            "execution_model": "asyncio workload over shared prebuilt semantic index",
        },
        "total_wall_ms": round(elapsed_ms, 6),
        "results": results,
        "hard_gates": hard_gates,
        "passed": all(hard_gates.values()),
        "caveats": (
            "Synthetic exact-match workload; results are not a production SLA.",
            "Peak RSS is process-lifetime high-water mark, not per-scale incremental allocation.",
            "CPU-bound semantic queries may serialize within one Python event loop.",
        ),
    }


def _integers(value: str) -> tuple[int, ...]:
    try:
        parsed = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not parsed or any(item < 1 for item in parsed):
        raise argparse.ArgumentTypeError("values must be positive integers")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=_integers, default=(10_000, 50_000))
    parser.add_argument("--concurrency", type=_integers, default=(10, 25, 50))
    parser.add_argument("--warm-queries", type=int, default=7)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(run_scale_benchmark(
        args.sizes,
        args.concurrency,
        args.warm_queries,
        seed=args.seed,
    ))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
