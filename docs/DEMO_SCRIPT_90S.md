# 90-Second Portfolio Demo Script

Start `docker compose up --build -d` and open http://127.0.0.1:8000.
For Python, install `.[test,api]` and run `cfr serve --demo`.
All examples below use the bundled synthetic catalog.

## 0–15s — Problem and boundary

CFR resolves structured factor queries and qualifies units, lifecycle boundaries,
subjects and provenance. Human review remains necessary before accounting use.

## 15–40s — Qualified match

Click **Qualified match**, then **Resolve factor**. The request is primary aluminium
 ingot, 1 t, primary aluminium production. Show `recommendation_ready`, the
`fixture-al-primary-a1a3` source, 8400 kgCO2e/t and `USABLE_WITH_ASSUMPTIONS`.
Expand **Source evidence and applicability** to show the synthetic citation,
A1/A2/A3 boundary, content hash and remaining evidence gaps.

## 40–62s — Missing route

Click **Missing route**, then **Resolve factor**. Show `more_input_needed` and the
message requiring a material subtype. Primary and secondary sources remain
`REFERENCE_ONLY`; neither has been selected or approved. The current fixture
returns the request for clarification in `message`, with an empty `questions` list.

## 62–80s — Safe refusal

Click **Unknown material**, then **Resolve factor**. Show `supplier_data_required`,
the explanation and the empty candidate table. No numeric factor is invented.

## 80–90s — Engineering evidence

Open the repository Evaluation page for versioned test and benchmark evidence.
Explain that benchmarks, full Trace and review/lock operations belong to the protected
admin surface. The default dashboard displays public response fields only.
Historical failed evaluations remain documented; synthetic results are not universal accuracy.
