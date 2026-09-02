# CFR Sealed Unit Holdout v4

Status: **INDEPENDENT FIRST RUN PASS**

This is the final post-fix unit-only acceptance set. It was authored after the v2 runtime
repair and after the v3 expected-answer adjudication. It contains 21 new cases and 13 new
synthetic records with no reused names, source IDs, values or answers.

| Frozen input | LF-normalized SHA-256 |
|---|---|
| `data/benchmarks/sealed_unit_holdout_v4.jsonl` | `1b66f08231f15628993a26fa97b6008bc3609ec86c0009eb4937eeb8401b5a89` |
| `data/fixtures/catalog/sealed_unit_holdout_v4_catalog.json` | `5c3ae062c065225346157ce5324d388c69fee84daa3565707566b95a55d44402` |

The set covers MASS, ENERGY, VOLUME, TRANSPORT_WORK and COUNT; numerator and denominator
scaling; factor and quantity directions; conditioned-volume evidence; explicit prevention
of automatic `L`/`Nm3` equivalence; cross-dimension refusal; syntax failures; invalid
catalogue records with and without a usable alternative; and genuine supplier-data absence.

Inputs and answers are immutable after the commit that freezes these hashes. The first
Resolver run retains full Trace and raw, normalized and decision fingerprints. Any failure
remains evidence and cannot be repaired by changing a benchmark answer.

The first Resolver run passed **21/21**, with 100% status, recommendation, reason-code,
refusal, evidence-gate, factor-unit, factor-value and total-emissions checks. No runtime or
expected-answer change was made after freeze. The full first-run artifact SHA-256 is
`0fbad5055769e8f40a55ba2d857537abe57ea5449e12707c970c3c04e0a4bfb5`.

Run from the repository root with:

```powershell
python -m tools.sealed_unit_holdout_v4 --output outputs/sealed_unit_holdout_v4/first_run.json
```
