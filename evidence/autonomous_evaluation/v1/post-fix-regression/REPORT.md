# Autonomous Evaluation V1 Post-Fix Regression

> Developer-only public-synthetic regression. This is not a new independent or sealed run,
> and it is not evidence of real-world production accuracy.

## Reproducibility

- Runtime repair commit: `07883423a5874b63dd2dff8ecf9d34cf8dde8260`
- Frozen generator seed: `20260902`
- Generated cases and first-run evidence: unchanged
- Result SHA-256: `cc26dcf1063e959fb25320e130b31a96152987adccdce881bd0cc2f5003348e4`

## Raw results

| Metric | Result |
|---|---:|
| Complete case contracts | 318 / 418 |
| Direct Recommendation Top-1 | 241 / 259 (93.05%) |
| Recall@5 | 257 / 259 (99.23%) |
| Abstention correctness | 81 / 90 (90.00%) |
| MORE_INPUT recall | 5 / 5 (100.00%) |
| Evidence metadata completeness | 280 / 280 (100.00%) |
| Deterministic replay | 414 / 414 (100.00%) |
| State-machine attacks | 8 / 8 (100.00%) |
| Boundary / subject / unit violations | 0 / 0 / 0 |
| Unhandled HTTP 500 | 0 / 4 |
| Raw forbidden-candidate escapes | 6 / 418 |

The raw evaluator hard gate remains **FAIL** because the six frozen geography/year labels count
published `USABLE_WITH_ASSUMPTIONS` behavior as forbidden. The exact cases and the decision not
to change runtime merely to improve the score are recorded in
[`CFR_AUTONOMOUS_EVALUATION_V1_ADJUDICATION.md`](../../../../docs/CFR_AUTONOMOUS_EVALUATION_V1_ADJUDICATION.md).

## Adjudicated engineering result

After excluding only those six versioned benchmark-label disagreements, every enforceable
runtime hard gate passes. The repair cycle closed the three accepted defects:

- four decisive-attribute cases now return `MORE_INPUT_NEEDED` (5/5 overall);
- structured catalogue records without a valid source-document hash fail closed with
  `SOURCE_DOCUMENT_HASH_REQUIRED` (evidence completeness 100%);
- concurrent duplicate approval attempts now have exactly one stored terminal decision
  (state-machine attacks 8/8).

No V1 expected answer, generated contract, or immutable first-run artifact was changed.
