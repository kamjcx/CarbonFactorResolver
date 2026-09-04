# CarbonFactorResolver v0.14.3 — Safety and Governance Hardening

v0.14.3 publishes the reviewed hardening stack integrated after v0.14.2. It is a compatible
patch release: the structured `/api/v1` Resolver contract remains versioned and no intentional
incompatible public API change, factor-value change, candidate-ID change, or automatic approval
path is introduced.

## Resolution and evidence safety

- Enforce formal geography, year, declared-product, lifecycle-boundary and evidence gates with
  stable fail-closed outcomes.
- Bind catalog content, source records, recommendations, approvals, locks and evidence traces to
  immutable digests and compare-and-set state transitions.
- Require explicit, signed, catalog-content-bound deployment policy for production approval;
  replay policy dates deterministically and reject missing, future or expired policy state.
- Harden connector redirects, payload limits, DNS/address validation, external-record
  normalization, request replay, correlation IDs, readiness probes and JSON error containment.
- Make graph-stage prerequisites explicit and keep stale signature state out of catalog caches.

## Delivery and supply-chain safety

- Pin CI actions, the Dockerfile frontend, runtime bases and scanner images to immutable digests.
- Build from the locked dependency graph; remove packaging tools from the runtime image; run as a
  non-root user and validate `/healthz` before publication.
- Add public-data and archive isolation, pip-audit, Bandit, Gitleaks, CycloneDX SBOM generation,
  Trivy image scanning, release checksums and an evidence-bound release manifest.
- Retain the protected `container` check as a fail-closed compatibility sentinel that can succeed
  only after the real `test` job completes Docker build, runtime health and Trivy gates.

## Evaluation governance

Historical and effective results are reported separately:

- **Raw Autonomous V1:** 103 Bad Cases, Direct Top-1 230/259 and Recall@5 259/259. The raw hard
  gate remains failed and the historical evidence is unchanged.
- **Effective Autonomous Contract V3:** 418/418 case contracts, Direct Top-1 230/230,
  Recall@5 230/230, abstention 145/145, `MORE_INPUT` 23/23, 0 unresolved Bad Cases and
  0 forbidden-candidate escapes. Boundary, subject, unit and unhandled HTTP-500 escapes are also 0.

Contract V3 is a versioned post-adjudication regression over project-authored public-synthetic
data. It is not an independent Holdout and not a real-world accuracy estimate. Effective
expectations are case/input/previous-expectation bound and re-evaluated; legacy adjudications and
forbidden candidates cannot act as waivers.

## Release evidence

The GitHub Release publishes the wheel, source distribution, release manifest, SHA256SUMS,
Docker image ID, locked dependency SBOM, Trivy, Gitleaks, Bandit, pip-audit and public-delivery
scan evidence. These public artifacts contain no licensed factor database or customer files.
