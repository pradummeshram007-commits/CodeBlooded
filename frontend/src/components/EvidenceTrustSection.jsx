import React from 'react';
import { Quote, HelpCircle, Clock, ShieldCheck, Info } from 'lucide-react';

export default function EvidenceTrustSection() {
  return (
    <section className="py-16 lg:py-24 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8" id="evidence-trust">
      {/* Section Header */}
      <div className="mb-14 space-y-3">
        <span className="font-mono text-xs tracking-widest uppercase text-primary font-bold">
          PROOF BEFORE CONFIDENCE
        </span>
        <h2 className="font-sans text-3xl sm:text-4xl font-bold tracking-tight text-dark-olive">
          Every finding should have a reason.
        </h2>
        <p className="font-sans text-sm sm:text-base text-secondary-olive max-w-2xl leading-relaxed">
          ODIN does not hallucinate authority. Every assertion maps directly to verbatim language with unambiguous uncertainty tracking.
        </p>
      </div>

      {/* 4 Core Pillar Panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
        <div className="p-6 rounded-xl bg-ivory border border-border-subtle space-y-3 shadow-sm hover:border-primary transition-all">
          <div className="w-9 h-9 rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-primary">
            <Quote className="w-4 h-4" />
          </div>
          <h3 className="font-sans text-base font-semibold text-dark-olive">Clause-Level Citations</h3>
          <p className="font-sans text-xs text-secondary-olive leading-relaxed">
            Users can trace a finding back to its supporting contractual language with exact paragraph, line, and sentence provenance.
          </p>
        </div>

        <div className="p-6 rounded-xl bg-ivory border border-border-subtle space-y-3 shadow-sm hover:border-accent-gold transition-all">
          <div className="w-9 h-9 rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-accent-gold">
            <HelpCircle className="w-4 h-4" />
          </div>
          <h3 className="font-sans text-base font-semibold text-dark-olive">Explicit Uncertainty</h3>
          <p className="font-sans text-xs text-secondary-olive leading-relaxed">
            Ambiguous, missing, or contradictory information is surfaced openly as structured risk tags rather than silently guessed.
          </p>
        </div>

        <div className="p-6 rounded-xl bg-ivory border border-border-subtle space-y-3 shadow-sm hover:border-primary transition-all">
          <div className="w-9 h-9 rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-primary-dark">
            <Clock className="w-4 h-4" />
          </div>
          <h3 className="font-sans text-base font-semibold text-dark-olive">Time-Aware Reasoning</h3>
          <p className="font-sans text-xs text-secondary-olive leading-relaxed">
            Deadlines and risk projections dynamically recalculate with the simulated clock and verifiable external events.
          </p>
        </div>

        <div className="p-6 rounded-xl bg-ivory border border-border-subtle space-y-3 shadow-sm hover:border-sage transition-all">
          <div className="w-9 h-9 rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-primary">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <h3 className="font-sans text-base font-semibold text-dark-olive">Human-Reviewed Actions</h3>
          <p className="font-sans text-xs text-secondary-olive leading-relaxed">
            Recommended notices and other consequential legal actions remain strictly subject to human partner authorization.
          </p>
        </div>
      </div>

      {/* High-Fidelity Verification Pipeline Artifact */}
      <div className="rounded-xl bg-ivory border border-border-subtle p-6 lg:p-8 backdrop-blur-md shadow-md">
        <div className="flex flex-wrap items-center justify-between pb-6 border-b border-border-subtle mb-6 gap-2">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-primary" />
            <span className="font-mono text-xs sm:text-sm text-dark-olive font-semibold">
              ODIN TRUTH VERIFICATION PIPELINE [AUDIT SPEC]
            </span>
          </div>
          <span className="font-mono text-xs text-secondary-olive">ISO-27001 &amp; SOC2 READY</span>
        </div>

        {/* Integrated Side-by-Side: Real Contract Photo with Section 14.3 + Cryptographic Verification */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
          {/* Left: Close-up Contract Image showing § 14.3 */}
          <div className="lg:col-span-5 relative group overflow-hidden rounded-xl border border-border-subtle shadow-md bg-cream">
            <div className="relative overflow-hidden aspect-[4/3]">
              <img
                alt="Editorial close-up photograph of commercial master services agreement Section 14.3 with olive highlight"
                className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
                src="/assets/contract_section14.jpg"
                loading="lazy"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-dark-olive/70 via-transparent to-transparent" />
              <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between text-cream font-mono text-[11px] bg-dark-olive/85 px-3 py-1.5 rounded backdrop-blur-sm border border-sage/30">
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-accent-gold" />
                  <span className="font-semibold text-cream">ANCHORED SOURCE CLAUSE</span>
                </span>
                <span className="text-sage">§ 14.3 Term &amp; Renewal</span>
              </div>
            </div>
          </div>

          {/* Right: Cryptographic Verification Pillars */}
          <div className="lg:col-span-7 space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {/* Col 1 */}
              <div className="space-y-2 p-3.5 rounded-lg bg-cream border border-border-subtle">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-primary-dark font-semibold">SOURCED FACTS</span>
                  <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-primary/15 text-primary-dark font-medium">
                    100% Verbatim
                  </span>
                </div>
                <p className="font-sans text-xs text-secondary-olive leading-snug">
                  Zero generative speculation. Ingested clauses are cryptographically hashed and tied directly to the original file bytes.
                </p>
                <div className="font-mono text-[10px] p-1.5 rounded bg-ivory text-primary-dark border border-border-subtle">
                  sha256:7f83b165... §21.4
                </div>
              </div>

              {/* Col 2 */}
              <div className="space-y-2 p-3.5 rounded-lg bg-cream border border-border-subtle">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-primary-dark font-semibold">TIMELINES</span>
                  <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-sage/25 text-dark-olive font-medium">
                    Deterministic
                  </span>
                </div>
                <p className="font-sans text-xs text-secondary-olive leading-snug">
                  Mathematical date offsets based on ISO 8601 calendar logic, accounting for non-business days and holidays.
                </p>
                <div className="font-mono text-[10px] p-1.5 rounded bg-ivory text-primary border border-border-subtle">
                  calc: Exec + 90d = 2025-04-18
                </div>
              </div>

              {/* Col 3 */}
              <div className="space-y-2 p-3.5 rounded-lg bg-cream border border-border-subtle">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-accent-gold font-semibold">INTERPRETATIONS</span>
                  <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-accent-gold/20 text-dark-olive font-medium">
                    Scored
                  </span>
                </div>
                <p className="font-sans text-xs text-secondary-olive leading-snug">
                  Heuristic adversarial reviews are explicitly labeled with confidence scores and cross-examined by LOKI before display.
                </p>
                <div className="font-mono text-[10px] p-1.5 rounded bg-ivory text-dark-olive border border-border-subtle">
                  conf: 0.94 | challenger: LOKI
                </div>
              </div>
            </div>

            {/* Sub-banner: Provenance summary */}
            <div className="p-3 rounded-lg bg-cream/70 border border-border-subtle flex flex-wrap items-center justify-between font-mono text-xs text-secondary-olive gap-2">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-sage" />
                Physical Paper Citation Lineage
              </span>
              <span className="text-dark-olive font-semibold">DOC-ID: #MSA-2024-EXP9</span>
            </div>
          </div>
        </div>

        {/* Disclaimer Banner */}
        <div className="mt-6 pt-4 border-t border-border-subtle flex items-start gap-3 text-secondary-olive">
          <Info className="w-4 h-4 text-accent-gold shrink-0 mt-0.5" />
          <p className="font-sans text-xs text-secondary-olive leading-relaxed">
            <strong className="text-dark-olive font-semibold">Legal Intelligence Notice:</strong> ODIN provides assistive intelligence and structured analysis; it does not replace professional legal counsel or guarantee judicial outcomes.
          </p>
        </div>
      </div>
    </section>
  );
}
