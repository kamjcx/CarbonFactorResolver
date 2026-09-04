# CFR Current Bad Case Audit

> Generated from the current evaluation JSON. No frozen answer or Resolver behavior was changed.

## Decision

- Evaluation execution: **completed**
- Quality gate: **FAIL**
- Raw Bad Cases: **100**
- Unresolved Bad Cases: **94**
- Raw forbidden escapes: **6**
- Unadjudicated forbidden escapes: **0**

## Root-cause and adjudication inventory

| Root cause / disposition | Count | Risk | Representative cases | Suggested follow-up PR |
|---|---:|---|---|---|
| `geography` | 3 | HIGH | `AUTO-GRID_2024-GEOGRAPHY-X`, `AUTO-COAL_MARKET-GEOGRAPHY-X`, `AUTO-COAL_COMBUSTION-GEOGRAPHY-X` | `temporal-geography-contract-v2` |
| `year_temporal` | 3 | HIGH | `AUTO-GRID_2024-YEAR-X`, `AUTO-COAL_MARKET-YEAR-X`, `AUTO-COAL_COMBUSTION-YEAR-X` | `temporal-geography-contract-v2` |
| `boundary` | 3 | CRITICAL | `AUTO-MATRIX-A3-A1`, `AUTO-MATRIX-A3-A2`, `AUTO-MATRIX-A3-A1-A3` | `boundary-reference-only-contract` |
| `declared_product` | 0 | CRITICAL | — | `declared-product-admission-hardening` |
| `subject` | 1 | CRITICAL | `AUTO-20-SUBJECT` | `subject-decision-contract-alignment` |
| `unit` | 2 | CRITICAL | `AUTO-11-UNIT-EQ`, `AUTO-12-UNIT-EQ` | `unit-syntax-contract-alignment` |
| `generic_exact_ambiguity` | 16 | HIGH | `AUTO-01-POS-reviewed-typo`, `AUTO-03-POS-reviewed-alias`, `AUTO-06-POS-reviewed-typo`, `AUTO-07-POS-reviewed-alias`, `AUTO-07-POS-reviewed-typo` | `review-tier-and-alias-contract-alignment` |
| `expected_more_input_but_recommended` | 0 | CRITICAL | — | `ambiguity-decision-hardening` |
| `expected_recommendation_but_asked` | 0 | MEDIUM | — | `ambiguity-question-regression` |
| `oracle_preset_error` | 0 | MEDIUM | — | `versioned-oracle-adjudication` |
| `stale_report` | 0 | MEDIUM | — | `dynamic-evaluation-reporting` |
| `accepted_limitation` | 6 | ACCEPTED | `AUTO-GRID_2024-GEOGRAPHY-X`, `AUTO-GRID_2024-YEAR-X`, `AUTO-COAL_MARKET-GEOGRAPHY-X`, `AUTO-COAL_MARKET-YEAR-X`, `AUTO-COAL_COMBUSTION-GEOGRAPHY-X` | `no-runtime-change; retain versioned adjudication` |
| `provenance` | 60 | HIGH | `AUTO-01-PROV-HASH`, `AUTO-01-PROV-QUALITY`, `AUTO-01-PROV-ELIGIBLE`, `AUTO-02-PROV-HASH`, `AUTO-02-PROV-QUALITY` | `provenance-reference-only-contract-alignment` |
| `catalog_coverage` | 12 | MEDIUM | `AUTO-UNKNOWN-00`, `AUTO-UNKNOWN-01`, `AUTO-UNKNOWN-02`, `AUTO-UNKNOWN-03`, `AUTO-UNKNOWN-04` | `abstention-status-contract-alignment` |
| `other` | 0 | MEDIUM | — | `bad-case-triage-follow-up` |

## Forbidden candidate escapes

- `AUTO-GRID_2024-GEOGRAPHY-X`: `AUTO-SYN-GRID_2024`
- `AUTO-GRID_2024-YEAR-X`: `AUTO-SYN-GRID_2024`
- `AUTO-COAL_MARKET-GEOGRAPHY-X`: `AUTO-SYN-COAL_MARKET`
- `AUTO-COAL_MARKET-YEAR-X`: `AUTO-SYN-COAL_MARKET`
- `AUTO-COAL_COMBUSTION-GEOGRAPHY-X`: `AUTO-SYN-COAL_COMBUSTION`
- `AUTO-COAL_COMBUSTION-YEAR-X`: `AUTO-SYN-COAL_COMBUSTION`

## Interpretation

A completed process only proves that the evaluator ran and wrote its evidence. A PASS quality
decision additionally requires every enforced metric and every unresolved Bad Case gate to pass.
Versioned adjudications remain visible in raw counts and may only be excluded after their case,
input, authority, reason, reviewer, and effective version bindings are verified.
