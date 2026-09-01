# CFR Unit System v1 Holdout

Status: **EXPECTED ANSWERS FROZEN BEFORE FIRST RESOLVER RUN**

This independent QA holdout exercises the frozen `cfr-unit-system/v1` contract through
the public resolution engine and the HTTP-catalog adapter. It is intentionally isolated
from existing benchmark and catalogue fixtures. Expected answers are authored in the
benchmark rows; the runner is read-only and exits non-zero on any mismatch.

## Frozen inputs

The digests below are SHA-256 over UTF-8 text normalized to LF. They were recorded after
the catalogue and all expected answers were authored, and before the first Resolver run.

| Input | Frozen LF SHA-256 |
|---|---|
| `data/benchmarks/unit_holdout_v1.jsonl` | `b11506f56287e6a391e6959c443cfc441a186034c94c5bf3766fc8966f0bb6ff` |
| `data/fixtures/catalog/unit_holdout_catalog.json` | `50285f7b36b34a001385de91a6a09b90d253092873fd55984b9d2357f7297186` |

Expected-answer changes after this point are prohibited. A product failure remains a
reported failure; it is not repaired by relabelling the holdout.

## Coverage and acceptance

The 28 cases cover MASS, ENERGY, VOLUME, TRANSPORT_WORK and COUNT; identity and
same-dimension scale conversions; explicit cross-dimension conflicts; malformed request
activity and target units; malformed catalogue units; conditioned `m3`/`Nm3` conversion
both without evidence and with direction-specific versioned evidence; a genuine zero-hit;
and a mixed catalogue where a malformed record must not suppress a usable alternative.

Each case independently checks terminal status, follow-up, ordered recommended source IDs,
stable reason codes, refusal behavior and evidence-gate behavior. Positive cases also pin
the output factor unit, converted factor value and total emissions. Acceptance requires
100% case pass rate and 100% accuracy for every reported check.

## Execution

```powershell
python tools/unit_holdout.py
pytest -q tests/test_unit_holdout.py
ruff check tools/unit_holdout.py tests/test_unit_holdout.py
```

## Run log

### First Resolver run after freeze — 2026-09-01

- Command: `python tools/unit_holdout.py --compact`
- Exit code: `1`
- Result: 24/28 passed; 4/28 failed; case pass rate `0.8571428571428571`.
- `UH-MASS-02`: recommendation, status, refusal and emissions were correct, but the
  observed candidate remained `0.084 kgCO2e/kg` instead of the frozen effective target
  `84 kgCO2e/t`.
- `UH-MASS-03`: recommendation, status, refusal and emissions were correct, but the
  observed candidate remained `0.084 kgCO2e/kg` instead of the frozen effective target
  `0.03810175908 kgCO2e/lb`.
- `UH-VOLUME-04`: an identity `Nm3` request unexpectedly returned
  `more_input_needed / UNIT_CONVERSION_EVIDENCE_REQUIRED`; Trace reported request
  conversion `Nm3` to `kgCO2e/Nm3`, so no candidate was returned.
- `UH-CONFLICT-02`: the explicit VOLUME-to-MASS conflict returned
  `more_input_needed` with required field `density` and no stable unit reason code,
  rather than the frozen `unresolved / UNIT_DIMENSION_MISMATCH` answer.

No expected answer or input record was changed after these failures. Final verification
results are reported in the implementation handoff.

### Implementation rerun — 2026-09-01

- Frozen benchmark and catalogue hashes remained unchanged.
- Result: **28/28 passed**; case pass rate `1.0`; every reported check accuracy `1.0`.
- The four first-run failures were repaired in runtime code only: omitted mass targets now
  derive the request denominator; `Nm3` identity does not request state-conversion evidence;
  unqualified VOLUME-to-MASS conflicts fail with `UNIT_DIMENSION_MISMATCH`; controlled
  reference-flow resolution remains available when the request supplies product-form context.
