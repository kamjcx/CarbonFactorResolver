# Autonomous Evaluation V1 — First-run Summary

## Frozen execution

- Evaluator commit: `fe4eee7101f4f53b463e65ba3edfd8e9f4641367`
- Seed: `20260902`
- Generated contract cases: 414
- HTTP safety probes: 4
- Generator contract SHA-256: `5882e4de5b7831bc757eb2e0c3ab3cf25026773035f6bf7ead647f00417d4b6f`
- Data classification: `PUBLIC_SYNTHETIC`
- Licensed/customer/formal factor data: none

The immutable first execution passed 314 of 418 complete row contracts and is **NO-GO** on
the autonomous hard gates. This does not revoke the published v0.14.1 synthetic release
evidence; it is a broader diagnostic against newly generated contracts.

## First-run metrics

| Metric | First run |
|---|---:|
| Direct Recommendation Top-1 | 93.05% (241/259) |
| Recall@5 | 99.23% (257/259) |
| Abstention correctness | 90.00% (81/90) |
| MORE_INPUT recall | 20.00% (1/5) |
| Forbidden candidate escape | 1.44% (6/418) |
| Boundary violation | 0/41 |
| Subject violation | 0/25 |
| Unit violation | 0/25 |
| Evidence metadata completeness | 93.27% (277/297) |
| Deterministic replay | 100% (414/414) |
| Unhandled HTTP 500 | 0/4 |
| Workflow attacks | 7/8 |

The failed workflow attack is concurrent duplicate approval: two simultaneous reviewers can
both write approvals before an idempotent lock is returned. Other preserved findings include
missing document-hash admission, four missing-decisive-attribute decisions, geography/year
applicability escapes, and alias/entity visibility differences. No first-run answer or result
was modified after observing these outcomes.

## Scale evidence

The complete 10k/50k run passed deterministic replay, catalog-order and unrelated-noise
Top-K invariants. Total wall time was 526.38 seconds on the recorded Windows/Python 3.11 host.

| Catalog | Index build | Warm Resolver P50/P95/P99 | Peak RSS | Throughput c10 / c25 / c50 |
|---:|---:|---:|---:|---:|
| 10,000 | 21.32 s | 263.62 / 292.07 / 296.69 ms | 72.1 MB | 3.72 / 3.77 / 3.72 req/s |
| 50,000 | 117.67 s | 1321.40 / 1408.64 / 1435.36 ms | 205.5 MB | 0.75 / 0.75 / 0.75 req/s |

The async workload is CPU-bound and effectively serial in one Python process. These numbers
are descriptive evidence, not a production SLA.

## Integrity note

The original Manifest's `git_dirty: true` is explained in
[`first-run/MANIFEST_ERRATUM.md`](first-run/MANIFEST_ERRATUM.md). The pre-run status was clean;
the old implementation sampled status after creating its own untracked output. Original raw
artifacts and their Manifest hashes remain unchanged.
