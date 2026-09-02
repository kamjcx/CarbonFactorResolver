# CFR Sealed Unit Holdout v2

Status: **FROZEN BEFORE FIRST RESOLVER RUN**

This is a post-fix, unit-only acceptance set authored after the v0.14.0 runtime was frozen.
It did not participate in development of the unit parser, conversion rules, qualification
logic or status mapping. Its cases, catalogue records, expected source IDs, factor values
and terminal decisions are immutable after the hashes below are committed.

| Frozen input | LF-normalized SHA-256 |
|---|---|
| `data/benchmarks/sealed_unit_holdout_v2.jsonl` | `828d3f73413ac6a471bb3330962d645c40f0f0064ba5d7637ac1d0291e076958` |
| `data/fixtures/catalog/sealed_unit_holdout_v2_catalog.json` | `2e8456de8070faf3f9cae1427a7dc59ec096130b602ca66e8b96c9886b49ec1c` |

The synthetic entities, record IDs and values are new. They are not aliases or copies of
the Frozen Unit Regression v1 answers. Coverage includes all five activity dimensions,
impact-unit spelling and scale, both quantity and factor conversion directions, mixed
energy scales, Unicode cubic units, conditioned-volume evidence in both directions,
cross-dimension refusal, request syntax failure, catalogue-unit failure, a usable
alternative and genuine supplier-data absence.

The first run must preserve full Trace, raw and normalized request fingerprints, and a
stable decision fingerprint for every case. A failing first run remains failure evidence;
it must never be repaired by changing an expected answer. If runtime code is changed in
response to a failure, this dataset becomes a regression set and a new sealed set is
required before any independent-holdout claim.

Run locally with:

```powershell
python tools/sealed_unit_holdout_v2.py --output outputs/sealed_unit_holdout_v2/first_run.json
pytest -q tests/test_sealed_unit_holdout_v2.py
```
