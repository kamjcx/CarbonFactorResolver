# CFR Engineering Delivery Hardening V6

## Scope and compatibility

This stacked change hardens engineering delivery around the frozen V5 runtime contract. It does
not change retrieval ranking, semantic aliases, factor values, candidate identifiers,
qualification or approval semantics, or frozen benchmark answers.

## Deployment policy boundary

The generic HTTP catalog repository no longer embeds a customer- or refractory-specific default
policy. Deployments may inject a versioned `CatalogPolicyBundle`, but the bundle is valid only for
the exact canonical catalog-content SHA-256 it declares. Any policy that can grant production
approval also requires a deployment-supplied signature verifier and a verified signature.

The public repository intentionally does not include a production key-management, signer,
certificate-rotation, or organizational approval service. A verified bundle proves conformance to
the injected verifier; operators remain responsible for establishing the verifier's trust root and
approval governance.

## Fail-closed execution invariants

Graph nodes that require normalized input now call an explicit stage invariant instead of silently
returning when the prerequisite is absent. The invariant produces a stable internal failure rather
than continuing with a partial state.

This is a focused strengthening of the existing mutable `GraphState`. A complete immutable,
stage-typed state-machine redesign is deliberately deferred because it would change a broad runtime
contract and review surface. The current module remains covered by deterministic transition and
end-to-end regression tests.

## Type and CLI contracts

- The five historical core-module `mypy` exemptions were removed. The complete package is checked
  under the repository configuration.
- The positional CLI is explicitly a mass-factor convenience shortcut. Energy, transport,
  process, subject-specific, or evidence-bearing requests must use the structured JSON contract.
- Positional arguments, structured field flags, and `--input-json` cannot be ambiguously mixed.

## Supply-chain controls

The delivery pipeline pins action revisions and container base images, consumes the locked runtime
dependency graph, scans source/dependencies/secrets/container content, generates a CycloneDX SBOM,
and binds build artifacts with checksums and a release manifest. Archive and public-delivery checks
reject common database, document, environment, credential, nested-archive, and customer-data paths.

These controls improve reproducibility but do not make this research prototype a production
service:

- `ubuntu-24.04` is a stable GitHub-hosted runner label, not an immutable runner image digest;
- vulnerability databases and their findings change over time, so archived reports and tool
  versions are part of the evidence;
- the local Docker daemon was unavailable during development, making the protected remote
  container job authoritative for build, health, image scan, and SBOM evidence;
- a local image ID is not a registry manifest digest, signature, or provenance attestation.

## Persistence limitation

Approval/lock integrity uses canonical digests and compare-and-set semantics in the repository
contract. Request idempotency is process-local. Multi-worker or horizontally scaled deployment
requires a shared atomic store, durable unique constraints, transaction isolation, key management,
and operational recovery procedures. None is implied by this change.

## Release decision

This branch is reviewable engineering hardening for the portfolio/research-prototype boundary.
The inherited autonomous evaluation gate remains authoritative and intentionally stays red while
its unresolved adjudicated cases remain open. Security tooling, passing unit tests, or an SBOM must
not be interpreted as authorization to merge, release, approve factor data, or claim production
readiness.
