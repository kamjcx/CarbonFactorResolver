# CFR v0.14 Release Readiness

## Decision

`v0.14.0` release: **NO-GO**

The Release Hardening changes are internally complete, but the independently frozen rc.2
sealed evaluation missed its Answerable Top-1 gate. No final tag or production-readiness claim
is authorized.

## Engineering gates

| Gate | Result |
|---|---|
| Product scope and JSON-only runtime | PASS |
| Three strict xfail adjudications | FIXED; 0 strict xfail |
| Public HTTP 500 / exception disclosure | PASS |
| Rejected-candidate approval monotonicity | PASS |
| Core tests | 286 passed |
| Core branch coverage | 86.90% |
| Evaluator critical-path branch coverage | 84.10% |
| Offline true-data harness | 13 passed; 43.24% branch coverage (separate metric) |
| FactorBench V1 | immutable historical 8/9 abstention |
| FactorBench V2 | 9/9 abstention; versioned adjudication |
| Frozen Unit Regression Set | independent first run 24/28; post-fix 28/28 |
| Package build / archive content verification | PASS |
| Public docs and data-license inventory | PASS |
| Local Docker | unavailable on this host; GitHub container job is authoritative |

## Sealed evidence

- rc.1 sealed metrics passed, but rc.1 release failed because the new CI image-evidence command
  returned non-zero after a successful image build. That result is preserved and not reused.
- rc.2 used a wholly new 40-case dataset and new catalogue. Safety, abstention, recall, replay
  and HTTP gates passed; Answerable Top-1 was 83.33% against a 90% threshold.

## What may be claimed

CFR may be described as a **portfolio-ready, reproducible research prototype** with strong
deterministic safety gates and transparent negative evidence. It must not be described as a
production-ready accounting system or as having 97.5% real-world accuracy.

## Next authorized work

Open a separate post-RC investigation for why three correctly recalled structured energy
records were not admitted. Do not alter rc.2, its answers, or its evidence. Any future release
candidate requires a reviewed fix, a new version, and a new independently frozen holdout.

