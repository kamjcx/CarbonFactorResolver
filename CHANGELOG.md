# Changelog

## Unreleased

- Freeze the `/api/v1` operability contract with stable JSON error envelopes, version and
  correlation headers, redacted unhandled-500 behavior, and JSON-only media enforcement.
- Separate liveness (`/healthz`) from aggregate dependency readiness (`/readyz`); the production
  factory no longer loads synthetic fixtures or claims readiness without explicit configuration.
- Make mapping-based readiness probes fail closed unless they report an explicit, consistent
  healthy state.
- Make CLI resolution scriptable with JSON stdin/file input, machine-only stdout, sanitized stderr,
  explicit demo selection, a formal-only Resolver path, and stable domain/usage/internal exit codes.
- Bind request-ID replay to canonical request fingerprints with per-key concurrency serialization;
  mismatched reuse returns a stable 409 instead of replaying an unrelated result.

- Added the frozen `cfr.catalog/v2` canonical content manifest and strict
  declared-versus-observed record digest validation.
- Bound dataset policy, source records, candidates, recommendations, approvals,
  locked results and evidence traces to versioned content digests.
- Added atomic approval/lock compare-and-set semantics, append-only trace hash
  chains and immutable locked evidence snapshots.
- Added fail-closed migration rules for unbound policies and legacy approvals.

## Unreleased

- Harden formal resolution: explicit geography/year conflicts fail closed unless a versioned
  deployment substitution policy authorizes that exact dimension; missing declared product or
  lifecycle boundary is `REFERENCE_ONLY` and cannot be approved or locked.
- Merge Exact, reviewed Alias and same-entity Related channels before decisive ambiguity
  analysis; revalidate reference-flow identity/packaging; preserve generic activity units and
  recompute non-mass totals at lock.
- Move `min_score` ownership to immutable `DeploymentPolicy`; formal JSON rejects request-side
  threshold overrides while the opt-in debug API/CLI retain an explicit debug path.
- Add `m²`, `roll`, `kgCO2e/(t*km)` and numeric-zero catalog coverage. Missing API extras now
  fail evaluation as an operational precondition instead of fabricating a 101st Bad Case.
- Make Autonomous Evaluation and Portfolio Validation fail closed when quality gates fail,
  while preserving generated evidence and distinguishing execution completion from quality
  approval.
- Add SHA-bound machine adjudications, dynamic Portfolio findings, reverse gate tests, and a
  100-case root-cause audit for the unchanged `5155a682` baseline; no Resolver behavior or
  frozen answer is changed.
- Add the SHA-bound Portfolio Challenge V2 adjudication overlay. Raw V1 metrics remain visible;
  effective metrics separately score formal candidates and exact `REFERENCE_ONLY`/provisional
  option contracts for FIN-05, CNF-01 and MI-01 through MI-06.
- Require broad English and Chinese steel-fibre raw-material queries to return
  `MORE_INPUT_NEEDED`; generic steel remains non-selectable reference evidence.
- Preserve the resulting 103 Autonomous raw failures and add a complete 13-case Safety V2
  oracle adjudication, leaving 90 unresolved effective failures instead of hiding the V1 delta.

## 0.14.2 - 2026-09-03

- Add a developer-only autonomous contract evaluator with 414 deterministic public-synthetic
  cases, an independent Oracle, explicit-denominator metrics, immutable first-run manifests,
  Bad Case attribution and adversarial approval/locking checks.
- Add deterministic 10k/50k synthetic performance and robustness benchmarks with cold/warm
  latency percentiles, peak RSS, concurrency 10/25/50, replay, ordering, noise and Top-K checks.
- Keep Resolver runtime, retrieval, ranking, qualification, formal factors and every existing
  frozen answer unchanged; autonomous failures require separate adjudication.
- Repair three contract-backed findings without rewriting Autonomous Evaluation V1: require
  decisive input when multiple process/form/geography/year values remain, fail closed when a
  structured source lacks a valid document SHA-256, and serialize terminal approval decisions.
- Preserve six geography/year raw failures and document them as a versioned benchmark-label
  disagreement with the published `USABLE_WITH_ASSUMPTIONS` contract.
- Add a 20-record `PUBLIC_SYNTHETIC` bring-your-own-catalog example spanning materials,
  energy, transport and processes, plus exact, `MORE_INPUT` and safe-refusal demonstrations.
- Add a BYOC tutorial for file, HTTP and custom repository adapters with explicit schema,
  fail-closed, licensing and human-approval boundaries.
- Redact local filesystem identity from BYOC demo output and Trace by using a stable synthetic
  locator and repository-relative display path.
- Replace the README hero architecture visual with CFR's internal resolution flow, making
  recall versus deterministic admission, excluded-candidate Trace, human review and immutable
  locking visible; no Resolver behavior changes are introduced by the presentation work.

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
