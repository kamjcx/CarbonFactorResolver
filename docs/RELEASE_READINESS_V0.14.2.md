# CFR v0.14.2 Release Readiness

## Decision

`GO` only after the release tag is bound to the merged `main` commit, all required GitHub
checks are green, and every published asset matches the attached SHA-256 manifest.

## Scope

This patch release contains the already-reviewed contract repairs merged after v0.14.1,
release documentation, a public-synthetic BYOC catalog/tutorial, and an internal architecture
visual. It does not add a new retrieval source, alias, factor value, ranking rule, or automatic
approval path.

## Required evidence

| Gate | Requirement |
|---|---|
| Core suite | 360 passed on Python 3.11; 87.15% branch coverage (85% gate) |
| Compatibility | The complete suite passes under Python 3.12 and 3.13 |
| Static checks | Ruff, mypy, and compileall pass under the documented scope |
| Frozen evaluations | FactorBench, Portfolio, Unit Regression, and sealed gates pass; Autonomous V1 retains six frozen geography/year label disagreements under its published adjudication |
| BYOC contract | Exactly 20 public-synthetic records load; exact, `MORE_INPUT`, and refusal cases pass |
| Package | wheel and sdist build and archive-isolation checks pass |
| Container | image builds, runs as configured, and `/healthz` passes |
| Presentation | HTML self-check, SVG parse, link check, desktop render, and 390px visual QA pass |
| Independent QA | A fresh read-only reviewer reports no release blocker |
| Remote governance | PR merged only after required checks pass; release tag targets merged `main` |

## Evidence binding

The GitHub Release attachment `release-manifest-v0.14.2.json` is authoritative for the final
commit SHA, CI run URL, Docker image digest, command results, and evidence-file hashes. The
companion `SHA256SUMS.txt` covers every uploaded release asset. Historical v0.14.1 evidence
remains unchanged and continues to report 324 tests.

## Boundaries

- All bundled factor values are project-authored synthetic examples and are not valid for
  carbon accounting.
- Users are responsible for rights to any external catalog they connect.
- Importing a record never constitutes human review, approval, or locking.
- CFR does not parse PDF, DOCX, Excel, images, OCR output, BOMs, or procurement ledgers.
