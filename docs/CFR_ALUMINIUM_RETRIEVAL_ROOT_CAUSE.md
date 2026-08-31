# Aluminium retrieval root-cause report

## Reproduction

On 2026-08-31 the 15 requested aluminium queries were executed through the real `HttpCatalogFactorRepository` against the formal catalogue service `factor-catalog-v0.2.1`. The pinned database SHA-256 was `799bff31f6cae963d07441b2ac8f7439f27628fef0f9586bbc5f5e38b8434e06`.

The service returned 177 raw records. All 177 converted to `SourceRecord`; conversion drops were zero. Only two raw records contained aluminium terms and both represented alumina/aluminium oxide. No metallic aluminium, primary aluminium, secondary aluminium, or aluminium-ingot record existed. Complete per-query traces were retained locally and licensed catalogue rows were not committed.

## Classification

The observed formal failure is primarily **catalogue coverage failure**. It is not an adapter conversion failure: raw=177, converted=177, dropped=0. It is also not a qualification or ranking failure for metallic aluminium because no metallic record reached those stages.

Synthetic adversarial reproduction exposed three independent general defects that could obscure future data: product-form `ingot` contaminated route choice, English alloy designations such as 6061 were lost, and diagnostics hid lower recall layers after a stronger layer succeeded. These were semantic-intent and observability defects, not the cause of the empty formal catalogue result.

## Fix

- Metallic `aluminium`, `aluminum`, `铝`, and `金属铝` share `mat.element.aluminium`.
- Primary and secondary aluminium remain distinct product-route variants; ingot is a product form.
- Alumina and aluminosilicate remain separate compound entities; alloy is not pure aluminium.
- Generic aluminium can discover primary and secondary evidence but cannot silently select either; it returns `MORE_INPUT_NEEDED` with `primary`, `secondary`, and `unknown`.
- Entity, reviewed alias, route/form/grade, lexical, and RapidFuzz recall are fused deterministically while identity authority remains registry-based.
- Raw search, conversion drops, qualification decisions, discovery hits, and funnel counts survive even when no candidate is returned.
- If local evidence is absent, validated external structured evidence enters the same qualification and approval graph.

## Acceptance evidence

Public synthetic tests verify that generic aluminium discovers both route variants without returning alumina, that primary aluminium ingot selects only the primary evidence, and that evidence provenance includes a content SHA-256 and parser version. FactorBench separately guards aluminium/alumina confusables and abstention.
