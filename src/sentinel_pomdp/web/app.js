"use strict";

let apiKey = null;
const $ = (id) => document.getElementById(id);
const authButton = $("authenticate");
const clearButton = $("clear-key");
const question = $("question");
const submitButton = $("submit-question");
const feedback = $("request-feedback");

function authHeaders() {
  return apiKey ? { "Authorization": `Bearer ${apiKey}` } : {};
}

async function apiFetch(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 50000);
  try {
    const contentHeaders = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
    const response = await fetch(path, {
      ...options,
      headers: { ...contentHeaders, ...authHeaders(), ...(options.headers || {}) },
      signal: controller.signal,
    });
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.message || "Request failed");
      error.code = body.code || `HTTP_${response.status}`;
      throw error;
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

async function checkHealth() {
  const status = $("connection-status");
  try {
    const response = await fetch("/health/ready");
    const body = await response.json();
    $("provider-mode").textContent = `Provider · ${body.provider || "unavailable"}`;
    status.textContent = response.ok ? `Ready · ${body.backend}` : "Not ready";
    status.className = `status-dot ${response.ok ? "online" : "offline"}`;
  } catch (_) {
    status.textContent = "API unavailable";
    status.className = "status-dot offline";
  }
}

authButton.addEventListener("click", async () => {
  const candidate = $("api-key").value;
  if (!candidate) return;
  apiKey = candidate;
  $("api-key").value = "";
  try {
    const session = await apiFetch("/api/v1/session");
    $("session-status").textContent = `${session.principal_id} · ${session.tenant_id}`;
    $("auth-feedback").textContent = "Authenticated for this page session.";
    question.disabled = false;
    submitButton.disabled = false;
    $("investigation-mode").disabled = false;
    $("domain-pack-id").disabled = false;
    clearButton.disabled = false;
    $("company-data").classList.remove("hidden");
    $("domain-management").classList.remove("hidden");
    if (session.permissions.includes("job:read") || session.permissions.includes("operations:read")) {
      $("operations").classList.remove("hidden");
      await loadOperations();
    }
    await Promise.allSettled([loadCompanyData(), loadPilotStatus(), loadOlistStatus(), loadDomains()]);
    question.focus();
  } catch (error) {
    apiKey = null;
    $("session-status").textContent = "Not authenticated";
    $("auth-feedback").textContent = `${error.code}: ${error.message}`;
  }
});

clearButton.addEventListener("click", () => {
  apiKey = null;
  question.value = "";
  question.disabled = true;
  submitButton.disabled = true;
  $("investigation-mode").disabled = true;
  $("domain-pack-id").disabled = true;
  clearButton.disabled = true;
  $("session-status").textContent = "Not authenticated";
  $("auth-feedback").textContent = "Credential cleared from page memory.";
  $("results").classList.add("hidden");
  $("company-data").classList.add("hidden");
  $("domain-management").classList.add("hidden");
  $("operations").classList.add("hidden");
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!question.disabled) {
      question.value = button.dataset.question;
      question.focus();
    }
  });
});

$("investigation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = question.value.trim();
  if (!text || !apiKey) return;
  submitButton.disabled = true;
  feedback.className = "request-feedback loader";
  feedback.textContent = "Running the authorized evidence investigation…";
  try {
    const mode = $("investigation-mode").value;
    const result = await apiFetch("/api/v1/investigations", {
      method: "POST", body: JSON.stringify({
        question: text, mode, domain_pack_id: mode === "domain_pomdp" ? $("domain-pack-id").value.trim() : null,
      }),
    });
    if (result.mode === "DOCUMENT_LOOKUP") renderLookup(result); else renderResult(result);
    feedback.className = "request-feedback";
    feedback.textContent = `Completed · correlation ${result.correlation_id}`;
  } catch (error) {
    feedback.className = "request-feedback error";
    feedback.textContent = `${error.code || "ERROR"}: ${error.message}`;
  } finally {
    submitButton.disabled = false;
  }
});

function renderLookup(result) {
  $("results").classList.add("hidden");
  const lines = result.records.map((record) => {
    const sourceCount = record.sources.length;
    return `${record.relation_type}: ${record.attributes.expected_date || "?"} → ${record.attributes.actual_date || "?"} (${sourceCount} source${sourceCount === 1 ? "" : "s"})`;
  });
  feedback.textContent = lines.length ? `${result.purchase_order} · ${lines.join("; ")}` : `${result.purchase_order} · no active approved evidence`;
}

let validatedDomain = null;

async function loadDomains() {
  try {
    const domains = await apiFetch("/api/v1/domains");
    const registry = $("domain-registry"); registry.replaceChildren();
    const selector = $("domain-selector"); selector.replaceChildren();
    domains.forEach((domain) => {
      const row = document.createElement("div"); row.className = "data-row";
      const label = document.createElement("span");
      label.textContent = `${domain.name} · ${domain.domain_id} / ${domain.model_version} · ${domain.investigation_mode} · ${domain.status}`;
      row.append(label);
      const actions = domain.status === "VALIDATED" ? ["SUBMIT"]
        : domain.status === "REVIEW_PENDING" ? ["APPROVE", "REJECT"]
        : domain.status === "APPROVED" ? ["ACTIVATE"]
        : domain.status === "ACTIVE" ? ["REVALIDATE", "RETIRE"] : [];
      actions.forEach((action) => {
        const button = document.createElement("button"); button.type = "button"; button.textContent = action;
        button.addEventListener("click", () => domainLifecycle(domain.domain_id, domain.model_version, action));
        row.append(button);
      });
      registry.append(row);
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `Details · ${domain.domain_id} / ${domain.model_version}`;
      const configuration = document.createElement("pre");
      configuration.textContent = JSON.stringify(domain, null, 2);
      details.append(summary, configuration);
      registry.append(details);
      if (["APPROVED", "ACTIVE"].includes(domain.status)) {
        const option = document.createElement("option");
        option.value = JSON.stringify({id: domain.domain_id, version: domain.model_version});
        option.textContent = `${domain.name} · ${domain.model_version}${domain.evaluation_status === "SYNTHETIC_ENGINEERING_ONLY" ? " · synthetic" : ""}`;
        selector.append(option);
      }
    });
    if (!domains.length) renderCompanyList("domain-registry", ["No tenant-scoped domain versions"]);
  } catch (error) { $("domain-feedback").textContent = `${error.code}: domain registry unavailable.`; }
}

async function domainLifecycle(domainId, version, action) {
  try {
    await apiFetch(`/api/v1/domains/${encodeURIComponent(domainId)}/${encodeURIComponent(version)}/lifecycle`, {
      method: "POST", body: JSON.stringify({action}) });
    $("domain-feedback").textContent = `${domainId} ${version}: ${action.toLowerCase()} completed.`;
    await loadDomains();
  } catch (error) { $("domain-feedback").textContent = `${error.code}: ${error.message}`; }
}

$("refresh-domains").addEventListener("click", loadDomains);
$("validate-domain").addEventListener("click", async () => {
  validatedDomain = null; $("save-domain").disabled = true;
  try {
    const draft = JSON.parse($("domain-json").value);
    const result = await apiFetch("/api/v1/domains/validate", {method:"POST", body:JSON.stringify(draft)});
    validatedDomain = result.pack; $("save-domain").disabled = false;
    $("domain-validation").textContent = `VALID · immutable ID ${result.immutable_version_id}\n${result.findings.join("\n")}`;
  } catch (error) { $("domain-validation").textContent = `${error.code || "INVALID_JSON"}: ${error.message}`; }
});
$("save-domain").addEventListener("click", async () => {
  if (!validatedDomain) return;
  try {
    await apiFetch("/api/v1/domains", {method:"POST", body:JSON.stringify(validatedDomain)});
    $("domain-feedback").textContent = "Validated domain draft saved for this tenant.";
    await loadDomains();
  } catch (error) { $("domain-feedback").textContent = `${error.code}: ${error.message}`; }
});
$("run-domain").addEventListener("click", async () => {
  try {
    const selected = JSON.parse($("domain-selector").value);
    const result = await apiFetch(`/api/v1/domains/${encodeURIComponent(selected.id)}/investigate`, {
      method:"POST", body:JSON.stringify({question:$("domain-question").value, version:selected.version})});
    $("domain-result").textContent = JSON.stringify(result, null, 2);
  } catch (error) { $("domain-result").textContent = `${error.code || "ERROR"}: ${error.message}`; }
});

async function loadCompanyData() {
  try {
    const [documents, candidates] = await Promise.all([
      apiFetch("/api/v1/company-data/documents"), apiFetch("/api/v1/company-data/candidates")]);
    renderCompanyList("company-documents", documents.map((document) =>
      `${document.source_name} · v${document.version} · ${document.status}`));
    const target = $("review-candidates"); target.replaceChildren();
    candidates.forEach((candidate) => {
      const row = document.createElement("div"); row.className = "data-row";
      const text = document.createElement("span");
      text.textContent = `${candidate.subject_id} · ${candidate.relation_type} · ${candidate.status}`;
      row.append(text);
      if (candidate.status === "NEEDS_REVIEW") {
        const approve = document.createElement("button"); approve.type = "button"; approve.textContent = "Approve";
        approve.addEventListener("click", () => reviewCandidate(candidate.candidate_id, "APPROVE"));
        const reject = document.createElement("button"); reject.type = "button"; reject.textContent = "Reject";
        reject.addEventListener("click", () => reviewCandidate(candidate.candidate_id, "REJECT"));
        row.append(approve, reject);
      }
      target.append(row);
    });
    if (!candidates.length) renderCompanyList("review-candidates", ["No extracted candidates"]);
  } catch (error) {
    $("company-feedback").textContent = `${error.code}: company-data access is unavailable for this role.`;
  }
}

async function loadPilotStatus() {
  try {
    const status = await apiFetch("/api/v1/pilot/status");
    $("real-validation-status").textContent = `Real-world validation · ${status.real_world_validation_status}`;
    const target = $("calibration-models"); target.replaceChildren();
    status.model_versions.forEach((model) => {
      const row = document.createElement("div"); row.className = "data-row";
      const metadata = model.calibration;
      const label = document.createElement("span");
      label.textContent = `${model.domain_id} / ${model.model_version} · ${model.status} · ${metadata ? metadata.status : model.parameter_source}`;
      row.append(label);
      if (model.status === "PROVISIONAL") {
        for (const action of ["APPROVE", "REJECT"]) {
          const button = document.createElement("button"); button.type = "button"; button.textContent = action;
          button.addEventListener("click", () => reviewModel(model.domain_id, model.model_version, action));
          row.append(button);
        }
      }
      target.append(row);
    });
    if (!status.model_versions.length) renderCompanyList("calibration-models", ["No model versions available"]);
  } catch (error) {
    $("real-validation-status").textContent = "Evaluation access unavailable";
  }
}

async function loadOlistStatus() {
  try {
    const status = await apiFetch("/api/v1/olist/status");
    $("olist-status").textContent = status.imported_orders + " orders · " + status.approved_review_records
      + " reviews · model " + status.predictive_model_status;
    $("olist-dataset-detail").textContent = `Dataset ${status.dataset_version} · ${status.eligibility.eligible} prediction-eligible · ${status.eligibility.missing_or_invalid_customer_delivery_date} missing delivery outcomes · evaluation ${status.evaluation_status}.`;
  } catch (_) { $("olist-status").textContent = "Olist not configured"; }
}

$("olist-investigate").addEventListener("click", async () => {
  const orderId = $("olist-order-id").value.trim(); if (!orderId || !apiKey) return;
  $("olist-source").disabled = true;
  $("olist-source-result").textContent = "";
  try {
    const mode = $("olist-mode").value;
    const result = mode === "historical"
      ? await apiFetch("/api/v1/olist/orders/" + encodeURIComponent(orderId))
      : await apiFetch("/api/v1/olist/predictions", {method:"POST",body:JSON.stringify({order_id:orderId,decision_time:mode})});
    if (result.mode === "HISTORICAL_FACTUAL") {
      $("olist-result-kind").textContent = "HISTORICAL FACT · approved evidence-backed record";
      $("olist-result").textContent = [
        `Order: ${result.order_id}`,
        `Estimated delivery: ${result.estimated_delivery_date || "not recorded"}`,
        `Actual delivery: ${result.actual_delivery_date || "not recorded"}`,
        `Recorded outcome: ${result.outcome}`,
        `Source references: ${result.sources.length}`,
        "Causal attribution: not claimed",
      ].join("\n");
    } else {
      $("olist-result-kind").textContent = `PROSPECTIVE RISK · ${result.status} · ${result.decision}`;
      $("olist-result").textContent = [
        `Prediction timestamp: ${result.prediction_timestamp || "unavailable"}`,
        `Probability late: ${result.probability_late === null ? "not issued" : percent(result.probability_late)}`,
        `Model version: ${result.model_version || "no approved model"}`,
        `Calibration: ${result.calibration_status}`,
        `Outcome hidden from inference: ${result.outcome_hidden ? "yes" : "no"}`,
        `Allowed pre-outcome evidence: ${Object.keys(result.features).join(", ") || "none"}`,
        `Investigation actions: ${result.investigation_actions.length ? result.investigation_actions.join(", ") : "none supported"}`,
        `Reason: ${result.reason}`,
      ].join("\n");
    }
    $("olist-source").disabled = mode !== "historical" || result.mode !== "HISTORICAL_FACTUAL";
  } catch (error) { $("olist-result").textContent = error.code + ": " + error.message; }
});

for (const control of [$("olist-order-id"), $("olist-mode")]) {
  control.addEventListener("input", () => {
    $("olist-source").disabled = true;
    $("olist-result-kind").textContent = "";
    $("olist-source-result").textContent = "";
  });
  control.addEventListener("change", () => {
    $("olist-source").disabled = true;
    $("olist-result-kind").textContent = "";
    $("olist-source-result").textContent = "";
  });
}

$("olist-source").addEventListener("click", async () => {
  const orderId = $("olist-order-id").value.trim();
  if (!orderId || !apiKey || $("olist-source").disabled) return;
  try {
    const source = await apiFetch("/api/v1/olist/orders/" + encodeURIComponent(orderId) + "/source");
    $("olist-source-result").textContent = JSON.stringify(source, null, 2);
  } catch (error) { $("olist-source-result").textContent = error.code + ": " + error.message; }
});

async function reviewModel(domainId, version, action) {
  try {
    await apiFetch(`/api/v1/pilot/models/${encodeURIComponent(domainId)}/${encodeURIComponent(version)}/review`, {
      method: "POST", body: JSON.stringify({ action }) });
    $("company-feedback").textContent = `Model ${version}: ${action.toLowerCase()} completed.`;
    await loadPilotStatus();
  } catch (error) { $("company-feedback").textContent = `${error.code}: ${error.message}`; }
}

function renderCompanyList(id, lines) {
  const target = $(id); target.replaceChildren();
  lines.forEach((line) => { const row = document.createElement("div"); row.className = "data-row"; row.textContent = line; target.append(row); });
}

async function reviewCandidate(candidateId, action) {
  try {
    await apiFetch(`/api/v1/company-data/candidates/${encodeURIComponent(candidateId)}/review`, {
      method: "POST", body: JSON.stringify({ action }) });
    $("company-feedback").textContent = `${action.toLowerCase()} completed.`;
    await loadCompanyData();
  } catch (error) { $("company-feedback").textContent = `${error.code}: ${error.message}`; }
}

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = $("company-file").files[0]; if (!selected) return;
  const body = new FormData(); body.append("dataset_id", $("dataset-id").value.trim());
  if ($("source-group").value.trim()) body.append("source_group", $("source-group").value.trim());
  body.append("file", selected);
  try {
    body.append("idempotency_key", `upload-${selected.name}-${selected.size}-${selected.lastModified}`);
    const result = await apiFetch("/api/v1/company-data/uploads/jobs", { method: "POST", body });
    $("company-feedback").textContent = `${selected.name} accepted as job ${result.job_id}; state ${result.state}.`;
    $("company-file").value = "";
    if (!$("operations").classList.contains("hidden")) await loadOperations();
  } catch (error) { $("company-feedback").textContent = `${error.code}: ${error.message}`; }
});

async function cancelJob(jobId) {
  try {
    const job = await apiFetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
    $("operations-feedback").textContent = `Job ${job.job_id}: ${job.state}.`;
    await loadOperations();
  } catch (error) { $("operations-feedback").textContent = `${error.code}: ${error.message}`; }
}

async function loadOperations() {
  try {
    const [jobs, health] = await Promise.all([
      apiFetch("/api/v1/jobs?limit=50"), apiFetch("/api/v1/operations/health")]);
    $("operations-health").textContent = [
      `Operational DB: ${health.operational_database}`,
      `Worker: ${health.worker}`,
      `Queue: ${health.queue}`,
      `Neo4j: ${health.neo4j}`,
      `Documents: ${health.document_storage}`,
    ].join(" · ");
    const target = $("operations-jobs"); target.replaceChildren();
    jobs.forEach((job) => {
      const row = document.createElement("div"); row.className = "data-row";
      const text = document.createElement("span");
      const phase = job.progress && job.progress.phase ? ` · ${job.progress.phase}` : "";
      const error = job.error_code ? ` · ${job.error_code}` : "";
      text.textContent = `${job.operation_type} · ${job.state}${phase}${error} · attempts ${job.attempt_count}`;
      row.append(text);
      if (["QUEUED", "RUNNING", "RETRY_WAIT"].includes(job.state)) {
        const cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "Cancel";
        cancel.addEventListener("click", () => cancelJob(job.job_id)); row.append(cancel);
      }
      target.append(row);
    });
    if (!jobs.length) renderCompanyList("operations-jobs", ["No durable jobs for this tenant"]);
  } catch (error) {
    $("operations-feedback").textContent = `${error.code}: operations unavailable for this role.`;
  }
}

$("refresh-operations").addEventListener("click", loadOperations);

$("configure-dataset").addEventListener("click", async () => {
  const datasetId = $("dataset-id").value.trim(); if (!datasetId) return;
  try {
    await apiFetch("/api/v1/company-data/datasets", { method: "POST", body: JSON.stringify({
      dataset_id: datasetId, name: "Delivery records",
      field_mapping: { purchase_order: "po", supplier: "supplier", expected_date: "expected", actual_date: "actual" },
      date_format: "%Y-%m-%d", timezone: "UTC", review_required: true,
      allowed_source_types: ["csv", "xlsx", "pdf", "docx", "txt"],
    })});
    $("company-feedback").textContent = `Dataset ${datasetId} is configured for explicit delivery fields.`;
  } catch (error) { $("company-feedback").textContent = `${error.code}: ${error.message}`; }
});

function renderResult(result) {
  $("results").classList.remove("hidden");
  const badge = $("decision-badge");
  const state = result.decision || result.status;
  badge.textContent = state;
  badge.className = `decision-badge ${state === "ANSWER" ? "answer" : state === "ABSTAIN" ? "abstain" : "error"}`;
  $("decision-title").textContent = result.decision === "ANSWER"
    ? `Evidence supports ${humanize(result.selected_hypothesis)}`
    : result.decision === "ABSTAIN" ? "Evidence does not justify an answer" : humanize(result.status);
  $("explanation").textContent = result.explanation;
  $("scenario").textContent = result.scenario_id || "Not resolved";
  $("provenance").textContent = result.provenance_status || "Not available";
  $("hypothesis").textContent = result.selected_hypothesis || "None selected";
  $("cost").textContent = `${Number(result.investigation_cost).toFixed(3)} utility-cost units`;
  const limitation = $("limitation");
  limitation.textContent = result.limitation ? `Limitation: ${result.limitation}` : "";
  limitation.classList.toggle("hidden", !result.limitation);
  renderBeliefs(result.belief_changes);
  renderReferences("supporting-evidence", result.supporting_evidence_ids, "support");
  renderReferences("contradicting-evidence", result.contradicting_evidence_ids, "contradict");
  renderReferences("documents", result.document_ids, "document");
  renderTimeline(result.timeline);
  renderTechnical(result);
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderBeliefs(changes) {
  const chart = $("belief-chart");
  chart.replaceChildren();
  changes.forEach((change) => {
    const row = document.createElement("div"); row.className = "belief-row";
    const header = document.createElement("header");
    const name = document.createElement("span"); name.textContent = humanize(change.hypothesis);
    const values = document.createElement("strong");
    values.textContent = `${percent(change.initial)} → ${percent(change.final)}`;
    header.append(name, values);
    const track = document.createElement("div"); track.className = "bar-track";
    track.setAttribute("aria-label", `${name.textContent}: ${values.textContent}`);
    const prior = document.createElement("div"); prior.className = "bar-prior"; prior.style.width = `${change.initial * 100}%`;
    const final = document.createElement("div"); final.className = "bar-final"; final.style.width = `${change.final * 100}%`;
    track.append(prior, final); row.append(header, track); chart.append(row);
  });
}

function renderReferences(targetId, ids, kind) {
  const target = $(targetId); target.replaceChildren();
  if (!ids.length) { const empty = document.createElement("span"); empty.textContent = "None"; target.append(empty); return; }
  ids.forEach((id) => {
    if (kind === "document") { const label = document.createElement("span"); label.textContent = id; target.append(label); return; }
    const button = document.createElement("button"); button.type = "button"; button.textContent = id;
    button.setAttribute("aria-label", `Open ${kind} evidence ${id}`);
    button.addEventListener("click", () => showEvidence(id)); target.append(button);
  });
}

function renderTimeline(steps) {
  const target = $("timeline"); target.replaceChildren();
  $("step-count").textContent = `${steps.length} ${steps.length === 1 ? "step" : "steps"}`;
  if (!steps.length) { const empty = document.createElement("p"); empty.textContent = "No mathematical workflow ran for this request."; target.append(empty); return; }
  steps.forEach((step) => {
    const item = document.createElement("section"); item.className = "timeline-step";
    const index = document.createElement("div"); index.className = "timeline-index"; index.textContent = step.step_number;
    const content = document.createElement("div"); content.className = "timeline-content";
    const title = document.createElement("h3"); title.textContent = humanize(step.action);
    const detail = document.createElement("p");
    detail.textContent = [step.tool_status, step.observation, `Evidence: ${step.evidence_support}`, `Cost: ${Number(step.investigation_cost).toFixed(3)}`].filter(Boolean).join(" · ");
    const delta = document.createElement("div"); delta.className = "belief-delta";
    Object.keys(step.belief_after).sort().forEach((key) => {
      const chip = document.createElement("span");
      chip.textContent = `${humanize(key)} ${percent(step.belief_before[key] || 0)} → ${percent(step.belief_after[key])}`;
      delta.append(chip);
    });
    content.append(title, detail, delta); item.append(index, content); target.append(item);
  });
}

function renderTechnical(result) {
  const values = {
    "Investigation ID": result.investigation_id, "Correlation ID": result.correlation_id,
    "Provider": `${result.provider} / ${result.model}`, "Explanation fallback": result.explanation_fallback_used ? "Yes" : "No",
    "Grounding valid": String(result.grounding_valid), "Planning runtime": `${result.timings.planning_ms.toFixed(3)} ms`,
    "Graph runtime": `${result.timings.graph_ms.toFixed(3)} ms`, "Model runtime": `${result.timings.model_ms.toFixed(3)} ms`,
    "Request runtime": `${result.timings.request_ms.toFixed(3)} ms`,
  };
  const target = $("technical-details"); target.replaceChildren();
  Object.entries(values).forEach(([label, value]) => {
    const wrapper = document.createElement("div"); const dt = document.createElement("dt"); const dd = document.createElement("dd");
    dt.textContent = label; dd.textContent = value; wrapper.append(dt, dd); target.append(wrapper);
  });
}

async function showEvidence(id) {
  try {
    const record = await apiFetch(`/api/v1/evidence/${encodeURIComponent(id)}`);
    $("dialog-title").textContent = record.evidence_id;
    const dl = document.createElement("dl");
    const fields = { "Content": record.content, "Document": record.document_title, "Document ID": record.document_id,
      "Source type": record.source_type, "Location": record.chunk_ref, "Classification": record.classification,
      "Extraction confidence": percent(record.extraction_confidence), "Observed": record.observed_at };
    Object.entries(fields).forEach(([label, value]) => {
      const dt = document.createElement("dt"); dt.textContent = label; const dd = document.createElement("dd"); dd.textContent = value; dl.append(dt, dd);
    });
    $("dialog-content").replaceChildren(dl); $("evidence-dialog").showModal();
  } catch (error) { feedback.className = "request-feedback error"; feedback.textContent = `${error.code}: ${error.message}`; }
}

$("close-dialog").addEventListener("click", () => $("evidence-dialog").close());
function percent(value) { return `${(Number(value) * 100).toFixed(1)}%`; }
function humanize(value) { return value ? String(value).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "Not available"; }
checkHealth();
