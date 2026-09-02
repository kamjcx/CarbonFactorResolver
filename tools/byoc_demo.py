"""Run three contract examples against the public-synthetic BYOC catalogue."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.engine import A1FactorResolutionEngine
from a1_factor_engine.serialization import to_jsonable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "fixtures" / "catalog" / "byoc_public_synthetic_20.json"

EXAMPLE_REQUESTS: Mapping[str, Mapping[str, Any]] = {
    "exact": {
        "request_id": "byoc-demo-exact",
        "material_name": "bauxite ore",
        "quantity": 1,
        "quantity_unit": "kg",
        "subject_type": "raw_material",
        "boundary": "A1",
        "product_form": "ore",
        "production_process": "mined",
        "target_factor_unit": "kgCO2e/kg",
        "top_k": 3,
    },
    "more-input": {
        "request_id": "byoc-demo-more-input",
        "material_name": "spinel",
        "quantity": 1,
        "quantity_unit": "kg",
        "subject_type": "raw_material",
        "boundary": "A1",
        "target_factor_unit": "kgCO2e/kg",
        "top_k": 3,
    },
    "safe-refusal": {
        "request_id": "byoc-demo-safe-refusal",
        "material_name": "unobtainium fiber",
        "quantity": 1,
        "quantity_unit": "kg",
        "subject_type": "raw_material",
        "boundary": "A1",
        "target_factor_unit": "kgCO2e/kg",
        "top_k": 3,
    },
}


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("BYOC catalogue must be a JSON object")
    return payload


def build_engine(path: Path = DEFAULT_CATALOG) -> A1FactorResolutionEngine:
    payload = load_catalog(path)
    repository = HttpCatalogFactorRepository(
        endpoint="fixture://byoc-public-synthetic-20",
        fetch_json=lambda _endpoint: payload,
    )
    return A1FactorResolutionEngine(local_retrieval=repository)


async def run_cases(
    names: Sequence[str],
    *,
    catalog_path: Path = DEFAULT_CATALOG,
) -> dict[str, Any]:
    unknown = tuple(name for name in names if name not in EXAMPLE_REQUESTS)
    if unknown:
        raise ValueError(f"unknown BYOC example(s): {', '.join(unknown)}")
    engine = build_engine(catalog_path)
    results = {
        name: to_jsonable(await engine.resolve(dict(EXAMPLE_REQUESTS[name])))
        for name in names
    }
    return {
        "catalog": (
            catalog_path.resolve().relative_to(ROOT).as_posix()
            if catalog_path.resolve().is_relative_to(ROOT)
            else catalog_path.name
        ),
        "data_classification": "PUBLIC_SYNTHETIC",
        "not_for_carbon_accounting": True,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=(*EXAMPLE_REQUESTS, "all"),
        default="all",
        help="example contract to execute",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args(argv)
    names = tuple(EXAMPLE_REQUESTS) if args.case == "all" else (args.case,)
    result = asyncio.run(run_cases(names, catalog_path=args.catalog))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
