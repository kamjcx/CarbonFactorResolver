from __future__ import annotations

import json

import pytest

from tools.autonomous_evaluation.performance import (
    GENERATOR_CONTRACT_SHA256,
    catalog_sha256,
    generate_public_synthetic_catalog,
    run_scale_benchmark,
)


def test_public_synthetic_catalog_is_deterministic_and_disclaims_licensed_data() -> None:
    first = generate_public_synthetic_catalog(12)
    second = generate_public_synthetic_catalog(12)

    assert catalog_sha256(first) == catalog_sha256(second)
    assert len(GENERATOR_CONTRACT_SHA256) == 64
    assert first[0].source_id == "public-synthetic-00000000"
    assert all(record.provider == "CFR public synthetic generator" for record in first)
    assert all(record.metadata["data_class"] == "PUBLIC_SYNTHETIC" for record in first)


@pytest.mark.parametrize("count", [0, -1])
def test_public_synthetic_catalog_rejects_invalid_sizes(count: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        generate_public_synthetic_catalog(count)


@pytest.mark.asyncio
async def test_scale_benchmark_smoke_schema_determinism_and_metrics() -> None:
    report = await run_scale_benchmark(
        sizes=(24,), concurrency_levels=(2, 4), warm_queries=2, seed=17
    )

    assert report["schema_version"] == "cfr-public-synthetic-performance/1.0"
    assert report["passed"] is True
    assert report["production_performance_claim"] is False
    assert report["licensed_or_customer_data_included"] is False
    assert report["hard_gates"] == {
        "deterministic_replay_100_percent": True,
        "catalog_order_invariant": True,
        "noise_expansion_top_k_stable": True,
    }

    result = report["results"][0]
    assert result["catalog"]["record_count"] == 24
    assert result["catalog"]["licensed_data_included"] is False
    assert len(result["catalog"]["sha256"]) == 64
    assert result["timings"]["catalog_generation_ms"] >= 0
    assert result["timings"]["semantic_index_build_ms"] >= 0
    assert result["timings"]["cold_start_total_ms"] >= result["timings"]["cold_resolver_ms"]
    assert result["timings"]["repository_query"]["samples"] == 2
    assert result["timings"]["warm_resolver"]["samples"] == 2
    assert set(result["concurrency"]) == {"2", "4"}
    assert all(item["top_k_stable"] for item in result["concurrency"].values())
    assert result["robustness"]["cold_top_k"] == ("public-synthetic-00000000",)
    assert result["robustness"]["deterministic_replay"]["passed"] is True
    assert result["robustness"]["catalog_order_perturbation"]["passed"] is True
    assert result["robustness"]["catalog_order_perturbation"]["catalog_sha_stable"] is True
    assert result["robustness"]["noise_expansion_top_k"]["passed"] is True
    json.dumps(report, allow_nan=False)


@pytest.mark.asyncio
async def test_scale_benchmark_validates_configuration() -> None:
    with pytest.raises(ValueError, match="sizes"):
        await run_scale_benchmark(sizes=(), concurrency_levels=(1,), warm_queries=1)
    with pytest.raises(ValueError, match="concurrency"):
        await run_scale_benchmark(sizes=(1,), concurrency_levels=(0,), warm_queries=1)
    with pytest.raises(ValueError, match="warm_queries"):
        await run_scale_benchmark(sizes=(1,), concurrency_levels=(1,), warm_queries=0)
