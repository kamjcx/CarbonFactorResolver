# CFR Autonomous Quality-Gate Contract V3

Status: **STACKED PR — VERSIONED ORACLE ADJUDICATION, NOT NEW SEALED EVIDENCE**

V3 closes the evaluator's 90 unresolved Bad Cases without changing Resolver retrieval,
ranking, qualification, factor values, candidate IDs, or formal-admission rules. The immutable
V1 result and Safety V2 adjudication remain byte-identical. Raw V1 metrics and all 103 raw Bad
Cases continue to be reported.

## Frozen input identity

- Baseline: PR #19 head `1d0956d7ea7697ed65c0dee1565a991bfef92b46`.
- Seed: `20260902`.
- Generator SHA-256: `5882e4de5b7831bc757eb2e0c3ab3cf25026773035f6bf7ead647f00417d4b6f`.
- Inventory: 414 generated resolution cases plus four HTTP safety cases.
- Every case and request is bound in
  `data/benchmarks/autonomous_evaluation_v3_freeze.json`.
- Freeze Manifest SHA-256:
  `a9790d4bdfc09b388eb4cd1a49c23f35c4251266fee7169420a2ad10ca52daa7`.
- Every changed expectation is bound by case SHA, input SHA, previous expectation, effective
  expectation, authority, reviewer, reason, and effective version in
  `data/benchmarks/autonomous_evaluation_v3_adjudications.json`.

The V3 builder is developer-only and does not import or run CarbonFactorResolver. Its output is
checked against the committed artifacts, preventing live runtime output from becoming its own
Oracle.

## Root-cause decisions

| Root cause | Cases | Decision |
|---|---:|---|
| Evidence HASH degradation | 20 | Missing document hashes remain non-selectable. The effective status follows the versioned request/process follow-up contract and requires `SOURCE_DOCUMENT_HASH_REQUIRED`. |
| QUALITY degradation | 20 | `NEEDS_REVIEW` records remain outside every selectable lane. They are not promoted to reference review merely because a value exists. |
| ELIGIBLE degradation | 20 | `admission_eligible=false` remains fail-closed and cannot be overridden by the benchmark. |
| Catalogue alias/typo identity authority | 16 | A catalogue-provided alias or generated typo without independent identity authority is `REFERENCE_ONLY`, not a formal direct recommendation. |
| Unresolved aluminium typo | 1 | The misspelled identity requires clarification; route/form context alone cannot create identity authority. |
| Catalogue coverage/status | 12 | A true zero-hit query uses the public `supplier_data_required` terminal status rather than generic `unresolved`. |
| Steel-fibre subtype contract | 13 | Safety V2 is carried forward: generic steel fibre requires `steel_fiber_type`; compatible records remain non-selectable references. |
| Steel-fibre subject conflict | 1 | The independent subtype input gap is asked first, while the incompatible subject record remains excluded. Subject escape stays zero. |

These are Oracle/status-contract adjudications, not exemptions. Each effective expectation still
specifies the exact terminal status, allowed `REFERENCE_ONLY` IDs, forbidden IDs, expected reason
codes, and approval prohibition. A changed runtime output that violates any field remains an
unresolved Bad Case.

## Raw versus effective metrics

V3 keeps both views:

- **Raw V1:** 230/259 Direct Top-1, 259/259 Recall@5, 103 raw Bad Cases.
- **Effective V3:** 230/230 Direct Top-1, 230/230 Recall@5, 145/145 abstention,
  23/23 `MORE_INPUT`, zero unresolved Bad Cases, and zero boundary, subject, unit, or forbidden
  candidate escapes.

The denominator change is explicit: 29 stale direct-answer presets are reclassified as
`REFERENCE_ONLY` or `MORE_INPUT`; no failed direct recommendation is silently dropped. The V3
run is a post-adjudication regression and must not be described as an independent first run or as
real-world accuracy evidence.

Runs carrying both raw and effective metrics use
`cfr-autonomous-evaluation-run/v2`; the original V1 run schema and evidence remain unchanged.
