# Limitations

CarbonFactorResolver v0.14 is a portfolio-ready, reproducible research prototype. It is not a
production carbon-accounting system and does not certify, approve, or calculate a product
carbon footprint.

- Public fixtures are intentionally small and synthetic; catalogue coverage is not
  representative of ecoinvent or any commercial database.
- Retrieval quality depends on structured source coverage and supplied query attributes.
- Non-material factors require an explicit subject. Explicit geography/year conflicts are hard
  exclusions unless a versioned deployment substitution policy authorizes that dimension.
- `MORE_INPUT` and refusal are expected outcomes when identity, unit, boundary, subject, or
  evidence is insufficient.
- Human review is required before locking a factor. Locked factors still require downstream
  calculation governance.
- Live source connectors require deployment-specific authentication, licensing, rate limits,
  and evidence validation; the public demo defaults to deterministic snapshots.
- The offline DOCX/PDF acceptance harness is developer QA tooling, not a runtime capability.
- Performance numbers apply only to the stated test environment and fixture set.
- Autonomous Evaluation V1 is project-authored and contract-generated. Its breadth improves
  systematic regression discovery, but it is not independent expert labelling and does not
  establish general accuracy on enterprise language or licensed catalogs.
- The 10k/50k benchmark is a synthetic exact-match/robustness workload. Python event-loop
  concurrency is not equivalent to multi-process production capacity, and no SLA is claimed.
- An unspecified request geography/year remains unknown. Ordinary reviewer assumption acceptance
  cannot override an explicit geography/year conflict.
- Deployment policy signatures depend on an operator-supplied verifier and trust root; the public
  project does not ship production keys or an organizational approval service.
- Request idempotency and the reference approval store are process-local. Multi-worker deployment
  needs a shared atomic store, durable constraints and recovery procedures.
- Pinned actions/images, vulnerability scans and SBOM generation strengthen delivery evidence but
  do not constitute signed provenance or production certification; scanner databases are dynamic.

Roadmap items such as broader ontologies, document intelligence, report generation, complex UI,
and automatic formal-catalogue workflows are deliberately outside this release.
