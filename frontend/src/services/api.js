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
