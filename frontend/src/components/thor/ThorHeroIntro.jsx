import React from 'react';
import { CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';

export default function ThorHeroIntro() {
  return (
    <section className="bg-ivory border border-border-subtle rounded-xl p-6 sm:p-8 shadow-sm">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div className="max-w-3xl space-y-2.5">
          <div className="flex items-center space-x-2">
            <span className="px-2 py-0.5 rounded bg-primary-dark text-cream font-mono text-[11px] font-semibold tracking-wider">
              ODIN AGENT 01
            </span>
            <span className="text-secondary-olive font-mono text-xs">·</span>
            <span className="text-secondary-olive font-mono text-[11px] uppercase tracking-wider">
              CONTRACT EXTRACTION &amp; DETERMINISTIC PROOF
            </span>
          </div>

          <h1 className="font-sans text-2xl sm:text-3xl lg:text-4xl text-primary-dark font-bold tracking-tight">
            Turn contractual language into structured evidence.
          </h1>

          <p className="font-sans text-sm sm:text-base text-secondary-olive leading-relaxed">
            THOR extracts obligations, dates, payment terms, penalties, and termination conditions from your contracts, preserving the clause-level evidence behind every finding.
          </p>

          <div className="flex flex-wrap items-center gap-2 pt-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-cream border border-border-subtle font-mono text-xs text-primary-dark shadow-xs">
              <CheckCircle2 className="w-3.5 h-3.5 text-primary" />
              Evidence-linked extraction
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-cream border border-border-subtle font-mono text-xs text-primary-dark shadow-xs">
              <AlertTriangle className="w-3.5 h-3.5 text-accent-gold" />
              Explicit uncertainty
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-cream border border-border-subtle font-mono text-xs text-primary-dark shadow-xs">
              <RefreshCw className="w-3.5 h-3.5 text-primary" />
              Targeted clause re-extraction
            </span>
          </div>
        </div>

        <div className="text-left md:text-right flex flex-col justify-end">
          <p className="font-mono text-xs text-secondary-olive italic max-w-xs md:ml-auto">
            Findings are presented with supporting source text and confidence information for review.
          </p>
        </div>
      </div>
    </section>
  );
}
