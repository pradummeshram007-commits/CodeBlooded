import React from 'react';

export default function ScrollingText() {
  const ribbonItems = (
    <>
      <span className="mx-6 inline-flex items-center gap-3">
        EXTRACT <span className="text-sage">→</span> PROJECT <span className="text-cream">→</span> CHALLENGE <span className="text-accent-gold">→</span> VERIFY <span className="text-sage">→</span> RESOLVE <span className="text-cream">→</span>
      </span>
      <span className="mx-6 inline-flex items-center gap-3">
        EXTRACT <span className="text-sage">→</span> PROJECT <span className="text-cream">→</span> CHALLENGE <span className="text-accent-gold">→</span> VERIFY <span className="text-sage">→</span> RESOLVE <span className="text-cream">→</span>
      </span>
      <span className="mx-6 inline-flex items-center gap-3">
        EXTRACT <span className="text-sage">→</span> PROJECT <span className="text-cream">→</span> CHALLENGE <span className="text-accent-gold">→</span> VERIFY <span className="text-sage">→</span> RESOLVE <span className="text-cream">→</span>
      </span>
      <span className="mx-6 inline-flex items-center gap-3">
        EXTRACT <span className="text-sage">→</span> PROJECT <span className="text-cream">→</span> CHALLENGE <span className="text-accent-gold">→</span> VERIFY <span className="text-sage">→</span> RESOLVE <span className="text-cream">→</span>
      </span>
    </>
  );

  return (
    <section className="border-y border-[#3D4B33] bg-primary-dark text-cream relative overflow-hidden py-10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mb-6">
        <div className="max-w-3xl space-y-2">
          <h2 className="font-sans text-2xl sm:text-3xl font-bold text-cream tracking-tight">
            A contract is signed once. Its consequences unfold every day.
          </h2>
          <p className="font-sans text-sm sm:text-base text-[#DCDCCB] leading-relaxed">
            Renewal windows close. Payment obligations mature. Clauses collide. External events change what matters. ODIN is designed to help teams understand these moving relationships instead of relying on a forgotten PDF.
          </p>
        </div>
      </div>

      {/* Marquee Ribbon */}
      <div className="border-t border-[#3D4B33] pt-4 pb-2 bg-[#252E1F]">
        <div
          className="relative w-full overflow-hidden whitespace-nowrap flex"
          aria-label="Workflow pipeline stages: Extract, Project, Challenge, Verify, Resolve"
        >
          <div className="animate-marquee font-mono text-xs sm:text-sm font-semibold tracking-widest text-[#DCDCCB] select-none hover:[animation-play-state:paused]">
            {ribbonItems}
          </div>
          <div
            aria-hidden="true"
            className="animate-marquee font-mono text-xs sm:text-sm font-semibold tracking-widest text-[#DCDCCB] select-none hover:[animation-play-state:paused]"
          >
            {ribbonItems}
          </div>
        </div>
      </div>
    </section>
  );
}
