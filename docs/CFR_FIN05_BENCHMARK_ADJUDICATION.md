# FIN-05 Benchmark Adjudication

## Status

FIN-05 remains unchanged pending a human benchmark adjudication. This document is a
read-only evidence assessment; it neither changes the frozen Portfolio Challenge answer
nor authorizes a production semantic-policy change.

## Current evidence

The frozen request is `钢纤维制品`, one kilogram, `finished_product`, with a
`cradle-to-gate` boundary. The frozen acceptable source is
`pc:steel-fiber-product`, whose synthetic record is `steel fiber product`,
`kgCO2e/kg`, `finished_product`, `GWP-total`, and `cradle-to-gate`.

The baseline resolver retrieves four same-entity records. The acceptable source is
recalled through its reviewed catalogue alias and passes identity, factor-kind,
subject-type, source-quality, indicator, declared-product, boundary, and unit
qualification. It is admitted as a direct candidate with no hard exclusion.

Independently, request normalization classifies steel fibre as a broad product family.
It records unresolved subtype, steel grade/family, surface coating, and application,
then requires a `steel_fiber_type` choice before an EPD is selected. Consequently the
trace funnel is 42 raw records, 4 retrieval hits, 1 qualified record, 0 candidate-pool
records, and 0 returned records; the status is `more_input_needed`.

The evidence therefore exposes a semantic-policy conflict rather than a unit defect:
the catalogue alias and direct qualification say the source is admissible, while the
request-gap policy says the request is not specific enough to select it.

## Adjudication options

### Option 1 — Confirm the frozen `retrieve` answer

The benchmark owner may establish that `pc:steel-fiber-product` is deliberately a
generic steel-fibre product record whose declared-product scope covers all meanings of
the request alias. Production policy would then need a reviewed rule explaining why
subtype, coating, grade, and application are not required for this generic record.

Risk: accepting the alias alone without source-scope evidence could silently apply an
ordinary, coated, or stainless-steel-fibre factor to a materially different product.

### Option 2 — Adjudicate the expected decision as `more_input`

The benchmark owner may conclude that subtype/coating/grade ambiguity is material and
that the current safe question is the intended result. This would align the benchmark
with current request-gap policy.

Risk: changing the answer without proving the benchmark's original intent would hide a
possible product-identity or generic-factor-policy defect.

### Option 3 — Preserve both sides pending evidence (recommended)

Keep the frozen benchmark label and current production behavior unchanged. Record
FIN-05 as an open adjudication, exclude it from the unit-fix success claim, and resolve
it only after the evidence and approvals below are complete. This preserves the
immutable benchmark and avoids weakening a safety gate merely to improve recall.

## Evidence required for a final decision

- Authoritative declared-product and product-scope documentation for
  `pc:steel-fiber-product`, including whether it is generic or subtype-specific.
- Steel family/grade, surface coating, application, manufacturing route, and any
  exclusions or representativeness limits for the source factor.
- The provenance for the Chinese alias `钢纤维制品` and an explicit statement of
  whether it denotes one product entity or a broad family.
- A reviewed comparison of ordinary uncoated carbon steel, copper-plated steel, and
  heat-resistant stainless steel fibre, including the consequence of selecting the
  wrong subtype.
- A product-identity or registry decision defining whether a generic factor may be a
  primary recommendation, a review-only reference, or must require more input.
- Benchmark-owner sign-off on the intended expected decision and carbon-domain/data-
  governance sign-off on the production policy. If production behavior or a public
  contract changes, technical-owner approval is also required.

Until those items exist in canonical, reviewable sources, the available evidence is
insufficient to choose Option 1 or Option 2. Option 3 is therefore the recommended
interim disposition, with the FIN-05 label left unchanged.
