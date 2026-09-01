# CFR v0.14.0-rc.2 Sealed First Run

Status: **NO-GO — SEALED TOP-1 GATE FAILED**

Runtime/config freeze: `b4dc4a67d8a19723863d661fb0a02612aa42f90d`  
Input freeze: `1c0ec86f4e3446bfe13597c8727e451d814f40b8`

| Artifact | SHA-256 |
|---|---|
| Cases (40) | `bfa1cf3dfecd961561037afda5702a9c931962d8844ed901546445068b9c4d79` |
| Synthetic catalogue (15 records) | `399e2e42a99fef50c4a1d9217094cbbcdc32b6906181502ddf860e906f237125` |
| Raw first-run JSON | `49b8844aefa234104eb326b04e6fa98bbd1c84789a35bea92c427663155aae3f` |

## Immutable first-run metrics

| Metric | Result | Gate | Decision |
|---|---:|---:|---|
| Answerable Top-1 | 83.33% (15/18) | >=90% | **FAIL** |
| Retrieval recall before gate | 100% (18/18) | >=95% | PASS |
| Abstention correctness | 100% (22/22) | >=90% | PASS |
| Boundary violations | 0 | 0 | PASS |
| Subject violations | 0 | 0 | PASS |
| Unit-dimension violations | 0 | 0 | PASS |
| Forbidden candidate escapes | 0 | 0 | PASS |
| Deterministic replay | 100% | 100% | PASS |
| Unhandled HTTP 500 | 0 | 0 | PASS |

Four cases did not match their pre-frozen expectations:

- `R2-UNIT-203`, `R2-UNIT-204`, `R2-UNIT-205`: the correct new electricity record was
  recalled before qualification, but no candidate was returned; status was
  `supplier_data_required`, so the three answerable Top-1 checks failed.
- `R2-MORE-405`: safely returned no candidate with `supplier_data_required` rather than the
  pre-frozen `more_input_needed` status. It did not affect the answerable Top-1 denominator.

No code, fixture, query or expected answer was changed after this run. A third dataset is not
created merely to search for a passing sample. The correct release decision for v0.14.0 is
therefore **NO-GO** until a separately scoped post-RC investigation is completed.

The full raw JSON with all traces is kept out of Git history because it is over two megabytes;
the digest above is authoritative and the file is reserved as a prerelease evidence asset.

