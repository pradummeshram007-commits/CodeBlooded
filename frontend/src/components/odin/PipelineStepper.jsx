import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowRight, ArrowUpRight, CheckCircle2, Circle, Clock, Database, Loader2, MinusCircle, Radar,
  ShieldAlert, XCircle,
} from 'lucide-react';
import { fetchOdinRun } from '../../services/api';
import { fmtCurrency, fmtDate } from '../common/format';

export const STAGES = [
  { name: 'thor', label: 'THOR', role: 'Extract clauses', icon: Database },
  { name: 'norns', label: 'NORNS', role: 'Timeline & exposure', icon: Clock },
  { name: 'loki', label: 'LOKI', role: 'Adversarial review', icon: ShieldAlert },
  { name: 'heimdall', label: 'HEIMDALL', role: 'Event monitoring', icon: Radar },
];

export const STAGE_STATUS = {
  pending: { label: 'Waiting', bg: '#F5F1E6', text: '#727665', border: '#DCDCCB', icon: Circle },
  running: { label: 'Running', bg: '#F7F1E1', text: '#8C7340', border: '#B79A59', icon: Loader2 },
  complete: { label: 'Complete', bg: '#EAF5EA', text: '#2E7D32', border: 'rgba(46,125,50,0.35)', icon: CheckCircle2 },
  partial: { label: 'Partial', bg: '#FFF8E1', text: '#B76E00', border: 'rgba(183,110,0,0.35)', icon: AlertTriangle },
  failed: { label: 'Failed', bg: '#FBEBEB', text: '#C83D3D', border: 'rgba(200,61,61,0.4)', icon: XCircle },
  skipped: { label: 'Skipped', bg: '#F5F1E6', text: '#727665', border: '#DCDCCB', icon: MinusCircle },
  not_applicable: { label: 'Not needed', bg: '#F5F1E6', text: '#727665', border: '#DCDCCB', icon: MinusCircle },
  stopped: { label: 'Stopped', bg: '#FBEBEB', text: '#8F2929', border: 'rgba(143,41,41,0.35)', icon: XCircle },
};

export const RUN_STATUS = {
  queued: { label: 'Queued', bg: '#F5F1E6', text: '#727665' },
  running: { label: 'Running', bg: '#F7F1E1', text: '#8C7340' },
  complete: { label: 'Complete', bg: '#EAF5EA', text: '#2E7D32' },
  partial: { label: 'Partial', bg: '#FFF8E1', text: '#B76E00' },
  failed: { label: 'Failed', bg: '#FBEBEB', text: '#C83D3D' },
  interrupted: { label: 'Interrupted', bg: '#FBEBEB', text: '#8F2929' },
};

export const FINISHED = ['complete', 'partial', 'failed', 'interrupted'];

/** Polls a pipeline run every 2 s until it finishes (complete, partial, failed or interrupted). */
export function usePipelineRun(runId, initial = null) {
  const [run, setRun] = useState(initial);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!runId) {
      setRun(null);
      return undefined;
    }
    let cancelled = false;
    let timer;
    const tick = () =>
      fetchOdinRun(runId)
        .then((r) => {
          if (cancelled) return;
          setRun(r);
          setError(null);
          if (!FINISHED.includes(r.status)) timer = setTimeout(tick, 2000);
        })
        .catch((e) => {
          if (cancelled) return;
          setError(e.message);
          timer = setTimeout(tick, 4000);
        });
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [runId]);
  return [run, error];
}

/** Where each agent's own page shows what it did for the run. */
export function agentLink(stage, run) {
  const asOf = run.as_of;
  const doc = encodeURIComponent(run.doc_id);
  switch (stage) {
    case 'thor':
      return `/thor?doc=${doc}`;
    case 'norns':
      return `/norns?doc_id=${encodeURIComponent(run.plan?.root || run.doc_id)}&as_of=${asOf}`;
    case 'loki':
      return `/loki?doc=${encodeURIComponent((run.plan?.loki_docs || [])[0] || run.doc_id)}&as_of=${asOf}`;
    default:
      return `/heimdall?as_of=${asOf}`;
  }
}

export function RunBadge({ status }) {
  const s = RUN_STATUS[status] || RUN_STATUS.queued;
  return (
    <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase whitespace-nowrap" style={{ background: s.bg, color: s.text }}>
      {s.label}
    </span>
  );
}

function StageCard({ def, stage: given, run, onOpen }) {
  // A run the server stopped (interrupted) leaves its stage "running" and the later ones "pending": they never finish.
  const stopped = given && run && FINISHED.includes(run.status) && ['pending', 'running'].includes(given.status);
  const stage = stopped ? { ...given, status: 'stopped' } : given;
  const st = STAGE_STATUS[stage?.status] || STAGE_STATUS.pending;
  const Icon = def.icon;
  const StatusIcon = st.icon;
  const finished = stage && !['pending', 'running', 'stopped'].includes(stage.status);
  return (
    <div className="rounded-lg border bg-white p-3 flex flex-col gap-1.5 min-w-0 relative overflow-hidden" style={{ borderColor: st.border }}>
      <div className="absolute top-0 left-0 h-0.5 w-full" style={{ background: st.text, opacity: stage?.status === 'pending' ? 0.15 : 0.7 }} />
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-mono text-xs font-bold text-primary-dark">
          <Icon className="w-3.5 h-3.5 text-primary" />
          {def.label}
        </span>
        <span className="inline-flex items-center gap-1 font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase" style={{ background: st.bg, color: st.text }}>
          <StatusIcon className={`w-3 h-3 ${stage?.status === 'running' ? 'animate-spin' : ''}`} />
          {st.label}
        </span>
      </div>
      <span className="font-mono text-[10px] text-secondary-olive">{def.role}</span>
      <p className="text-xs text-dark-olive leading-snug min-h-[2.5em]">
        {stage?.summary || (stage?.status === 'running' ? 'working…' : '—')}
      </p>
      {stage?.reason && stage.status !== 'complete' && (
        <p className="font-mono text-[10px] leading-snug" style={{ color: stage.status === 'failed' ? '#8F2929' : '#8A5300' }}>
          {stage.reason.length > 220 ? `${stage.reason.slice(0, 220)}…` : stage.reason}
        </p>
      )}
      <div className="mt-auto pt-1 flex items-center justify-between gap-2 font-mono text-[10px] text-secondary-olive">
        <span>
          {stage?.seconds !== null && stage?.seconds !== undefined ? `${stage.seconds}s` : ''}
          {stage?.llm_calls ? ` · ${stage.llm_calls} LLM call${stage.llm_calls === 1 ? '' : 's'}` : ''}
          {stage?.cache_hits ? ` · ${stage.cache_hits} cached` : ''}
        </span>
        {finished && run && (
          <button onClick={() => onOpen(agentLink(def.name, run))} className="font-semibold text-primary hover:underline inline-flex items-center gap-0.5">
            Open <ArrowUpRight className="w-3 h-3" />
          </button>
        )}
      </div>
    </div>
  );
}

/** THOR -> NORNS -> LOKI -> HEIMDALL for one run. Without a run: the four agents, waiting. */
export default function PipelineStepper({ run, title }) {
  const navigate = useNavigate();
  const stages = Object.fromEntries((run?.stages || []).map((s) => [s.name, s]));
  const llm = run?.llm || {};
  return (
    <div className="space-y-2">
      {run && (
        <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-[11px]">
          <span className="flex items-center gap-2 flex-wrap text-dark-olive">
            <RunBadge status={run.status} />
            <span className="font-bold">{title || `ODIN pipeline · ${run.doc_id}`}</span>
            <span className="text-secondary-olive">
              as of {fmtDate(run.as_of)} · {run.source === 'upload' ? 'started by upload' : 'started by hand'}
            </span>
          </span>
          <span className="text-secondary-olive">
            {FINISHED.includes(run.status)
              ? `${llm.llm_calls ?? 0} LLM call(s) · ${llm.cache_hits ?? 0} cached · ${(llm.tokens ?? 0).toLocaleString()} tokens`
              : run.status === 'queued'
              ? 'waiting for the run before it'
              : `now: ${(run.current_stage || '').toUpperCase()}`}
          </span>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] gap-2 items-stretch">
        {STAGES.map((def, i) => (
          <React.Fragment key={def.name}>
            <StageCard def={def} stage={stages[def.name] || (run ? null : { status: 'pending' })} run={run} onOpen={navigate} />
            {i < STAGES.length - 1 && (
              <div className="hidden lg:flex items-center justify-center text-sage">
                <ArrowRight className="w-4 h-4" />
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
      {run && run.reason && FINISHED.includes(run.status) && run.status !== 'complete' && (
        <p className="font-mono text-[10px] text-secondary-olive leading-snug">
          Not complete because: {run.reason.length > 400 ? `${run.reason.slice(0, 400)}…` : run.reason}
        </p>
      )}
    </div>
  );
}

/** The numbers each agent reported for the run (ODIN page). */
export function StageDetails({ run }) {
  const s = Object.fromEntries((run?.stages || []).map((x) => [x.name, x.details || {}]));
  const thor = s.thor || {};
  const norns = s.norns || {};
  const loki = s.loki || {};
  const heim = s.heimdall || {};
  const Row = ({ k, v }) => (
    <div className="flex justify-between gap-3 py-0.5 border-b border-border-subtle/40 last:border-0">
      <span className="text-secondary-olive">{k}</span>
      <span className="text-dark-olive font-semibold text-right">{v ?? '—'}</span>
    </div>
  );
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 font-mono text-[11px]">
      <div className="rounded-lg border border-border-subtle bg-ivory p-3">
        <div className="font-bold text-primary-dark mb-1.5">THOR</div>
        <Row k="document status" v={thor.doc_status} />
        <Row k="fields extracted" v={thor.fields} />
        <Row k="citations verified" v={thor.citations_verified !== undefined ? `${thor.citations_verified} / ${(thor.citations_verified || 0) + (thor.citations_failed || 0)}` : null} />
        <Row k="coverage" v={thor.coverage !== undefined && thor.coverage !== null ? `${Number(thor.coverage).toFixed(1)}%` : null} />
        <Row k="missing / ambiguous" v={thor.missing !== undefined ? `${thor.missing} / ${thor.ambiguous}` : null} />
        <Row k="open flags" v={thor.open_flags} />
        {thor.deterministic_fields > 0 && <Row k="fallback fields (no LLM)" v={thor.deterministic_fields} />}
      </div>
      <div className="rounded-lg border border-border-subtle bg-ivory p-3">
        <div className="font-bold text-primary-dark mb-1.5">NORNS</div>
        <Row k="contract followed" v={norns.root || '—'} />
        <Row k="rules / dated obligations" v={norns.rules !== undefined ? `${norns.rules} / ${norns.instances}` : null} />
        <Row k="worst case (this contract)" v={norns.root_worst_case !== undefined ? fmtCurrency(norns.root_worst_case, 0) : null} />
        <Row k="worst case (portfolio)" v={norns.worst_case_total !== undefined ? fmtCurrency(norns.worst_case_total, 0) : null} />
        <Row k="next deadline" v={norns.next_deadline ? `${norns.next_deadline.name} · ${fmtDate(norns.next_deadline.due)}` : null} />
        {(norns.flags || []).slice(0, 3).map((f, i) => (
          <p key={i} className="text-[10px] text-[#8A5300] leading-snug mt-1">• {f}</p>
        ))}
      </div>
      <div className="rounded-lg border border-border-subtle bg-ivory p-3">
        <div className="font-bold text-primary-dark mb-1.5">LOKI</div>
        {Object.entries(loki.reviews || {}).map(([doc, r]) => (
          <Row key={doc} k={`${doc} review`} v={`${r.status} · ${r.accepted} accepted · ${r.rejected} rejected`} />
        ))}
        {(loki.top_findings || []).map((f, i) => (
          <p key={i} className="text-[10px] text-dark-olive leading-snug mt-1">
            <span className="font-bold uppercase" style={{ color: f.severity === 'critical' ? '#C83D3D' : '#8C7340' }}>{f.severity}</span> {f.title}
          </p>
        ))}
        {!loki.reviews && <p className="text-secondary-olive">No review in this run.</p>}
      </div>
      <div className="rounded-lg border border-border-subtle bg-ivory p-3">
        <div className="font-bold text-primary-dark mb-1.5">HEIMDALL</div>
        {(heim.actions || []).map((a, i) => (
          <p key={i} className="text-[10px] text-dark-olive leading-snug mb-1">
            <span className="font-bold">{a.action} {a.drop}</span>: {a.why}
            {typeof a.result === 'string' ? ` → ${a.result}` : a.result ? ` → ${a.result.total} events, ${a.result.mapped_by_code + a.result.mapped_by_llm} mapped` : ''}
          </p>
        ))}
        <Row k="events behind the date" v={heim.events} />
        <Row k="events about this contract" v={heim.events_about_document ? heim.events_about_document.length : null} />
        <Row k="alerts (critical)" v={heim.alerts !== undefined ? `${heim.alerts} (${heim.alerts_by_severity?.critical ?? 0})` : null} />
        <Row k="tasks on the board" v={heim.tasks} />
        <Row k="live worst case" v={heim.worst_case_live !== undefined ? fmtCurrency(heim.worst_case_live, 0) : null} />
      </div>
    </div>
  );
}
