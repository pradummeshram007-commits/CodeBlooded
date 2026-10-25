/**
 * Centralized API client for THOR backend services.
 * Communicates with the FastAPI backend at /api and falls back gracefully
 * to pre-computed verified artifacts in /data/thor/ if the local server is offline.
 */

const API_BASE = '/api';

export async function fetchSummary() {
  try {
    const res = await fetch(`${API_BASE}/summary`);
    if (res.ok) return await res.json();
  } catch (err) {
    console.warn('API server unreachable, loading static summary fallback:', err);
  }
  // Fallback to static summary
  const res = await fetch('/data/thor/_run_summary.json');
  if (!res.ok) throw new Error('Could not load summary');
  return await res.json();
}

export async function fetchDocuments() {
  try {
    const res = await fetch(`${API_BASE}/documents`);
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) return data;
    }
  } catch (err) {
    console.warn('API server unreachable for documents list:', err);
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
    const res = await fetch(`${API_BASE}/documents/${docId}`);
    if (res.ok) return await res.json();
  } catch (err) {
    console.warn(`API server unreachable for doc ${docId}, checking static data:`, err);
  }

  // Fallback to static extraction json
  const res = await fetch(`/data/thor/${docId}.json`);
  if (!res.ok) throw new Error(`Document ${docId} not found`);
  return await res.json();
}

export async function uploadContractFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Upload failed with HTTP ${res.status}`);
  }

  return await res.json();
}

export async function reextractClause(docId, clauseId, question) {
  const res = await fetch(`${API_BASE}/reextract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      doc_id: docId,
      clause_id: clauseId,
      question: question || '',
    }),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Re-extraction failed: HTTP ${res.status}`);
  }

  return await res.json();
}
