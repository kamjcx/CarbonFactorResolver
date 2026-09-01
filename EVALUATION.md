# Evaluation

CFR uses versioned, public-synthetic regression suites. These results measure the shipped
fixtures and contracts; they are not a claim of accuracy across all real-world factor queries.

## Published suites

- **FactorBench V1** is immutable historical evidence. Its `wrong-unit-53` historical label
  remains `supplier_data_required`.
- **FactorBench V2** applies the versioned unit adjudication without rewriting V1.
- **Portfolio Challenge V1** is a closed regression/safety diagnostic, not an unseen-query
  benchmark. Its recorded result is 39/40 answerable Top-1 with zero boundary and subject
  escapes.
- **Frozen Unit Regression Set** contains 28 cases. Its independent first run was 24/28;
  runtime code was then repaired and the regression rerun was 28/28. It is not described as
  an independent holdout after that repair.
- **Sealed Portfolio Holdout** is created only after the RC code, configuration and public
  fixtures are frozen. Its first-run artifacts remain immutable.

The rc.1 sealed gate passed but its release was invalidated by a failing remote CI evidence
step. A wholly new rc.2 dataset then achieved 100% pre-gate recall, abstention, safety and
replay but only 83.33% Answerable Top-1, below the 90% release threshold. The rc.2 inputs and
answers remain unchanged and the v0.14 decision is NO-GO.

Release thresholds, denominators, raw result hashes and environment information are recorded
in the RC manifest and sealed-evaluation report. Latency is descriptive for the recorded test
environment, not a service-level guarantee.

Detailed methodology: [docs/CFR_EVALUATION_METHODOLOGY.md](docs/CFR_EVALUATION_METHODOLOGY.md).
