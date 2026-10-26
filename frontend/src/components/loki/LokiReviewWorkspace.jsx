import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle2, Clock, Crosshair, FileText, Loader2, Quote, RefreshCw, Scale,
  ShieldAlert, Swords, XCircle,
} from 'lucide-react';
import { fetchLokiDocuments, fetchLokiFindings, runLokiReview } from '../../services/api';
import { SEVERITY, flatten, fmtCurrency, fmtDate } from '../common/format';

// ─── helpers ────────────────────────────────────────────────────────────────

const TYPE = {
  ambiguity: { label: 'Ambiguity', icon: Scale, text: '#8C7340', bg: '#F7F1E1' },
  one_sided: { label: 'One-sided term', icon: Swords, text: '#303B28', bg: '#E3E7D3' },
  hidden_liability: { label: 'Hidden liability', icon: ShieldAlert, text: '#C83D3D', bg: '#FBEBEB' },
};

const REVIEW_STATUS = {
  complete: { label: 'Complete', text: '#2E7D32', bg: '#EAF5EA' },
  partial: { label: 'Partial', text: '#B76E00', bg: '#FFF8E1' },
  failed: { label: 'Failed', text: '#C83D3D', bg: '#FBEBEB' },
  skipped: { label: 'Skipped', text: '#727665', bg: '#F5F1E6' },
};

const TABS = [
  { id: 'all', label: 'All accepted' },
  { id: 'ambiguity', label: 'Ambiguity' },
  { id: 'one_sided', label: 'One-sided' },
  { id: 'hidden_liability', label: 'Hidden liability' },
  { id: 'rejected', label: 'Rejected' },
];

// ─── sub-components ─────────────────────────────────────────────────────────

function Badge({ children, bg, text, className = '' }) {
  return (
    <span
      className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase whitespace-nowrap ${className}`}
      style={{ background: bg, color: text }}
    >
      {children}
    </span>
  );
}

function SeverityBadge({ severity }) {
  const s = SEVERITY[severity];
  if (!s) return <Badge bg="#F5F1E6" text="#727665">No severity</Badge>;
  return <Badge bg={s.bg} text={s.text}>{s.label}</Badge>;
}

function TypeBadge({ type }) {
  const t = TYPE[type];
  if (!t) return <Badge bg="#F5F1E6" text="#727665">Unknown type</Badge>;
  const Icon = t.icon;
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-[10px] font-bold px-1.5 py-0.5 rounded uppercase whitespace-nowrap"
      style={{ background: t.bg, color: t.text }}
    >
      <Icon className="w-3 h-3" />
      {t.label}
    </span>
  );
}

function MetricCard({ label, value, sub, color }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-ivory p-3.5 flex flex-col justify-between shadow-xs">
      <span className="font-mono text-[10px] uppercase tracking-wider text-secondary-olive">{label}</span>
      <div className="mt-2">
        <div className="text-xl font-bold font-mono" style={{ color: color || '#303B28' }}>{value}</div>
        {sub && <div className="text-[11px] font-mono mt-0.5 text-secondary-olive">{sub}</div>}
      </div>
    </div>
  );
}

function FindingCard({ finding, isSelected, onSelect }) {
  const sev = SEVERITY[finding.severity] || { bar: '#DCDCCB' };
  const clauses = [...new Set((finding.citations || []).map((c) => c.clause_id).filter(Boolean))];
  const rejected = finding.status === 'rejected';
  return (
    <button
      onClick={() => onSelect(finding)}
      className={`w-full text-left rounded-lg border bg-ivory p-3.5 pl-4 relative overflow-hidden transition-all hover:border-sage ${
        isSelected ? 'border-primary-dark shadow-sm ring-2 ring-primary/20' : 'border-border-subtle'
      } ${rejected ? 'opacity-80' : ''}`}
    >
      <div className="absolute top-0 left-0 w-1 h-full" style={{ background: rejected ? '#DCDCCB' : sev.bar }} />
      <div className="flex items-center gap-1.5 flex-wrap mb-1.5">
        <span className="font-mono text-[10px] font-bold text-secondary-olive">#{finding.rank}</span>
        <TypeBadge type={finding.type} />
        <SeverityBadge severity={finding.severity} />
        {finding.likelihood && (
          <span className="font-mono text-[10px] text-secondary-olive">likelihood {finding.likelihood}</span>
        )}
        {rejected && <Badge bg="#FBEBEB" text="#C83D3D">Rejected</Badge>}
      </div>
      <h3 className="text-sm font-bold leading-snug text-dark-olive">{finding.title || '(no title)'}</h3>
      <div className="mt-2 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1 flex-wrap">
          {clauses.length > 0 ? (
            clauses.map((c) => (
              <span key={c} className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-border-subtle bg-cream text-primary-dark">
                {c}
              </span>
            ))
          ) : (
            <span className="font-mono text-[10px] text-secondary-olive">no verified citation</span>
          )}
        </div>
        <span className="font-mono text-[10px] text-secondary-olive">
          confidence {Math.round((finding.confidence || 0) * 100)}%
        </span>
      </div>
      {rejected && finding.rejection_reason && (
        <p className="mt-2 font-mono text-[11px] text-odin-red leading-snug">{finding.rejection_reason}</p>
      )}
    </button>
  );
}

function FindingInspector({ finding }) {
  if (!finding) {
    return (
      <div className="rounded-lg border border-border-subtle bg-ivory p-6 text-center lg:sticky lg:top-20">
        <Crosshair className="w-8 h-8 mx-auto mb-3 text-border-subtle" />
        <p className="font-mono text-xs text-secondary-olive">
          Select a finding to inspect its verbatim citations, attack path and impact.
        </p>
      </div>
    );
  }
  const sev = SEVERITY[finding.severity];
  const impact = finding.impact;
  return (
    <div className="rounded-lg border border-border-subtle bg-ivory overflow-hidden lg:sticky lg:top-20">
      <div className="p-3 border-b border-border-subtle bg-cream flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Crosshair className="w-3.5 h-3.5 text-primary" />
          <span className="font-mono text-xs font-bold text-primary-dark">Attack Inspector</span>
        </div>
        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-border-subtle bg-ivory text-primary-dark">
          {finding.doc_id} · {fmtDate(finding.as_of)}
        </span>
      </div>

      <div className="p-4 space-y-4 max-h-[calc(100vh-7rem)] overflow-y-auto">
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 flex-wrap">
            <TypeBadge type={finding.type} />
            <SeverityBadge severity={finding.severity} />
            {finding.status === 'rejected' ? (
              <Badge bg="#FBEBEB" text="#C83D3D">Rejected</Badge>
            ) : (
              <Badge bg="#EAF5EA" text="#2E7D32">Accepted</Badge>
            )}
          </div>
          <h3 className="font-bold text-sm text-dark-olive leading-snug">{finding.title}</h3>
          {finding.exploited_by && (
            <p className="font-mono text-[11px] text-secondary-olive">
              Exploited by: <span className="text-dark-olive font-semibold">{finding.exploited_by}</span>
            </p>
          )}
        </div>

        {finding.status === 'rejected' && finding.rejection_reason && (
          <div className="rounded border p-3 font-mono text-[11px] leading-snug" style={{ background: '#FBEBEB', borderColor: 'rgba(200,61,61,0.35)', color: '#8F2929' }}>
            <strong className="block mb-0.5 uppercase text-[10px] tracking-wider">Rejected by code checks</strong>
            {finding.rejection_reason}
          </div>
        )}

        {/* Severity / likelihood with reasons */}
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded border border-border-subtle bg-cream/60 p-2.5">
            <div className="font-mono text-[10px] uppercase tracking-wider text-secondary-olive">Severity</div>
            <div className="font-mono text-xs font-bold mt-0.5" style={{ color: sev ? sev.text : '#727665' }}>
              {finding.severity || '—'}
            </div>
            {finding.severity_reason && <p className="text-[11px] text-secondary-olive mt-1 leading-snug">{finding.severity_reason}</p>}
          </div>
          <div className="rounded border border-border-subtle bg-cream/60 p-2.5">
            <div className="font-mono text-[10px] uppercase tracking-wider text-secondary-olive">Likelihood</div>
            <div className="font-mono text-xs font-bold mt-0.5 text-primary-dark">{finding.likelihood || '—'}</div>
            {finding.likelihood_reason && <p className="text-[11px] text-secondary-olive mt-1 leading-snug">{finding.likelihood_reason}</p>}
          </div>
        </div>

        {/* Citations */}
        <div className="space-y-2">
          <span className="font-mono text-[10px] uppercase tracking-wider font-bold text-secondary-olive">
            Verbatim clause citations ({(finding.citations || []).length})
          </span>
          {(finding.citations || []).length === 0 && (
            <p className="font-mono text-[11px] text-secondary-olive">No citation survived verification.</p>
          )}
          {(finding.citations || []).map((c, i) => (
            <div key={i} className="rounded border border-border-subtle bg-[#FAF6EC] p-3 text-xs space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-bold text-primary-dark">
                  {c.clause_id}
                  {c.clause_ref && <span className="font-normal text-secondary-olive"> · {c.clause_ref}</span>}
                </span>
                {c.verified ? (
                  <span className="inline-flex items-center gap-1 font-mono text-[10px] text-[#2E7D32]">
                    <CheckCircle2 className="w-3 h-3" /> verified · {c.match_method}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 font-mono text-[10px] text-odin-red">
                    <XCircle className="w-3 h-3" /> unverified
                  </span>
                )}
              </div>
              <p className="font-serif leading-relaxed text-dark-olive">
                <Quote className="w-3 h-3 inline -mt-1 mr-1 text-accent-gold" />
                {flatten(c.quote)}
              </p>
            </div>
          ))}
        </div>

        {/* Attack path */}
        {(finding.attack_path || []).length > 0 && (
          <div className="space-y-2">
            <span className="font-mono text-[10px] uppercase tracking-wider font-bold text-secondary-olive">
              Counterparty's attack path
            </span>
            <ol className="relative border-l-2 border-border-subtle ml-2 space-y-2.5">
              {finding.attack_path.map((step, i) => (
                <li key={i} className="pl-4 relative">
                  <span className="absolute -left-[9px] top-0.5 w-4 h-4 rounded-full bg-primary-dark text-cream font-mono text-[9px] font-bold flex items-center justify-center">
                    {i + 1}
                  </span>
                  <p className="text-xs text-dark-olive leading-snug">{step}</p>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Readings (ambiguity) */}
        {(finding.readings || []).length > 0 && (
          <div className="space-y-2">
            <span className="font-mono text-[10px] uppercase tracking-wider font-bold text-secondary-olive">
              Competing readings
            </span>
            {finding.readings.map((r, i) => (
              <div
                key={i}
                className="rounded border p-2.5 text-xs leading-snug"
                style={{
                  borderColor: r.counterparty_argues ? 'rgba(200,61,61,0.35)' : '#DCDCCB',
                  background: r.counterparty_argues ? '#FDF3F1' : '#FCFAF3',
                }}
              >
                {r.counterparty_argues && (
                  <span className="block font-mono text-[10px] font-bold uppercase text-odin-red mb-0.5">Counterparty argues</span>
                )}
                <span className="text-dark-olive">{r.reading}</span>
              </div>
            ))}
          </div>
        )}

        {/* Impact from Norns */}
        <div className="rounded border border-border-subtle bg-cream/60 p-3 space-y-1">
          <span className="font-mono text-[10px] uppercase tracking-wider font-bold text-secondary-olive">Financial impact (NORNS)</span>
          {impact && impact !== 'unquantified' ? (
            <div className="font-mono text-xs space-y-0.5">
              <div className="flex justify-between">
                <span className="text-secondary-olive">{impact.category} · {impact.scenario}</span>
                <span className="font-bold text-odin-red">{impact.amount !== null && impact.amount !== undefined ? fmtCurrency(impact.amount) : 'not quantified'}</span>
              </div>
              <div className="text-[10px] text-secondary-olive">
                Exposure item #{impact.exposure_item_id} cites {impact.clause_id}
                {impact.other_exposure_ids?.length > 0 && ` · ${impact.other_exposure_ids.length} more item(s)`}
              </div>
            </div>
          ) : (
            <p className="font-mono text-[11px] text-secondary-olive leading-snug">
              Unquantified: no NORNS exposure item cites these clauses on this date. LOKI never computes an amount itself.
            </p>
          )}
        </div>

        {/* Code-check notes */}
        {(finding.notes || []).length > 0 && (
          <div className="space-y-1">
            <span className="font-mono text-[10px] uppercase tracking-wider font-bold text-secondary-olive">Code-check notes</span>
            {finding.notes.map((n, i) => (
              <p key={i} className="font-mono text-[10px] text-secondary-olive leading-snug">• {n}</p>
            ))}
          </div>
        )}

        <div className="pt-2 border-t border-border-subtle font-mono text-[10px] text-secondary-olive flex flex-wrap gap-x-3 gap-y-0.5">
          <span>confidence {Math.round((finding.confidence || 0) * 100)}%</span>
          {finding.model && <span>model {finding.model}</span>}
          {finding.part && <span>part {finding.part}</span>}
          {finding.run_id && <span>{finding.run_id}</span>}
          <span>AI-generated analysis</span>
        </div>
      </div>
    </div>
  );
}

function ScalesLegend({ scales }) {
  if (!scales) return null;
  const blocks = [
    { title: 'Finding types', entries: scales.types, color: (k) => TYPE[k]?.text },
    { title: 'Severity scale', entries: scales.severity, color: (k) => SEVERITY[k]?.text },
    { title: 'Likelihood scale', entries: scales.likelihood, color: () => '#303B28' },
  ];
  return (
    <section className="rounded-lg border border-border-subtle bg-ivory p-4">
      <div className="flex items-center gap-2 mb-3">
        <Scale className="w-4 h-4 text-primary" />
        <h2 className="font-bold text-sm text-dark-olive">Fixed scales</h2>
        <span className="font-mono text-[10px] text-secondary-olive">stated in prompts/loki_review.md and enforced in code</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {blocks.map((b) => (
          <div key={b.title} className="space-y-1.5">
            <span className="font-mono text-[10px] uppercase tracking-wider font-bold text-secondary-olive">{b.title}</span>
            {Object.entries(b.entries || {}).map(([k, v]) => (
              <p key={k} className="text-[11px] leading-snug text-secondary-olive">
                <span className="font-mono font-bold" style={{ color: b.color(k) }}>{k.replace('_', '-')}</span>: {v}
              </p>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── main workspace ─────────────────────────────────────────────────────────

export default function LokiReviewWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState(null);
  const [docId, setDocId] = useState(searchParams.get('doc'));
  const [asOf, setAsOf] = useState(searchParams.get('as_of'));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [tab, setTab] = useState('all');
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [runResult, setRunResult] = useState(null);

  const loadMeta = useCallback(() => {
    return fetchLokiDocuments()
      .then((m) => {
        setMeta(m);
        setMetaError(null);
        return m;
      })
      .catch((e) => {
        setMetaError(e.message);
        return null;
      });
  }, []);

  // Documents, checkpoints and LLM readiness; pick the initial contract and date.
  useEffect(() => {
    loadMeta().then((m) => {
      if (!m) return;
      const docs = m.documents || [];
      const reviewable = docs.filter((d) => d.reviewable);
      const initial =
        reviewable.find((d) => d.doc_id === searchParams.get('doc')) ||
        reviewable.find((d) => d.reviews.length > 0) ||
        reviewable.find((d) => d.doc_id === 'A1') ||
        reviewable[0];
      if (!initial) return;
      setDocId(initial.doc_id);
      if (!searchParams.get('as_of')) {
        const cp1 = (m.checkpoints || []).find((p) => p.idx === 1);
        setAsOf(initial.reviews[0]?.as_of || cp1?.date || new Date().toISOString().split('T')[0]);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Findings for the selected contract and date.
  useEffect(() => {
    if (!docId || !asOf) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSearchParams({ doc: docId, as_of: asOf }, { replace: true });
    fetchLokiFindings(docId, asOf)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        const first = (d.findings || []).find((f) => f.status === 'accepted') || (d.findings || [])[0];
        setSelectedId(first ? first.id : null);
      })
      .catch((e) => !cancelled && setLoadError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId, asOf]);

  const documents = meta?.documents || [];
  const doc = documents.find((d) => d.doc_id === docId);
  const llm = meta?.llm;
  const findings = data?.findings || [];
  const accepted = findings.filter((f) => f.status === 'accepted');
  const rejected = findings.filter((f) => f.status === 'rejected');
  const visible = tab === 'all' ? accepted : tab === 'rejected' ? rejected : accepted.filter((f) => f.type === tab);
  const selected = findings.find((f) => f.id === selectedId) || null;
  const summary = data?.summary;

  // Dates offered: the clock's checkpoints plus every date this contract was reviewed on.
  const dateOptions = useMemo(() => {
    const out = new Map();
    (meta?.checkpoints || []).forEach((p) => out.set(p.date, p.label));
    (doc?.reviews || []).forEach((r) => {
      if (!out.has(r.as_of)) out.set(r.as_of, 'Reviewed');
    });
    return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [meta, doc]);
  const reviewedDates = new Set((doc?.reviews || []).map((r) => r.as_of));

  const selectDoc = (d) => {
    if (!d.reviewable) return;
    setDocId(d.doc_id);
    setTab('all');
    setRunResult(null);
    setRunError(null);
    if (d.reviews.length > 0 && !d.reviews.some((r) => r.as_of === asOf)) setAsOf(d.reviews[0].as_of);
  };

  const runReview = () => {
    if (!docId || !asOf) return;
    setRunning(true);
    setRunError(null);
    setRunResult(null);
    runLokiReview([docId], asOf)
      .then((res) => {
        const review = (res.reviews || [])[0];
        setRunResult(review || null);
        return Promise.all([loadMeta(), fetchLokiFindings(docId, asOf)]);
      })
      .then(([, d]) => {
        setData(d);
        setTab('all');
        const first = (d.findings || []).find((f) => f.status === 'accepted') || (d.findings || [])[0];
        setSelectedId(first ? first.id : null);
        try {
          window.dispatchEvent(new CustomEvent('odin-doc-updated', { detail: { docId, agent: 'loki' } }));
        } catch (e) {
          // non-browser context
        }
      })
      .catch((e) => setRunError(e.message))
      .finally(() => setRunning(false));
  };

  const thorIncomplete = doc && doc.thor_status && doc.thor_status !== 'complete';
  const runDisabled = running || !llm?.configured || !doc?.reviewable || !asOf;
  const last = data?.last_review || doc?.last_review;

  return (
    <div className="space-y-5">
      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <div className="rounded-lg border border-border-subtle bg-ivory p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-[10px] font-bold uppercase px-2 py-0.5 rounded tracking-wider bg-[#F4ECDB] text-dark-olive">
                ODIN AGENT 04 · ADVERSARIAL REVIEW
              </span>
              <span className="font-mono text-[11px] text-secondary-olive">Counterparty's-lawyer mode</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-primary-dark">
              Read every contract the way the other side's lawyer will.
            </h1>
            <p className="text-sm max-w-3xl text-secondary-olive">
              LOKI attacks each agreement from the counterparty's side and reports ambiguous clauses, one-sided terms and
              hidden liabilities. Every finding must quote the contract verbatim, lay out an attack path and carry a
              severity and likelihood on fixed scales; anything that fails the code checks is rejected, never shown as fact.
            </p>
          </div>
          <div className="shrink-0 rounded border border-border-subtle bg-cream px-3 py-2 font-mono text-[11px] space-y-0.5 min-w-[220px]">
            <div className="flex items-center gap-1.5 font-semibold text-dark-olive">
              <span className={`w-2 h-2 rounded-full ${llm?.configured ? 'bg-emerald-600 animate-pulse' : 'bg-odin-red'}`} />
              {llm ? (llm.configured ? 'LLM ready' : 'LLM not configured') : 'Checking LLM…'}
            </div>
            {llm && (
              <div className="text-secondary-olive">
                {llm.provider}
                {llm.model ? ` · ${llm.model}` : ''}
              </div>
            )}
            {llm && !llm.configured && <div className="text-odin-red leading-snug max-w-[260px]">{llm.problem}</div>}
            {meta && <div className="text-secondary-olive">≤ {meta.max_llm_calls} LLM calls per run</div>}
          </div>
        </div>
      </div>

      {metaError && (
        <div className="rounded-lg border p-4 font-mono text-xs flex items-start gap-2" style={{ background: '#FBEBEB', borderColor: 'rgba(200,61,61,0.35)', color: '#8F2929' }}>
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{metaError}</span>
        </div>
      )}

      {/* ── Contract + date + run ─────────────────────────────────────── */}
      <div className="rounded-lg border border-border-subtle bg-ivory p-4 space-y-4 shadow-xs">
        <div>
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-border-subtle/60 font-mono text-xs">
            <span className="text-secondary-olive font-semibold uppercase tracking-wider text-[11px]">Contract under review</span>
            <span className="text-primary font-bold">{documents.filter((d) => d.reviewable).length} reviewable agreements</span>
          </div>
          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
            {documents.map((d) => {
              const active = d.doc_id === docId;
              const status = d.last_review ? REVIEW_STATUS[d.last_review.status] : null;
              const inside = d.reviewed_inside?.length ? d.reviewed_inside.join(', ') : 'the documents it applies to';
              return (
                <button
                  key={d.doc_id}
                  onClick={() => selectDoc(d)}
                  disabled={!d.reviewable}
                  title={d.reviewable ? d.title : `${d.doc_id} is ${d.kind === 'amendment' ? 'an amendment' : 'standard terms'}: reviewed inside ${inside}`}
                  className={`shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg font-mono text-xs transition-all border ${
                    active
                      ? 'bg-primary-dark text-cream border-primary-dark shadow-sm'
                      : d.reviewable
                      ? 'bg-cream/70 hover:bg-cream text-dark-olive border-border-subtle'
                      : 'bg-cream/40 text-secondary-olive/70 border-dashed border-border-subtle cursor-not-allowed'
                  }`}
                >
                  <FileText className="w-3.5 h-3.5 shrink-0" />
                  <span className="font-bold">{d.doc_id}</span>
                  {d.reviewable ? (
                    <span
                      className="text-[10px] px-1.5 rounded font-medium"
                      style={active ? { background: 'rgba(164,177,138,0.4)', color: '#F5F1E6' } : { background: status?.bg || '#F5F1E6', color: status?.text || '#727665' }}
                    >
                      {status ? status.label : 'Not reviewed'}
                    </span>
                  ) : (
                    <span className="text-[10px]">via {d.reviewed_inside?.length ? d.reviewed_inside.join('/') : 'host'}</span>
                  )}
                </button>
              );
            })}
          </div>
          {doc && (
            <p className="mt-2 text-xs text-secondary-olive">
              <span className="font-semibold text-dark-olive">{doc.title}</span> · {doc.kind} · THOR {doc.thor_status}
              {doc.coverage !== null && doc.coverage !== undefined ? ` (${Number(doc.coverage).toFixed(0)}% coverage)` : ''}
            </p>
          )}
        </div>

        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
          <div className="space-y-1.5">
            <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-secondary-olive flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-primary" /> Review as of (simulated clock)
            </span>
            <div className="flex items-center gap-1.5 flex-wrap">
              {dateOptions.map(([d, label]) => (
                <button
                  key={d}
                  onClick={() => setAsOf(d)}
                  className={`px-2.5 py-1.5 rounded border font-mono text-[11px] transition-colors ${
                    asOf === d ? 'bg-primary-dark text-white border-primary-dark font-semibold' : 'bg-cream/70 text-dark-olive border-border-subtle hover:bg-cream'
                  }`}
                >
                  {label} · {fmtDate(d)}
                  {reviewedDates.has(d) && <span className={`ml-1.5 inline-block w-1.5 h-1.5 rounded-full ${asOf === d ? 'bg-odin-palesage' : 'bg-primary'}`} title="Findings stored" />}
                </button>
              ))}
              <input
                type="date"
                value={asOf || ''}
                onChange={(e) => e.target.value && setAsOf(e.target.value)}
                className="px-2 py-1 rounded border border-border-subtle bg-cream/70 font-mono text-[11px] text-dark-olive"
                aria-label="Custom review date"
              />
            </div>
          </div>

          <div className="flex flex-col items-start lg:items-end gap-1.5 shrink-0">
            <button
              onClick={runReview}
              disabled={runDisabled}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded font-semibold text-sm text-cream bg-primary-dark hover:bg-dark-olive transition-all active:scale-95 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldAlert className="w-4 h-4" />}
              {running ? `Reviewing ${docId}…` : `Run LOKI review on ${docId || '—'}`}
            </button>
            <span className="font-mono text-[10px] text-secondary-olive text-left lg:text-right max-w-xs">
              {llm && !llm.configured
                ? 'Needs an LLM key in .env (see the status card above).'
                : `One LLM call; replaces ${docId || 'this contract'}'s findings for ${fmtDate(asOf)}.`}
            </span>
          </div>
        </div>

        {thorIncomplete && (
          <div className="rounded border p-2.5 font-mono text-[11px] flex items-start gap-2" style={{ background: '#FFF8E1', borderColor: 'rgba(183,110,0,0.3)', color: '#8A5300' }}>
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>
              THOR's extraction for {doc.doc_id} is {doc.thor_status}
              {doc.coverage !== null && doc.coverage !== undefined ? ` (${Number(doc.coverage).toFixed(1)}% coverage)` : ''}. LOKI reads the clause
              text itself, but its hints from THOR (fields, flags) are incomplete until THOR finishes this document.
            </span>
          </div>
        )}

        {running && (
          <div className="rounded border border-border-subtle bg-cream/70 p-3 font-mono text-[11px] text-secondary-olive flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
            LOKI is reading {docId} as the counterparty's counsel. Rate-limited providers can take a few minutes; the page
            updates when the review is stored.
          </div>
        )}
        {runError && (
          <div className="rounded border p-3 font-mono text-[11px] flex items-start gap-2" style={{ background: '#FBEBEB', borderColor: 'rgba(200,61,61,0.35)', color: '#8F2929' }}>
            <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{runError}</span>
          </div>
        )}
        {runResult && (
          <div
            className="rounded border p-3 font-mono text-[11px] space-y-1"
            style={{ background: REVIEW_STATUS[runResult.status]?.bg || '#F5F1E6', borderColor: '#DCDCCB', color: '#303B28' }}
          >
            <div className="font-bold" style={{ color: REVIEW_STATUS[runResult.status]?.text }}>
              Review {runResult.status}: {(runResult.findings || []).filter((f) => f.status === 'accepted').length} accepted ·{' '}
              {(runResult.findings || []).filter((f) => f.status === 'rejected').length} rejected · {runResult.seconds}s
            </div>
            <div className="text-secondary-olive">
              {runResult.llm?.llm_calls ?? 0} LLM call(s), {runResult.llm?.cache_hits ?? 0} cached,{' '}
              {((runResult.llm?.input_tokens || 0) + (runResult.llm?.output_tokens || 0)).toLocaleString()} tokens
              {runResult.model ? ` · ${runResult.model}` : ''}
              {runResult.standard_terms ? ` · Standard Terms ${runResult.standard_terms}` : ''}
            </div>
            {runResult.reason && <div className="text-odin-red">{runResult.reason}</div>}
            {(runResult.context_notes || []).slice(0, 4).map((n, i) => (
              <div key={i} className="text-secondary-olive">note: {n}</div>
            ))}
          </div>
        )}
      </div>

      {/* ── Metrics ───────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Accepted findings" value={summary?.accepted ?? '—'} sub={summary?.counterparty ? `vs ${summary.counterparty}` : 'passed every code check'} />
        <MetricCard
          label="Critical / High"
          value={summary ? `${summary.by_severity.critical} / ${summary.by_severity.high}` : '—'}
          sub="most severe first"
          color="#C83D3D"
        />
        <MetricCard label="Ambiguities" value={summary?.by_type.ambiguity ?? '—'} sub="two+ readings" color={TYPE.ambiguity.text} />
        <MetricCard label="One-sided terms" value={summary?.by_type.one_sided ?? '—'} sub="no matching protection" />
        <MetricCard label="Hidden liabilities" value={summary?.by_type.hidden_liability ?? '—'} sub="buried or uncapped" color="#C83D3D" />
        <MetricCard label="Rejected by checks" value={summary?.rejected ?? '—'} sub="never shown as fact" color="#727665" />
      </div>

      {/* ── Findings + inspector ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        <section className="lg:col-span-7 rounded-lg border border-border-subtle bg-ivory shadow-sm overflow-hidden">
          <div className="p-4 border-b border-border-subtle flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h2 className="font-bold text-dark-olive flex items-center gap-2">
                <Swords className="w-4 h-4 text-accent-gold" />
                Adversarial findings · {docId || '—'}
              </h2>
              <p className="text-xs mt-0.5 text-secondary-olive">
                {data?.as_of ? `Review as of ${fmtDate(data.as_of)}` : 'No review date selected'}
                {last ? ` · last run ${last.status} on ${fmtDate(last.as_of)}` : ''}
              </p>
            </div>
            <button
              onClick={() => {
                setLoading(true);
                Promise.all([loadMeta(), fetchLokiFindings(docId, asOf)])
                  .then(([, d]) => setData(d))
                  .catch((e) => setLoadError(e.message))
                  .finally(() => setLoading(false));
              }}
              disabled={!docId || !asOf || loading}
              className="self-start sm:self-auto inline-flex items-center gap-1 text-xs font-semibold underline text-primary disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
            </button>
          </div>

          <div className="flex items-center border-b border-border-subtle px-4 overflow-x-auto no-scrollbar text-xs font-mono bg-[#FAF6EC]">
            {TABS.map((t) => {
              const count = t.id === 'all' ? accepted.length : t.id === 'rejected' ? rejected.length : accepted.filter((f) => f.type === t.id).length;
              return (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`py-2.5 px-3 border-b-2 whitespace-nowrap transition-colors ${
                    tab === t.id ? 'border-primary-dark text-primary-dark font-bold' : 'border-transparent text-secondary-olive'
                  }`}
                >
                  {t.label} ({count})
                </button>
              );
            })}
          </div>

          <div className="p-4 space-y-3">
            {loading ? (
              <div className="flex items-center justify-center py-12 gap-2 font-mono text-xs text-secondary-olive">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading findings…
              </div>
            ) : loadError ? (
              <div className="text-center py-10 font-mono text-xs text-odin-red">{loadError}</div>
            ) : findings.length === 0 ? (
              <div className="text-center py-10 space-y-2">
                <ShieldAlert className="w-8 h-8 mx-auto text-border-subtle" />
                <p className="font-mono text-xs text-secondary-olive">
                  No LOKI review stored for {docId || 'this contract'} on {fmtDate(asOf)}.
                </p>
                <p className="font-mono text-[11px] text-secondary-olive">
                  {llm?.configured
                    ? 'Run a review above (one LLM call).'
                    : 'Add an LLM key to .env and restart the API to run a review.'}
                </p>
              </div>
            ) : visible.length === 0 ? (
              <p className="text-center py-10 font-mono text-xs text-secondary-olive">No findings in this category.</p>
            ) : (
              visible.map((f) => (
                <FindingCard key={f.id} finding={f} isSelected={f.id === selectedId} onSelect={(x) => setSelectedId(x.id)} />
              ))
            )}
          </div>
        </section>

        <section className="lg:col-span-5">
          <FindingInspector finding={selected} />
        </section>
      </div>

      <ScalesLegend scales={meta?.scales} />
    </div>
  );
}
