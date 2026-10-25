import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, ArrowDown, ShieldCheck } from 'lucide-react';
import AgentNetwork from './AgentNetwork';

export default function HeroSection() {
  const navigate = useNavigate();

  const scrollToAgents = () => {
    const el = document.getElementById('agents');
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <section className="min-h-[calc(100vh-4rem)] flex items-center py-12 lg:py-20 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative" id="hero">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-8 items-center w-full">
        {/* Left Column: Editorial & Value Proposition */}
        <div className="lg:col-span-6 space-y-6">
          {/* Eyebrow Pill */}
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-ivory border border-primary/30 shadow-xs animate-fade-slide-up [animation-delay:100ms]">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
            </span>
            <span className="font-mono text-[11px] tracking-wider uppercase text-primary font-semibold">
              MULTI-AGENT CONTRACT INTELLIGENCE
            </span>
          </div>

          {/* Headline */}
          <h1 className="font-sans text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-dark-olive leading-[1.08] animate-fade-slide-up [animation-delay:200ms]">
            Contracts don't just contain terms.<br />
            <span className="bg-gradient-to-r from-primary-dark via-primary to-accent-gold bg-clip-text text-transparent">
              They contain future consequences.
            </span>
          </h1>

          {/* Supporting Copy */}
          <p className="font-sans text-base sm:text-lg text-secondary-olive max-w-xl leading-relaxed animate-fade-slide-up [animation-delay:300ms]">
            Meet ODIN: a coordinated intelligence system that turns contractual language into traceable obligations, time-aware risks, and evidence-backed actions.
          </p>

          {/* CTAs */}
          <div className="pt-2 flex flex-wrap items-center gap-4 animate-fade-slide-up [animation-delay:400ms]">
            <button
              onClick={() => navigate('/dashboard')}
              className="inline-flex items-center gap-2 px-6 py-3.5 rounded-lg bg-primary-dark text-cream font-mono text-xs font-semibold transition-all duration-200 active:scale-95 shadow-md hover:bg-dark-olive hover:shadow-[0_4px_18px_rgba(48,59,40,0.35)] focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span>Launch ODIN</span>
              <ArrowUpRight className="w-4 h-4" />
            </button>
            <button
              onClick={scrollToAgents}
              className="inline-flex items-center gap-2 px-5 py-3.5 rounded-lg bg-ivory border border-primary/40 text-dark-olive font-mono text-xs font-medium hover:border-primary hover:bg-cream transition-all shadow-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span>Explore the Agent Network</span>
              <ArrowDown className="w-4 h-4" />
            </button>
          </div>

          {/* Descriptor */}
          <p className="font-mono text-xs tracking-wide text-secondary-olive flex items-center gap-2 pt-2 animate-fade-slide-up [animation-delay:500ms]">
            <ShieldCheck className="w-4 h-4 text-primary shrink-0" />
            <span>Evidence-linked. Time-aware. Built for accountable decisions.</span>
          </p>

          {/* Micro Architecture Badges */}
          <div className="pt-6 border-t border-border-subtle flex flex-wrap gap-3 sm:gap-4 items-center animate-fade-slide-up [animation-delay:600ms]">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-ivory border border-border-subtle shadow-xs">
              <span className="w-2 h-2 rounded-full bg-primary" />
              <span className="font-mono text-xs text-dark-olive font-medium">6 Specialized Agents</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-ivory border border-border-subtle shadow-xs">
              <span className="w-2 h-2 rounded-full bg-sage" />
              <span className="font-mono text-xs text-dark-olive font-medium">Determinism Engine</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-ivory border border-border-subtle shadow-xs">
              <span className="w-2 h-2 rounded-full bg-accent-gold" />
              <span className="font-mono text-xs text-dark-olive font-medium">Full Lineage Audit</span>
            </div>
          </div>
        </div>

        {/* Right Column: Real Contract Image Underlayer + Agent Network */}
        <div className="lg:col-span-6 relative animate-fade-slide-up [animation-delay:400ms]">
          {/* Contract Image Underlayer Backdrop */}
          <div className="absolute -top-6 -right-6 w-full h-full rounded-2xl overflow-hidden border border-border-subtle/80 shadow-lg pointer-events-none hidden sm:block opacity-65 transform rotate-1 scale-[0.98]">
            <img
              alt="Top-down architectural still life of layered legal contract documents on fine ivory archival paper"
              className="w-full h-full object-cover filter contrast-[1.03] sepia-[0.1]"
              src="/assets/contract_underlayer.jpg"
              loading="lazy"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-cream via-transparent to-transparent opacity-80" />
          </div>

          {/* Dynamic Living Agent Network Visualization */}
          <AgentNetwork />
        </div>
      </div>
    </section>
  );
}
