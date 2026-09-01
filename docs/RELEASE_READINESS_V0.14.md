# CFR v0.14 Release Readiness

## Decision

`v0.14.0` portfolio release: **GO**, subject to merge and remote CI remaining green

RC3–RC5 failures are preserved without rewriting their inputs or results. RC6 used a wholly
new 48-case public-synthetic set and passed every frozen case contract and aggregate safety
gate on its first run. This authorizes a portfolio/research-prototype release, not production
carbon-accounting use or formal factor admission.

## Engineering gates

| Gate | Result |
|---|---|
| Product scope and JSON-only runtime | PASS |
| Three strict xfail adjudications | FIXED; 0 strict xfail |
| Public HTTP 500 / exception disclosure | PASS |
| Rejected-candidate approval monotonicity | PASS |
| Core tests | 315 passed |
| Core branch coverage | 87.05% |
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
- rc.3 exposed an aggregate-only gate defect: 35/48 full contracts passed while the obsolete
  gate incorrectly reported success. The raw output is preserved and rc.3 is NO-GO.
- rc.4 validated the corrected gate and failed closed at 36/48 full contracts.
- rc.5 failed before retrieval because its database anchor was malformed; rc.6 added a static
  preflight validator rather than repairing the frozen input.
- rc.6 passed 48/48 full contracts, 100% Top-1/recall/abstention/replay, with zero boundary,
  subject, unit, forbidden-candidate, or HTTP-500 failures.

## What may be claimed

CFR may be described as a **portfolio-ready, reproducible research prototype** with strong
deterministic safety gates and transparent negative evidence. It must not be described as a
production-ready accounting system or as having 97.5% real-world accuracy.

## Release boundary

Merge only after remote `test` and `container` checks pass at the final branch SHA. Publish
the wheel, source distribution, manifest, raw rc.6 result hash, and container digest. Do not
publish licensed factor data, customer evidence, or claim production readiness.

Historical first-run SHA values and their patch-equivalent post-merge/rebase commits are
recorded in [CFR_RC_REBASE_MAP.md](CFR_RC_REBASE_MAP.md); raw evidence is never rewritten.
