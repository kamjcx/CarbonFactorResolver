# CarbonFactorResolver v0.14.4 — Contract and Release Alignment

v0.14.4 aligns the latest stable Release with the reviewed changes merged after v0.14.3. The old
v0.14.3 tag and Release remain immutable at their original commit. This patch introduces no new
factor values, retrieval rules, semantic aliases, benchmark expectations or automatic approval.

## Public API safety

- Freeze the JSON-only API safety contract with strict request DTOs and independently validated
  domain requests.
- Return an allowlisted public recommendation that excludes full traces, internal diagnostics,
  transformation internals, application previews and mutable review state.
- Keep full diagnostics and human-review mutations on the separately constructed administration
  application, whose reviewer identity comes from verified authorization context.
- Return stable, redacted validation, conflict and unexpected-error envelopes without reflecting
  unsafe caller identifiers or internal exception text.

## Unit field contract

- Apply each factor using `resolved_activity_value` aligned to `resolved_activity_unit` rather than
  multiplying every factor by a mass compatibility field.
- Retain `resolved_quantity_kg` only as auxiliary normalized mass; it is null for energy,
  transport-work, volume, area and count unless evidence-backed reference-flow conversion first
  produces mass.
- Normalize `gCO2e`, `kgCO2e` and `tCO2e` impact numerators for preview calculation, then recompute
  and validate denominator alignment and finite totals before locking.
- Preserve all earlier locked snapshots and trace bytes; the corrected semantics apply
  prospectively.

## Human-review state machine

- Define `OPEN -> SELECTED -> LOCKED` with independent candidate rejections, one approved candidate
  per request and one immutable lock.
- Bind decisions to candidate and recommendation digests, catalog/registry/policy anchors, verified
  reviewer identity and the immutable hash-chain prefix at the decision revision.
- Make exact retries idempotent, explicit stale revisions fail closed, and concurrent competing
  approvals converge on one winner through atomic store compare-and-set behavior.
- Keep review routes off the public application and reject identity supplied in request bodies.

The repository's reference `ResolutionStorePort` adapter remains **in-memory**. It demonstrates
atomic state transitions, retry behavior and reconstruction over the same store instance; durable
cross-process persistence and recovery require a deployment-owned adapter and are not claimed by
this Release.

## Recruiter-first documentation

The README now presents the problem, ownership, architecture, public-synthetic demo and current
quality evidence before the detailed audit history. It distinguishes what the default Quickstart
Dashboard actually renders from deeper repository and test coverage. The default demo does not
claim full Trace, rejected-candidate diagnostics, process-transformation views, admin review/lock
controls or a fused-spinel fixture.

## Admission and evaluation boundaries

Three structured electricity records remain blocked from formal admission until complete formal
source and approval evidence is available. v0.14.4 does not silently approve them or add any formal
factor catalog.

Evaluation results remain versioned project-authored **public-synthetic** contract evidence. They
are not an independent Holdout and not a real-world accuracy estimate. Historical failed runs,
raw/effective metric separation and the v0.14.3 evidence remain unchanged.

## Release evidence

The GitHub Release publishes a wheel, source distribution, release manifest, package and complete
SHA-256 lists, Docker image ID, CycloneDX SBOM, Trivy, Gitleaks, Bandit, pip-audit and public-delivery
scan evidence generated from the final v0.14.4 commit. No licensed factor database or customer file
is included.
