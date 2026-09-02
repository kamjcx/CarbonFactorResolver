# Changelog

## Unreleased

- Add a developer-only autonomous contract evaluator with 414 deterministic public-synthetic
  cases, an independent Oracle, explicit-denominator metrics, immutable first-run manifests,
  Bad Case attribution and adversarial approval/locking checks.
- Add deterministic 10k/50k synthetic performance and robustness benchmarks with cold/warm
  latency percentiles, peak RSS, concurrency 10/25/50, replay, ordering, noise and Top-K checks.
- Keep Resolver runtime, retrieval, ranking, qualification, formal factors and every existing
  frozen answer unchanged; autonomous failures require separate adjudication.

## 0.14.1 - 2026-09-02

- Preserve sealed unit v2's 31/32 first run, repair conditioned-volume evidence direction,
  and retain its unchanged 32/32 post-fix regression result.
- Preserve sealed unit v3's 23/24 NO-GO caused by an erroneous frozen expected value without
  relabelling the answer.
- Pass the wholly new sealed unit v4 first run at 21/21 with all reported checks at 100%.
- Treat any ambient-volume/conditioned-volume crossing, including `L`/`Nm3`, as requiring
  directional versioned evidence.
- Close FIN-05 as `MORE_INPUT_NEEDED` with its otherwise-qualified source retained only as
  `REFERENCE_ONLY`; standard selection and locking remain prohibited.
- Keep deployment-side structured electricity records blocked until their complete formal
  source and approval evidence is available.

- Reframe the README as a recruiter-friendly portfolio entry with a concise problem statement,
  five-minute synthetic-data quickstart, three demo decisions, honest evaluation summary, and
  direct links to detailed engineering documentation.
- Add a branded decision-architecture visual and two screenshots captured from the running
  synthetic CFR Dashboard.
- Update the Dashboard eyebrow from the obsolete A1-only label to the full factor-evidence
  scope; no API, retrieval, qualification, approval, fixture, or factor behavior changes.
- Add Python 3.12 and 3.13 compatibility jobs after the complete 324-test suite passed under
  both interpreters; Python 3.11 remains the authoritative branch-coverage job.

## 0.14.0 - 2026-09-02

- Promote rc.6 to the stable portfolio release after merge and required remote checks passed.
- Correct stale public documentation that still described rc.2/rc.3 as the current release
  blocker; RC3-RC5 remain preserved historical NO-GO evidence and RC6 remains the sealed GO
  evidence.
- Change packaging and release documentation only. Runtime resolution, qualification,
  ranking, public fixtures, frozen answers, and sealed evaluation evidence are unchanged from
  rc.6.
- Publish as a portfolio-ready, reproducible research prototype, not a production
  carbon-accounting system or formal factor catalogue.

## 0.14.0-rc.6 - 2026-09-02

- Preserve RC5 as NO-GO after a malformed 62-character sealed database anchor caused all
  requests to fail closed before retrieval.
- Validate sealed catalogue database anchors as exactly 64 lowercase hexadecimal characters
  during pre-runtime loading.
- Require a wholly new RC6 sealed dataset and first run.
- Passed the preserved RC6 first run: 48/48 full case contracts, 100% Top-1/recall/
  abstention/replay, and zero safety or HTTP-500 violations.

## 0.14.0-rc.5 - 2026-09-02

- Preserve RC4 as NO-GO after 36/48 complete frozen case contracts passed.
- Keep reviewed aliases and applicability alternatives in `reference_review_required` rather
  than silently promoting them to primary recommendations.
- Suppress the misleading `ADMISSION_REJECTED` reason when a request gap already produces
  `MORE_INPUT_NEEDED`; genuine hard-rejected records retain the governance reason.
- Require a wholly new RC5 sealed dataset and first run.

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
