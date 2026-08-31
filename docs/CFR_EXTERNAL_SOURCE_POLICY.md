# External source policy

External discovery runs only when local evidence is insufficient and before class-aware proxy fallback. Discovery references are not factors. A fetched structured document must pass numeric, unit, GWP indicator, declared-product, lifecycle-boundary/module, locator, parser-version, and SHA-256 validation before it can become a `SourceRecord`.

- `FixtureExternalConnector` is deterministic synthetic evidence for CI and demos.
- `PublicStructuredEPDConnector` reads a pinned structured snapshot and preserves record and snapshot hashes.
- `OpenEPDConnector` is credential-gated and reports `unavailable` without blocking other connectors. Network I/O is injected by a deployment adapter and is disabled in CI.

Search snippets, unstructured summaries, missing hashes, invalid units, non-GWP indicators, mismatched products, and incomplete boundaries are rejected. External candidates use the same qualification, gap analysis, ranking, human approval, and immutable locking path as local candidates. The repository contains no ecoinvent or other licensed database records.
