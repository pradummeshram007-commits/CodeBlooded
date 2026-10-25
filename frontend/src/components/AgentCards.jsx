import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Network,
  Database,
  Clock,
  ShieldAlert,
  Radar,
  Scale,
  ArrowUpRight,
} from 'lucide-react';

export default function AgentCards() {
  const navigate = useNavigate();

  return (
    <section className="py-16 lg:py-24 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8" id="agents">
      {/* Section Header */}
      <div className="mb-12 space-y-3">
        <span className="font-mono text-xs tracking-widest uppercase text-primary font-bold">
          ONE SYSTEM. SIX SPECIALIZED RESPONSIBILITIES.
        </span>
        <h2 className="font-sans text-3xl sm:text-4xl font-bold tracking-tight text-dark-olive">
          Different perspectives. One contractual reality.
        </h2>
        <p className="font-sans text-sm sm:text-base text-secondary-olive max-w-2xl leading-relaxed">
          ODIN coordinates specialized agents that work on different parts of the same problem, sharing structured evidence rather than relying on isolated summaries.
        </p>
      </div>

      {/* 6-Card Responsive Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* 1. ODIN - The Coordinator */}
        <div
          className="rounded-xl bg-ivory border border-border-subtle p-6 flex flex-col justify-between hover:border-primary transition-all duration-300 relative group overflow-hidden shadow-sm"
          id="agent-odin"
        >
          <div className="absolute -top-12 -right-12 w-28 h-28 bg-sage/15 rounded-full blur-xl group-hover:bg-sage/25 transition-all" />
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="w-10 h-10 rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-primary group-hover:border-primary/50 transition-colors">
                <Network className="w-5 h-5 wobble-organic-1" />
              </div>
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-cream border border-border-subtle text-secondary-olive">
                Coordinator
              </span>
            </div>
            <h3 className="font-sans text-lg font-bold text-dark-olive mb-1">ODIN</h3>
            <p className="font-mono text-xs text-primary font-medium mb-3">The Autonomous Coordinator</p>
            <p className="font-sans text-xs text-secondary-olive leading-relaxed">
              Plans contract-specific and cross-contract workstreams, tracks progress, and coordinates the final synthesis across all specialized sub-agents.
            </p>
          </div>
          <div className="mt-6 pt-4 border-t border-border-subtle flex items-center justify-between font-mono text-xs text-secondary-olive">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              Synthesis Mode
            </span>
            <span>ORD-001</span>
          </div>
        </div>

        {/* 2. THOR - Core Extractor (SPOTLIGHT CARD) */}
        <div
          className="rounded-xl bg-ivory border-2 border-primary p-6 flex flex-col justify-between shadow-olive-glow transition-all duration-300 relative group overflow-hidden shadow-md"
          id="agent-thor"
        >
          <div className="absolute top-0 right-0 bg-gradient-to-l from-primary to-primary-dark text-cream font-mono text-xs font-bold px-3 py-1 rounded-bl-lg tracking-wider">
            Initial Focus
          </div>
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="w-10 h-10 rounded-lg bg-cream border border-primary/40 flex items-center justify-center text-primary shadow-xs">
                <Database className="w-5 h-5 wobble-organic-2 text-primary" />
              </div>
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-primary/10 text-primary-dark font-medium border border-primary/30">
                Core Extractor
              </span>
            </div>
            <h3 className="font-sans text-lg font-bold text-dark-olive mb-1 flex items-center gap-2">
              <span>THOR</span>
              <span className="w-2 h-2 rounded-full bg-primary animate-ping" />
            </h3>
            <p className="font-mono text-xs text-primary font-semibold mb-3">
              The Fact &amp; Obligation Extractor
            </p>
            <p className="font-sans text-xs text-secondary-olive leading-relaxed">
              Identifies parties, deadlines, renewal terms, payment schedules, obligations, penalties, compliance requirements, and termination conditions, with clause-level evidence and uncertainty flags.
            </p>
          </div>
          <div className="mt-6 pt-4 border-t border-primary/20 flex items-center justify-between font-mono text-xs">
            <span className="text-primary font-medium flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              Verbatim Anchored
            </span>
            <button
              onClick={() => navigate('/thor')}
              className="text-primary-dark font-bold hover:underline flex items-center gap-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded px-1"
            >
              <span>Launch THOR</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* 3. NORNS - Timeline Intelligence */}
        <div
          className="rounded-xl bg-ivory border border-border-subtle p-6 flex flex-col justify-between hover:border-primary transition-all duration-300 relative group overflow-hidden shadow-sm"
          id="agent-norns"
        >
          <div className="absolute -top-12 -right-12 w-28 h-28 bg-primary/10 rounded-full blur-xl group-hover:bg-primary/20 transition-all" />
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="w-10 h-10 rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-primary-dark group-hover:border-primary/50 transition-colors">
                <Clock className="w-5 h-5 wobble-organic-3" />
              </div>
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-cream border border-border-subtle text-secondary-olive">
                Temporal
              </span>
            </div>
            <h3 className="font-sans text-lg font-bold text-dark-olive mb-1">NORNS</h3>
            <p className="font-mono text-xs text-primary font-medium mb-3">
              Timeline &amp; Exposure Simulator
            </p>
            <p className="font-sans text-xs text-secondary-olive leading-relaxed">
              Projects obligations through time, simulates future dates, and estimates supported financial exposure when contractual numbers are available.
            </p>
          </div>
          <div className="mt-6 pt-4 border-t border-border-subtle flex items-center justify-between font-mono text-xs text-secondary-olive">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              Date Graph Simulation
            </span>
            <span>TEMP-003</span>
          </div>
        </div>

        {/* 4. LOKI - The Adversarial Reviewer */}
        <div
          className="rounded-xl bg-ivory border border-border-subtle p-6 flex flex-col justify-between hover:border-accent-gold transition-all duration-300 relative group overflow-hidden shadow-sm"
          id="agent-loki"
        >
          <div className="absolute -top-12 -right-12 w-28 h-28 bg-accent-gold/15 rounded-full blur-xl group-hover:bg-accent-gold/25 transition-all" />
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="w-10 h-10 rounded-lg bg-cream border border-accent-gold/40 flex items-center justify-center text-accent-gold group-hover:border-accent-gold transition-colors">
                <ShieldAlert className="w-5 h-5 wobble-organic-1" />
              </div>
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-accent-gold/10 text-dark-olive border border-accent-gold/30">
                Adversarial
              </span>
            </div>
            <h3 className="font-sans text-lg font-bold text-dark-olive mb-1">LOKI</h3>
            <p className="font-mono text-xs text-accent-gold font-semibold mb-3">
              The Ambiguity &amp; Conflict Reviewer
            </p>
            <p className="font-sans text-xs text-secondary-olive leading-relaxed">
              Investigates ambiguous terms, one-sided clauses, and conflicting commitments across multiple agreements with counter-factual probing.
            </p>
          </div>
          <div className="mt-6 pt-4 border-t border-border-subtle flex items-center justify-between font-mono text-xs text-secondary-olive">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-gold" />
              Conflict Spotter
            </span>
            <span>ADV-004</span>
          </div>
        </div>

        {/* 5. HEIMDALL - The Event Watcher */}
        <div
          className="rounded-xl bg-ivory border border-border-subtle p-6 flex flex-col justify-between hover:border-sage transition-all duration-300 relative group overflow-hidden shadow-sm"
          id="agent-heimdall"
        >
          <div className="absolute -top-12 -right-12 w-28 h-28 bg-sage/20 rounded-full blur-xl group-hover:bg-sage/30 transition-all" />
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="w-10 h-10 rounded-lg bg-cream border border-sage/40 flex items-center justify-center text-primary group-hover:border-sage transition-colors">
                <Radar className="w-5 h-5 wobble-organic-2" />
              </div>
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-sage/20 text-dark-olive border border-sage/30">
                Continuous
              </span>
            </div>
            <h3 className="font-sans text-lg font-bold text-dark-olive mb-1">HEIMDALL</h3>
            <p className="font-mono text-xs text-primary font-medium mb-3">
              The Real-World Event Watcher
            </p>
            <p className="font-sans text-xs text-secondary-olive leading-relaxed">
              Maps relevant events to contracts and clauses, verifies findings against external factual data, and identifies changes in potential legal exposure.
            </p>
          </div>
          <div className="mt-6 pt-4 border-t border-border-subtle flex items-center justify-between font-mono text-xs text-secondary-olive">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-sage" />
              Dynamic Watchdog
            </span>
            <span>EVT-005</span>
          </div>
        </div>

        {/* 6. TYR - The Arbiter */}
        <div
          className="rounded-xl bg-ivory border border-border-subtle p-6 flex flex-col justify-between hover:border-primary-dark transition-all duration-300 relative group overflow-hidden shadow-sm"
          id="agent-tyr"
        >
          <div className="absolute -top-12 -right-12 w-28 h-28 bg-primary/10 rounded-full blur-xl group-hover:bg-primary/20 transition-all" />
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="w-10 h-10 rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-primary-dark group-hover:border-primary-dark transition-colors">
                <Scale className="w-5 h-5 wobble-organic-3" />
              </div>
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-cream border border-border-subtle text-secondary-olive">
                Resolution
              </span>
            </div>
            <h3 className="font-sans text-lg font-bold text-dark-olive mb-1">TYR</h3>
            <p className="font-mono text-xs text-primary-dark font-medium mb-3">
              The Arbiter &amp; Action Drafter
            </p>
            <p className="font-sans text-xs text-secondary-olive leading-relaxed">
              Records resolutions between competing findings and drafts evidence-linked actions for formal human review and legal approval.
            </p>
          </div>
          <div className="mt-6 pt-4 border-t border-border-subtle flex items-center justify-between font-mono text-xs text-secondary-olive">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary-dark" />
              Human-Gated
            </span>
            <span>ARB-006</span>
          </div>
        </div>
      </div>
    </section>
  );
}
