# CarbonFactorResolver

[![CI](https://github.com/kamjcx/CarbonFactorResolver/actions/workflows/ci.yml/badge.svg)](https://github.com/kamjcx/CarbonFactorResolver/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kamjcx/CarbonFactorResolver)](https://github.com/kamjcx/CarbonFactorResolver/releases/latest)
[![Python 3.11–3.13](https://img.shields.io/badge/python-3.11%E2%80%933.13-0b695f)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ed713a)](LICENSE)

**Evidence-governed carbon-factor retrieval and qualification for materials, energy,
transport, and processes.** CFR turns a structured factor request into an explainable
candidate, a precise `MORE_INPUT` question, or a safe refusal. Numeric values always come
from traceable source records; deterministic gates enforce unit, lifecycle-boundary,
subject, and provenance compatibility before human review and immutable locking.

> **Status:** portfolio-ready, reproducible research prototype. Bundled evaluations use
> public-synthetic fixtures. Results are not a claim of universal real-world accuracy or
> production carbon-accounting readiness.

![CarbonFactorResolver dashboard resolving a synthetic primary aluminium query](docs/assets/dashboard-resolved.png)

## Why this exists

Semantic similarity alone can return a plausible but invalid factor: a finished product for
a raw material, A1-A3 total for an A2 request, ordinary graphite for a graphite electrode,
or a mass factor for an energy activity. CFR separates recall from admission:

1. resolve the material or activity entity and its modifiers;
2. retrieve local and hash-pinned structured external records;
3. reject incompatible units, boundaries, subjects, processes, and evidence;
4. rank only qualified candidates and explain every inclusion and exclusion;
5. require a human decision before an immutable factor is locked.

![CarbonFactorResolver structured decision architecture](docs/assets/cfr-resolution-architecture.png)

The editable diagram source is
[docs/assets/cfr-resolution-architecture.html](docs/assets/cfr-resolution-architecture.html).

## Five-minute quickstart

The default runtime uses small project-authored synthetic fixtures. It does not download or
ship ecoinvent, customer records, or any commercial factor database.

```bash
git clone https://github.com/kamjcx/CarbonFactorResolver.git
cd CarbonFactorResolver
docker compose up --build -d
curl http://127.0.0.1:8000/healthz
```

Open `http://127.0.0.1:8000`, or submit a JSON request:

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

Python/CLI development setup:

```bash
pip install -e ".[test,api]"
cfr resolve --material "aluminium" --quantity 1 --unit t
cfr benchmark run data/benchmarks/factorbench_v3.jsonl
cfr serve --host 127.0.0.1 --port 8000
```

## Three demo decisions

| Request | Expected behavior | Safety property |
|---|---|---|
| `primary aluminium ingot` + primary-production process | returns the traceable primary-aluminium candidate | exact entity/process qualification |
| `metallic aluminium feedstock` without a route | returns `MORE_INPUT_NEEDED` | does not choose primary vs. secondary production |
| unknown material or cross-dimension unit | returns a safe refusal with reason codes | never invents a numeric factor |

The Dashboard exposes the pipeline, terminal state, candidate evidence, score, result tier,
and decision reasons rather than presenting an unexplained search result.

![Candidate evidence and deterministic qualification trace](docs/assets/dashboard-evidence.png)

See the [90-second demo script](docs/DEMO_SCRIPT_90S.md) for a concise interview walkthrough.

## Autonomous contract evaluation

The developer-only evaluator generates 414 non-duplicate public-synthetic cases from an
independent, versioned Oracle. It exercises exact boundary and subject matrices, unit
dimensions, evidence degradation, source priority, ambiguity, high-risk neighbouring
entities, deterministic replay, catalog perturbation, and approval/lock attacks against the
real Resolver. A separate scale harness measures 10k/50k synthetic catalogs at concurrency
10/25/50. Neither harness changes or approves a factor, and neither contains licensed or
customer data.

```bash
python -m tools.autonomous_evaluation --output outputs/autonomous-evaluation.json
python -m tools.autonomous_evaluation.performance --sizes 10000,50000 --concurrency 10,25,50
```

Generated expectations come from explicit contracts rather than from Resolver output. First
runs, failures, Bad Case attribution and artifact hashes are retained; a failed gate is a
diagnostic result, not tuned away. See the
[autonomous evaluation specification](docs/CFR_AUTONOMOUS_EVALUATION_V1.md).

## Architecture and product boundary

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

**In scope**

- structured `FactorQuery` / `ResolutionRequest` input;
- multilingual entity resolution and controlled aliases;
- local and structured external factor-source retrieval;
- deterministic qualification, ranking, explanation, and Trace;
- human review support and immutable factor locking.

**Out of scope**

- PDF, DOCX, Excel, image parsing, or OCR;
- BOM, procurement-ledger, or enterprise activity-data extraction;
- full product-carbon-footprint calculation and report generation;
- automatic writes to, or approval in, a formal factor catalogue.

The document-capable tool under `tools/true_data_acceptance.py` is a developer-only offline
QA harness. It is not imported by the runtime or exposed through the CFR API.

## Reproducible evaluation

| Evidence set | Result | What it proves |
|---|---:|---|
| Core package | 324 passed, 87.06% branch coverage | implementation regression gate |
| FactorBench V3 | 57 cases, contract metrics passed | versioned resolver behavior |
| Frozen Unit Regression | first run 24/28; post-fix 28/28 | unit-system regression, not an independent holdout |
| Closed Portfolio Benchmark | 39 direct + 1 `MORE_INPUT` with correct `REFERENCE_ONLY`; 0 boundary/subject violations | public-synthetic comparison and safety diagnostic |
| Sealed Unit Holdout v4 | independent first run 21/21; all checks 100% | post-fix unit-only acceptance |
| RC6 sealed first run | 48/48 full contracts; 0 safety escapes or HTTP 500 | frozen public-synthetic release gate |
| Autonomous Evaluation V1 | 414 generated contracts + workflow attacks + 10k/50k scale | systematic contract exploration; results do not replace sealed or real-world validation |

RC3-RC5 and sealed unit v2/v3 remain preserved NO-GO evidence. `v0.14.1` adds the
conditioned-volume direction repair, FIN-05 reference-only adjudication, and the independent
sealed unit v4 acceptance. See
[Evaluation](EVALUATION.md), [Release Readiness](docs/RELEASE_READINESS_V0.14.1.md), and the
[v0.14.1 release](https://github.com/kamjcx/CarbonFactorResolver/releases/tag/v0.14.1).

## Design guarantees

- No language model or fallback code may originate an emission-factor value.
- Exact A1/A2/A3/A1-A3 and factor-subject matrices fail closed.
- Unsupported or cross-dimension units return stable reason codes.
- Source locator, content hash, declared product, boundary, and database anchors stay in Trace.
- Rejected candidates cannot later be approved in the same immutable resolution run.
- `REFERENCE_ONLY` results require an explicit, reasoned human override.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Evaluation methodology and results](EVALUATION.md)
- [Limitations](LIMITATIONS.md)
- [Data licensing](DATA_LICENSE.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Release notes](docs/RELEASE_NOTES_V0.14.1.md)
- [Technical implementation reference](docs/CFR_TECHNICAL_DOCUMENT.md)

## Data and license

The software is available under the [MIT License](LICENSE). Code licensing does not grant
rights to third-party factor data. No ecoinvent database, licensed factor export, customer
document, credential, or formal production catalogue is included. Users must provide their
own authorized structured sources and comply with their data licences; see
[DATA_LICENSE.md](DATA_LICENSE.md).
