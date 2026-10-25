import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, ArrowDown, Network } from 'lucide-react';

export default function FinalCTA() {
  const navigate = useNavigate();

  const scrollToHowItWorks = () => {
    const el = document.getElementById('how-it-works');
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <section className="py-20 lg:py-28 relative overflow-hidden border-t border-[#3D4B33] bg-primary-dark text-cream">
      {/* Convergent Perspective Ray Illusion */}
      <div className="absolute inset-0 pointer-events-none opacity-20">
        <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 1000 400">
          <path d="M 0 400 L 500 0 L 1000 400" fill="none" stroke="#A4B18A" strokeWidth="0.8" />
          <path d="M 150 400 L 500 0 L 850 400" fill="none" stroke="#B79A59" strokeWidth="0.8" />
          <path d="M 300 400 L 500 0 L 700 400" fill="none" stroke="#A4B18A" strokeWidth="0.8" />
          <circle cx="500" cy="0" r="120" fill="#A4B18A" opacity="0.15" />
        </svg>
      </div>

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center relative z-10 space-y-6">
        <div className="w-12 h-12 mx-auto rounded-xl bg-[#252E1F] border border-sage/40 flex items-center justify-center text-sage shadow-md">
          <Network className="w-6 h-6 text-sage" />
        </div>

        <h2 className="font-sans text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-cream">
          See the risk before it becomes a surprise.
        </h2>

        <p className="font-sans text-base sm:text-lg text-[#DCDCCB] max-w-2xl mx-auto leading-relaxed">
          Turn disconnected contractual obligations into a clearer, evidence-backed view of what needs attention next.
        </p>

        <div className="pt-4 flex flex-wrap items-center justify-center gap-4">
          <button
            onClick={() => navigate('/thor')}
            className="inline-flex items-center gap-2 px-8 py-4 rounded-lg bg-cream text-dark-olive font-mono text-xs sm:text-sm font-bold transition-all duration-200 active:scale-95 shadow-md hover:bg-ivory hover:shadow-[0_4px_20px_rgba(252,250,243,0.35)] focus:outline-none focus-visible:ring-2 focus-visible:ring-cream"
          >
            <span>Launch ODIN</span>
            <ArrowUpRight className="w-4 h-4" />
          </button>
          <button
            onClick={scrollToHowItWorks}
            className="inline-flex items-center gap-2 px-6 py-4 rounded-lg bg-[#252E1F] border border-[#3D4B33] text-cream font-mono text-xs sm:text-sm font-medium hover:border-sage hover:bg-[#303B28] transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-sage"
          >
            <span>Explore How It Works</span>
            <ArrowDown className="w-4 h-4" />
          </button>
        </div>

        <p className="font-mono text-xs text-[#A4B18A] pt-4">
          Strict Enterprise Data Isolation • Human-in-the-Loop Safeguards
        </p>
      </div>
    </section>
  );
}
