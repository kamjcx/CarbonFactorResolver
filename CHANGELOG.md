# Changelog

## 0.14.0-rc.4 - 2026-09-02

- Fail the sealed release gate unless every frozen case satisfies its full HTTP/status/reason/
  candidate/trace contract, in addition to the aggregate safety thresholds.
- Preserve the RC3 first run as a NO-GO: 35/48 full case contracts passed even though the
  previous aggregate-only gate incorrectly reported success.
- Require a wholly new sealed dataset for RC4; no RC3 expectation or runtime result is rewritten.

## 0.14.0-rc.3 - 2026-09-02

- Added a versioned electricity entity and reviewed `铝金属` alias, repairing the four
  immutable rc.2 diagnostic mismatches without changing rc.2 evidence.
- Added end-to-end admission for structured energy, combustion and transport factor kinds,
  with explicit non-material subject confirmation.
- Made geography/year applicability outrank source preference and prevented mismatched or
  stale records from being presented as primary recommendations.
- Unified local/external qualification and admission diagnostics; conflicting duplicate
  source IDs now fail closed.
- Anchored semantic-index and HTTP cache identity to decision-relevant record content and
  made unordered JSON serialization deterministic.
- Added FactorBench V3 admission adjudications while retaining V1/V2 unchanged.

RC3 remains a release candidate until a wholly new sealed first run and remote CI pass.

## 0.14.0-rc.2 - 2026-09-02

- Replaced the failing Compose-container lookup in the image-digest evidence step with a
  direct inspection of the successfully built image.
- Preserved the complete rc.1 sealed first-run metrics and hashes; rc.1 remains a release
  NO-GO because remote CI was not green.
- Requires a wholly new sealed holdout before rc.2 can be promoted.

## 0.14.0-rc.1 - 2026-09-02

- Merged the Portfolio Challenge and Unit System work onto a clean `main` baseline.
- Fixed all three strict fault-injection findings: catalogue transport failures now fail
  closed without HTTP 500, and health/request/benchmark failures no longer reflect internal
  exception text.
- Made rejection terminal for a candidate within the same immutable resolution run.
- Preserved FactorBench V1 and introduced FactorBench V2 with a versioned `wrong-unit-53`
  adjudication; historical scores remain unchanged.
- Renamed the 28-case unit evaluation to **Frozen Unit Regression Set** and retained both
  the independent first-run 24/28 result and the post-fix 28/28 regression result.
- Added canonical architecture, evaluation, limitation, data-license, security and
  contribution documents plus public package/container safety gates.
- Hardened Docker context and source-distribution exclusions against local reports,
  credentials, databases, documents and customer material.

This release candidate is a portfolio-ready reproducible research prototype. It is not a
production carbon-accounting system and includes no licensed factor database.

## 0.13.1 - 2026-09-01

- Clarified the production boundary: CFR accepts structured factor requests and records; document parsing, OCR, activity-data extraction, full footprint calculation, report generation, and automatic catalogue approval remain outside the product runtime.
- Split developer-only document dependencies into `acceptance-tools` and `energy-db-build`; neither is installed by the default package, API extra, or production image.
- Added architecture tests that prohibit document/OCR imports in `src`, enforce JSON-only resolution/OpenAPI, and verify production dependency isolation.
- Enforced an exact A1/A2/A3/A1-A3 qualification matrix and removed subset-based stage leakage.
- Added hard subject-type and source-quality admission gates so raw materials, finished products, energy, transport, process, and waste cannot silently cross-qualify.
- Made missing quality/admission metadata fail closed for catalogue and external records.
- Hardened true-data extraction with strict report pairing, Decimal preservation, row/column-bound PDF verification, source immutability checks, and path-redacted evidence manifests.
- Split closed-loop ingestion acceptance from a static, independently frozen real-query holdout with release thresholds for precision, abstention, `MORE_INPUT`, and evidence.
- Ensured API tests install and execute in CI, added branch coverage for the true-data tool, and restored package branch coverage to the 85% gate.

No extracted true-data factors are admitted to the formal catalogue by this release.

## 0.13.0 - 2026-08-31

- Added end-to-end retrieval, conversion, qualification, and funnel diagnostics.
- Added explainable entity/alias/lexical/fuzzy hybrid recall with deterministic fusion.
- Corrected aluminium metal, route, ingot-form, alloy-grade, alumina, and aluminosilicate semantics.
- Added evidence-gated external discovery with fixture, OpenEPD-compatible, and public snapshot connectors.
- Added FactorBench V1 with 43 reproducible public-synthetic cases and regression comparison.
- Added FastAPI, CLI, dashboard, typed package marker, Docker, and expanded CI quality gates.

No licensed catalogue content is included in this release.
