# CarbonFactorResolver v0.14.2 — Contract Repairs and BYOC

v0.14.2 publishes the contract-backed runtime repairs merged after v0.14.1 and adds a
public-synthetic bring-your-own-catalog path. It remains a portfolio-ready reproducible
research prototype, not a production carbon-accounting system.

## Runtime changes

- Require decisive input when multiple process, form, geography, or year values remain.
- Fail closed when a structured source lacks a valid document SHA-256.
- Serialize terminal approval decisions for deterministic replay.
- Preserve the published geography/year benchmark contract and its six raw disagreements;
  historical expectations are not rewritten.

## Public integration example

- A 20-record `PUBLIC_SYNTHETIC` catalog covers materials, energy, transport, and processes.
- Near-neighbor pairs demonstrate ore versus clinker, raw material versus finished product,
  road versus rail, graphite versus graphite electrode, and upstream market versus combustion.
- Three copyable cases demonstrate a direct recommendation, `MORE_INPUT_NEEDED`, and safe
  refusal without generating a numeric value.
- The BYOC guide covers file, HTTP, and custom repository adapters. It does not auto-approve
  records or grant rights to third-party factor data.

## Presentation and evidence

The README architecture visual now explains CFR's internal request, retrieval, deterministic
qualification, ranking, fail-closed, review, and immutable-lock flow. Editable HTML and SVG
sources and a rendered PNG are included. This presentation-only change does not alter Resolver
behavior.

Exact release commit, CI run, package hashes, Docker digest, test totals, and public evidence
hashes are recorded in the attached release manifest and `SHA256SUMS`.
