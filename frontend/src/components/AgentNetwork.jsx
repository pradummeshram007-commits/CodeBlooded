import React, { useState } from 'react';
import { ArrowDown, CheckCircle2 } from 'lucide-react';

const agentDetails = {
  odin: {
    name: 'ODIN',
    role: 'Autonomous Orchestrator',
    desc: 'Plans contract-specific and cross-contract workstreams, tracks progress, and coordinates the final synthesis across all specialized sub-agents.',
    badge: 'Coordinator',
    status: 'Active',
    dotColor: '#F5F1E6',
    cardId: 'agent-odin',
  },
  thor: {
    name: 'THOR: Extraction Engine',
    role: 'Fact & Obligation Extractor',
    desc: 'Identifies parties, deadlines, renewal terms, obligations, and penalties with verbatim clause anchors.',
    badge: 'Core Extractor',
    status: 'Operational Focus',
    dotColor: '#B79A59',
    cardId: 'agent-thor',
  },
  norns: {
    name: 'NORNS: Timeline Intelligence',
    role: 'Timeline & Exposure Simulator',
    desc: 'Simulates forward-looking obligation dates and calculates deterministic exposure graphs.',
    badge: 'Temporal',
    status: 'Active',
    dotColor: '#A4B18A',
    cardId: 'agent-norns',
  },
  loki: {
    name: 'LOKI: Adversarial Reviewer',
    role: 'Ambiguity & Conflict Reviewer',
    desc: 'Probes cross-clause contradictions, one-sided commitments, and latent contractual ambiguities.',
    badge: 'Adversarial',
    status: 'Active',
    dotColor: '#B79A59',
    cardId: 'agent-loki',
  },
  heimdall: {
    name: 'HEIMDALL: Event Watcher',
    role: 'Real-World Event Watcher',
    desc: 'Monitors real-world events and maps shifting obligations back to specific contract terms.',
    badge: 'Continuous',
    status: 'Active',
    dotColor: '#66734A',
    cardId: 'agent-heimdall',
  },
  tyr: {
    name: 'TYR: Resolution & Arbiter',
    role: 'Arbiter & Action Drafter',
    desc: 'Harmonizes conflicting agent analyses into evidence-linked draft actions for human counsel.',
    badge: 'Resolution',
    status: 'Active',
    dotColor: '#DCDCCB',
    cardId: 'agent-tyr',
  },
  bus: {
    name: 'Shared Evidence Bus',
    role: 'Cryptographic Fact Repository',
    desc: 'Central append-only ledger storing token-level citations, hashes, and lineage proofs.',
    badge: 'Substrate',
    status: 'Verified',
    dotColor: '#B79A59',
    cardId: 'evidence-trust',
  },
};

export default function AgentNetwork() {
  const [selectedAgent, setSelectedAgent] = useState('thor');

  const activeAgent = agentDetails[selectedAgent] || agentDetails.thor;

  const handleInspect = (cardId) => {
    const el = document.getElementById(cardId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-primary', 'scale-[1.01]');
      setTimeout(() => {
        el.classList.remove('ring-2', 'ring-primary', 'scale-[1.01]');
      }, 2000);
    }
  };

  return (
    <div className="relative w-full aspect-square max-w-[560px] mx-auto rounded-xl bg-[#263020] border border-[#3D4B33] p-4 backdrop-blur-xl shadow-2xl overflow-hidden group shadow-olive-glow">
      {/* Atmospheric Inner Spotlights */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,rgba(164,177,138,0.12),transparent_70%)] pointer-events-none" />

      {/* Operational Focus Badge for THOR */}
      <div className="absolute top-4 right-4 z-20 px-2.5 py-1 rounded bg-ivory/10 border border-primary/40 text-cream font-mono text-[11px] flex items-center gap-1.5 backdrop-blur-sm pointer-events-none">
        <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
        <span className="tracking-wider">THOR OPERATIONAL FOCUS</span>
      </div>

      {/* SVG Living Agent Graph */}
      <svg
        className="w-full h-full select-none"
        viewBox="0 0 500 500"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-label="ODIN Multi-Agent Network Topology"
      >
        <defs>
          <radialGradient id="odin-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#A4B18A" stopOpacity="0.9" />
            <stop offset="60%" stopColor="#66734A" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#1B2217" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="thor-edge-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#FCFAF3" />
            <stop offset="100%" stopColor="#B79A59" />
          </linearGradient>
        </defs>

        {/* Concentric Coordinates / Rings */}
        <circle cx="250" cy="250" r="190" stroke="rgba(220,220,203,0.12)" strokeWidth="1" />
        <circle className="pulsing-ring" cx="250" cy="250" r="145" stroke="rgba(164,177,138,0.25)" strokeDasharray="3 6" />
        <circle cx="250" cy="250" r="95" stroke="rgba(183,154,89,0.3)" strokeWidth="1.5" />
        <circle cx="250" cy="250" r="50" stroke="#A4B18A" strokeDasharray="2 4" strokeOpacity="0.5" strokeWidth="1.5" />

        {/* Dynamic Traveling Particle Connection Lines (from ODIN to Orbiters) */}
        {/* To THOR (120, 110) */}
        <path
          id="path-thor"
          className="flow-line transition-all duration-300"
          d="M 250 250 Q 180 180 120 110"
          stroke={selectedAgent === 'thor' ? '#FCFAF3' : '#FCFAF3'}
          strokeOpacity={selectedAgent === 'thor' ? 1 : 0.75}
          strokeWidth={selectedAgent === 'thor' ? 2.5 : 1.8}
        />
        {/* To NORNS (380, 110) */}
        <path
          id="path-norns"
          className="flow-line transition-all duration-300"
          d="M 250 250 Q 320 170 380 110"
          stroke="#A4B18A"
          strokeOpacity={selectedAgent === 'norns' ? 0.95 : 0.65}
          strokeWidth={selectedAgent === 'norns' ? 2.2 : 1.3}
        />
        {/* To LOKI (410, 260) */}
        <path
          id="path-loki"
          className="flow-line transition-all duration-300"
          d="M 250 250 Q 340 260 410 260"
          stroke="#B79A59"
          strokeOpacity={selectedAgent === 'loki' ? 0.95 : 0.65}
          strokeWidth={selectedAgent === 'loki' ? 2.2 : 1.3}
        />
        {/* To HEIMDALL (360, 400) */}
        <path
          id="path-heimdall"
          className="flow-line transition-all duration-300"
          d="M 250 250 Q 310 330 360 400"
          stroke="#A4B18A"
          strokeOpacity={selectedAgent === 'heimdall' ? 0.95 : 0.65}
          strokeWidth={selectedAgent === 'heimdall' ? 2.2 : 1.3}
        />
        {/* To TYR (140, 390) */}
        <path
          id="path-tyr"
          className="flow-line transition-all duration-300"
          d="M 250 250 Q 190 320 140 390"
          stroke="#DCDCCB"
          strokeOpacity={selectedAgent === 'tyr' ? 0.95 : 0.6}
          strokeWidth={selectedAgent === 'tyr' ? 2.2 : 1.3}
        />
        {/* To Shared Evidence Bus (90, 240) */}
        <path
          id="path-bus"
          className="flow-line transition-all duration-300"
          d="M 250 250 Q 170 250 90 240"
          stroke="#B79A59"
          strokeOpacity={selectedAgent === 'bus' ? 0.95 : 0.55}
          strokeWidth={selectedAgent === 'bus' ? 2.2 : 1.3}
        />

        {/* Edge Labels */}
        <text className="font-mono text-[9px] tracking-wider" fill="#FCFAF3" opacity="0.85" x="160" y="160">EXTRACT</text>
        <text className="font-mono text-[9px] tracking-wider" fill="#A4B18A" opacity="0.85" x="325" y="165">PROJECT</text>
        <text className="font-mono text-[9px] tracking-wider" fill="#B79A59" opacity="0.85" x="330" y="250">CHALLENGE</text>
        <text className="font-mono text-[9px] tracking-wider" fill="#A4B18A" opacity="0.85" x="305" y="345">VERIFY</text>
        <text className="font-mono text-[9px] tracking-wider" fill="#DCDCCB" opacity="0.85" x="175" y="340">RESOLVE</text>

        {/* Central Hub: ODIN */}
        <g
          className="cursor-pointer group/odin"
          onClick={() => {
            setSelectedAgent('odin');
            handleInspect('agent-odin');
          }}
          onMouseEnter={() => setSelectedAgent('odin')}
          role="button"
          tabIndex={0}
          aria-label="ODIN Orchestrator Hub"
        >
          <circle cx="250" cy="250" r="38" fill="url(#odin-core)" />
          <circle
            cx="250"
            cy="250"
            r="32"
            fill="#1B2217"
            stroke={selectedAgent === 'odin' ? '#FCFAF3' : '#66734A'}
            strokeWidth={selectedAgent === 'odin' ? 3 : 2}
            className="transition-all"
          />
          <circle cx="250" cy="250" r="10" fill="#FCFAF3" className="animate-pulse" />
          <text className="font-mono text-[11px] font-bold tracking-widest" fill="#F5F1E6" textAnchor="middle" x="250" y="275">ODIN</text>
          <text className="font-mono text-[8px] uppercase tracking-wider" fill="#A4B18A" textAnchor="middle" x="250" y="292">Orchestrator</text>
        </g>

        {/* 1. THOR Node */}
        <g
          className="cursor-pointer group/node"
          onClick={() => {
            setSelectedAgent('thor');
            handleInspect('agent-thor');
          }}
          onMouseEnter={() => setSelectedAgent('thor')}
          role="button"
          tabIndex={0}
          aria-label="THOR Extraction Agent"
        >
          <circle
            cx="120"
            cy="110"
            r="33"
            fill="#1B2217"
            stroke="url(#thor-edge-grad)"
            strokeWidth={selectedAgent === 'thor' ? 3.5 : 2.5}
            className="filter drop-shadow-[0_0_12px_rgba(183,154,89,0.6)] transition-all"
          />
          <circle cx="120" cy="110" r="26" fill="#263020" />
          <text className="font-mono text-[11px] font-bold" fill="#FCFAF3" textAnchor="middle" x="120" y="108">THOR</text>
          <text className="font-mono text-[7.5px]" fill="#A4B18A" textAnchor="middle" x="120" y="122">EXTRACTION</text>
          {/* Active gold dot indicator */}
          <circle cx="140" cy="90" r="4.5" fill="#B79A59" className="animate-pulse" />
        </g>

        {/* 2. NORNS Node */}
        <g
          className="cursor-pointer group/node"
          onClick={() => {
            setSelectedAgent('norns');
            handleInspect('agent-norns');
          }}
          onMouseEnter={() => setSelectedAgent('norns')}
          role="button"
          tabIndex={0}
          aria-label="NORNS Timeline Agent"
        >
          <circle
            cx="380"
            cy="110"
            r="28"
            fill="#1B2217"
            stroke="#A4B18A"
            strokeWidth={selectedAgent === 'norns' ? 2.5 : 1.5}
            className="transition-all"
          />
          <text className="font-mono text-[10px] font-bold" fill="#DCDCCB" textAnchor="middle" x="380" y="108">NORNS</text>
          <text className="font-mono text-[7.5px]" fill="#A4B18A" textAnchor="middle" x="380" y="122">TIMELINE</text>
        </g>

        {/* 3. LOKI Node */}
        <g
          className="cursor-pointer group/node"
          onClick={() => {
            setSelectedAgent('loki');
            handleInspect('agent-loki');
          }}
          onMouseEnter={() => setSelectedAgent('loki')}
          role="button"
          tabIndex={0}
          aria-label="LOKI Adversarial Agent"
        >
          <circle
            cx="410"
            cy="260"
            r="28"
            fill="#1B2217"
            stroke="#B79A59"
            strokeWidth={selectedAgent === 'loki' ? 2.5 : 1.5}
            className="transition-all"
          />
          <text className="font-mono text-[10px] font-bold" fill="#B79A59" textAnchor="middle" x="410" y="258">LOKI</text>
          <text className="font-mono text-[7.5px]" fill="#DCDCCB" textAnchor="middle" x="410" y="272">ADVERSARIAL</text>
        </g>

        {/* 4. HEIMDALL Node */}
        <g
          className="cursor-pointer group/node"
          onClick={() => {
            setSelectedAgent('heimdall');
            handleInspect('agent-heimdall');
          }}
          onMouseEnter={() => setSelectedAgent('heimdall')}
          role="button"
          tabIndex={0}
          aria-label="HEIMDALL Watcher Agent"
        >
          <circle
            cx="360"
            cy="400"
            r="28"
            fill="#1B2217"
            stroke="#66734A"
            strokeWidth={selectedAgent === 'heimdall' ? 2.5 : 1.5}
            className="transition-all"
          />
          <text className="font-mono text-[10px] font-bold" fill="#A4B18A" textAnchor="middle" x="360" y="398">HEIMDALL</text>
          <text className="font-mono text-[7.5px]" fill="#DCDCCB" textAnchor="middle" x="360" y="412">WATCHER</text>
        </g>

        {/* 5. TYR Node */}
        <g
          className="cursor-pointer group/node"
          onClick={() => {
            setSelectedAgent('tyr');
            handleInspect('agent-tyr');
          }}
          onMouseEnter={() => setSelectedAgent('tyr')}
          role="button"
          tabIndex={0}
          aria-label="TYR Arbiter Agent"
        >
          <circle
            cx="140"
            cy="390"
            r="28"
            fill="#1B2217"
            stroke="#DCDCCB"
            strokeWidth={selectedAgent === 'tyr' ? 2.5 : 1.5}
            className="transition-all"
          />
          <text className="font-mono text-[10px] font-bold" fill="#FCFAF3" textAnchor="middle" x="140" y="388">TYR</text>
          <text className="font-mono text-[7.5px]" fill="#A4B18A" textAnchor="middle" x="140" y="402">ARBITER</text>
        </g>

        {/* 6. Shared Evidence Bus Node */}
        <g
          className="cursor-pointer group/node"
          onClick={() => {
            setSelectedAgent('bus');
            handleInspect('evidence-trust');
          }}
          onMouseEnter={() => setSelectedAgent('bus')}
          role="button"
          tabIndex={0}
          aria-label="Shared Evidence Bus Node"
        >
          <circle
            cx="90"
            cy="240"
            r="26"
            fill="#1B2217"
            stroke="#B79A59"
            strokeDasharray="3 2"
            strokeWidth={selectedAgent === 'bus' ? 2.5 : 1.5}
            className="transition-all"
          />
          <text className="font-mono text-[8px] font-bold" fill="#B79A59" textAnchor="middle" x="90" y="238">EVIDENCE</text>
          <text className="font-mono text-[7px]" fill="#DCDCCB" textAnchor="middle" x="90" y="250">SHARED BUS</text>
        </g>
      </svg>

      {/* Dynamic HUD Tooltip canvas inside viewport */}
      <div
        className="absolute bottom-4 left-4 right-4 bg-[#1B2217]/95 border border-[#3D4B33] rounded-lg p-3 backdrop-blur-md shadow-lg flex items-center justify-between transition-all duration-200 pointer-events-auto"
        id="graph-tooltip"
      >
        <div className="flex items-center gap-2.5 overflow-hidden pr-2">
          <span
            className="w-2.5 h-2.5 rounded-full shrink-0"
            style={{ backgroundColor: activeAgent.dotColor }}
          />
          <div className="min-w-0">
            <div className="font-mono text-xs font-semibold text-cream flex items-center gap-2">
              <span className="truncate">{activeAgent.name}</span>
              <span className="text-[9px] px-1.5 py-0.2 rounded bg-primary/40 border border-sage/30 text-cream font-mono">
                {activeAgent.status}
              </span>
            </div>
            <div className="font-sans text-xs text-[#DCDCCB] truncate">
              {activeAgent.desc}
            </div>
          </div>
        </div>
        <button
          onClick={() => handleInspect(activeAgent.cardId)}
          className="shrink-0 font-mono text-xs text-accent-gold hover:text-cream hover:underline flex items-center gap-0.5 ml-2"
        >
          <span>Inspect</span>
          <ArrowDown className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
