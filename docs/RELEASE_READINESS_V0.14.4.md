# CFR v0.14.4 Release Readiness

## Decision

`GO` only after the release-alignment PR is merged normally into protected `main`, every exact
PR-head and merged-main required check succeeds, the annotated v0.14.4 tag resolves to that final
main commit, and every downloaded GitHub Release attachment matches its published SHA-256 evidence.
The v0.14.3 tag and Release must remain unchanged.

## Scope

v0.14.4 publishes the API safety, unit field and human-review state contracts integrated after
v0.14.3, plus the recruiter-first README ordering. Release preparation changes only version,
lockfile metadata, changelog/release documentation and release-contract tests. It does not change
retrieval, ranking, semantic identity, qualification, factor values, candidate IDs, formal
admission rules, frozen answers or benchmark case inventories.

The public API remains JSON-only and excludes internal diagnostics and application previews. The
administration application remains separately protected. The reference review store is in-memory;
durable cross-process persistence requires a deployment adapter and is not claimed by this Release.
Three structured electricity records remain blocked from formal admission pending complete source
and approval evidence.

## Evaluation statement

Historical FactorBench, Frozen/Sealed Unit, Portfolio and Autonomous results remain the governing
versioned evidence. These are project-authored **public-synthetic** regression and contract sets,
not an independent Holdout and not a real-world accuracy estimate. v0.14.4 does not alter their
queries, expected answers, candidate IDs or factor values.

## Required gates

| Gate | Requirement |
|---|---|
| Scope | Diff contains only approved release metadata, documentation and release-contract tests |
| Core and compatibility | Full suite and branch-coverage gate pass on Python 3.11, 3.12 and 3.13 |
| Evaluation | FactorBench, Frozen Unit, Sealed Unit, Portfolio and Autonomous gates all pass |
| Static checks | Ruff, mypy and compileall pass under the repository's documented scope |
| Package | Exact-version wheel and sdist build; metadata and archive isolation pass |
| Public safety | No licensed database, customer file, credential or absolute local path is included |
| Supply chain | pip-audit, Bandit, Gitleaks and Trivy pass; CycloneDX SBOM is generated |
| Container | Locked image builds, starts, becomes healthy and produces an immutable image ID |
| Governance | Protected checks pass and both merges use normal PR paths without bypass |
| Publication | Annotated tag equals final main; every downloaded attachment verifies |

## Required attachments

- `carbon_factor_resolver-0.14.4-py3-none-any.whl`
- `carbon_factor_resolver-0.14.4.tar.gz`
- `release-manifest-v0.14.4.json`
- `SHA256SUMS-v0.14.4.txt`
- `package-SHA256SUMS-v0.14.4.txt`
- `docker-image-id-v0.14.4.txt`
- `sbom-v0.14.4.cdx.json`
- `trivy-v0.14.4.json`
- `gitleaks-v0.14.4.json`
- `bandit-v0.14.4.json`
- `pip-audit-v0.14.4.json`
- `public-delivery-scan-v0.14.4.json`

The annotated tag may be unsigned when no signing identity is configured. The Release must state
that accurately and must not claim cryptographic signature verification unless it occurred.
