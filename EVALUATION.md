# Evaluation

CFR uses versioned, public-synthetic regression suites. These results measure the shipped
fixtures and contracts; they are not a claim of accuracy across all real-world factor queries.

## Published suites

- **FactorBench V1** is immutable historical evidence. Its `wrong-unit-53` historical label
  remains `supplier_data_required`.
- **FactorBench V2** applies the versioned unit adjudication without rewriting V1.
- **FactorBench V3** distinguishes true zero-recall from records recalled and then rejected
  for indicator, declared-product, or boundary incompatibility. V1/V2 remain immutable.
- **Portfolio Challenge V1** is a closed regression/safety diagnostic, not an unseen-query
  benchmark. It returns 39 direct recommendations plus FIN-05 as `MORE_INPUT_NEEDED` with
  the correct source retained as `REFERENCE_ONLY`; boundary and subject escapes remain zero.
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
