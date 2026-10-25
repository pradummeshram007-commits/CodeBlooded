import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  AlertTriangle, ArrowUpRight, Calendar, ChevronDown, ChevronLeft, ChevronRight,
  Clock, FileText, Filter, Loader2, RefreshCw, Search, TrendingUp, X, Zap,
} from 'lucide-react';
import { fetchNornsDocuments, fetchNornsTimeline, fetchNornsObligations, fetchNornsWorstCase } from '../../services/api';

// ─── helpers ────────────────────────────────────────────────────────────────

function fmtDate(d) {
  if (!d) return '—';
  try { return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
  catch { return d; }
}

function daysFromNow(d, asOf) {
  if (!d) return null;
  const a = new Date(asOf + 'T00:00:00');
  const b = new Date(d + 'T00:00:00');
  return Math.round((b - a) / 86400000);
}

function fmtCurrency(v) {
  if (!v || v === 'None' || v === 'null') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return v;
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);
}

function statusColor(status) {
  switch (status) {
    case 'unpaid': case 'missed': return { bg: '#F7E8E4', text: '#C83D3D', border: 'rgba(200,61,61,0.4)', label: 'Overdue' };
    case 'partial': return { bg: '#FFF8E1', text: '#B76E00', border: 'rgba(183,110,0,0.3)', label: 'Partial' };
    case 'upcoming': return { bg: '#F5F1E6', text: '#303B28', border: '#DCDCCB', label: 'Upcoming' };
    case 'paid_on_time': return { bg: '#EAF5EA', text: '#2E7D32', border: 'rgba(46,125,50,0.3)', label: 'Paid' };
    case 'paid_late': return { bg: '#FFF8E1', text: '#B76E00', border: 'rgba(183,110,0,0.3)', label: 'Paid Late' };
    default: return { bg: '#F5F1E6', text: '#727665', border: '#DCDCCB', label: status || '—' };
  }
}

function kindIcon(kind) {
  switch (kind) {
    case 'payment': return '💳';
    case 'renewal': return '🔄';
    case 'compliance': return '✅';
    case 'penalty': return '⚠️';
    default: return '📋';
  }
}

const TABS = [
  { id: 'all', label: 'All Obligations' },
  { id: 'overdue', label: 'Past Due' },
  { id: 'upcoming', label: 'Upcoming' },
  { id: 'paid', label: 'Recorded' },
];

// ─── sub-components ─────────────────────────────────────────────────────────

function MetricCard({ label, value, sub, color, dot }) {
  const dotColors = { error: '#C83D3D', secondary: '#66734A', tertiary: '#527A54', outline: '#DCDCCB' };
  return (
    <div
      className="rounded border p-4 flex flex-col justify-between"
      style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: '#727665' }}>{label}</span>
        {dot && <span className="w-2 h-2 rounded-full" style={{ background: dotColors[dot] }} />}
      </div>
      <div>
        <div className="text-xl font-bold font-mono" style={{ color: color || '#303B28' }}>{value}</div>
        {sub && <div className="text-[11px] font-mono mt-0.5" style={{ color: '#727665' }}>{sub}</div>}
      </div>
    </div>
  );
}

function AlertCard({ item, asOf, onSelect, isSelected }) {
  const days = daysFromNow(item.due, asOf);
  const col = statusColor(item.status);
  const isOverdue = ['unpaid', 'missed', 'partial'].includes(item.status) && days !== null && days < 0;

  return (
    <button
      onClick={() => onSelect(item)}
      className="text-left rounded border p-3 flex flex-col justify-between gap-3 relative overflow-hidden transition-all w-full"
      style={{
        background: isOverdue ? 'rgba(247,232,228,0.6)' : '#FCFAF3',
        borderColor: isSelected ? col.border : (isOverdue ? 'rgba(200,61,61,0.4)' : '#DCDCCB'),
        boxShadow: isSelected ? `0 0 0 2px ${col.border}` : undefined,
      }}
    >
      <div
        className="absolute top-0 left-0 w-1 h-full"
        style={{ background: isOverdue ? '#C83D3D' : col.text }}
      />
      <div className="pl-2">
        <div className="flex items-center justify-between text-xs mb-1">
          <span
            className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase"
            style={{ background: col.bg, color: col.text }}
          >
            {col.label}
          </span>
          <span className="font-mono text-[10px] font-semibold" style={{ color: col.text }}>
            {days !== null ? (days < 0 ? `${Math.abs(days)}d late` : days === 0 ? 'Today' : `${days}d left`) : '—'}
          </span>
        </div>
        <h3 className="text-sm font-bold leading-tight mb-1" style={{ color: '#303B28' }}>{item.name}</h3>
        <p className="text-[11px]" style={{ color: '#727665' }}>{item.contract}</p>
        {item.amount && (
          <div className="mt-2 pt-2 border-t font-mono text-xs flex justify-between" style={{ borderColor: 'rgba(220,220,203,0.5)' }}>
            <span style={{ color: '#727665' }}>Amount:</span>
            <span className="font-bold" style={{ color: '#303B28' }}>{fmtCurrency(item.amount)} {item.currency || ''}</span>
          </div>
        )}
      </div>
    </button>
  );
}

function TimelineRail({ instances, asOf, onSelect }) {
  if (!instances.length) return (
    <div className="text-center py-8 font-mono text-xs" style={{ color: '#727665' }}>
      No obligation events loaded yet.
    </div>
  );

  const today = new Date(asOf + 'T00:00:00');
  const sorted = [...instances].filter(i => i.due).sort((a, b) => a.due.localeCompare(b.due));
  const minDate = new Date(sorted[0]?.due + 'T00:00:00');
  const maxDate = new Date(sorted[sorted.length - 1]?.due + 'T00:00:00');
  const range = Math.max((maxDate - minDate) / 86400000, 1);

  function pct(d) {
    const dt = new Date(d + 'T00:00:00');
    return Math.min(100, Math.max(2, ((dt - minDate) / 86400000 / range) * 96 + 2));
  }

  const todayPct = Math.min(100, Math.max(0, ((today - minDate) / 86400000 / range) * 96 + 2));
  const col = statusColor;

  return (
    <div className="overflow-x-auto pb-4" style={{ background: '#FAF6EC', borderRadius: 6, border: '1px solid #DCDCCB', padding: '24px 16px 48px' }}>
      <div className="relative" style={{ minWidth: 820, height: 80 }}>
        {/* Base line */}
        <div className="absolute left-0 right-0" style={{ top: 38, height: 2, background: 'rgba(220,220,203,0.7)' }} />
        {/* Today marker */}
        <div
          className="absolute flex flex-col items-center z-10"
          style={{ left: `${todayPct}%`, top: 0, bottom: 0, transform: 'translateX(-50%)' }}
        >
          <span
            className="font-mono text-[9px] font-bold px-1.5 py-0.5 rounded mb-1 whitespace-nowrap"
            style={{ background: '#303B28', color: '#fff' }}
          >
            TODAY
          </span>
          <div style={{ width: 2, flex: 1, background: '#303B28' }} />
          <div className="w-3 h-3 rounded-full" style={{ background: '#303B28', boxShadow: '0 0 0 4px rgba(48,59,40,0.15)' }} />
        </div>
        {/* Events */}
        {sorted.map((item, idx) => {
          const c = col(item.status);
          const isOverdue = ['unpaid', 'missed'].includes(item.status);
          const stagger = idx % 2 === 0 ? 0 : 50;
          return (
            <button
              key={item.key || idx}
              onClick={() => onSelect(item)}
              className="absolute flex flex-col items-center group cursor-pointer"
              style={{ left: `${pct(item.due)}%`, top: stagger, transform: 'translateX(-50%)' }}
            >
              <span className="font-mono text-[9px] font-semibold mb-1 whitespace-nowrap" style={{ color: c.text }}>
                {fmtDate(item.due)}
              </span>
              <div
                className="w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center text-white text-[8px] shadow-sm transition-transform group-hover:scale-125"
                style={{ background: c.text, borderColor: '#FCFAF3' }}
              >
                {isOverdue ? '!' : ''}
              </div>
              <div
                className="absolute top-9 w-36 p-1.5 rounded border text-center opacity-0 group-hover:opacity-100 transition-opacity z-20 pointer-events-none"
                style={{ background: '#FCFAF3', border: `1px solid ${c.border}`, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
              >
                <p className="font-mono text-[9px] font-bold leading-tight" style={{ color: c.text }}>{item.name}</p>
                <p className="text-[9px]" style={{ color: '#727665' }}>{item.contract}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ObligationRow({ item, asOf, isSelected, onSelect }) {
  const col = statusColor(item.status);
  const days = daysFromNow(item.due, asOf);

  return (
    <tr
      onClick={() => onSelect(item)}
      className="cursor-pointer transition-colors"
      style={{
        background: isSelected ? col.bg : undefined,
        borderLeft: isSelected ? `3px solid ${col.text}` : undefined,
      }}
      onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = 'rgba(245,241,230,0.6)'; }}
      onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = ''; }}
    >
      <td className="py-2.5 px-3 font-mono text-xs whitespace-nowrap" style={{ color: col.text }}>
        {fmtDate(item.due)}
        {days !== null && (
          <span className="block text-[9px]" style={{ color: '#727665' }}>
            {days < 0 ? `(${Math.abs(days)}d late)` : days === 0 ? '(Today)' : `(+${days}d)`}
          </span>
        )}
      </td>
      <td className="py-2.5 px-3">
        <span className="font-bold text-xs block" style={{ color: '#303B28' }}>
          {kindIcon(item.kind)} {item.name}
        </span>
        <span className="text-[11px]" style={{ color: '#727665' }}>{item.kind}</span>
      </td>
      <td className="py-2.5 px-3">
        <span className="font-medium text-xs block" style={{ color: '#303B28' }}>{item.contract}</span>
        {item.payer && <span className="font-mono text-[10px]" style={{ color: '#727665' }}>{item.payer} → {item.payee}</span>}
      </td>
      <td className="py-2.5 px-3 font-mono text-xs font-bold" style={{ color: '#303B28' }}>
        {item.amount ? fmtCurrency(item.amount) : '—'}
        {item.outstanding && item.outstanding !== '0.00' && item.outstanding !== item.amount && (
          <span className="block text-[10px] font-normal" style={{ color: '#C83D3D' }}>
            Outstanding: {fmtCurrency(item.outstanding)}
          </span>
        )}
      </td>
      <td className="py-2.5 px-3">
        <span className="font-mono text-[10px] font-semibold px-1.5 py-0.5 rounded" style={{ background: col.bg, color: col.text }}>
          {col.label}
        </span>
      </td>
      <td className="py-2.5 px-3 text-right">
        <button
          className="px-2 py-1 rounded border text-[11px] font-semibold transition-colors"
          style={{ borderColor: '#DCDCCB', color: '#303B28', background: '#FCFAF3' }}
          onClick={(e) => { e.stopPropagation(); onSelect(item); }}
        >
          Inspect
        </button>
      </td>
    </tr>
  );
}

function EvidencePanel({ item, asOf }) {
  if (!item) {
    return (
      <div
        className="rounded border p-6 text-center sticky top-20"
        style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}
      >
        <FileText className="w-8 h-8 mx-auto mb-3" style={{ color: '#DCDCCB' }} />
        <p className="font-mono text-xs" style={{ color: '#727665' }}>
          Select an obligation from the ledger to inspect its clause evidence.
        </p>
      </div>
    );
  }

  const col = statusColor(item.status);
  const days = daysFromNow(item.due, asOf);
  const citations = item.citations || [];

  return (
    <div
      className="rounded border overflow-hidden sticky top-20"
      style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}
    >
      {/* Header */}
      <div className="p-3 border-b flex items-center justify-between" style={{ background: '#F5F1E6', borderColor: '#DCDCCB' }}>
        <div className="flex items-center gap-2">
          <Search className="w-3.5 h-3.5" style={{ color: '#66734A' }} />
          <span className="font-mono text-xs font-bold" style={{ color: '#303B28' }}>Clause Evidence Inspector</span>
        </div>
        <span
          className="font-mono text-[10px] px-1.5 py-0.5 rounded border"
          style={{ background: '#FCFAF3', borderColor: '#DCDCCB', color: '#303B28' }}
        >
          {item.contract}
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* Status badge */}
        <div className="flex items-center justify-between">
          <span
            className="font-mono text-[10px] font-bold px-2 py-1 rounded uppercase"
            style={{ background: col.bg, color: col.text }}
          >
            {col.label}
          </span>
          {days !== null && (
            <span className="font-mono text-[11px]" style={{ color: col.text }}>
              {days < 0 ? `${Math.abs(days)} days overdue` : days === 0 ? 'Due today' : `${days} days remaining`}
            </span>
          )}
        </div>

        {/* Obligation name */}
        <div>
          <h3 className="font-bold text-sm mb-1" style={{ color: '#303B28' }}>{item.name}</h3>
          {item.period && <p className="font-mono text-[11px]" style={{ color: '#727665' }}>Period: {item.period}</p>}
        </div>

        {/* Financial details */}
        <div className="rounded border p-3 space-y-2 font-mono text-xs" style={{ background: '#FAF6EC', borderColor: '#DCDCCB' }}>
          <div className="flex justify-between items-center">
            <span style={{ color: '#727665' }}>Amount Due:</span>
            <span className="font-bold" style={{ color: '#303B28' }}>{fmtCurrency(item.amount)}</span>
          </div>
          {item.paid_amount && item.paid_amount !== '0.00' && (
            <div className="flex justify-between">
              <span style={{ color: '#727665' }}>Paid:</span>
              <span className="font-semibold" style={{ color: '#2E7D32' }}>{fmtCurrency(item.paid_amount)}</span>
            </div>
          )}
          {item.outstanding && item.outstanding !== '0.00' && (
            <div className="flex justify-between border-t pt-2" style={{ borderColor: '#DCDCCB' }}>
              <span className="font-bold" style={{ color: '#C83D3D' }}>Outstanding:</span>
              <span className="font-bold" style={{ color: '#C83D3D' }}>{fmtCurrency(item.outstanding)}</span>
            </div>
          )}
          {item.due_calendar && (
            <div className="flex justify-between">
              <span style={{ color: '#727665' }}>Calendar Due:</span>
              <span style={{ color: '#303B28' }}>{fmtDate(item.due_calendar)}</span>
            </div>
          )}
          {item.due_business && item.due_business !== item.due_calendar && (
            <div className="flex justify-between">
              <span style={{ color: '#727665' }}>Business Day Due:</span>
              <span style={{ color: '#303B28' }}>{fmtDate(item.due_business)}</span>
            </div>
          )}
        </div>

        {/* Citations / clause evidence */}
        {citations.length > 0 ? (
          <div className="space-y-2">
            <span className="font-mono text-[10px] uppercase tracking-wider font-bold" style={{ color: '#727665' }}>
              Clause Citations
            </span>
            {citations.slice(0, 3).map((c, i) => (
              <div key={i} className="rounded border p-3 text-xs" style={{ background: '#FAF6EC', borderColor: '#DCDCCB' }}>
                {c.section && (
                  <div className="font-mono font-bold mb-1" style={{ color: '#303B28' }}>§ {c.section}</div>
                )}
                {c.text && (
                  <p className="font-serif leading-relaxed text-xs" style={{ color: '#252B20' }}>
                    {c.text.length > 200 ? c.text.slice(0, 200) + '…' : c.text}
                  </p>
                )}
                {c.confidence !== undefined && (
                  <div className="mt-1 font-mono text-[10px]" style={{ color: '#527A54' }}>
                    Confidence: {(c.confidence * 100).toFixed(0)}%
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded border p-3 text-center" style={{ borderColor: '#DCDCCB', background: '#FAF6EC' }}>
            <p className="font-mono text-[11px]" style={{ color: '#727665' }}>
              No clause citations available for this obligation.
            </p>
          </div>
        )}

        {/* Flags */}
        {item.flags && item.flags.length > 0 && (
          <div className="space-y-1.5">
            <span className="font-mono text-[10px] uppercase tracking-wider font-bold" style={{ color: '#C83D3D' }}>
              Flags & Caveats
            </span>
            {item.flags.slice(0, 3).map((f, i) => (
              <div key={i} className="flex gap-2 text-[11px]" style={{ color: '#727665' }}>
                <span style={{ color: '#C83D3D' }}>•</span>
                <span>{f}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function WorstCasePanel({ wc, isOpen, onToggle, selectedDocId }) {
  if (!isOpen) return null;

  const accruals = wc?.accruals || [];
  const worstTotal = parseFloat(wc?.worst_case_total || 0);
  const onTimeTotal = parseFloat(wc?.on_time_total || 0);
  const avoidable = parseFloat(wc?.avoidable_exposure || 0);
  const wcAccruals = accruals.filter(a => a.scenario === 'worst_case');
  const otAccruals = accruals.filter(a => a.scenario === 'on_time');

  return (
    <div
      className="rounded border p-4 space-y-4"
      style={{
        background: 'linear-gradient(to right, rgba(247,232,228,0.3), transparent)',
        borderColor: 'rgba(200,61,61,0.5)',
        boxShadow: '0 0 0 2px rgba(200,61,61,0.1), 0 10px 25px -5px rgba(200,61,61,0.15)',
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full animate-ping" style={{ background: '#C83D3D' }} />
          <h3 className="font-mono text-xs font-bold uppercase tracking-wider" style={{ color: '#C83D3D' }}>
            Counterfactual Projection: Default & Worst-Case Cascade
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] font-semibold" style={{ color: '#C83D3D' }}>
            {selectedDocId ? `Doc: ${selectedDocId}` : 'All Contracts'} · Inaction Simulation
          </span>
          <button onClick={onToggle} className="p-1 rounded hover:opacity-70">
            <X className="w-3.5 h-3.5" style={{ color: '#C83D3D' }} />
          </button>
        </div>
      </div>

      <p className="font-mono text-xs" style={{ color: '#727665' }}>
        Projected financial exposure if all mandatory responses are neglected from the simulation date forward.
      </p>

      {/* Summary row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded border p-3 text-center" style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}>
          <div className="font-mono text-xs font-bold mb-1" style={{ color: '#C83D3D' }}>Worst-Case Total</div>
          <div className="text-lg font-bold" style={{ color: '#C83D3D' }}>{fmtCurrency(wc?.worst_case_total)}</div>
        </div>
        <div className="rounded border p-3 text-center" style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}>
          <div className="font-mono text-xs font-bold mb-1" style={{ color: '#527A54' }}>On-Time Total</div>
          <div className="text-lg font-bold" style={{ color: '#527A54' }}>{fmtCurrency(wc?.on_time_total)}</div>
        </div>
        <div className="rounded border p-3 text-center" style={{ background: '#F7E8E4', borderColor: 'rgba(200,61,61,0.4)' }}>
          <div className="font-mono text-xs font-bold mb-1" style={{ color: '#C83D3D' }}>Avoidable Exposure</div>
          <div className="text-lg font-bold" style={{ color: '#C83D3D' }}>{fmtCurrency(wc?.avoidable_exposure)}</div>
        </div>
      </div>

      {/* Accrual breakdown */}
      {wcAccruals.length > 0 && (
        <div className="space-y-2">
          <span className="font-mono text-[10px] uppercase tracking-wider font-bold" style={{ color: '#C83D3D' }}>
            Worst-Case Accrual Sequence
          </span>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {wcAccruals.slice(0, 3).map((a, i) => (
              <div key={i} className="rounded border p-2.5 space-y-1" style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}>
                <div className="flex justify-between font-mono text-[10px]" style={{ color: '#C83D3D' }}>
                  <span>{fmtDate(a.at)}</span>
                  <span>{fmtCurrency(a.amount)}</span>
                </div>
                <p className="font-bold text-xs" style={{ color: '#303B28' }}>{a.description}</p>
                {a.formula && <p className="text-[10px] font-mono" style={{ color: '#727665' }}>{a.formula}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unquantified items */}
      {wc?.unquantified?.length > 0 && (
        <div className="rounded border p-3" style={{ borderColor: '#DCDCCB', background: '#FAF6EC' }}>
          <span className="font-mono text-[10px] font-bold uppercase" style={{ color: '#727665' }}>
            {wc.unquantified.length} Unquantified Risk Item{wc.unquantified.length !== 1 ? 's' : ''}
          </span>
          {wc.unquantified.slice(0, 2).map((u, i) => (
            <p key={i} className="mt-1 text-[11px]" style={{ color: '#727665' }}>• {u.description}</p>
          ))}
        </div>
      )}

      {wc?.flags?.map((f, i) => (
        <p key={i} className="text-[11px] font-mono" style={{ color: '#727665' }}>⚠ {f}</p>
      ))}
    </div>
  );
}

// ─── main page ───────────────────────────────────────────────────────────────

export default function NornsObligationsWorkspace() {
  const today = new Date().toISOString().split('T')[0];

  // State
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [asOf, setAsOf] = useState(today);
  const [dateOffset, setDateOffset] = useState(0);
  const [timeline, setTimeline] = useState(null);
  const [obligations, setObligations] = useState([]);
  const [totalObligs, setTotalObligs] = useState(0);
  const [offset, setOffset] = useState(0);
  const [activeTab, setActiveTab] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedItem, setSelectedItem] = useState(null);
  const [worstCase, setWorstCase] = useState(null);
  const [worstCaseOpen, setWorstCaseOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingWC, setLoadingWC] = useState(false);
  const [error, setError] = useState(null);
  const PAGE_SIZE = 25;

  // Load documents
  useEffect(() => {
    fetchNornsDocuments()
      .then(setDocuments)
      .catch((e) => console.warn('docs:', e));
  }, []);

  // Compute asOf from offset
  useEffect(() => {
    const d = new Date(today + 'T00:00:00');
    d.setDate(d.getDate() + dateOffset);
    setAsOf(d.toISOString().split('T')[0]);
  }, [dateOffset, today]);

  // Debounced load timeline & obligations whenever asOf / doc changes
  useEffect(() => {
    let isCancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      Promise.all([
        fetchNornsTimeline(asOf, selectedDocId),
        fetchNornsObligations(asOf, selectedDocId, activeTab === 'all' ? null : activeTab, PAGE_SIZE, offset),
      ])
        .then(([tl, ob]) => {
          if (isCancelled) return;
          setTimeline(tl);
          setObligations(ob?.obligations || []);
          setTotalObligs(ob?.total || 0);
          if (!selectedItem && ob?.obligations?.length > 0) setSelectedItem(ob.obligations[0]);
        })
        .catch((e) => {
          if (!isCancelled) setError(e.message);
        })
        .finally(() => {
          if (!isCancelled) setLoading(false);
        });
    }, 150);

    return () => {
      isCancelled = true;
      clearTimeout(timer);
    };
  }, [asOf, selectedDocId, activeTab, offset]);

  const loadWorstCase = useCallback(() => {
    setLoadingWC(true);
    fetchNornsWorstCase(asOf, selectedDocId)
      .then((wc) => { setWorstCase(wc); setWorstCaseOpen(true); })
      .catch((e) => console.warn('wc:', e))
      .finally(() => setLoadingWC(false));
  }, [asOf, selectedDocId]);

  // Summary stats from timeline
  const overdueCnt = timeline?.overdue?.length || 0;
  const dueNowCnt = timeline?.due_now?.length || 0;
  const upcomingCnt = (timeline?.all_instances || []).filter(i => i.status === 'upcoming').length;
  const alertItems = [
    ...(timeline?.overdue || []),
    ...(timeline?.due_now || []),
    ...(timeline?.next_deadlines || []).slice(0, 2),
  ].slice(0, 4);

  // Filter obligations by search
  const filteredObligs = obligations.filter((o) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      o.name?.toLowerCase().includes(q) ||
      o.contract?.toLowerCase().includes(q) ||
      o.payer?.toLowerCase().includes(q) ||
      o.payee?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-5">
      {/* ── Hero + Clock controller ─────────────────────────────────────── */}
      <div className="rounded border p-5 shadow-sm" style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}>
        {/* Header row */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 mb-4 border-b" style={{ borderColor: '#DCDCCB' }}>
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className="font-mono text-[10px] font-bold uppercase px-2 py-0.5 rounded tracking-wider"
                style={{ background: '#E3E7D3', color: '#303B28' }}
              >
                ODIN AGENT 02 · TIMELINE INTELLIGENCE
              </span>
              <span className="font-mono text-[11px]" style={{ color: '#727665' }}>Determinism Engine active</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight" style={{ color: '#303B28', fontFamily: 'Plus Jakarta Sans, sans-serif' }}>
              Know what is due before it becomes a risk.
            </h1>
            <p className="text-sm max-w-3xl" style={{ color: '#727665', fontFamily: 'Plus Jakarta Sans, sans-serif' }}>
              NORNS maps contract-derived obligations across time, tracks payment and commitment records, and deterministically projects upcoming deadlines, renewals, and penalty triggers.
            </p>
          </div>

          {/* Worst-case button */}
          <div className="flex flex-col items-start lg:items-end gap-1.5 shrink-0">
            <button
              onClick={loadWorstCase}
              disabled={loadingWC}
              className="flex items-center gap-2 px-4 py-2.5 rounded font-semibold text-sm text-white transition-all active:scale-95 shadow-sm disabled:opacity-60"
              style={{ background: '#C83D3D' }}
            >
              {loadingWC ? <Loader2 className="w-4 h-4 animate-spin" /> : <AlertTriangle className="w-4 h-4" />}
              <span>⚠ Worst-Case Timeline ↗</span>
            </button>
            <span className="font-mono text-[10px]" style={{ color: '#727665' }}>Cascading failure counterfactual</span>
          </div>
        </div>

        {/* Simulated clock controller */}
        <div
          className="flex flex-col md:flex-row items-center justify-between gap-4 px-4 py-3 rounded border text-xs font-mono"
          style={{ background: '#FAF6EC', borderColor: '#DCDCCB' }}
        >
          <div className="flex items-center gap-3 flex-wrap w-full md:w-auto">
            <div className="flex items-center gap-1.5 font-bold" style={{ color: '#303B28' }}>
              <Clock className="w-4 h-4" style={{ color: '#66734A' }} />
              <span>Simulated Date:</span>
              <span
                className="px-2 py-0.5 rounded border font-bold"
                style={{ background: '#FCFAF3', borderColor: '#DCDCCB', color: '#303B28' }}
              >
                {asOf} {dateOffset !== 0 ? `(T${dateOffset > 0 ? '+' : ''}${dateOffset}d)` : '(Today)'}
              </span>
            </div>
            <div className="h-4 w-px hidden sm:block" style={{ background: '#DCDCCB' }} />
            <div className="flex items-center gap-1 flex-wrap">
              {[-30, 0, 30, 90].map((offset) => (
                <button
                  key={offset}
                  onClick={() => { setDateOffset(offset); setOffset(0); }}
                  className="px-2 py-1 rounded border text-[11px] transition-colors"
                  style={{
                    background: dateOffset === offset ? '#303B28' : '#FCFAF3',
                    color: dateOffset === offset ? '#fff' : '#303B28',
                    borderColor: '#DCDCCB',
                    fontWeight: dateOffset === offset ? 600 : 400,
                  }}
                >
                  {offset === 0 ? 'Today' : offset < 0 ? `Past ${Math.abs(offset)}d` : `Next ${offset}d`}
                </button>
              ))}
            </div>
          </div>

          {/* Slider */}
          <div className="flex items-center gap-3 w-full md:w-auto justify-end">
            <span style={{ color: '#727665' }}>Offset:</span>
            <input
              type="range"
              min="-30"
              max="90"
              value={dateOffset}
              onChange={(e) => { setDateOffset(Number(e.target.value)); setOffset(0); }}
              className="w-32 cursor-pointer accent-olive-600"
              style={{ accentColor: '#303B28' }}
            />
            <button
              onClick={() => { setDateOffset(0); setOffset(0); }}
              className="flex items-center gap-1 text-xs font-semibold underline"
              style={{ color: '#66734A' }}
            >
              <RefreshCw className="w-3 h-3" />
              <span>Reset</span>
            </button>
          </div>
        </div>
      </div>

      {/* ── Portfolio urgency metrics ──────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="Overdue Obligations" value={overdueCnt} sub="Need immediate action" color="#C83D3D" dot="error" />
        <MetricCard label="Due This Week" value={dueNowCnt} sub="Commitments scheduled" color="#303B28" dot="secondary" />
        <MetricCard label="Upcoming 30d" value={upcomingCnt} sub="Milestones pending" color="#303B28" dot="tertiary" />
        <MetricCard
          label="Financial Exposure"
          value={timeline ? fmtCurrency(
            (timeline.overdue || []).reduce((sum, i) => sum + (parseFloat(i.outstanding || i.amount || 0)), 0)
          ) : '—'}
          sub="Overdue & outstanding"
          color="#303B28"
        />
        <MetricCard
          label="Renewals in Window"
          value={Object.keys(timeline?.renewal_deadlines || {}).length}
          sub="Active notice periods"
          color="#303B28"
          dot="tertiary"
        />
      </div>

      {/* ── Priority alert strip ──────────────────────────────────────── */}
      {alertItems.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-bold flex items-center gap-2" style={{ color: '#303B28' }}>
                <AlertTriangle className="w-4 h-4" style={{ color: '#C83D3D' }} />
                Needs Attention · Priority Alerts
              </h2>
              <p className="text-xs mt-0.5" style={{ color: '#727665' }}>
                Upcoming commitments, overdue obligations, renewal windows, and penalty triggers.
              </p>
            </div>
            <span
              className="font-mono text-xs px-2 py-1 rounded border"
              style={{ background: '#F5F1E6', borderColor: '#DCDCCB', color: '#303B28' }}
            >
              {alertItems.length} Priority Trigger{alertItems.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {alertItems.map((item, i) => (
              <AlertCard
                key={item.key || i}
                item={item}
                asOf={asOf}
                onSelect={setSelectedItem}
                isSelected={selectedItem?.key === item.key}
              />
            ))}
          </div>
        </section>
      )}

      {/* ── Timeline rail ─────────────────────────────────────────────── */}
      <section className="rounded border p-4 space-y-3" style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h2 className="font-bold flex items-center gap-2" style={{ color: '#303B28' }}>
              <TrendingUp className="w-4 h-4" style={{ color: '#66734A' }} />
              Contractual Milestone Horizon
            </h2>
            <p className="text-xs mt-0.5" style={{ color: '#727665' }}>
              Deterministic timeline derived from extracted contract stipulations.
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs font-mono">
            <div className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: '#C83D3D' }} /> Overdue</div>
            <div className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: '#66734A' }} /> Upcoming</div>
            <div className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: '#527A54' }} /> Settled</div>
          </div>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-8 gap-2 font-mono text-xs" style={{ color: '#727665' }}>
            <Loader2 className="w-4 h-4 animate-spin" /> Computing timeline...
          </div>
        ) : (
          <TimelineRail
            instances={timeline?.all_instances || []}
            asOf={asOf}
            onSelect={setSelectedItem}
          />
        )}
      </section>

      {/* ── Worst-case panel ──────────────────────────────────────────── */}
      <WorstCasePanel
        wc={worstCase}
        isOpen={worstCaseOpen}
        onToggle={() => setWorstCaseOpen(false)}
        selectedDocId={selectedDocId}
      />

      {/* ── Main 2-column workspace ───────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Obligations ledger */}
        <section className="lg:col-span-8 space-y-0">
          <div className="rounded border shadow-sm overflow-hidden" style={{ background: '#FCFAF3', borderColor: '#DCDCCB' }}>
            {/* Ledger header */}
            <div className="p-4 border-b flex flex-col sm:flex-row sm:items-center justify-between gap-3" style={{ borderColor: '#DCDCCB' }}>
              <div>
                <h2 className="font-bold" style={{ color: '#303B28' }}>Obligations & Commitments Ledger</h2>
                <p className="text-xs mt-0.5" style={{ color: '#727665' }}>
                  Indexed contract clauses cross-referenced with extracted payment and obligation records.
                </p>
              </div>
              {/* Doc filter + Search */}
              <div className="flex items-center gap-2 flex-wrap">
                {documents.length > 0 && (
                  <select
                    value={selectedDocId || ''}
                    onChange={(e) => { setSelectedDocId(e.target.value || null); setOffset(0); }}
                    className="text-xs font-mono rounded border px-2 py-1.5"
                    style={{ background: '#FAF6EC', borderColor: '#DCDCCB', color: '#303B28' }}
                  >
                    <option value="">All Contracts</option>
                    {documents.map((d) => (
                      <option key={d.doc_id} value={d.doc_id}>{d.doc_id}</option>
                    ))}
                  </select>
                )}
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2" style={{ color: '#727665' }} />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search obligations..."
                    className="pl-7 pr-2.5 py-1.5 text-xs font-mono rounded border w-40 focus:outline-none"
                    style={{ background: '#FAF6EC', borderColor: '#DCDCCB', color: '#303B28' }}
                  />
                </div>
              </div>
            </div>

            {/* Tabs */}
            <div
              className="flex items-center border-b px-4 overflow-x-auto text-xs font-mono"
              style={{ background: '#FAF6EC', borderColor: '#DCDCCB' }}
            >
              {TABS.map((tab) => {
                const counts = {
                  all: totalObligs,
                  overdue: timeline?.overdue?.length || 0,
                  upcoming: upcomingCnt,
                  paid: (timeline?.status_counts?.paid_on_time || 0) + (timeline?.status_counts?.paid_late || 0),
                };
                return (
                  <button
                    key={tab.id}
                    onClick={() => { setActiveTab(tab.id); setOffset(0); }}
                    className="py-2.5 px-3 border-b-2 whitespace-nowrap transition-colors"
                    style={{
                      borderColor: activeTab === tab.id ? '#303B28' : 'transparent',
                      color: activeTab === tab.id ? '#303B28' : '#727665',
                      fontWeight: activeTab === tab.id ? 700 : 400,
                    }}
                  >
                    {tab.label} ({counts[tab.id] ?? 0})
                  </button>
                );
              })}
            </div>

            {/* Table */}
            {loading ? (
              <div className="flex items-center justify-center py-12 gap-2 font-mono text-xs" style={{ color: '#727665' }}>
                <Loader2 className="w-4 h-4 animate-spin" /> Loading obligations...
              </div>
            ) : filteredObligs.length === 0 ? (
              <div className="text-center py-12 font-mono text-xs" style={{ color: '#727665' }}>
                {error ? `Error: ${error}` : 'No obligations found for this filter. Start the backend to load real data.'}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr
                      className="border-b font-mono text-[10px] uppercase tracking-wider"
                      style={{ background: '#F5F1E6', borderColor: '#DCDCCB', color: '#727665' }}
                    >
                      <th className="py-2.5 px-3">Due Date</th>
                      <th className="py-2.5 px-3">Obligation / Action</th>
                      <th className="py-2.5 px-3">Contract & Entity</th>
                      <th className="py-2.5 px-3">Value / Exposure</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody style={{ borderTop: '1px solid #DCDCCB' }}>
                    {filteredObligs.map((item, i) => (
                      <ObligationRow
                        key={item.key || i}
                        item={item}
                        asOf={asOf}
                        isSelected={selectedItem?.key === item.key}
                        onSelect={setSelectedItem}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {totalObligs > PAGE_SIZE && (
              <div
                className="p-3 border-t flex items-center justify-between text-xs font-mono"
                style={{ background: '#FAF6EC', borderColor: '#DCDCCB', color: '#727665' }}
              >
                <span>Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, totalObligs)} of {totalObligs} obligations</span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                    disabled={offset === 0}
                    className="px-2 py-0.5 border rounded transition-colors disabled:opacity-40"
                    style={{ background: '#FCFAF3', borderColor: '#DCDCCB', color: '#303B28' }}
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setOffset((o) => o + PAGE_SIZE)}
                    disabled={offset + PAGE_SIZE >= totalObligs}
                    className="px-2 py-0.5 border rounded transition-colors disabled:opacity-40"
                    style={{ background: '#FCFAF3', borderColor: '#DCDCCB', color: '#303B28' }}
                  >
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* NORNS flags from backend */}
          {timeline?.flags?.length > 0 && (
            <div
              className="mt-3 rounded border p-3 space-y-1 font-mono text-xs"
              style={{ background: '#FAF6EC', borderColor: '#DCDCCB' }}
            >
              <span className="font-bold uppercase tracking-wider text-[10px]" style={{ color: '#C83D3D' }}>Engine Flags</span>
              {timeline.flags.map((f, i) => (
                <p key={i} style={{ color: '#727665' }}>• {f}</p>
              ))}
            </div>
          )}
        </section>

        {/* Evidence inspector */}
        <section className="lg:col-span-4">
          <EvidencePanel item={selectedItem} asOf={asOf} />
        </section>
      </div>
    </div>
  );
}
