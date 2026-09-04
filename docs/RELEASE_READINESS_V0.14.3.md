# CFR v0.14.3 Release Readiness

## Decision

`GO` only after the release-preparation PR is merged normally into protected `main`, every exact
merged-main required check is green, all public-safe artifacts are generated from that commit,
and the downloaded GitHub Release assets match their published SHA-256 evidence.

## Scope

This patch publishes the resolution-safety, catalog-to-lock integrity, connector/control-plane,
versioned API operability, engineering-delivery and evaluation-governance hardening integrated
after v0.14.2. Release preparation changes only package version and release documentation/tests;
it does not alter Resolver behavior, factor values, candidate IDs, frozen answers or benchmark
case inventories. No intentional incompatible public API change is introduced.

## Evaluation statement

- **Raw Autonomous V1:** 103 Bad Cases, Direct Top-1 230/259 and Recall@5 259/259; raw failure
  evidence remains visible and immutable.
- **Effective Autonomous Contract V3:** 418/418 contracts, Direct Top-1 230/230,
  Recall@5 230/230, abstention 145/145, `MORE_INPUT` 23/23, 0 unresolved Bad Cases and
  0 forbidden-candidate escapes; boundary, subject, unit and HTTP-500 escapes are 0.

V3 is a versioned post-adjudication regression over project-authored public-synthetic data. It is
not an independent Holdout and not a real-world accuracy estimate. It does not validate licensed
catalog coverage, unknown enterprise queries or production service operation.

## Required gates

| Gate | Requirement |
|---|---|
| Core and compatibility | Full suite and branch-coverage gate pass on Python 3.11, 3.12 and 3.13 |
| Evaluation | FactorBench, Frozen Unit, Sealed Unit, Portfolio and Autonomous effective gates pass while raw metrics remain visible |
| Static checks | Ruff, mypy and compileall pass under the repository's documented scope |
| Package | Exact-version wheel and sdist build; metadata and archive isolation pass |
| Public safety | No licensed database, customer file, credential or absolute local path is included |
| Supply chain | pip-audit, Bandit, Gitleaks and Trivy pass; CycloneDX SBOM is generated |
| Container | Locked image builds, starts, becomes healthy and produces an immutable image ID |
| Governance | Protected required checks pass; merge uses the normal PR path without bypass |
| Publication | Annotated tag equals final `main`; every downloaded Release attachment verifies |

## Required attachments

- `carbon_factor_resolver-0.14.3-py3-none-any.whl`
- `carbon_factor_resolver-0.14.3.tar.gz`
- `release-manifest-v0.14.3.json`
- `SHA256SUMS-v0.14.3.txt`
- `docker-image-id-v0.14.3.txt`
- `sbom-v0.14.3.cdx.json`
- `trivy-v0.14.3.json`
- `gitleaks-v0.14.3.json`
- `bandit-v0.14.3.json`
- `pip-audit-v0.14.3.json`
- `public-delivery-scan-v0.14.3.json`

The annotated tag may be unsigned when no signing identity is configured; the Release must not
claim a cryptographic signature unless verification actually succeeds.
