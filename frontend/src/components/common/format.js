// Shared formatting and the fixed severity palette for the LOKI and HEIMDALL workspaces.

export function fmtDate(d) {
  if (!d) return '—';
  try {
    return new Date(String(d).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return d;
  }
}

export function fmtCurrency(v, maximumFractionDigits = 2) {
  if (v === null || v === undefined || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return String(v);
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits }).format(n);
}

/** Verbatim quote with the contract's hard line wraps and indentation folded into single spaces. */
export function flatten(text) {
  return (text || '').replace(/\s+/g, ' ').trim();
}

// critical > high > medium > low, as in odin/agents/loki.py and odin/agents/heimdall.py (SEVERITY_SCALE).
export const SEVERITY = {
  critical: { label: 'Critical', bg: '#FBEBEB', text: '#C83D3D', bar: '#C83D3D' },
  high: { label: 'High', bg: '#F4ECDB', text: '#A8641A', bar: '#C78A32' },
  medium: { label: 'Medium', bg: '#F7F1E1', text: '#8C7340', bar: '#B79A59' },
  low: { label: 'Low', bg: '#EEF2E4', text: '#66734A', bar: '#A4B18A' },
  done: { label: 'Done', bg: '#EAF5EA', text: '#2E7D32', bar: '#2E7D32' },
};

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low'];
