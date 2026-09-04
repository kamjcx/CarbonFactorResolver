# FIN-05 Benchmark Adjudication

## Status

**CLOSED — Option 3 adopted.** The frozen Portfolio Challenge answer remains unchanged.
The Resolver returns `MORE_INPUT_NEEDED`, preserves `pc:steel-fiber-product` as a
`REFERENCE_ONLY` candidate, and requires `steel_fiber_type` before ordinary selection.
This benchmark adjudication does not approve the synthetic record for production use.

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
then requires a `steel_fiber_type` choice before an EPD is selected. The qualified record
is therefore visible only in `reviewable_candidates`; `candidates` remains empty and the
terminal status is `more_input_needed`.

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

### Option 3 — Preserve both sides pending evidence (adopted)

Keep the frozen benchmark label unchanged and preserve the qualified source as
`REFERENCE_ONLY`. The request remains `MORE_INPUT_NEEDED`; the reference cannot use
standard approval or locking. This preserves the immutable benchmark and avoids weakening
a safety gate merely to improve recall.

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

Until those items exist in canonical, reviewable sources, the available evidence remains
insufficient for direct recommendation. Option 3 is the final safe benchmark disposition.
Future source-scope evidence may create a new versioned adjudication, but must not rewrite
this frozen answer or its recorded history.

The machine-readable V2 overlay now records Option 3 as an effective `more_input` contract while
retaining the V1 `retrieve` label and raw metrics unchanged. See
[`portfolio_challenge_v2_adjudications.json`](../data/benchmarks/portfolio_challenge_v2_adjudications.json)
and [the V2 adjudication specification](CFR_PORTFOLIO_CHALLENGE_V2_ADJUDICATION.md).
