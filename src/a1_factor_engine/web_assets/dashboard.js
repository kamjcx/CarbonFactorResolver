const $ = (selector) => document.querySelector(selector);
const count = (value) => Array.isArray(value) ? value.length : (value && typeof value === "object" ? Object.keys(value).length : 0);
const showError = (id, error) => { $(id).textContent = error ? String(error.message || error) : ""; };

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : payload.detail?.message || payload.message || `Request failed (${response.status})`);
  return payload;
}

function cell(row, value, className = "") {
  const td = document.createElement("td"); td.textContent = value ?? "—"; td.className = className; row.appendChild(td);
}

function renderCandidates(result) {
  const tbody = $("#candidate-rows"); tbody.replaceChildren();
  const candidates = [...(result.candidates || []), ...(result.reviewable_candidates || [])];
  if (!candidates.length) { const row = document.createElement("tr"); cell(row, "No candidate returned. See the decision above."); row.firstChild.colSpan = 5; tbody.appendChild(row); }
  candidates.forEach((candidate) => {
    const row = document.createElement("tr");
    cell(row, candidate.source?.source_id || candidate.candidate_id);
    cell(row, `${candidate.factor_value ?? "—"} ${candidate.factor_unit || ""}`);
    cell(row, candidate.score == null ? "—" : Number(candidate.score).toFixed(3));
    cell(row, candidate.result_tier);
    cell(row, (candidate.reasons || []).join("; "));
    tbody.appendChild(row);
    const evidenceRow = document.createElement("tr"); const td = document.createElement("td"); td.colSpan = 5;
    const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "Source evidence and applicability"; details.appendChild(summary);
    const source = candidate.source || {};
    [source.citation, `Boundary: ${(source.boundary_modules || []).join(" / ") || source.boundary || "unspecified"}`, `Subject: ${source.subject_type || "unspecified"} · Geography: ${source.geography || "unspecified"} · Year: ${source.year || "unspecified"}`, `Evidence hash: ${source.content_sha256 || "unavailable"}`, ...(candidate.limitations || []), ...(candidate.warnings || [])].filter(Boolean).forEach((line) => { const p = document.createElement("p"); p.textContent = line; details.appendChild(p); });
    td.appendChild(details); evidenceRow.appendChild(td); tbody.appendChild(evidenceRow);
  });
}

$("#query-form").addEventListener("submit", async (event) => {
  event.preventDefault(); showError("#query-error", null);
  const data = Object.fromEntries(new FormData(event.currentTarget)); data.quantity = Number(data.quantity);
  if (!data.production_process) delete data.production_process;
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true; button.textContent = "Resolving…";
  $("#candidate-rows").replaceChildren(); $("#request-id").textContent = "Request in progress";
  document.querySelectorAll(".pipeline p").forEach((p) => { p.textContent = "—"; });
  $("#decision-title").textContent = "Resolving your query…"; $("#decision-message").textContent = "";
  $("#decision-questions").replaceChildren(); $("#decision-reasons").textContent = "";
  try {
    const result = await api("/api/v1/resolve", { method: "POST", body: JSON.stringify(data) });
    $("#request-id").textContent = result.request_id;
    $("#pipe-identity").textContent = data.material_name;
    $("#decision-title").textContent = result.status.replaceAll("_", " ");
    $("#decision-message").textContent = result.message || "Review candidate evidence before selecting a factor.";
    (result.questions || []).forEach((question) => { const li = document.createElement("li"); li.textContent = question; $("#decision-questions").appendChild(li); });
    $("#decision-reasons").textContent = (result.reason_codes || []).join(" · ");
    $("#pipe-candidates").textContent = `${count(result.candidates) + count(result.reviewable_candidates)} surfaced`;
    $("#pipe-terminal").textContent = result.status;
    renderCandidates(result);
  } catch (error) {
    showError("#query-error", error); $("#decision-title").textContent = "Request could not be completed"; $("#request-id").textContent = "No result";
  } finally { button.disabled = false; button.textContent = "Resolve factor"; }
});
const examples = { exact: ["primary aluminium ingot", "primary aluminium production"], ambiguous: ["metallic aluminium feedstock", ""], refusal: ["unknown portfolio material xyz", ""] };
document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => {
  const [material, process] = examples[button.dataset.example]; const form = $("#query-form");
  form.elements.material_name.value = material; form.elements.production_process.value = process;
  form.elements.quantity.value = "1"; form.elements.quantity_unit.value = "t"; form.elements.material_name.focus();
}));
api("/healthz").then(() => { $("#service-status").textContent = "service online"; }).catch(() => { $("#service-status").textContent = "service unavailable"; });
