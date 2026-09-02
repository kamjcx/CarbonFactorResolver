# CFR Autonomous Public-Synthetic Contract Evaluation

> Developer-only offline evaluation. This is not real-world accuracy or production-readiness evidence.

## Decision

- Generated cases: **418**
- Passed cases: **314 / 418**
- Bad Cases: **104**
- State-machine attacks passed: **7 / 8**
- Hard safety gates: **FAIL**

## Metrics

| Metric | Result |
|---|---:|
| Direct Recommendation Top-1 | 93.05% (241/259) |
| Recall@5 | 99.23% (257/259) |
| Forbidden Candidate Escape | 1.44% (6/418) |
| Abstention Correctness | 90.00% (81/90) |
| MORE_INPUT Recall | 20.00% (1/5) |
| Unnecessary Question Rate | 0.24% (1/413) |
| Boundary Violation | 0.00% (0/41) |
| Subject Violation | 0.00% (0/25) |
| Unit Violation | 0.00% (0/25) |
| Proxy Disclosure | N/A (0/0) |
| Evidence Metadata Completeness | 93.27% (277/297) |
| Deterministic Replay | 100.00% (414/414) |
| Unhandled HTTP 500 | 0.00% (0/4) |

## Bad Case Attribution

| Category | Count |
|---|---:|
| `ALIAS_OR_ENTITY_FAILURE` | 16 |
| `BOUNDARY_FAILURE` | 3 |
| `CATALOG_COVERAGE_GAP` | 12 |
| `PROVENANCE_FAILURE` | 60 |
| `QUERY_AMBIGUITY` | 4 |
| `RANKING_FAILURE` | 6 |
| `RETRIEVAL_FAILURE` | 2 |
| `SUBJECT_FAILURE` | 1 |

## Interpretation

Accuracy comes from hybrid recall that finds plausible records, deterministic gates that prevent
incompatible records from admission, and explicit `MORE_INPUT` or safe refusal when evidence is
insufficient. It is not attributed to an embedding swap or similarity-score increase alone.

The catalogue and queries are project-authored public-synthetic contracts. Results do not claim
general accuracy on enterprise queries, licensed databases, or unseen real-world materials.
