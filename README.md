# CarbonFactorResolver

[![CI](https://github.com/kamjcx/CarbonFactorResolver/actions/workflows/ci.yml/badge.svg)](https://github.com/kamjcx/CarbonFactorResolver/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kamjcx/CarbonFactorResolver)](https://github.com/kamjcx/CarbonFactorResolver/releases/latest)
[![Python 3.11–3.13](https://img.shields.io/badge/python-3.11%E2%80%933.13-0b695f)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ed713a)](LICENSE)

**Evidence-governed carbon-factor retrieval and qualification for materials, energy,
transport, and processes.** CarbonFactorResolver (CFR) receives a structured factor request
and returns one of three reviewable outcomes: a qualified candidate, a precise
`MORE_INPUT_NEEDED` question, or a safe refusal.

> **Portfolio status:** reproducible research prototype, not a production carbon-accounting
> system. CFR is a deterministic retrieval-and-qualification engine—not an autonomous LLM
> agent—and bundled factor records are project-authored synthetic examples.

![CarbonFactorResolver dashboard resolving a synthetic primary aluminium query](docs/assets/dashboard-resolved.png)

## The problem, the responsibility, the safety value

Semantic similarity can find a plausible but invalid factor: a finished product for a raw
material, an A1-A3 total for an A2 request, ordinary graphite for a graphite electrode, or a
mass factor for an energy activity. CFR separates broad recall from formal admission.

| CFR receives | CFR is responsible for | CFR returns |
|---|---|---|
| structured `FactorQuery` / `ResolutionRequest` JSON | entity resolution, structured-source retrieval, deterministic unit/boundary/subject/provenance checks, ranking and explanation | qualified recommendations, `MORE_INPUT_NEEDED`, or a reason-coded refusal for human review and locking |

It does **not** parse documents, extract BOM or activity data, calculate a complete product
footprint, generate reports, or automatically approve formal factors. Numeric values must
come from traceable source records; the model cannot invent a factor value.

## Verified public-synthetic evidence

| Gate | Published result |
|---|---:|
| Core package | 360 tests passed on Python 3.11; 87.15% branch coverage |
| Python compatibility | complete suite passed on 3.11, 3.12, and 3.13 |
| FactorBench V3 | 57 versioned contracts passed |
| Closed portfolio diagnostic | 39 direct recommendations + 1 correct `MORE_INPUT_NEEDED` with `REFERENCE_ONLY` |
| RC6 sealed first run | 48/48 complete contracts; 0 boundary, subject, unit, forbidden-candidate, or HTTP-500 escapes |

These figures measure frozen, public-synthetic fixtures and contracts. They are not a claim
of universal real-world accuracy, production readiness, or validity for carbon accounting.
Historical first-run failures, adjudications, denominators, hashes, and scale results remain
available in [Evaluation](EVALUATION.md) and the [evidence index](evidence/README.md).

## 30-second quickstart

The default runtime ships only small project-authored synthetic fixtures. It does not
download or include ecoinvent, customer records, or any commercial factor database.

```bash
git clone https://github.com/kamjcx/CarbonFactorResolver.git
cd CarbonFactorResolver
docker compose up --build -d
curl http://127.0.0.1:8000/healthz
```

Open `http://127.0.0.1:8000`, or resolve a structured JSON request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "material_name": "primary aluminium ingot",
    "quantity": 1,
    "quantity_unit": "t",
    "production_process": "primary aluminium production"
  }'
```

Python development setup:

```bash
pip install -e ".[test,api]"
cfr resolve --material "aluminium" --quantity 1 --unit t
cfr benchmark run data/benchmarks/factorbench_v3.jsonl
```

To connect an authorized structured catalogue, follow the
[Bring Your Own Catalog tutorial](docs/BRING_YOUR_OWN_CATALOG.md). Imported records remain
candidates until a human reviews and locks a factor.

## How a decision is made

```text
Document Intelligence / carbon-report
             |
             | structured ResolutionRequest
             v
     CarbonFactorResolver
             |
             | reviewed / locked factor
             v
carbon-report calculation and report generation
```

![CarbonFactorResolver internal decision flow from structured request through retrieval, deterministic gates, human review, and immutable lock](docs/assets/cfr-resolution-architecture.png)

Retrieval may be broad, but only deterministically qualified candidates reach ranking and
review. Exclusions remain visible with stable reason codes in Trace. See
[Architecture](ARCHITECTURE.md) for component and trust-boundary details.

## Three demo decisions

| Request | Expected behavior | Safety property |
|---|---|---|
| `primary aluminium ingot` + primary-production process | returns the traceable primary-aluminium candidate | exact entity/process qualification |
| `metallic aluminium feedstock` without a route | returns `MORE_INPUT_NEEDED` | does not choose primary vs. secondary production |
| unknown material or cross-dimension unit | returns a reason-coded refusal | does not invent a numeric factor |

![Candidate evidence and deterministic qualification trace](docs/assets/dashboard-evidence.png)

See the [90-second demo script](docs/DEMO_SCRIPT_90S.md) for an interview walkthrough.

## Product boundary

**In scope:** structured requests; multilingual entity resolution and controlled aliases;
local and structured external-source retrieval; deterministic qualification, ranking,
explanation and Trace; human review support and immutable locking.

**Out of scope:** PDF/DOCX/Excel/image parsing and OCR; BOM, procurement-ledger, or enterprise
activity-data extraction; full product-carbon-footprint calculation; report generation; and
automatic catalogue writes or approvals.

`tools/true_data_acceptance.py` and the autonomous evaluator are developer-only offline QA
harnesses. They are not imported by the runtime or exposed as CFR product capabilities.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Evaluation methodology, detailed results, and historical failures](EVALUATION.md)
- [Evidence and generated-artifact policy](evidence/README.md)
- [Limitations](LIMITATIONS.md)
- [Data licensing](DATA_LICENSE.md)
- [Security policy](SECURITY.md)
- [Bring Your Own Catalog](docs/BRING_YOUR_OWN_CATALOG.md)
- [v0.14.2 release readiness](docs/RELEASE_READINESS_V0.14.2.md)
- [v0.14.2 release notes](docs/RELEASE_NOTES_V0.14.2.md)

## Data and license

The software is available under the [MIT License](LICENSE). Code licensing does not grant
rights to third-party factor data. No ecoinvent database, licensed factor export, customer
document, credential, or formal production catalogue is included. Users must provide their
own authorized structured sources and comply with their data licences; see
[DATA_LICENSE.md](DATA_LICENSE.md).
