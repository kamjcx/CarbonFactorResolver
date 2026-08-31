# Changelog

## 0.13.1 - 2026-09-01

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
