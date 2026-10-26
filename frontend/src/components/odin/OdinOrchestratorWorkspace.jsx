import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Clock, GitBranch, History, KeyRound, Loader2, Network, Play, Upload, Workflow } from 'lucide-react';
import { fetchOdinOverview, fetchOdinRuns, runOdinPipeline } from '../../services/api';
import { fmtDate } from '../common/format';
import PipelineStepper, { FINISHED, RunBadge, STAGES, STAGE_STATUS, StageDetails, usePipelineRun } from './PipelineStepper';

const AGENT_STATUS = {
  complete: { bg: '#EAF5EA', text: '#2E7D32' },
  partial: { bg: '#FFF8E1', text: '#B76E00' },
  failed: { bg: '#FBEBEB', text: '#C83D3D' },
  in_progress: { bg: '#F7F1E1', text: '#8C7340' },
  pending: { bg: '#F5F1E6', text: '#727665' },
};

function when(ts) {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}

function seconds(run) {
  if (!run.started_at || !run.finished_at) return null;
  return Math.max(0, Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000));
}

function StageDots({ run }) {
  const done = FINISHED.includes(run.status);
  const by = Object.fromEntries((run.stages || []).map((s) => [
    s.name, done && ['pending', 'running'].includes(s.status) ? 'stopped' : s.status]));
  return (
    <span className="inline-flex items-center gap-1">
      {STAGES.map((def) => {
        const st = STAGE_STATUS[by[def.name]] || STAGE_STATUS.pending;
        return (
          <span key={def.name} title={`${def.label}: ${st.label}`} className="w-2.5 h-2.5 rounded-full border"
                style={{ background: by[def.name] === 'pending' ? '#FCFAF3' : st.text, borderColor: st.text }} />
        );
      })}
    </span>
  );
}

export default function OdinOrchestratorWorkspace() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [overview, setOverview] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [runs, setRuns] = useState([]);
  const [queue, setQueue] = useState({ current: null, queued: 0 });
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get('run'));
  const [run] = usePipelineRun(selectedRunId);
  const [docId, setDocId] = useState(searchParams.get('doc') || '');
  const [asOf, setAsOf] = useState(null);
  const [forceThor, setForceThor] = useState(false);
  const [runLoki, setRunLoki] = useState(true);
  const [heimdallLlm, setHeimdallLlm] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  const loadAll = useCallback(() => {
    return Promise.all([fetchOdinOverview(), fetchOdinRuns(null, 25)])
      .then(([o, r]) => {
        setOverview(o);
        setRuns(r.runs || []);
        setQueue({ current: r.current, queued: r.queued });
        setLoadError(null);
        return [o, r];
      })
      .catch((e) => {
        setLoadError(e.message);
        return [null, null];
      });
  }, []);

  // First load: pick the run to show, the document and the date for a new run.
  useEffect(() => {
    loadAll().then(([o, r]) => {
      if (!o) return;
      setAsOf((prev) => prev || o.default_as_of);
      setRunLoki(Boolean(o.options?.run_loki));
      setHeimdallLlm(Boolean(o.options?.heimdall_use_llm));
      setDocId((prev) => prev || r?.runs?.[0]?.doc_id || o.documents?.find((d) => d.kind === 'contract')?.doc_id || '');
      setSelectedRunId((prev) => prev || r?.runs?.[0]?.run_id || null);
    });
  }, [loadAll]);

  // While anything is queued or running, keep the history and the workstreams fresh.
  const busy = Boolean(queue.current) || queue.queued > 0 || runs.some((x) => !FINISHED.includes(x.status));
  useEffect(() => {
    const timer = setInterval(loadAll, busy ? 4000 : 15000);
    return () => clearInterval(timer);
  }, [busy, loadAll]);

  // The shown run just finished: refresh everything it changed.
  useEffect(() => {
    if (run && FINISHED.includes(run.status)) loadAll();
  }, [run?.status, run?.run_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const params = {};
    if (selectedRunId) params.run = selectedRunId;
    if (docId) params.doc = docId;
    setSearchParams(params, { replace: true });
  }, [selectedRunId, docId]); // eslint-disable-line react-hooks/exhaustive-deps

  const dateOptions = useMemo(() => {
    const out = new Map();
    (overview?.checkpoints || []).forEach((p) => out.set(p.date, p.label));
    if (overview?.default_as_of && !out.has(overview.default_as_of)) out.set(overview.default_as_of, 'Clock');
    return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [overview]);

  const submit = () => {
    if (!docId) return;
    setSubmitting(true);
    setSubmitError(null);
    runOdinPipeline(docId, { asOf, forceThor, runLoki, heimdallUseLlm: heimdallLlm })
      .then((r) => {
        setSelectedRunId(r.run_id);
        return loadAll();
      })
      .catch((e) => setSubmitError(e.message))
      .finally(() => setSubmitting(false));
  };

  const llm = overview?.llm || {};
  const budget = overview?.budget;
  const shownRun = run && run.run_id === selectedRunId ? run : runs.find((x) => x.run_id === selectedRunId) || null;

  return (
    <div className="space-y-5">
      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <div className="rounded-lg border border-border-subtle bg-ivory p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-[10px] font-bold uppercase px-2 py-0.5 rounded tracking-wider bg-[#E3E7D3] text-primary-dark">
                ODIN · ORCHESTRATOR
              </span>
              <span className="font-mono text-[11px] text-secondary-olive">THOR → NORNS → LOKI → HEIMDALL</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-primary-dark">Upload once. Four agents, one evidence trail.</h1>
            <p className="text-sm max-w-3xl text-secondary-olive">
              ODIN plans one workstream per contract family plus a cross-contract one, runs THOR → NORNS → LOKI → HEIMDALL on
              every uploaded contract, records each stage with its numbers and, when it is not complete, the reason. LLM
              spend stays inside a per-run budget, and every agent falls back across your API keys when one is rate-limited
              or out of quota.
            </p>
            <button onClick={() => navigate('/thor')} className="mt-1 inline-flex items-center gap-1.5 font-mono text-xs font-semibold text-primary hover:underline">
              <Upload className="w-3.5 h-3.5" /> Upload a contract on the THOR page: the pipeline starts by itself
            </button>
          </div>
          <div className="shrink-0 rounded border border-border-subtle bg-cream px-3 py-2 font-mono text-[11px] space-y-1 min-w-[250px]">
            <div className="flex items-center gap-1.5 font-semibold text-dark-olive">
              <KeyRound className="w-3.5 h-3.5 text-primary" /> Agents' LLM access
            </div>
            {STAGES.map((def) => {
              const s = llm[def.name];
              return (
                <div key={def.name} className="flex items-center justify-between gap-3">
                  <span className="text-dark-olive">{def.label}</span>
                  {s ? (
                    <span style={{ color: s.configured ? '#2E7D32' : '#8A5300' }}>
                      {s.configured ? `ready · ${s.keys} key${s.keys === 1 ? '' : 's'}` : def.name === 'norns' ? 'no LLM (optional)' : 'no key'}
                    </span>
                  ) : (
                    <span className="text-secondary-olive">…</span>
                  )}
                </div>
              );
            })}
            {budget && (
              <div className="pt-1 border-t border-border-subtle text-secondary-olive">
                ≤ {budget.max_llm_calls} LLM calls · {budget.max_tokens_budget.toLocaleString()} tokens per run
              </div>
            )}
            {llm.thor && !llm.thor.configured && <div className="text-[10px] text-[#8A5300] leading-snug max-w-[260px]">{llm.thor.problem}</div>}
          </div>
        </div>
      </div>

      {loadError && (
        <div className="rounded-lg border p-3 font-mono text-xs flex items-start gap-2" style={{ background: '#FBEBEB', borderColor: 'rgba(200,61,61,0.35)', color: '#8F2929' }}>
          <AlertTriangle className="w-4 h-4 shrink-0" /> {loadError}
        </div>
      )}

      {/* ── Run the pipeline ─────────────────────────────────────────── */}
      <div className="rounded-lg border border-border-subtle bg-ivory p-4 shadow-xs space-y-3">
        <h2 className="font-bold text-dark-olive flex items-center gap-2">
          <Workflow className="w-4 h-4 text-primary" /> Run the pipeline on a stored document
        </h2>
        <div className="flex flex-col lg:flex-row lg:items-end gap-4 justify-between">
          <div className="flex flex-col sm:flex-row gap-4 flex-wrap">
            <label className="font-mono text-[11px] text-secondary-olive space-y-1">
              <span className="block uppercase tracking-wider font-semibold">Document</span>
              <select
                value={docId}
                onChange={(e) => setDocId(e.target.value)}
                className="block w-full sm:w-80 px-2 py-1.5 rounded border border-border-subtle bg-cream/70 text-dark-olive text-xs"
              >
                {(overview?.documents || []).map((d) => (
                  <option key={d.doc_id} value={d.doc_id}>
                    {d.doc_id} · {d.kind} · THOR {d.thor_status}
                  </option>
                ))}
              </select>
            </label>
            <div className="font-mono text-[11px] text-secondary-olive space-y-1">
              <span className="block uppercase tracking-wider font-semibold flex items-center gap-1"><Clock className="w-3 h-3" /> Clock date</span>
              <div className="flex items-center gap-1.5 flex-wrap">
                {dateOptions.map(([d, label]) => (
                  <button
                    key={d}
                    onClick={() => setAsOf(d)}
                    className={`px-2 py-1 rounded border text-[11px] ${asOf === d ? 'bg-primary-dark text-white border-primary-dark font-semibold' : 'bg-cream/70 text-dark-olive border-border-subtle hover:bg-cream'}`}
                  >
                    {label} · {fmtDate(d)}
                  </button>
                ))}
                <input type="date" value={asOf || ''} onChange={(e) => e.target.value && setAsOf(e.target.value)}
                       className="px-2 py-0.5 rounded border border-border-subtle bg-cream/70 text-[11px] text-dark-olive" aria-label="Custom clock date" />
              </div>
            </div>
          </div>
          <div className="flex flex-col items-start lg:items-end gap-2">
            <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-dark-olive">
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={forceThor} onChange={(e) => setForceThor(e.target.checked)} className="accent-[#303B28]" /> Re-extract with THOR</label>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={runLoki} onChange={(e) => setRunLoki(e.target.checked)} className="accent-[#303B28]" /> LOKI review</label>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={heimdallLlm} onChange={(e) => setHeimdallLlm(e.target.checked)} className="accent-[#303B28]" /> HEIMDALL may use the LLM</label>
            </div>
            <button
              onClick={submit}
              disabled={submitting || !docId || !asOf}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded font-semibold text-sm text-cream bg-primary-dark hover:bg-dark-olive transition-all active:scale-95 shadow-sm disabled:opacity-50"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              Run ODIN pipeline on {docId || '—'}
            </button>
            <span className="font-mono text-[10px] text-secondary-olive text-left lg:text-right max-w-sm">
              THOR is skipped when the text is unchanged and already extracted, so a re-run mostly costs LOKI's one call.
              {queue.current ? ' A run is in progress: this one waits for it.' : ''}
            </span>
          </div>
        </div>
        {submitError && (
          <p className="font-mono text-[11px]" style={{ color: '#8F2929' }}>{submitError}</p>
        )}
      </div>

      {/* ── The selected run ─────────────────────────────────────────── */}
      <section className="rounded-lg border border-border-subtle bg-ivory p-4 shadow-sm space-y-4">
        <h2 className="font-bold text-dark-olive flex items-center gap-2">
          <Network className="w-4 h-4 text-primary" /> Pipeline run
          {shownRun && <span className="font-mono text-[10px] font-normal text-secondary-olive">{shownRun.run_id}</span>}
        </h2>
        {shownRun ? (
          <>
            <PipelineStepper run={shownRun} />
            <StageDetails run={shownRun} />
            <div className="rounded-lg border border-border-subtle bg-cream/50 p-3 font-mono text-[11px] text-dark-olive space-y-1">
              <div className="font-bold text-primary-dark flex items-center gap-1.5"><GitBranch className="w-3.5 h-3.5" /> ODIN's plan</div>
              <div><span className="text-secondary-olive">workstream:</span> {shownRun.plan?.workstream || '—'} ({(shownRun.plan?.family || []).join(', ') || shownRun.doc_id})</div>
              <div><span className="text-secondary-olive">NORNS follows:</span> {(shownRun.plan?.followed || []).join(', ') || '—'}</div>
              <div><span className="text-secondary-olive">LOKI reviews:</span> {(shownRun.plan?.loki_docs || []).join(', ') || 'nothing'}</div>
              <div>
                <span className="text-secondary-olive">HEIMDALL:</span>{' '}
                {(shownRun.plan?.heimdall || []).length
                  ? shownRun.plan.heimdall.map((a) => `${a.action} ${a.drop} (${a.why})`).join('; ')
                  : 'no drop to (re)process: alerts and the task board rebuilt'}
              </div>
              <div><span className="text-secondary-olive">started:</span> {when(shownRun.started_at)} · <span className="text-secondary-olive">finished:</span> {when(shownRun.finished_at)}{seconds(shownRun) !== null ? ` · ${seconds(shownRun)}s` : ''}</div>
            </div>
          </>
        ) : (
          <p className="font-mono text-xs text-secondary-olive">No pipeline run yet. Upload a contract on the THOR page, or run one above.</p>
        )}
      </section>

      {/* ── History + workstreams ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
        <section className="xl:col-span-7 rounded-lg border border-border-subtle bg-ivory shadow-sm overflow-hidden">
          <div className="p-4 border-b border-border-subtle flex items-center justify-between gap-2">
            <h2 className="font-bold text-dark-olive flex items-center gap-2"><History className="w-4 h-4 text-primary" /> Runs</h2>
            <span className="font-mono text-[10px] text-secondary-olive">
              {queue.current ? `running ${queue.current.slice(-6)}` : 'idle'}{queue.queued ? ` · ${queue.queued} queued` : ''}
            </span>
          </div>
          {runs.length === 0 ? (
            <p className="p-6 text-center font-mono text-xs text-secondary-olive">No runs yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="font-mono text-[10px] uppercase tracking-wider bg-cream text-secondary-olive">
                    <th className="py-2 px-3">Document</th>
                    <th className="py-2 px-3">Clock date</th>
                    <th className="py-2 px-3">Status</th>
                    <th className="py-2 px-3">Stages</th>
                    <th className="py-2 px-3">LLM</th>
                    <th className="py-2 px-3">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr
                      key={r.run_id}
                      onClick={() => setSelectedRunId(r.run_id)}
                      className={`cursor-pointer border-t border-border-subtle/70 hover:bg-cream/60 ${r.run_id === selectedRunId ? 'bg-cream' : ''}`}
                    >
                      <td className="py-2 px-3 font-mono font-bold text-primary-dark">
                        {r.doc_id}
                        <span className="block font-normal text-[10px] text-secondary-olive">{r.source === 'upload' ? 'upload' : 'by hand'}</span>
                      </td>
                      <td className="py-2 px-3 font-mono">{fmtDate(r.as_of)}</td>
                      <td className="py-2 px-3"><RunBadge status={r.status} /></td>
                      <td className="py-2 px-3"><StageDots run={r} /></td>
                      <td className="py-2 px-3 font-mono text-[11px]">{r.llm?.llm_calls ?? '—'}</td>
                      <td className="py-2 px-3 font-mono text-[11px] text-secondary-olive">{when(r.started_at || r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="xl:col-span-5 rounded-lg border border-border-subtle bg-ivory p-4 shadow-sm space-y-3">
          <div>
            <h2 className="font-bold text-dark-olive flex items-center gap-2"><GitBranch className="w-4 h-4 text-primary" /> Workstreams</h2>
            <p className="font-mono text-[10px] text-secondary-olive mt-0.5">
              One per contract family plus cross-contract (FR1.2), with each agent's status (FR1.3).
            </p>
          </div>
          <div className="space-y-2 max-h-[520px] overflow-y-auto pr-1">
            {(overview?.workstreams || []).map((w) => (
              <div key={w.id} className="rounded border border-border-subtle bg-white p-2.5 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-bold text-primary-dark">{w.id}</span>
                  <span className="font-mono text-[10px] text-secondary-olive truncate max-w-[60%]" title={w.title}>{w.title}</span>
                </div>
                <div className="font-mono text-[10px] text-secondary-olive truncate" title={(w.members || []).join(', ')}>
                  {(w.members || []).join(' · ')}
                </div>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(w.agent_status || {})
                    .filter(([agent]) => !agent.includes(':'))
                    .map(([agent, st]) => {
                      const c = AGENT_STATUS[st] || AGENT_STATUS.pending;
                      return (
                        <span key={agent} className="font-mono text-[9px] font-bold px-1.5 py-0.5 rounded uppercase" style={{ background: c.bg, color: c.text }}>
                          {agent} {st}
                        </span>
                      );
                    })}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
