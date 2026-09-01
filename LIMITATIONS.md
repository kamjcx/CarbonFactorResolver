# Limitations

CarbonFactorResolver v0.14 is a portfolio-ready, reproducible research prototype. It is not a
production carbon-accounting system and does not certify, approve, or calculate a product
carbon footprint.

- Public fixtures are intentionally small and synthetic; catalogue coverage is not
  representative of ecoinvent or any commercial database.
- Retrieval quality depends on structured source coverage and supplied query attributes.
- `MORE_INPUT` and refusal are expected outcomes when identity, unit, boundary, subject, or
  evidence is insufficient.
- Human review is required before locking a factor. Locked factors still require downstream
  calculation governance.
- Live source connectors require deployment-specific authentication, licensing, rate limits,
  and evidence validation; the public demo defaults to deterministic snapshots.
- The offline DOCX/PDF acceptance harness is developer QA tooling, not a runtime capability.
- Performance numbers apply only to the stated test environment and fixture set.

Roadmap items such as broader ontologies, document intelligence, report generation, complex UI,
and automatic formal-catalogue workflows are deliberately outside this release.

