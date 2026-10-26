import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle, ArrowUpRight, Bell, ChevronDown, ChevronRight, Clock, Inbox, Loader2, Radar, RefreshCw,
  Siren, XCircle, Zap,
} from 'lucide-react';
import {
  fetchHeimdallBoard, fetchHeimdallOverview, reassessHeimdall, runHeimdallDrop, setHeimdallTaskStatus,
} from '../../services/api';
import { SEVERITY, SEVERITY_ORDER, flatten, fmtCurrency, fmtDate } from '../common/format';
import HeimdallTaskBoard from './HeimdallTaskBoard';

// ─── helpers ────────────────────────────────────────────────────────────────

const EVENT_STATUS = {
  mapped: { label: 'Mapped', bg: '#EAF5EA', text: '#2E7D32' },
  noise: { label: 'Noise', bg: '#F5F1E6', text: '#727665' },
  unmapped: { label: 'Unmapped', bg: '#FFF8E1', text: '#B76E00' },
  unparseable: { label: 'Unparseable', bg: '#FBEBEB', text: '#C83D3D' },
};

function label(kind) {
  return (kind || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

function signedMoney(v) {
  const n = parseFloat(v);
  if (isNaN(n) || n === 0) return '$0';
  return `${n > 0 ? '+' : '−'}${fmtCurrency(Math.abs(n), 0)}`;
}

function factText(fact) {
  if (!fact) return '—';
  const skip = new Set(['type', 'source', 'event_id', 'contract', 'date', 'task_id']);
  const extra = Object.entries(fact)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== '')
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${k === 'amount' ? fmtCurrency(v, 0) : v}`);
  return [label(fact.type), fact.contract, fact.date, ...extra].filter(Boolean).join(' · ');
}

function MetricCard({ label: title, value, sub, color }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-ivory p-3.5 flex flex-col justify-between shadow-xs">
      <span className="font-mono text-[10px] uppercase tracking-wider text-secondary-olive">{title}</span>
      <div className="mt-2">
        <div className="text-xl font-bold font-mono" style={{ color: color || '#303B28' }}>{value}</div>
        {sub && <div className="text-[11px] font-mono mt-0.5 text-secondary-olive">{sub}</div>}
      </div>
    </div>
  );
}

function Notice({ tone = 'info', children }) {
  const tones = {
    info: { bg: '#FAF6EC', border: '#DCDCCB', text: '#727665' },
    warn: { bg: '#FFF8E1', border: 'rgba(183,110,0,0.3)', text: '#8A5300' },
    error: { bg: '#FBEBEB', border: 'rgba(200,61,61,0.35)', text: '#8F2929' },
    ok: { bg: '#EAF5EA', border: 'rgba(46,125,50,0.3)', text: '#1F5A23' },
  };
  const t = tones[tone];
  return (
    <div className="rounded border p-2.5 font-mono text-[11px] leading-snug" style={{ background: t.bg, borderColor: t.border, color: t.text }}>
      {children}
    </div>
  );
}

function AlertRow({ alert, asOf, onOpenNorns }) {
  const sev = SEVERITY[alert.severity] || SEVERITY.low;
  const quote = flatten(alert.citation?.quote);
  return (
    <div className="rounded-lg border border-border-subtle bg-white p-3 pl-4 relative overflow-hidden">
      <div className="absolute top-0 left-0 w-1 h-full" style={{ background: sev.bar }} />
      <div className="flex items-center gap-1.5 flex-wrap mb-1">
        <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase" style={{ background: sev.bg, color: sev.text }}>
          {sev.label}
        </span>
        <span className="font-mono text-[10px] font-semibold text-primary-dark uppercase tracking-wide">{label(alert.kind)}</span>
        <span className="font-mono text-[10px] px-1 rounded bg-cream border border-border-subtle text-secondary-olive">
          {alert.source === 'event' ? `EVENT ${alert.event_id || ''}` : 'NORNS'}
        </span>
        {alert.due_date && <span className="font-mono text-[10px] text-secondary-olive">· {fmtDate(alert.due_date)}</span>}
      </div>
      <p className="text-xs text-dark-olive leading-snug">{alert.message}</p>
      <div className="mt-1.5 flex items-center justify-between gap-2 flex-wrap">
        <span className="font-mono text-[10px] text-secondary-olive min-w-0" title={quote}>
          {alert.clause_id ? (
            <>
              <span className="px-1 py-0.5 rounded border border-border-subtle bg-cream text-primary-dark">{alert.clause_id}</span>
              {quote && ` “${quote.slice(0, 80)}${quote.length > 80 ? '…' : ''}”`}
            </>
          ) : (
            'no clause citation'
          )}
        </span>
        {alert.contract && (
          <button
            onClick={() => onOpenNorns(alert.contract, asOf)}
            className="font-mono text-[10px] font-semibold text-primary hover:underline inline-flex items-center gap-0.5"
          >
            Open {alert.contract} in NORNS <ArrowUpRight className="w-3 h-3" />
          </button>
        )}
      </div>
    </div>
  );
}

function EventRow({ ev, expanded, onToggle }) {
  const st = EVENT_STATUS[ev.status] || EVENT_STATUS.unmapped;
  const exp = ev.exposure || {};
  const delta = exp.delta !== undefined ? parseFloat(exp.delta) : null;
  const reason = ev.noise_reason || ev.status_reason || ev.breach_reason;
  return (
    <>
      <tr onClick={onToggle} className="cursor-pointer hover:bg-cream/60 transition-colors border-t border-border-subtle/70 align-top">
        <td className="py-2.5 px-3 font-mono text-xs whitespace-nowrap">
          <span className="inline-flex items-center gap-1 font-bold text-primary-dark">
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            {ev.event_id || `line ${ev.line_no}`}
          </span>
          <span className="block text-[10px] text-secondary-olive pl-4">{fmtDate(ev.event_date)} · {ev.channel || '—'}</span>
        </td>
        <td className="py-2.5 px-3 text-xs max-w-[280px]">
          <span className="block font-semibold text-dark-olive truncate" title={ev.subject}>{ev.subject || (ev.status === 'unparseable' ? 'Malformed line' : '—')}</span>
          <span className="block text-[11px] text-secondary-olive truncate" title={ev.sender}>{ev.sender || '—'}</span>
        </td>
        <td className="py-2.5 px-3 whitespace-nowrap">
          <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase" style={{ background: st.bg, color: st.text }}>
            {st.label}
          </span>
          {ev.mapped_by && <span className="block font-mono text-[10px] text-secondary-olive mt-0.5">by {ev.mapped_by}</span>}
          {ev.potential_breach && (
            <span className="font-mono text-[10px] font-bold text-odin-red mt-0.5 flex items-center gap-0.5">
              <Siren className="w-3 h-3" /> breach risk
            </span>
          )}
        </td>
        <td className="py-2.5 px-3 font-mono text-[10px] text-primary-dark">
          {(ev.clause_ids || []).length > 0 ? ev.clause_ids.join(', ') : (ev.doc_ids || []).join(', ') || '—'}
        </td>
        <td className="py-2.5 px-3 text-[11px] text-dark-olive max-w-[240px]">{factText(ev.fact)}</td>
        <td className="py-2.5 px-3 font-mono text-xs text-right whitespace-nowrap font-bold" style={{ color: delta > 0 ? '#C83D3D' : delta < 0 ? '#2E7D32' : '#727665' }}>
          {delta === null || isNaN(delta) ? '—' : signedMoney(delta)}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-[#FAF6EC]">
          <td colSpan={6} className="px-4 py-3 space-y-2">
            {reason && (
              <p className="font-mono text-[11px] text-dark-olive">
                <span className="font-bold uppercase text-[10px] text-secondary-olive">Why: </span>
                {reason}
              </p>
            )}
            {exp.before !== undefined && (
              <p className="font-mono text-[11px] text-dark-olive">
                <span className="font-bold uppercase text-[10px] text-secondary-olive">Worst case: </span>
                {fmtCurrency(exp.before, 0)} → {fmtCurrency(exp.after, 0)}
                {Object.keys(exp.by_contract || {}).length > 0 &&
                  ` (${Object.entries(exp.by_contract).map(([c, d]) => `${c} ${signedMoney(d)}`).join(', ')})`}
              </p>
            )}
            {(exp.changes || []).length > 0 && (
              <ul className="font-mono text-[11px] text-secondary-olive space-y-0.5">
                {exp.changes.map((c, i) => (
                  <li key={i}>• {c}</li>
                ))}
              </ul>
            )}
            {ev.confidence !== null && ev.confidence !== undefined && (
              <p className="font-mono text-[10px] text-secondary-olive">confidence {Math.round(ev.confidence * 100)}% · drop {ev.drop_name}, line {ev.line_no}</p>
            )}
            <pre className="whitespace-pre-wrap break-words font-mono text-[10px] text-secondary-olive bg-ivory border border-border-subtle rounded p-2 max-h-40 overflow-y-auto">
              {ev.raw}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── main workspace ─────────────────────────────────────────────────────────

export default function HeimdallEventWorkspace() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [overview, setOverview] = useState(null);
  const [overviewError, setOverviewError] = useState(null);
  const [asOf, setAsOf] = useState(searchParams.get('as_of'));
  const [board, setBoard] = useState(null);
  const [boardError, setBoardError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [drop, setDrop] = useState(null);
  const [useLlm, setUseLlm] = useState(false);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [reassessing, setReassessing] = useState(false);
  const [showNoise, setShowNoise] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [busyTaskId, setBusyTaskId] = useState(null);
  const [flash, setFlash] = useState(null);

  const loadOverview = useCallback(() => {
    return fetchHeimdallOverview()
      .then((o) => {
        setOverview(o);
        setOverviewError(null);
        return o;
      })
      .catch((e) => {
        setOverviewError(e.message);
        return null;
      });
  }, []);

  const loadBoard = useCallback((day, { silent = false } = {}) => {
    if (!day) return Promise.resolve(null);
    if (!silent) setLoading(true);
    return fetchHeimdallBoard(day)
      .then((b) => {
        setBoard(b);
        setBoardError(null);
        return b;
      })
      .catch((e) => {
        setBoardError(e.message);
        return null;
      })
      .finally(() => !silent && setLoading(false));
  }, []);

  // Drops, checkpoints, stored runs and LLM readiness; the initial clock date.
  useEffect(() => {
    loadOverview().then((o) => {
      if (!o) return;
      setUseLlm(Boolean(o.llm?.configured));
      if (!searchParams.get('as_of')) {
        const cp1 = (o.checkpoints || []).find((p) => p.idx === 1);
        setAsOf(o.run_dates?.[0] || cp1?.date || new Date().toISOString().split('T')[0]);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The board for the clock date; re-read every 20 s so teammates' task tags show up.
  useEffect(() => {
    if (!asOf) return undefined;
    setSearchParams({ as_of: asOf }, { replace: true });
    setExpanded(null);
    loadBoard(asOf);
    const timer = setInterval(() => loadBoard(asOf, { silent: true }), 20000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asOf, loadBoard]);

  const drops = overview?.drops || [];
  const released = drops.filter((d) => d.release_date && d.release_date <= asOf);

  // Default drop: the latest one released on the clock date.
  useEffect(() => {
    if (!drops.length) return;
    if (!drop || !released.some((d) => d.name === drop)) {
      setDrop(released.length ? released[released.length - 1].name : null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asOf, overview]);

  const dateOptions = useMemo(() => {
    const out = new Map();
    (overview?.checkpoints || []).forEach((p) => out.set(p.date, p.label));
    (overview?.run_dates || []).forEach((d) => {
      if (!out.has(d)) out.set(d, 'Run');
    });
    return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [overview]);
  const runDates = new Set(overview?.run_dates || []);

  const llm = overview?.llm;
  const alerts = board?.alerts || [];
  const events = board?.events || [];
  const tasks = board?.tasks || [];
  const counts = board?.counts;
  const wc = board?.worst_case;
  const noise = events.filter((e) => e.status === 'noise');
  const sevCounts = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, alerts.filter((a) => a.severity === s).length]));
  const visibleEvents = showNoise ? events : events.filter((e) => e.status !== 'noise');
  const hasRunOnDate = runDates.has(asOf);

  const runDrop = () => {
    if (!drop || !asOf) return;
    setRunning(true);
    setRunError(null);
    setRunResult(null);
    runHeimdallDrop(drop, asOf, useLlm && Boolean(llm?.configured))
      .then((res) => {
        setRunResult(res);
        return Promise.all([loadOverview(), loadBoard(asOf, { silent: true })]);
      })
      .then(() => {
        try {
          window.dispatchEvent(new CustomEvent('odin-doc-updated', { detail: { agent: 'heimdall', asOf } }));
        } catch (e) {
          // non-browser context
        }
      })
      .catch((e) => setRunError(e.message))
      .finally(() => setRunning(false));
  };

  const reassess = () => {
    setReassessing(true);
    setFlash(null);
    reassessHeimdall(asOf)
      .then((r) => {
        setFlash({ tone: 'ok', text: `Recomputed ${fmtDate(r.as_of)}: ${r.alerts} alert(s), ${r.tasks} task(s), worst case ${fmtCurrency(r.worst_case, 0)}.` });
        return loadBoard(asOf, { silent: true });
      })
      .catch((e) => setFlash({ tone: 'error', text: e.message }))
      .finally(() => setReassessing(false));
  };

  const setTaskStatus = (task, status) => {
    setBusyTaskId(task.task_id);
    setFlash(null);
    setHeimdallTaskStatus(asOf, task.task_id, status)
      .then((r) => {
        setFlash({ tone: 'ok', text: r.message });
        return loadBoard(asOf, { silent: true });
      })
      .catch((e) => setFlash({ tone: 'error', text: e.message }))
      .finally(() => setBusyTaskId(null));
  };

  const openNorns = (contract, day) => navigate(`/norns?doc_id=${encodeURIComponent(contract)}&as_of=${day}`);

  const afterDelta = wc ? parseFloat(wc.after_events) - parseFloat(wc.baseline) : 0;
  const liveDelta = wc ? parseFloat(wc.live) - parseFloat(wc.after_events) : 0;

  return (
    <div className="space-y-5">
      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <div className="rounded-lg border border-border-subtle bg-ivory p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-[10px] font-bold uppercase px-2 py-0.5 rounded tracking-wider bg-[#E3E7D3] text-primary-dark">
                ODIN AGENT 04 · EVENT MONITORING
              </span>
              <span className="font-mono text-[11px] text-secondary-olive">Code first · LLM only for what code cannot map</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-primary-dark">Every event, mapped to the clause it touches.</h1>
            <p className="text-sm max-w-3xl text-secondary-olive">
              HEIMDALL reads each released event drop, maps every message to the contracts and clauses it affects, feeds the
              facts to NORNS to reassess exposure, and raises severity-rated alerts. Noise is filtered out with a stated
              reason, never silently dropped.
            </p>
          </div>
          <div className="shrink-0 rounded border border-border-subtle bg-cream px-3 py-2 font-mono text-[11px] space-y-0.5 min-w-[220px]">
            <div className="flex items-center gap-1.5 font-semibold text-dark-olive">
              <span className={`w-2 h-2 rounded-full ${llm?.configured ? 'bg-emerald-600 animate-pulse' : 'bg-odin-amber'}`} />
              {llm ? (llm.configured ? 'LLM ready for mapping' : 'Code mapping only') : 'Checking LLM…'}
            </div>
            {llm && (
              <div className="text-secondary-olive">
                {llm.provider}
                {llm.model ? ` · ${llm.model}` : ''}
              </div>
            )}
            {llm && !llm.configured && <div className="text-[#8A5300] leading-snug max-w-[260px]">{llm.problem}</div>}
            {overview && <div className="text-secondary-olive">≤ {overview.max_llm_calls} LLM calls per run</div>}
          </div>
        </div>
      </div>

      {overviewError && (
        <Notice tone="error">
          <span className="flex items-start gap-2"><AlertTriangle className="w-4 h-4 shrink-0" /> {overviewError}</span>
        </Notice>
      )}

      {/* ── Clock + drops ─────────────────────────────────────────────── */}
      <div className="rounded-lg border border-border-subtle bg-ivory p-4 space-y-4 shadow-xs">
        <div className="space-y-1.5">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-secondary-olive flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-primary" /> Clock date (simulated)
          </span>
          <div className="flex items-center gap-1.5 flex-wrap">
            {dateOptions.map(([d, lbl]) => (
              <button
                key={d}
                onClick={() => setAsOf(d)}
                className={`px-2.5 py-1.5 rounded border font-mono text-[11px] transition-colors ${
                  asOf === d ? 'bg-primary-dark text-white border-primary-dark font-semibold' : 'bg-cream/70 text-dark-olive border-border-subtle hover:bg-cream'
                }`}
              >
                {lbl} · {fmtDate(d)}
                {runDates.has(d) && <span className={`ml-1.5 inline-block w-1.5 h-1.5 rounded-full ${asOf === d ? 'bg-odin-palesage' : 'bg-primary'}`} title="Heimdall run stored" />}
              </button>
            ))}
            <input
              type="date"
              value={asOf || ''}
              onChange={(e) => e.target.value && setAsOf(e.target.value)}
              className="px-2 py-1 rounded border border-border-subtle bg-cream/70 font-mono text-[11px] text-dark-olive"
              aria-label="Custom clock date"
            />
          </div>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
          <div className="space-y-1.5 min-w-0">
            <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-secondary-olive flex items-center gap-1.5">
              <Inbox className="w-3.5 h-3.5 text-primary" /> Event drops
            </span>
            <div className="flex items-stretch gap-2 flex-wrap">
              {drops.map((d) => {
                const isReleased = d.release_date && d.release_date <= asOf;
                const active = drop === d.name;
                return (
                  <button
                    key={d.name}
                    onClick={() => isReleased && setDrop(d.name)}
                    disabled={!isReleased}
                    className={`text-left px-3 py-2 rounded-lg border font-mono text-[11px] transition-all ${
                      active
                        ? 'bg-primary-dark text-cream border-primary-dark shadow-sm'
                        : isReleased
                        ? 'bg-cream/70 text-dark-olive border-border-subtle hover:bg-cream'
                        : 'bg-cream/40 text-secondary-olive/70 border-dashed border-border-subtle cursor-not-allowed'
                    }`}
                  >
                    <span className="block font-bold">{d.name}</span>
                    <span className={`block text-[10px] ${active ? 'text-odin-palesage' : 'text-secondary-olive'}`}>
                      {isReleased ? 'released' : 'releases'} {fmtDate(d.release_date)} (Checkpoint {d.release_checkpoint})
                    </span>
                    <span className={`block text-[10px] ${active ? 'text-cream/80' : 'text-secondary-olive'}`}>
                      {d.runs.length ? `processed: ${d.runs.map(fmtDate).join(', ')}` : 'not processed yet'}
                    </span>
                  </button>
                );
              })}
            </div>
            <label className={`flex items-center gap-2 font-mono text-[11px] ${llm?.configured ? 'text-dark-olive' : 'text-secondary-olive'}`}>
              <input
                type="checkbox"
                checked={useLlm && Boolean(llm?.configured)}
                disabled={!llm?.configured}
                onChange={(e) => setUseLlm(e.target.checked)}
                className="accent-[#303B28]"
              />
              Send events code cannot map to the LLM
              {!llm?.configured && <span className="text-[10px]">(no LLM key: those events stay unmapped)</span>}
            </label>
          </div>

          <div className="flex flex-col items-start lg:items-end gap-1.5 shrink-0">
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={reassess}
                disabled={reassessing || running || !asOf}
                className="inline-flex items-center gap-1.5 px-3 py-2.5 rounded border border-border-subtle bg-cream text-primary-dark text-xs font-mono font-semibold hover:bg-white transition-all disabled:opacity-50"
                title="Rebuild this date's alerts and tasks from the stored events (no LLM)"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${reassessing ? 'animate-spin' : ''}`} /> Recompute (no LLM)
              </button>
              <button
                onClick={runDrop}
                disabled={running || !drop || !asOf}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded font-semibold text-sm text-cream bg-primary-dark hover:bg-dark-olive transition-all active:scale-95 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Radar className="w-4 h-4" />}
                {running ? `Processing ${drop}…` : drop ? `Process ${drop} at ${fmtDate(asOf)}` : 'No drop released yet'}
              </button>
            </div>
            <span className="font-mono text-[10px] text-secondary-olive text-left lg:text-right max-w-sm">
              {useLlm && llm?.configured
                ? `Code maps first; the rest goes to the LLM in batches (≤ ${overview?.max_llm_calls ?? 4} calls).`
                : 'Code mapping only: no LLM call.'}{' '}
              A re-run replaces this drop's events for the date.
            </span>
          </div>
        </div>

        {running && (
          <Notice>
            <span className="flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Mapping {drop} events to contracts and clauses, then reassessing exposure through NORNS…</span>
          </Notice>
        )}
        {runError && (
          <Notice tone="error">
            <span className="flex items-start gap-2"><XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {runError}</span>
          </Notice>
        )}
        {runResult && (
          <Notice tone="ok">
            <span className="font-bold">
              {runResult.drop} processed at {fmtDate(runResult.as_of)}: {runResult.counts.total} visible event(s) ·{' '}
              {runResult.counts.mapped_by_code} mapped by code · {runResult.counts.mapped_by_llm} by LLM · {runResult.counts.noise} noise ·{' '}
              {runResult.counts.unmapped} unmapped · {runResult.counts.unparseable} unparseable · {runResult.counts.not_yet_visible} dated later
            </span>
            <span className="block">
              Worst case {fmtCurrency(runResult.worst_case.before, 0)} → {fmtCurrency(runResult.worst_case.after_events, 0)} ·{' '}
              {runResult.llm.llm_calls} LLM call(s), {runResult.llm.cache_hits} cached,{' '}
              {(runResult.llm.input_tokens + runResult.llm.output_tokens).toLocaleString()} tokens
            </span>
          </Notice>
        )}
        {flash && <Notice tone={flash.tone}>{flash.text}</Notice>}
        {board && !hasRunOnDate && (
          <Notice tone="warn">
            {(overview?.run_dates || []).some((d) => d <= asOf)
              ? `No HEIMDALL run on ${fmtDate(asOf)}: events from earlier runs are shown. Process a released drop here, or Recompute to rebuild this date's alerts and tasks.`
              : `No HEIMDALL run on or before ${fmtDate(asOf)} yet. ${released.length ? `Process ${released[released.length - 1].name} to map its events.` : 'The first drop is released at Checkpoint 1.'}`}
          </Notice>
        )}
      </div>

      {boardError && <Notice tone="error">{boardError}</Notice>}

      {/* ── Exposure + counts ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <MetricCard label="Worst case · no events" value={wc ? fmtCurrency(wc.baseline, 0) : '—'} sub="NORNS, if nobody acts" />
        <MetricCard
          label="After event facts"
          value={wc ? fmtCurrency(wc.after_events, 0) : '—'}
          sub={wc ? `${signedMoney(afterDelta)} from mapped events` : ' '}
          color={afterDelta > 0 ? '#C83D3D' : '#303B28'}
        />
        <MetricCard
          label="Live exposure"
          value={wc ? fmtCurrency(wc.live, 0) : '—'}
          sub={wc ? `${signedMoney(liveDelta)} from task-board payments` : ' '}
          color="#C83D3D"
        />
        <MetricCard
          label="Alerts"
          value={board ? alerts.length : '—'}
          sub={board ? `${sevCounts.critical} critical · ${sevCounts.high} high` : ' '}
          color={sevCounts.critical ? '#C83D3D' : '#303B28'}
        />
        <MetricCard
          label="Events behind this date"
          value={counts ? counts.total : '—'}
          sub={counts ? `${counts.mapped_by_code + counts.mapped_by_llm} mapped · ${counts.noise} noise · ${counts.unmapped} unmapped` : ' '}
        />
      </div>

      {/* ── Alerts + exposure by contract ─────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        <section className="lg:col-span-7 rounded-lg border border-border-subtle bg-ivory p-4 shadow-sm space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h2 className="font-bold text-dark-olive flex items-center gap-2">
                <Bell className="w-4 h-4 text-odin-red" /> Alert feed · {fmtDate(asOf)}
              </h2>
              <p className="text-xs mt-0.5 text-secondary-olive">Deadlines, renewals, payments and potential breaches, most severe first.</p>
            </div>
            <div className="flex items-center gap-1 flex-wrap">
              {SEVERITY_ORDER.map((s) => (
                <span key={s} className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase" style={{ background: SEVERITY[s].bg, color: SEVERITY[s].text }}>
                  {sevCounts[s]} {s}
                </span>
              ))}
            </div>
          </div>
          {loading && !board ? (
            <div className="flex items-center justify-center py-10 gap-2 font-mono text-xs text-secondary-olive">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading the board…
            </div>
          ) : alerts.length === 0 ? (
            <p className="text-center py-8 font-mono text-xs text-secondary-olive">No alerts on this date.</p>
          ) : (
            <div className="space-y-2 max-h-[560px] overflow-y-auto pr-1">
              {alerts.map((a) => (
                <AlertRow key={a.alert_key} alert={a} asOf={asOf} onOpenNorns={openNorns} />
              ))}
            </div>
          )}
          <label className="flex items-center gap-2 font-mono text-[11px] text-secondary-olive pt-1 border-t border-border-subtle">
            <input type="checkbox" checked={showNoise} onChange={(e) => setShowNoise(e.target.checked)} className="accent-[#303B28]" />
            Show filtered noise ({noise.length})
          </label>
          {showNoise &&
            noise.map((e) => (
              <p key={`${e.drop_name}-${e.line_no}`} className="font-mono text-[11px] text-secondary-olive leading-snug">
                <span className="font-bold text-dark-olive">{e.event_id}</span> {e.subject || ''} — {e.noise_reason}
              </p>
            ))}
        </section>

        <section className="lg:col-span-5 space-y-5">
          <div className="rounded-lg border border-border-subtle bg-ivory p-4 shadow-sm space-y-3">
            <h2 className="font-bold text-dark-olive flex items-center gap-2">
              <Zap className="w-4 h-4 text-accent-gold" /> Exposure by contract
            </h2>
            {!wc || Object.keys(wc.by_contract || {}).length === 0 ? (
              <p className="font-mono text-xs text-secondary-olive">No quantified exposure on this date.</p>
            ) : (
              Object.entries(wc.by_contract).map(([c, v]) => {
                const max = Math.max(...Object.values(wc.by_contract).map((x) => parseFloat(x.after_events) || 0), 1);
                const after = parseFloat(v.after_events) || 0;
                const live = parseFloat(v.live) || 0;
                return (
                  <div key={c} className="space-y-1">
                    <div className="flex items-baseline justify-between font-mono text-xs">
                      <span className="font-bold text-primary-dark">{board?.process_labels?.[c] || c}</span>
                      <span className="text-dark-olive font-semibold">{fmtCurrency(live, 0)}</span>
                    </div>
                    <div className="h-2 rounded bg-border-subtle/60 overflow-hidden relative">
                      <div className="absolute inset-y-0 left-0 bg-[#E6C9C4]" style={{ width: `${(after / max) * 100}%` }} />
                      <div className="absolute inset-y-0 left-0 bg-odin-red" style={{ width: `${(live / max) * 100}%` }} />
                    </div>
                    {after !== live && (
                      <p className="font-mono text-[10px] text-secondary-olive">
                        {fmtCurrency(after, 0)} after events → {fmtCurrency(live, 0)} with board payments
                      </p>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {overview?.severity_scale && (
            <div className="rounded-lg border border-border-subtle bg-ivory p-4 space-y-1.5">
              <span className="font-mono text-[10px] uppercase tracking-wider font-bold text-secondary-olive">Alert severity scale</span>
              {Object.entries(overview.severity_scale).map(([k, v]) => (
                <p key={k} className="text-[11px] leading-snug text-secondary-olive">
                  <span className="font-mono font-bold" style={{ color: SEVERITY[k]?.text }}>{k}</span>: {v}
                </p>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* ── Event feed ────────────────────────────────────────────────── */}
      <section className="rounded-lg border border-border-subtle bg-ivory shadow-sm overflow-hidden">
        <div className="p-4 border-b border-border-subtle flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h2 className="font-bold text-dark-olive flex items-center gap-2">
              <Inbox className="w-4 h-4 text-primary" /> Event feed
            </h2>
            <p className="text-xs mt-0.5 text-secondary-olive">
              Each visible event with the contracts and clauses it maps to, the NORNS fact it adds and its worst-case delta. Click a row for the raw line.
            </p>
          </div>
          {counts && (
            <span className="font-mono text-[10px] text-secondary-olive">
              {counts.mapped_by_code} by code · {counts.mapped_by_llm} by LLM · {counts.noise} noise · {counts.unmapped} unmapped · {counts.unparseable} unparseable
            </span>
          )}
        </div>
        {events.length === 0 ? (
          <p className="text-center py-10 font-mono text-xs text-secondary-olive">No events processed on or before {fmtDate(asOf)}.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="font-mono text-[10px] uppercase tracking-wider bg-cream text-secondary-olive">
                  <th className="py-2.5 px-3">Event</th>
                  <th className="py-2.5 px-3">Subject / From</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Clauses</th>
                  <th className="py-2.5 px-3">Fact for NORNS</th>
                  <th className="py-2.5 px-3 text-right">Exposure Δ</th>
                </tr>
              </thead>
              <tbody>
                {visibleEvents.map((e) => {
                  const key = `${e.drop_name}-${e.line_no}`;
                  return <EventRow key={key} ev={e} expanded={expanded === key} onToggle={() => setExpanded(expanded === key ? null : key)} />;
                })}
              </tbody>
            </table>
            {!showNoise && noise.length > 0 && (
              <p className="px-4 py-2 border-t border-border-subtle font-mono text-[10px] text-secondary-olive">
                {noise.length} noise event(s) hidden ·{' '}
                <button onClick={() => setShowNoise(true)} className="underline text-primary">show them</button>
              </p>
            )}
          </div>
        )}
      </section>

      {/* ── Task board + progress ─────────────────────────────────────── */}
      <HeimdallTaskBoard
        tasks={tasks}
        asOf={asOf}
        statuses={overview?.task_statuses || ['Not Complete', 'In Progress', 'Completed']}
        processLabels={board?.process_labels}
        busyTaskId={busyTaskId}
        onSetStatus={setTaskStatus}
      />
    </div>
  );
}
