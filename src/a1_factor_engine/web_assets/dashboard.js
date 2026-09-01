const $ = (selector) => document.querySelector(selector);
const count = (value) => Array.isArray(value) ? value.length : (value && typeof value === "object" ? Object.keys(value).length : 0);
const showError = (id, error) => { $(id).textContent = error ? String(error.message || error) : ""; };

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".tab,.panel").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  $(`#${button.dataset.tab}`).classList.add("active");
}));

function cell(row, value, className = "") {
  const td = document.createElement("td"); td.textContent = value ?? "—"; td.className = className; row.appendChild(td);
}

function renderCandidates(result) {
  const tbody = $("#candidate-rows"); tbody.replaceChildren();
  const candidates = [...(result.candidates || []), ...(result.reviewable_candidates || []), ...(result.diagnostic_candidates || [])];
  candidates.forEach((candidate) => {
    const row = document.createElement("tr");
    cell(row, candidate.source?.source_id || candidate.candidate_id);
    cell(row, `${candidate.factor_value ?? "—"} ${candidate.factor_unit || ""}`);
    cell(row, candidate.score == null ? "—" : Number(candidate.score).toFixed(3));
    cell(row, candidate.result_tier);
    cell(row, (candidate.reasons || []).join("; "));
    tbody.appendChild(row);
  });
}

$("#query-form").addEventListener("submit", async (event) => {
  event.preventDefault(); showError("#query-error", null);
  const data = Object.fromEntries(new FormData(event.currentTarget)); data.quantity = Number(data.quantity);
  if (!data.production_process) delete data.production_process;
  try {
    const result = await api("/api/v1/resolve", { method: "POST", body: JSON.stringify(data) });
    const trace = result.trace || {};
    const explanation = trace.entries ? await api(`/api/v1/traces/${encodeURIComponent(result.request_id)}`) : trace;
    const localHits = explanation.raw_related_hits || explanation.local_retrieval?.records || [];
    const externalHits = (explanation.entries || [])
      .filter((entry) => entry.stage === "external_discovery")
      .flatMap((entry) => entry.details?.source_ids || []);
    const discovered = new Set([
      ...localHits.map((item) => item.source_id || item.record_id || String(item)),
      ...externalHits,
    ]);
    $("#request-id").textContent = result.request_id;
    $("#pipe-identity").textContent = explanation.identity_resolution?.outcome || explanation.material_identity?.canonical_name || data.material_name;
    $("#pipe-hits").textContent = `${discovered.size} discovered`;
    $("#pipe-drops").textContent = `${count(explanation.excluded_candidates)} excluded`;
    $("#pipe-qualification").textContent = `${count(explanation.record_qualifications)} records checked`;
    $("#pipe-candidates").textContent = `${count(result.candidates) + count(result.reviewable_candidates)} surfaced`;
    $("#pipe-terminal").textContent = result.status;
    renderCandidates(result);
  } catch (error) { showError("#query-error", error); }
});

function flattenMetrics(payload) {
  const metrics = payload.aggregates || payload.metrics || payload.aggregate_metrics || {};
  return Object.entries(metrics).filter(([, value]) => ["number", "string", "boolean"].includes(typeof value));
}

$("#benchmark-form").addEventListener("submit", async (event) => {
  event.preventDefault(); showError("#benchmark-error", null);
  const data = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const result = await api("/api/v1/benchmarks/runs", { method: "POST", body: JSON.stringify(data) });
    $("#benchmark-run-id").textContent = result.run_id || "completed";
    const rows = $("#metric-rows"); const cards = $("#metric-grid"); rows.replaceChildren(); cards.replaceChildren();
    flattenMetrics(result).forEach(([name, value], index) => {
      const row = document.createElement("tr"); cell(row, name); cell(row, value); rows.appendChild(row);
      if (index < 4) { const card = document.createElement("article"); card.className = "metric"; const label = document.createElement("span"); label.textContent = name; const strong = document.createElement("strong"); strong.textContent = value; card.append(label, strong); cards.appendChild(card); }
    });
  } catch (error) { showError("#benchmark-error", error); }
});

$("#compare-form").addEventListener("submit", async (event) => {
  event.preventDefault(); showError("#compare-error", null);
  const data = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const result = await api(`/api/v1/benchmarks/compare?base=${encodeURIComponent(data.base)}&candidate=${encodeURIComponent(data.candidate)}`);
    const rows = $("#regression-rows"); rows.replaceChildren();
    Object.entries(result.deltas || result).filter(([, value]) => typeof value === "number").forEach(([name, value]) => {
      const row = document.createElement("tr"); cell(row, name); cell(row, value.toFixed(4)); cell(row, value < 0 ? "regression" : value > 0 ? "improvement" : "unchanged", value < 0 ? "bad" : "good"); rows.appendChild(row);
    });
  } catch (error) { showError("#compare-error", error); }
});

api("/healthz").then(() => { $("#service-status").textContent = "service online"; }).catch(() => { $("#service-status").textContent = "service unavailable"; });
