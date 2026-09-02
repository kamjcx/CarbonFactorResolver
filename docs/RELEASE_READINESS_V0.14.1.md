# CFR v0.14.1 Release Readiness

## Decision

Status: **LOCAL QA PASS; REMOTE QA PENDING**.

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
| Local Docker health | pending; local Docker engine did not become responsive |
| Remote CI | pending branch push |

The local Docker limitation is environmental rather than waived: the release remains blocked
until the remote `container` job builds the image and observes a healthy service. Commit SHA
and remote checks are recorded after the branch is pushed.
