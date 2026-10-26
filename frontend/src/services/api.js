/**
 * Centralized API client for THOR backend services.
 * Communicates with the FastAPI backend at /api and falls back gracefully
 * to pre-computed verified artifacts in /data/thor/ if the local server is offline.
 */

const API_BASE = '/api';

/**
 * Safe JSON fetch — returns null if the response is not valid JSON
 * (e.g. the proxy returned an HTML error page from Vite).
 */
async function safeFetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) return null;

  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    // Proxy returned HTML (e.g. Vite SPA fallback) — treat as unreachable
    return null;
  }

  return res.json();
}

export async function fetchSummary() {
  try {
    const data = await safeFetchJson(`${API_BASE}/summary`);
    if (data) return data;
  } catch (err) {
    console.warn('API server unreachable, loading static summary fallback:', err.message);
  }
  // Fallback to static summary
  const res = await fetch('/data/thor/_run_summary.json');
  if (!res.ok) throw new Error('Could not load summary');
  return await res.json();
}

export async function fetchDocuments() {
  try {
    const data = await safeFetchJson(`${API_BASE}/documents`);
    if (Array.isArray(data) && data.length > 0) return data;
  } catch (err) {
    console.warn('API server unreachable for documents list:', err.message);
  }

  // Fallback: load summary to get document list
  const summary = await fetchSummary();
  return (summary.documents || []).map((d) => ({
    doc_id: d.doc_id,
    title: `Contract Document ${d.doc_id}`,
    status: d.status,
    clause_count: d.clauses || 0,
    coverage: d.coverage || 100,
  }));
}

export async function fetchDocumentReport(docId) {
  try {
    const data = await safeFetchJson(`${API_BASE}/documents/${docId}`);
    if (data) return data;
  } catch (err) {
    console.warn(`API server unreachable for doc ${docId}, checking static data:`, err.message);
  }

  // Fallback to static extraction json
  const res = await fetch(`/data/thor/${docId}.json`);
  if (!res.ok) throw new Error(`Document ${docId} not found`);
  return await res.json();
}

export async function uploadContractFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  let res;
  try {
    res = await fetch(`${API_BASE}/upload`, {
      method: 'POST',
      body: formData,
    });
  } catch (err) {
    throw new Error(
      'THOR backend server is not running. Start it with: uvicorn odin.api:app --port 8000'
    );
  }

  // Check if the response is actually JSON (not Vite's HTML fallback)
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    throw new Error(
      'THOR backend server is not reachable. The upload requires the API server. ' +
      'Start it with: uvicorn odin.api:app --port 8000'
    );
  }

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Upload failed with HTTP ${res.status}`);
  }

  return await res.json();
}

export async function reextractClause(docId, clauseId, question) {
  let res;
  try {
    res = await fetch(`${API_BASE}/reextract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doc_id: docId,
        clause_id: clauseId,
        question: question || '',
      }),
    });
  } catch (err) {
    throw new Error(
      'THOR backend server is not running. Re-extraction requires the API server. ' +
      'Start it with: uvicorn odin.api:app --port 8000'
    );
  }

  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    throw new Error(
      'THOR backend server is not reachable. Re-extraction requires the API server.'
    );
  }

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Re-extraction failed: HTTP ${res.status}`);
  }

  return await res.json();
}

// ========================================================
// NORNS — Timeline Intelligence API
// ========================================================

/** Fetch list of documents eligible for NORNS timeline processing. */
export async function fetchNornsDocuments() {
  try {
    const data = await safeFetchJson(`${API_BASE}/norns/documents`);
    if (Array.isArray(data)) return data;
  } catch (err) {
    console.warn('NORNS documents unreachable:', err.message);
  }
  // Fallback: use THOR documents list
  const docs = await fetchDocuments().catch(() => []);
  return docs.map((d) => ({
    doc_id: d.doc_id,
    title: d.title || `Contract ${d.doc_id}`,
    status: d.status,
    coverage: d.coverage || 0,
    extraction_count: d.extraction_count || 0,
    clause_count: d.clause_count || 0,
  }));
}

/** Compute NORNS timeline for a given date and optional doc filter. */
export async function fetchNornsTimeline(asOf, docId) {
  const params = new URLSearchParams();
  if (asOf) params.set('as_of', asOf);
  if (docId) params.set('doc_id', docId);

  try {
    const data = await safeFetchJson(`${API_BASE}/norns/timeline?${params}`);
    if (data) return data;
  } catch (err) {
    console.warn('NORNS timeline API unreachable:', err.message);
  }
  // Return empty scaffold so UI can render gracefully
  return {
    as_of: asOf || new Date().toISOString().split('T')[0],
    contracts: [],
    status_counts: {},
    overdue: [],
    due_now: [],
    next_deadlines: [],
    renewal_deadlines: {},
    penalty_triggers: [],
    all_instances: [],
    flags: ['Backend not connected. Start: uvicorn odin.api:app --port 8000'],
  };
}

/** Fetch paginated obligation instances with optional status filter. */
export async function fetchNornsObligations(asOf, docId, statusFilter, limit = 50, offset = 0) {
  const params = new URLSearchParams();
  if (asOf) params.set('as_of', asOf);
  if (docId) params.set('doc_id', docId);
  if (statusFilter && statusFilter !== 'all') params.set('status_filter', statusFilter);
  params.set('limit', String(limit));
  params.set('offset', String(offset));

  try {
    const data = await safeFetchJson(`${API_BASE}/norns/obligations?${params}`);
    if (data) return data;
  } catch (err) {
    console.warn('NORNS obligations API unreachable:', err.message);
  }
  return { total: 0, offset, limit, obligations: [] };
}

/** Compute worst-case financial exposure projection. */
export async function fetchNornsWorstCase(asOf, docId, projectionMonths = 12) {
  const params = new URLSearchParams();
  if (asOf) params.set('as_of', asOf);
  if (docId) params.set('doc_id', docId);
  params.set('projection_months', String(projectionMonths));

  try {
    const data = await safeFetchJson(`${API_BASE}/norns/worst-case?${params}`);
    if (data) return data;
  } catch (err) {
    console.warn('NORNS worst-case API unreachable:', err.message);
  }
  return {
    as_of: asOf || new Date().toISOString().split('T')[0],
    worst_case_total: '0.00',
    on_time_total: '0.00',
    avoidable_exposure: '0.00',
    accruals: [],
    unquantified: [],
    deadlines: [],
    flags: ['Worst-case engine requires backend connection.'],
  };
}

// ========================================================
// DASHBOARD — Command Center API
// ========================================================

/** Fetch aggregated dashboard intelligence metrics. */
export async function fetchDashboard(asOf) {
  const params = new URLSearchParams();
  if (asOf) params.set('as_of', asOf);

  try {
    const data = await safeFetchJson(`${API_BASE}/dashboard?${params}`);
    if (data) return data;
  } catch (err) {
    console.warn('Dashboard API unreachable:', err.message);
  }
  return null;
}

// ========================================================
// LOKI & HEIMDALL — shared request helper
// ========================================================

const BACKEND_DOWN =
  'ODIN API backend unreachable. Start it with: python backend/run.py (or uvicorn odin.api:app --port 8000)';

/**
 * JSON request that throws an Error carrying the backend's `detail` message,
 * so the pages can show exactly why a run was refused (no LLM key, drop not released, ...).
 */
async function requestJson(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    throw new Error(BACKEND_DOWN);
  }
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    throw new Error(BACKEND_DOWN);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || {});
    throw new Error(detail || `Request failed with HTTP ${res.status}`);
  }
  return data;
}

function postJson(url, body) {
  return requestJson(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// ========================================================
// LOKI — Adversarial Review API
// ========================================================

/** Reviewable documents, last review per document, clock checkpoints, LLM readiness and the fixed scales. */
export function fetchLokiDocuments() {
  return requestJson(`${API_BASE}/loki/documents`);
}

/** Loki's stored findings for one document; asOf defaults to the latest date reviewed. */
export function fetchLokiFindings(docId, asOf) {
  const params = new URLSearchParams({ doc_id: docId });
  if (asOf) params.set('as_of', asOf);
  return requestJson(`${API_BASE}/loki/findings?${params}`);
}

/** Run Loki on the given documents as of a date (one LLM call per document). */
export function runLokiReview(docIds, asOf) {
  return postJson(`${API_BASE}/loki/review`, { doc_ids: docIds, as_of: asOf });
}

// ========================================================
// HEIMDALL — Event Monitoring & Task Board API
// ========================================================

/** Event drops with their release dates, stored runs, checkpoints and LLM readiness. */
export function fetchHeimdallOverview() {
  return requestJson(`${API_BASE}/heimdall/overview`);
}

/** Exposure, alerts, events and the task board for one clock date (defaults to the latest run). */
export function fetchHeimdallBoard(asOf) {
  const params = new URLSearchParams();
  if (asOf) params.set('as_of', asOf);
  return requestJson(`${API_BASE}/heimdall/board?${params}`);
}

/** Process one released drop on a clock date; useLlm sends what code cannot map to the LLM. */
export function runHeimdallDrop(drop, asOf, useLlm) {
  return postJson(`${API_BASE}/heimdall/run`, { drop, as_of: asOf, use_llm: useLlm });
}

/** Move a task-board card (Not Complete / In Progress / Completed). */
export function setHeimdallTaskStatus(asOf, taskId, status) {
  return postJson(`${API_BASE}/heimdall/tasks/status`, { as_of: asOf, task_id: taskId, status });
}

/** Rebuild a date's alerts and tasks from the stored events (no LLM). */
export function reassessHeimdall(asOf) {
  return postJson(`${API_BASE}/heimdall/reassess`, { as_of: asOf });
}

// ========================================================
// ODIN — Orchestrator (THOR -> NORNS -> LOKI -> HEIMDALL)
// ========================================================

/** Workstreams, followed contracts, each agent's LLM readiness, budgets and the run queue. */
export function fetchOdinOverview() {
  return requestJson(`${API_BASE}/odin/overview`);
}

/** Pipeline runs, newest first (optionally for one document). */
export function fetchOdinRuns(docId, limit = 20) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (docId) params.set('doc_id', docId);
  return requestJson(`${API_BASE}/odin/runs?${params}`);
}

/** One pipeline run with every stage's status, numbers and reason. */
export function fetchOdinRun(runId) {
  return requestJson(`${API_BASE}/odin/runs/${encodeURIComponent(runId)}`);
}

/** Queue the pipeline for a stored document. */
export function runOdinPipeline(docId, { asOf, forceThor = false, runLoki, heimdallUseLlm } = {}) {
  const body = { doc_id: docId, force_thor: forceThor };
  if (asOf) body.as_of = asOf;
  if (runLoki !== undefined) body.run_loki = runLoki;
  if (heimdallUseLlm !== undefined) body.heimdall_use_llm = heimdallUseLlm;
  return postJson(`${API_BASE}/odin/run`, body);
}

/** Dispatch a certified legal notice with authoritative clause citations. */
export async function sendCertifiedNotice(payload) {
  let res;
  try {
    res = await fetch(`${API_BASE}/notices/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    throw new Error('ODIN API backend unreachable. Ensure server is running on port 8000.');
  }

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Notice dispatch failed with HTTP ${res.status}`);
  }

  return await res.json();
}

