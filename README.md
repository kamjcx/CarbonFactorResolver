# CarbonFactorResolver

[![CI](https://github.com/kamjcx/CarbonFactorResolver/actions/workflows/ci.yml/badge.svg)](https://github.com/kamjcx/CarbonFactorResolver/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kamjcx/CarbonFactorResolver)](https://github.com/kamjcx/CarbonFactorResolver/releases/latest)
[![Python 3.11–3.13](https://img.shields.io/badge/python-3.11%E2%80%933.13-0b695f)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ed713a)](LICENSE)

**Turn ambiguous carbon-factor searches into reviewable, traceable accounting inputs.**

CarbonFactorResolver grew out of a refractory-material carbon-accounting system. It turns
structured material, energy, transport and process queries into qualified factor candidates with
provenance, units, lifecycle boundaries and explicit applicability constraints. When information
is insufficient, CFR asks for the specific missing input instead of guessing. When an available
factor uses a different production route, CFR can derive an evidence-backed process adjustment.
After human review, the selected factor is locked as an immutable accounting input.

> **Status:** portfolio-ready, reproducible research prototype. CFR is a factor-resolution
> component, not a complete production carbon-accounting platform. Bundled evaluations use
> public-synthetic fixtures and do not claim universal real-world accuracy.

![CarbonFactorResolver dashboard resolving a synthetic primary aluminium query](docs/assets/dashboard-resolved.png)

## In 30 seconds

| Question | Answer |
|---|---|
| What problem does it solve? | Similar names can hide incompatible materials, processes, units, lifecycle boundaries and factor subjects. |
| What was built? | The structured API, entity resolution, hybrid retrieval, deterministic qualification, Gap Analysis, evidence-backed derivation, explanation, review state machine, immutable locking and evaluation gates. |
| What does the quickstart demo show? | Pipeline progress, terminal state, qualified candidate evidence, score, result tier, decision reasons, `MORE_INPUT` and safe refusal. |
| What does the repository additionally cover? | Full Trace and exclusion diagnostics, evidence-backed process adjustment, human-review state transitions and immutable locking through code and regression tests. |
| Where does it fit? | Between upstream document/activity-data extraction and downstream footprint calculation and report generation. |

## Where it fits

```text
Enterprise documents / Document Intelligence / carbon-report
                           |
                           | structured ResolutionRequest
                           v
                   CarbonFactorResolver
                           |
          validate request, units and source records
                           |
             resolve material, subject and process
                           |
              retrieve structured factor records
                           |
          deterministic qualification and hard gates
                           |
                      Gap Analysis
             /              |               \
      exact match    resolvable gap      unresolved gap
             |              |               |
             |       evidence-backed      MORE_INPUT /
             |        transformation      REFERENCE_ONLY /
             |              |             safe refusal
             +--------------+
                           |
                    rank and explain
                           |
                 human review and lock
                           |
                           | reviewed / locked factor
                           v
          carbon-report calculation and report generation
```

Gap Analysis is not limited to production-process differences. The implemented gap model covers
unit scale, reference flow, process variant, grade/composition, missing target material, lifecycle
boundary, geography, time and product form. Subject compatibility and provenance completeness are
enforced separately by the qualification and admission gates. Only a closed, source-backed
deterministic transformation can produce a derived factor. An unresolved gap becomes a precise
question, a reference-only result or a safe refusal rather than an invented value.

## What the quickstart demo shows

| Request | Resolver decision | Engineering behavior |
|---|---|---|
| `primary aluminium ingot` + primary-production route | direct qualified candidate | exact entity, route and evidence qualification |
| `metallic aluminium feedstock` without a route | `MORE_INPUT_NEEDED` | does not silently choose primary or secondary production |
| unknown material or cross-dimension unit | safe refusal with reason codes | never invents a numeric factor |

The default Dashboard exposes pipeline progress, terminal state, qualified candidate evidence,
score, result tier and decision reasons instead of presenting an unexplained search result.
It does not expose full Trace, rejected-candidate diagnostics, process-transformation steps or the
admin review/lock surface. Those are repository and regression-test capabilities, not claims about
the default Quickstart UI.

![Candidate evidence and deterministic qualification trace](docs/assets/dashboard-evidence.png)

See the [90-second demo script](docs/DEMO_SCRIPT_90S.md) for an interview walkthrough.

## Why this exists

Semantic similarity alone can return a plausible but invalid factor: a finished product for a raw
material, an A1-A3 total for an A2 request, ordinary graphite for a graphite electrode, or a mass
factor for an energy activity. CFR separates recall from admission:

1. resolve the material or activity entity and its modifiers;
2. retrieve local and hash-pinned structured external records;
3. reject incompatible units, boundaries, subjects, processes and evidence;
4. analyse resolvable and unresolved gaps;
5. rank only qualified candidates and explain every inclusion and exclusion;
6. require a human decision before an immutable factor is locked.

![CarbonFactorResolver internal decision flow from structured request through retrieval, deterministic gates, human review, and immutable lock](docs/assets/cfr-resolution-architecture.png)

Retrieval may be broad, but only deterministically qualified candidates reach ranking and review.
Exclusions remain visible with reason codes in Trace. Editable diagram sources:
[HTML](docs/assets/cfr-resolution-architecture.html) and
[SVG](docs/assets/cfr-resolution-architecture.svg).

## Current quality snapshot

| Gate | Current `main` result |
|---|---:|
| Test suite | 587 passed |
| Branch coverage | 86.91% |
| Python compatibility | 3.11 / 3.12 / 3.13 |
| Boundary, subject and unit safety regressions | PASS |
| Deterministic replay and review/lock integrity | PASS |
| Protected GitHub Actions delivery gate | PASS |

These results demonstrate deterministic contract behavior and safety properties on the documented
fixtures. They are not a claim of universal real-world retrieval accuracy. Historical first runs,
failed release candidates, Raw V1 Bad Cases, adjudications and artifact hashes remain available in
[Evaluation](EVALUATION.md) rather than being rewritten after fixes.

## Five-minute quickstart

The Compose quickstart uses small project-authored public-synthetic fixtures. It does not download
or ship ecoinvent, customer records or any commercial factor database.

```bash
git clone https://github.com/kamjcx/CarbonFactorResolver.git
cd CarbonFactorResolver
docker compose up --build -d
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

Open `http://127.0.0.1:8000`, or submit a structured JSON request:

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
cfr resolve --demo --material "aluminium" --quantity 1 --unit t
cfr benchmark run data/benchmarks/factorbench_v3.jsonl
cfr serve --demo --host 127.0.0.1 --port 8000
```

To connect a licensed or internal structured catalogue, follow the
[Bring Your Own Catalog tutorial](docs/BRING_YOUR_OWN_CATALOG.md). Imported records remain
candidates until a human reviews and locks a factor; the tutorial does not authorize accounting use.

## How resolution works

1. **Validate** the closed JSON contract, numeric ranges and unit syntax.
2. **Resolve** the material/activity entity, subject, process, form and grade.
3. **Retrieve** from local and hash-pinned structured external sources.
4. **Qualify** unit dimension, boundary, subject, process and provenance before ranking.
5. **Analyse gaps** and choose a direct result, a supported transformation, `MORE_INPUT`,
   `REFERENCE_ONLY`, `PROCESS_MODEL_REQUIRED` or a safe refusal.
6. **Rank and explain** only qualified candidates while retaining exclusions in Trace.
7. **Review and lock** one approved candidate with content hashes and compare-and-set semantics.

The implemented Gap Analysis types and their controlled outcomes are:

| Gap | Allowed resolution |
|---|---|
| unit scale | deterministic same-dimension conversion; otherwise reject |
| reference flow | controlled conversion using explicit parameter evidence; otherwise request evidence or reject |
| process variant | subtract the evidence-backed reference process and add the evidence-backed target process; otherwise require a process model |
| grade or composition | use a supported grade/composition resolution, disclose a proxy/reference tier, or ask for clarification |
| target material absent | use only a class-aware, disclosed material proxy path; never bridge materials by similarity score alone |
| lifecycle boundary | record the difference, then enforce the exact-stage qualification matrix before admission |
| geography | retain a visible limitation or request a better-scoped source according to policy |
| temporal coverage | retain the year delta and limitation or request a current source according to policy |
| product form | retain the form difference, downgrade or ask for clarification according to policy |

Outside Gap Analysis, wrong factor subjects and incomplete provenance are admission failures: they
cannot be repaired by ranking or by a process-adjustment formula.

The electrofused-spinel implementation uses the versioned formula
`process.replace_energy_and_additional_process/v2`:

```text
target factor
= reference lifecycle factor
- documented reference-route energy
- documented reference additional-process emissions
+ documented target-route energy
+ documented target additional-process emissions
```

This is a factor-level, evidence-governed derivation. Full activity multiplication, A1-A3
aggregation and product-footprint reporting remain downstream `carbon-report` responsibilities.

## Product boundary

**In scope**

- structured `FactorQuery` / `ResolutionRequest` input;
- multilingual entity resolution and controlled aliases;
- local and structured external factor-source retrieval;
- deterministic qualification, Gap Analysis, supported derivation, ranking, explanation and Trace;
- human review support and immutable factor locking.

**Out of scope**

- PDF, DOCX, Excel, image parsing or OCR;
- BOM, procurement-ledger or enterprise activity-data extraction;
- full product-carbon-footprint calculation and report generation;
- automatic writes to, or approval in, a formal factor catalogue.

The document-capable `tools/true_data_acceptance.py` is a developer-only offline QA harness. It is
not imported by the runtime or exposed through the CFR API.

## Design guarantees

- No language model or fallback code may originate an emission-factor value.
- Exact A1/A2/A3/A1-A3 and factor-subject matrices fail closed.
- Unsupported or cross-dimension units return stable reason codes.
- Source identity, content hash, declared product, boundary and database anchors remain in Trace.
- Candidate, recommendation, approval, reviewer and locked evidence are content-addressed.
- Locking uses compare-and-set semantics and freezes a separate evidence snapshot.
- Rejected candidates cannot later be approved in the same immutable resolution run.
- `REFERENCE_ONLY` results require an explicit, reasoned human override.

## Deployment and security boundary

The default `create_app` is a fail-closed data plane for a trusted single scope or a deployment
behind an enforcing authorization gateway. It is not a complete multi-tenant IAM system and does
not load demo fixtures unless demo mode is explicitly selected. Full Trace and diagnostics are
available only through the separately protected admin/development surface.

Live structured-source adapters are HTTPS-only and bounded against SSRF, redirect,
credential-forwarding, timeout and oversized-response attacks. Persistent multi-instance storage,
tenant authorization, trust-root management, monitoring, recovery and formal factor-data approval
remain deployment responsibilities. See the
[connector threat model](docs/CFR_CONNECTOR_CONTROL_PLANE_SECURITY_V4.md),
[API safety contract](docs/CFR_API_SAFETY_CONTRACT.md),
[engineering hardening contract](docs/CFR_ENGINEERING_DELIVERY_HARDENING_V6.md) and
[Limitations](LIMITATIONS.md).

## Reproducible evaluation and historical evidence

FactorBench, Frozen and Sealed Unit sets, the Portfolio benchmark and Autonomous Contract
Evaluation exercise the actual Resolver. Generated expectations come from explicit versioned
contracts rather than Resolver output. First runs, failed release candidates, Bad Case attribution,
adjudications and artifact hashes are retained instead of being tuned away after fixes.

The evidence is separated by what it proves: regression consistency, sealed first-run behavior,
safety properties and scale measurements are not presented as one universal accuracy score. See
[Evaluation](EVALUATION.md), the
[autonomous evaluation specification](docs/CFR_AUTONOMOUS_EVALUATION_V1.md), the
[V3 quality-gate contract](docs/CFR_AUTONOMOUS_QUALITY_GATE_V3.md), the
[v0.14.4 release readiness report](docs/RELEASE_READINESS_V0.14.4.md) and the
[v0.14.4 release](https://github.com/kamjcx/CarbonFactorResolver/releases/tag/v0.14.4).

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Evaluation methodology and results](EVALUATION.md)
- [Limitations](LIMITATIONS.md)
- [Data licensing](DATA_LICENSE.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Bring Your Own Catalog](docs/BRING_YOUR_OWN_CATALOG.md)
- [Catalog-to-lock integrity contract](docs/CFR_CATALOG_LOCK_INTEGRITY_V3.md)
- [Human-review workflow state machine](docs/CFR_REVIEW_WORKFLOW_STATE_MACHINE_V1.md)
- [Public API safety contract](docs/CFR_API_SAFETY_CONTRACT.md)
- [Unit field contract](docs/CFR_UNIT_FIELD_CONTRACT_V1.md)
- [Versioned API and operability contract](docs/CFR_VERSIONED_API_OPERABILITY_V5.md)
- [Release notes](docs/RELEASE_NOTES_V0.14.4.md)
- [Technical implementation reference](docs/CFR_TECHNICAL_DOCUMENT.md)

## Data and license

The software is available under the [MIT License](LICENSE). Code licensing does not grant rights to
third-party factor data. No ecoinvent database, licensed factor export, customer document,
credential or formal production catalogue is included. Users must provide their own authorized
structured sources and comply with their data licences; see [DATA_LICENSE.md](DATA_LICENSE.md).
