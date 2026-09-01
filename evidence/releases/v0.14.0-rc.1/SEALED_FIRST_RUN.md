# CFR v0.14.0-rc.1 Sealed First Run

Status: **SEALED EVALUATION PASS / RC RELEASE FAIL**

The runtime was frozen at `bbd75dbef00d0bf4e4f46b18fed5ff75e0a62cb4`. The new
inputs were committed before first execution at
`500bf6c29efe1c755fafb26f1aa4fadbf8f0cb98`.

| Artifact | SHA-256 |
|---|---|
| Cases (50) | `79cb99800c5cc2457766744f90c75ace6a2b650cb7ac20a73c589d3816ff87ee` |
| Synthetic catalogue (17 records) | `8a62990996a75f75d77959ba5b16958e34a511660e42dd19c56251b5fed8f087` |
| Raw first-run JSON | `5e23ac93b47577e252fd4b58a0bcc062ccdf7ecb7953b840cbbe1751f0b8b7d5` |

## Immutable first-run metrics

| Metric | Result | Gate |
|---|---:|---:|
| Answerable Top-1 | 91.67% (22/24) | >=90% |
| Retrieval recall before gate | 100% (24/24) | >=95% |
| Abstention correctness | 100% (26/26) | >=90% |
| Boundary violations | 0 | 0 |
| Subject violations | 0 | 0 |
| Unit-dimension violations | 0 | 0 |
| Forbidden candidate escapes | 0 | 0 |
| Deterministic replay | 100% | 100% |
| Unhandled HTTP 500 | 0 | 0 |

The sealed release gate passed. Nine cases had non-safety expectation differences and remain
unchanged: `SEA-UNIT-07`, `SEA-UNIT-08`, `SEA-SAFE-01` through `SEA-SAFE-06`, and
`SEA-REPLAY-03`. The two road cases safely abstained rather than recommending; six hard-gate
cases returned `supplier_data_required` instead of the expected `process_model_required`; the
Chinese road alias returned a review-only reference. None escaped a forbidden candidate.

## Why RC1 is not released

The remote container built successfully and reported image ID
`sha256:6ad1c229ac23d6320b845037a3add7678e5f305736dc1c874c44b43821569ff8`, but the
subsequent CI evidence command attempted to resolve the image through an empty Compose
container list and exited non-zero. Because remote CI was not green, RC1 is a release NO-GO.
The runtime result is preserved but is not reused as the independent rc.2 holdout.

The full raw JSON (including traces) is retained outside Git history for release evidence; it
is intentionally not committed as a multi-megabyte blob. Its digest above is authoritative.

