import React from 'react';

export default function SummaryIndicators({ summary }) {
  const fin = summary?.financial_exposure || {
    total_formatted: '$0',
    confirmed_formatted: '$0',
    conditional_formatted: '$0',
    variance_live: true,
  };

  const deadlines = summary?.upcoming_deadlines_30d || {
    headline: '0 Milestones',
    critical_count: 0,
    renewals_count: 0,
    attestations_count: 0,
  };

  const obligations = summary?.critical_obligations || {
    headline: '0 Critical',
    detail: 'All obligations audited against Supabase ledger',
    status_label: 'AUDITED',
  };

  const conflicts = summary?.contractual_conflicts || {
    headline: '0 Flags',
    detail: 'Autonomous multi-agent consensus active',
    status_label: 'LOKI/HEIMDALL',
  };

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
      {/* Card 1: Financial Exposure */}
      <div className="p-4 rounded-lg bg-odin-ivory border border-odin-border hover:border-odin-sage transition-all shadow-sm flex flex-col justify-between">
        <div className="flex justify-between items-start mb-2">
          <span className="text-xs font-mono font-semibold uppercase tracking-wider text-odin-muted">
            Financial Exposure
          </span>
          <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-[#FBEBEB] text-odin-red border border-odin-red/30 flex items-center gap-1 font-semibold">
            <span className="w-1.5 h-1.5 rounded-full bg-odin-red animate-pulse"></span>
            Variance Live
          </span>
        </div>
        <div>
          <div className="text-2xl lg:text-3xl font-extrabold text-odin-dark tracking-tight">
            {fin.total_formatted}
          </div>
          <div className="mt-2.5 flex items-center justify-between border-t border-odin-border-subtle pt-2 text-xs font-mono">
            <span className="text-odin-muted">
              Confirmed: <strong className="text-odin-red font-bold">{fin.confirmed_formatted}</strong>
            </span>
            <span className="text-odin-muted">
              Conditional: <strong className="text-odin-forest font-bold">{fin.conditional_formatted}</strong>
            </span>
          </div>
        </div>
      </div>

      {/* Card 2: Upcoming Deadlines */}
      <div className="p-4 rounded-lg bg-odin-ivory border border-odin-border hover:border-odin-sage transition-all shadow-sm flex flex-col justify-between">
        <div className="flex justify-between items-start mb-2">
          <span className="text-xs font-mono font-semibold uppercase tracking-wider text-odin-muted">
            Upcoming Deadlines (30D)
          </span>
          <span className="material-symbols-outlined text-odin-sage text-base">calendar_month</span>
        </div>
        <div>
          <div className="text-2xl lg:text-3xl font-extrabold text-odin-dark tracking-tight">
            {deadlines.headline}
          </div>
          <div className="mt-2.5 flex items-center gap-2 border-t border-odin-border-subtle pt-2 text-xs font-mono">
            <span className="text-odin-red font-bold">{deadlines.critical_count} Critical</span>
            <span className="text-odin-border">•</span>
            <span className="text-odin-forest font-semibold">{deadlines.renewals_count} Renewals</span>
            <span className="text-odin-border">•</span>
            <span className="text-odin-muted">{deadlines.attestations_count} Attestations</span>
          </div>
        </div>
      </div>

      {/* Card 3: Critical Obligations */}
      <div className="p-4 rounded-lg bg-odin-ivory border border-odin-border hover:border-odin-sage transition-all shadow-sm flex flex-col justify-between">
        <div className="flex justify-between items-start mb-2">
          <span className="text-xs font-mono font-semibold uppercase tracking-wider text-odin-muted">
            Critical Obligations
          </span>
          <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-[#FBEBEB] text-odin-red font-bold border border-odin-red/25">
            {obligations.status_label}
          </span>
        </div>
        <div>
          <div className="text-2xl lg:text-3xl font-extrabold text-odin-red tracking-tight">
            {obligations.headline}
          </div>
          <div className="mt-2.5 border-t border-odin-border-subtle pt-2 text-xs text-odin-muted truncate font-sans">
            {obligations.detail}
          </div>
        </div>
      </div>

      {/* Card 4: Open Contractual Conflicts */}
      <div className="p-4 rounded-lg bg-odin-ivory border border-odin-border hover:border-odin-sage transition-all shadow-sm flex flex-col justify-between">
        <div className="flex justify-between items-start mb-2">
          <span className="text-xs font-mono font-semibold uppercase tracking-wider text-odin-muted">
            Contractual Conflicts
          </span>
          <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-odin-palesage text-odin-forest border border-odin-sage/30 font-semibold">
            {conflicts.status_label}
          </span>
        </div>
        <div>
          <div className="text-2xl lg:text-3xl font-extrabold text-odin-forest tracking-tight">
            {conflicts.headline}
          </div>
          <div className="mt-2.5 border-t border-odin-border-subtle pt-2 text-xs text-odin-muted truncate font-sans">
            {conflicts.detail}
          </div>
        </div>
      </div>
    </section>
  );
}
