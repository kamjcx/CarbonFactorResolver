# CFR Sealed Unit Holdout v3

Status: **SEALED FIRST-RUN NO-GO — EXPECTED ANSWER ERROR PRESERVED**

This unit-only holdout was authored after the conditioned-volume runtime repair and did
not participate in that repair. It uses 24 new cases, 13 new synthetic records, new entity
names, new values and new source IDs. Neither v1 nor v2 expected answers are reused.

| Frozen input | LF-normalized SHA-256 |
|---|---|
| `data/benchmarks/sealed_unit_holdout_v3.jsonl` | `cb2e09d52aea3636db0733392c3e4521e5a451af56db869acc446046e9aff326` |
| `data/fixtures/catalog/sealed_unit_holdout_v3_catalog.json` | `a75dd2c7a8e4627c9273c3eab2fb63043e47b0a3ec517235227280cfe3668d6c` |

The set directly checks all five activity dimensions, impact-unit spellings and scaling,
`g/kg/t`, `kWh/MWh/MJ/GJ`, `L/m3/Nm3`, `kgkm/tkm`, count aliases, both factor and quantity
conversion directions, explicit cross-dimension refusal, catalogue/request syntax errors,
true zero recall and the distinction between system parsing failure and genuine supplier
data absence.

Conditioned volume has three independent controls: the repaired `m3 -> Nm3` factor path,
an unevidenced `L -> Nm3` path that must return `MORE_INPUT`, and an evidenced
`Nm3 -> L` path. Full Trace plus raw, normalized and decision fingerprints are retained.

The committed inputs and answers did not change after the first run. The Resolver run
passed 23/24. `SUH3-MASS-03` was correctly recommended, but the frozen answer incorrectly
expected `0.0042 tCO2e/t` to become `4.2 kgCO2e/kg`. Multiplying the numerator by 1000 and
dividing the denominator by 1000 cancel, so the observed `0.0042 kgCO2e/kg` and `2.1`
kgCO2e for 500 kg were correct. The erroneous answer remains unchanged and v3 is NO-GO.

No runtime change was made in response. A wholly new v4 unit holdout is required for the
post-fix independent acceptance claim; v3 must not be relabelled to improve metrics.

Run from the repository root with:

```powershell
python -m tools.sealed_unit_holdout_v3 --output outputs/sealed_unit_holdout_v3/first_run.json
```
