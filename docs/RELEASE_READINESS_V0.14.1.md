# CFR v0.14.1 Release Readiness

## Decision

Status: **PASS — ELIGIBLE FOR MERGE**.

The release is eligible only after the complete core suite, FactorBench, Portfolio Challenge,
all unit suites, package build, archive inspection and container health checks pass. Frozen
answers and first-run artifacts must remain unchanged.

## Acceptance evidence

| Gate | Result |
|---|---|
| Conditioned-volume forward/reverse evidence | PASS |
| Ambient/conditioned automatic equivalence | BLOCKED |
| Sealed Unit v2 | 31/32 first run preserved; 32/32 post-fix regression |
| Sealed Unit v3 | 23/24 first-run NO-GO preserved; expected answer unchanged |
| Sealed Unit v4 | independent first run 21/21; all checks 100% |
| FIN-05 | `MORE_INPUT_NEEDED` + correct `REFERENCE_ONLY` source |
| Structured deployment electricity records | remain blocked pending formal evidence |
| Formal factor admission | not authorized by this release |
| Core test suite (Python 3.11) | 324 passed; 87.06% branch coverage |
| Compatibility (Python 3.12) | 324 passed |
| Compatibility (Python 3.13) | 324 passed |
| Offline acceptance harness | 13 passed; 43.24% branch coverage |
| Evaluation critical path | 6 passed; 84.10% branch coverage |
| Ruff / mypy / compile | PASS |
| FactorBench v1/v2/v3 and frozen unit v1 | PASS |
| Package build | wheel and sdist built for 0.14.1 |
| Release archive isolation | both 0.14.1 archives PASS |
| Local Docker health | unavailable; local Docker engine did not become responsive |
| Remote CI | PASS — run `33615963987` on commit `dea1763dae7121ede17957fcfe85ab865aadd798` |
| Remote container | PASS — build, digest capture, startup and health check |
| Pull request | [#8](https://github.com/kamjcx/CarbonFactorResolver/pull/8) |

The local Docker limitation was not waived. The protected remote `container` job built the
image, recorded its digest, started the service and observed a healthy state. The companion
`test`, Python 3.12 and Python 3.13 jobs also completed successfully. This document-only
evidence update must receive the same protected checks before merge.
