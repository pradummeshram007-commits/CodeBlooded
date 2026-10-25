import React from 'react';
import { useNavigate } from 'react-router-dom';

export default function DashboardNav({ searchQuery, onSearchChange, onDeployClick }) {
  const navigate = useNavigate();

  return (
    <header className="w-full h-16 bg-odin-forest text-odin-cream border-b border-[#21281B] px-4 sm:px-6 lg:px-8 flex items-center justify-between z-50 sticky top-0 shadow-sm flex-shrink-0">
      {/* Left: Brand mark & telemetric status */}
      <div className="flex items-center gap-6">
        <div 
          onClick={() => navigate('/')} 
          className="flex items-center gap-3 cursor-pointer group"
          title="Return to ODIN Landing"
        >
          <div className="w-8 h-8 rounded bg-[#252E1F] border border-odin-sage/40 flex items-center justify-center text-odin-cream font-bold font-mono text-sm shadow-inner group-hover:border-odin-palesage transition-colors">
            <span className="material-symbols-outlined text-odin-palesage text-base" style={{ fontVariationSettings: "'FILL' 1" }}>
              account_balance
            </span>
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="font-bold text-base tracking-wider text-white font-mono">ODIN</span>
              <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-odin-panel text-odin-palesage border border-odin-sage/30">
                v4.2
              </span>
            </div>
            <span className="text-[10px] text-odin-muted tracking-tight">Enterprise Intelligence</span>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="hidden xl:flex items-center gap-1 font-mono text-xs">
          <a
            className="px-3 py-1.5 rounded bg-[#3D4B33] text-white font-semibold flex items-center gap-1.5 shadow-sm border border-odin-sage/30"
            href="#dashboard"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-odin-palesage"></span>
            Dashboard
          </a>
          <a
            className="px-3 py-1.5 rounded text-odin-cream/80 hover:text-white hover:bg-[#38452F] transition-colors"
            href="#contracts"
          >
            Contracts
          </a>
          <button
            onClick={() => navigate('/thor')}
            className="px-3 py-1.5 rounded text-odin-cream/80 hover:text-white hover:bg-[#38452F] transition-colors flex items-center gap-1 cursor-pointer"
          >
            <span className="material-symbols-outlined text-xs text-odin-amber">bolt</span>
            THOR — Extraction
          </button>
          <button
            onClick={() => navigate('/norns')}
            className="px-3 py-1.5 rounded text-odin-cream/80 hover:text-white hover:bg-[#38452F] transition-colors flex items-center gap-1 cursor-pointer"
          >
            <span className="material-symbols-outlined text-xs text-odin-palesage">schedule</span>
            NORNS — Timeline
          </button>
          <a
            className="px-3 py-1.5 rounded text-odin-cream/80 hover:text-white hover:bg-[#38452F] transition-colors"
            href="#agents"
          >
            Agent Activity
          </a>
          <a
            className="px-3 py-1.5 rounded text-odin-cream/80 hover:text-white hover:bg-[#38452F] transition-colors"
            href="#actions"
          >
            Actions &amp; Notices
          </a>
        </nav>
      </div>

      {/* Right utility controls */}
      <div className="flex items-center gap-3">
        {/* Search Input */}
        <div className="relative hidden md:block w-56 lg:w-72">
          <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-odin-sage text-sm">
            search
          </span>
          <input
            className="w-full pl-8 pr-10 py-1.5 text-xs bg-odin-panel text-odin-cream placeholder:text-odin-muted rounded border border-odin-sage/30 focus:outline-none focus:border-odin-palesage font-mono"
            placeholder="Search contracts, clauses (§)..."
            type="text"
            value={searchQuery || ''}
            onChange={(e) => onSearchChange && onSearchChange(e.target.value)}
          />
          <kbd className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono px-1 py-0.5 rounded bg-[#252E1F] text-odin-sage border border-odin-sage/20">
            ⌘K
          </kbd>
        </div>

        {/* Engine Status Chip */}
        <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded bg-odin-panel border border-odin-sage/25 text-[11px] font-mono text-odin-cream/90">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>Deterministic Engine v2.4</span>
        </div>

        {/* Worst-Case Timeline High-Contrast Red Button */}
        <button
          onClick={() => navigate('/norns')}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-odin-red hover:bg-odin-darkred text-white text-xs font-mono font-semibold transition-all shadow-sm active:scale-95"
          title="Open Worst-Case Exposure Matrix in NORNS"
        >
          <span className="material-symbols-outlined text-xs">warning</span>
          <span>Worst-Case Timeline</span>
          <span className="text-xs">↗</span>
        </button>

        {/* Deploy Agent / Trigger Audit Action */}
        <button
          onClick={onDeployClick}
          className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-odin-palesage text-odin-dark hover:bg-white text-xs font-mono font-semibold transition-all shadow-sm active:scale-95"
          type="button"
        >
          <span className="material-symbols-outlined text-xs text-odin-forest">smart_toy</span>
          <span>Deploy Agent</span>
        </button>

        {/* User Operator Identifier */}
        <div
          className="w-8 h-8 rounded bg-odin-panel border border-odin-sage/40 flex items-center justify-center font-mono text-xs font-bold text-odin-cream shadow-inner cursor-default"
          title="Operator Key: EO-9 (Counsel Enclave)"
        >
          EO-9
        </div>
      </div>
    </header>
  );
}
