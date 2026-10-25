import React from 'react';

export default function HowItWorks() {
  return (
    <section className="py-16 lg:py-24 border-t border-[#3D4B33] bg-primary-dark text-cream" id="how-it-works">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="mb-14 space-y-3">
          <span className="font-mono text-xs tracking-widest uppercase text-sage font-semibold">
            DETERMINISTIC PIPELINE EXECUTION
          </span>
          <h2 className="font-sans text-3xl sm:text-4xl font-bold tracking-tight text-cream">
            How ODIN Operates
          </h2>
          <p className="font-sans text-sm sm:text-base text-[#DCDCCB] max-w-2xl leading-relaxed">
            A continuous loop from raw text ingestion to verified legal action. Every stage preserves a cryptographic lineage back to verbatim contractual text.
          </p>
        </div>

        {/* 4-Step Progressive Timeline Workflow */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 relative">
          {/* Step 1 */}
          <div className="rounded-xl bg-[#252E1F] border border-[#3D4B33] p-6 flex flex-col justify-between relative group hover:border-sage transition-all shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-cream px-2.5 py-1 rounded bg-[#35422D] border border-sage/30 font-bold">
                  01
                </span>
                <span className="font-mono text-xs text-[#A4B18A] tracking-wider">
                  INGESTION
                </span>
              </div>
              <h3 className="font-sans text-lg font-bold text-cream">Read the Contract</h3>
              <p className="font-sans text-xs text-[#DCDCCB] leading-relaxed">
                THOR identifies contractual facts and retains the language supporting each extraction with sentence-level coordinates.
              </p>

              {/* Diagram Preview: Syntax Tree Fragment */}
              <div className="mt-4 p-3 rounded bg-[#1B2217] border border-[#3D4B33] font-mono text-xs text-[#DCDCCB] space-y-1.5">
                <div className="text-sage flex items-center gap-1.5 font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-sage" />
                  <span>§ 14.3 Termination</span>
                </div>
                <div className="pl-3 border-l border-[#3D4B33] text-[11px]">
                  → Window: [90 Days Prior]
                </div>
                <div className="pl-3 border-l border-[#3D4B33] text-[11px] text-accent-gold">
                  ✓ Verbatim Linked
                </div>
              </div>
            </div>
            <div className="mt-6 pt-3 border-t border-[#3D4B33] font-mono text-xs text-sage">
              Step 01 Pipeline Complete
            </div>
          </div>

          {/* Step 2 */}
          <div className="rounded-xl bg-[#252E1F] border border-[#3D4B33] p-6 flex flex-col justify-between relative group hover:border-sage transition-all shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-cream px-2.5 py-1 rounded bg-[#35422D] border border-sage/30 font-bold">
                  02
                </span>
                <span className="font-mono text-xs text-[#A4B18A] tracking-wider">
                  SIMULATION
                </span>
              </div>
              <h3 className="font-sans text-lg font-bold text-cream">Model the Consequences</h3>
              <p className="font-sans text-xs text-[#DCDCCB] leading-relaxed">
                NORNS maps obligations and deadlines onto a timeline, including supported worst-case financial projections.
              </p>

              {/* Diagram Preview: Timeline Milestones */}
              <div className="mt-4 p-3 rounded bg-[#1B2217] border border-[#3D4B33] font-mono text-xs text-[#DCDCCB] space-y-1.5">
                <div className="text-cream flex items-center justify-between text-[11px]">
                  <span>T+0: Execution</span>
                  <span>OCT 2024</span>
                </div>
                <div className="w-full bg-[#35422D] h-1.5 rounded-full overflow-hidden">
                  <div className="bg-sage h-full w-2/3 rounded-full" />
                </div>
                <div className="text-accent-gold text-[11px] flex items-center justify-between">
                  <span>T+270: Notice Deadline</span>
                  <span>JUL 2025</span>
                </div>
              </div>
            </div>
            <div className="mt-6 pt-3 border-t border-[#3D4B33] font-mono text-xs text-sage">
              Step 02 Timeline Synced
            </div>
          </div>

          {/* Step 3 */}
          <div className="rounded-xl bg-[#252E1F] border border-[#3D4B33] p-6 flex flex-col justify-between relative group hover:border-accent-gold transition-all shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-accent-gold px-2.5 py-1 rounded bg-accent-gold/15 border border-accent-gold/30 font-bold">
                  03
                </span>
                <span className="font-mono text-xs text-[#A4B18A] tracking-wider">
                  COLLISION
                </span>
              </div>
              <h3 className="font-sans text-lg font-bold text-cream">Challenge Interpretation</h3>
              <p className="font-sans text-xs text-[#DCDCCB] leading-relaxed">
                LOKI investigates ambiguities and cross-clause conflicts; HEIMDALL evaluates relevant external events and evidence.
              </p>

              {/* Diagram Preview: Collision Detection */}
              <div className="mt-4 p-3 rounded bg-[#1B2217] border border-[#3D4B33] font-mono text-xs text-[#DCDCCB] space-y-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-accent-gold">Overlap Clash: §4 vs §18</span>
                  <span className="text-[#FF8D7A] font-semibold">Flagged</span>
                </div>
                <div className="text-[10px] text-[#A4B18A]">
                  Indemnification scope exceeds liability cap.
                </div>
              </div>
            </div>
            <div className="mt-6 pt-3 border-t border-[#3D4B33] font-mono text-xs text-accent-gold">
              Step 03 Adversarial Review
            </div>
          </div>

          {/* Step 4 */}
          <div className="rounded-xl bg-[#252E1F] border border-[#3D4B33] p-6 flex flex-col justify-between relative group hover:border-sage transition-all shadow-sm">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-cream px-2.5 py-1 rounded bg-[#35422D] border border-sage/30 font-bold">
                  04
                </span>
                <span className="font-mono text-xs text-[#A4B18A] tracking-wider">
                  ARBITRATION
                </span>
              </div>
              <h3 className="font-sans text-lg font-bold text-cream">Resolve and Recommend</h3>
              <p className="font-sans text-xs text-[#DCDCCB] leading-relaxed">
                TYR records the reasoning behind a resolution and prepares actions for human review, while ODIN coordinates workflow.
              </p>

              {/* Diagram Preview: Human-in-the-loop Checkpoint */}
              <div className="mt-4 p-3 rounded bg-[#1B2217] border border-[#3D4B33] font-mono text-xs text-[#DCDCCB] space-y-1.5">
                <div className="text-cream flex items-center justify-between text-[11px]">
                  <span>Action: Formal Cure Notice</span>
                  <span className="text-sage font-bold">READY</span>
                </div>
                <div className="text-[10px] text-[#A4B18A]">
                  Requires Partner Counsel Signature [e-Sign]
                </div>
              </div>
            </div>
            <div className="mt-6 pt-3 border-t border-[#3D4B33] font-mono text-xs text-sage">
              Step 04 Human-Gated Approval
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
