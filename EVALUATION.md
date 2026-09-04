# Evaluation

CFR uses versioned, public-synthetic regression suites. These results measure the shipped
fixtures and contracts; they are not a claim of accuracy across all real-world factor queries.

## Current gate audit

A read-only rerun on `main` commit `5155a6829fcdd521f04359263f543245a1c6b03f`
completed successfully but did **not** pass its quality gates. Autonomous Evaluation reported
100 raw Bad Cases (94 unresolved after six validated adjudications) and six raw forbidden
escapes; Portfolio Validation reported 53/60 decision accuracy, 4/10 MORE_INPUT positive
recall, and 6/46 wrong candidates. The evaluator CLIs now return non-zero for this result so a
completed run cannot appear as release approval. See the
[bound baseline and Bad Case audit](evidence/evaluation_gate_audit/5155a68/BASELINE.md).

## Published suites

- **FactorBench V1** is immutable historical evidence. Its `wrong-unit-53` historical label
  remains `supplier_data_required`.
- **FactorBench V2** applies the versioned unit adjudication without rewriting V1.
- **FactorBench V3** distinguishes true zero-recall from records recalled and then rejected
  for indicator, declared-product, or boundary incompatibility. V1/V2 remain immutable.
- **Portfolio Challenge V1** is a closed regression/safety diagnostic, not an unseen-query
  benchmark. It returns 39 direct recommendations plus FIN-05 as `MORE_INPUT_NEEDED` with
  the correct source retained as `REFERENCE_ONLY`; boundary and subject escapes remain zero.
- **Portfolio Challenge V2 adjudication overlay** leaves every V1 line and raw metric intact.
  It separately evaluates selectable candidates, non-selectable reference/provisional evidence,
  and required choices for eight SHA-bound ambiguity cases. This prevents valid discovery clues
  from being counted as formal recommendations without simply ignoring them.
- **Autonomous Safety V2 adjudication** records 13 stale steel-fibre oracle presets introduced by
  the stricter subtype requirement. Current raw results retain all 103 failures; the effective
  view adjudicates those 13 and leaves 90 unresolved, so the release gate remains closed.
- **Frozen Unit Regression Set** contains 28 cases. Its independent first run was 24/28;
  runtime code was then repaired and the regression rerun was 28/28. It is not described as
  an independent holdout after that repair.
- **Sealed Portfolio Holdout** is created only after the RC code, configuration and public
  fixtures are frozen. Its first-run artifacts remain immutable.
- **Sealed Unit Holdout v2** first ran 31/32 and exposed the conditioned-volume evidence-
  direction defect. Its unchanged post-fix rerun is 32/32, so v2 is a regression set.
- **Sealed Unit Holdout v3** first ran 23/24 because one frozen expected answer had the wrong
  numerator/denominator scaling. The answer and NO-GO evidence remain unchanged.
- **Sealed Unit Holdout v4** is the post-fix independent unit-only set. Its first run passed
  21/21 with 100% status, recommendation, reason, refusal, evidence, value and emissions
  checks. No runtime or answer changed after its freeze.

The rc.1 and rc.2 outcomes remain immutable historical evidence. RC3 exposed a release-gate
defect, RC4 proved the corrected gate fails closed, and RC5 exposed a missing catalogue-anchor
preflight. None of their answers or first-run outputs was rewritten.

RC6 used a wholly new 48-case public-synthetic dataset after runtime/evaluator freeze. Its
preserved first run passed 48/48 complete case contracts, with 100% Answerable Top-1,
pre-gate recall, abstention correctness and deterministic replay; boundary, subject, unit,
forbidden-candidate and unhandled-HTTP-500 counts were all zero. These are sealed-fixture
results, not a real-world accuracy claim.

Release thresholds, denominators, raw result hashes and environment information are recorded
in the RC manifest and sealed-evaluation report. Latency is descriptive for the recorded test
environment, not a service-level guarantee.

Detailed methodology: [docs/CFR_EVALUATION_METHODOLOGY.md](docs/CFR_EVALUATION_METHODOLOGY.md).

## Autonomous Evaluation V1

The autonomous suite is a developer-only public-synthetic diagnostic. An independent Oracle
derives outcomes from reviewed boundary, subject, unit, provenance and workflow contracts;
it does not call Resolver qualification or ranking code to create its answers. The fixed seed
produces 414 unique cases and supports immutable first-run JSON/Markdown, Bad Case categories,
SHA-256 manifests, 100% replay checks, and API safety probes.

Scale evidence is reported separately for deterministic 10k and 50k synthetic catalogs,
including build/cold/warm P50/P95/P99, peak process RSS, concurrency 10/25/50, throughput,
catalog-order invariance, noise expansion and Top-K stability. These measurements describe
the recorded environment and are not a service-level objective.

The suite is deliberately more adversarial than the frozen release benchmarks. A NO-GO
result identifies a contract or implementation issue for separate adjudication; generated
answers and first-run failures are not rewritten to improve scores.

The V1 first run at commit `fe4eee7` is preserved as NO-GO: 314/418 complete rows passed,
Direct Top-1 was 93.05%, Recall@5 99.23%, abstention 90%, MORE_INPUT recall 20%, evidence
metadata presence 93.27%, and deterministic replay 100%. Boundary, subject, unit and HTTP-500
counts were zero, while six geography/year forbidden candidates escaped and one of eight
workflow attacks failed. See the [raw summary](evidence/autonomous_evaluation/v1/SUMMARY.md).

The accompanying 10k/50k synthetic performance run passed replay/order/noise invariants.
Its 50k index build was 117.67 seconds, warm Resolver P50/P95/P99 was 1.321/1.409/1.435 seconds,
peak RSS was 205.5 MB, and one-process throughput was about 0.75 requests/second at concurrency
10/25/50. These results expose scale cost; they are not a production SLA.

The post-first-run repair cycle is a regression, not a new independent evaluation. It fixes
decisive-attribute `MORE_INPUT`, structured-source document-hash admission, and concurrent
terminal-decision races without changing the V1 generator or frozen first-run evidence. Safety V2
classifies the six geography/year disagreements as fixed runtime defects: explicit conflicts now
hard-reject unless a versioned substitution policy applies. The historical V1 interpretation and
its superseding SHA-bound record remain available in
[the V1 adjudication](docs/CFR_AUTONOMOUS_EVALUATION_V1_ADJUDICATION.md) and
[the Safety V2 contract](docs/CFR_RESOLUTION_SAFETY_HARDENING_V2.md).
