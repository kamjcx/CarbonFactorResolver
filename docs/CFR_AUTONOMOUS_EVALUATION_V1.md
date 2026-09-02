# CFR Autonomous Evaluation V1

## Scope

This is a developer-only offline evaluation system. It sends structured requests to the real
CarbonFactorResolver runtime, but it is not part of the production API and cannot approve or
write factor data. All generated records are project-authored `PUBLIC_SYNTHETIC` data. No
ecoinvent, customer, licensed, or formal internal catalog content is used.

The evaluation PR may change only `tools/`, tests, documentation, CI evidence collection and
new evaluation artifacts. Resolver retrieval, ranking, qualification, candidate IDs, factor
values and existing frozen answers are immutable.

## Independent Oracle

The Oracle is a small declarative contract implementation. It does not import runtime
qualification, ranking or matching helpers. Its reviewed tables define:

- exact `A1`, `A2`, `A3`, and `A1-A3` boundary compatibility;
- exact raw-material, finished-product, energy, transport, process and waste subjects;
- mass, energy, transport-work and conditioned-volume unit dimensions;
- traceable source evidence, quality, admission and publication requirements;
- applicability-first source priority;
- reference-only ambiguity alternatives and safe refusal.

The default seed `20260902` creates 414 unique semantic fingerprints over 20 synthetic
records. Cases include multilingual aliases, reviewed typos, quantity/order/noise
metamorphics, high-risk neighbouring entities, source-priority conflicts, provenance
degradation, missing decisive attributes, geography/year conflicts and the complete 4x4
boundary matrix.

## Workflow attacks

The state-machine suite attempts to approve an unreturned candidate, use standard approval on
`REFERENCE_ONLY`, approve a hard-blocked candidate, modify a locked result, replay an old
catalog, tamper with a catalog hash, reapprove a rejected candidate, and race duplicate
approve/lock operations. Failures are preserved as Bad Cases; the harness never repairs them.

## Metrics and gates

Every rate stores its numerator and denominator; zero denominators are reported as `N/A`.
The report includes Direct Top-1, Recall@5, abstention, MORE_INPUT recall, unnecessary-question
rate, forbidden-candidate escape, boundary/subject/unit violations, proxy disclosure, evidence
metadata presence, deterministic replay, HTTP 500s, unknown reason codes and harness errors.

Hard gates require Top-1 >=90%, Recall@5 >=95%, abstention and MORE_INPUT >=90%, complete
evidence metadata, 100% replay, zero forbidden/boundary/subject/unit escapes, zero unhandled
HTTP 500s, zero unknown reason codes, zero harness errors, and all state-machine attacks.

Bad Cases use stable attribution categories: query ambiguity, catalog coverage, alias/entity,
retrieval, ranking, unit, boundary, subject, provenance, benchmark-label disagreement, and
explanation/UI failure.

## Performance and robustness

`tools.autonomous_evaluation.performance` generates deterministic 10k and 50k synthetic
catalogs and measures catalog/index construction, cold and warm Resolver latency, repository
latency, P50/P95/P99, peak RSS and throughput at concurrency 10/25/50. It also tests repeated
resolution, catalog ordering, unrelated noise expansion and Top-K stability.

The benchmark is descriptive. It uses one Python process and a synthetic workload, so its
numbers are not a production SLA or evidence about licensed-catalog semantics.

## Evidence lifecycle

1. Freeze and commit evaluator code and contracts.
2. Run the first evaluation from a clean commit.
3. Store raw results, generated contract, Bad Cases, Markdown report and a SHA-256 manifest.
4. Never overwrite first-run artifacts.
5. Adjudicate exposed runtime defects separately. Any repair gets a separate PR and a clearly
   labelled post-fix regression; the original first run remains unchanged.
