import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function OdinTopNav({
  activePage = 'dashboard',
  searchQuery,
  onSearchChange,
  onDeployClick,
}) {
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="w-full h-16 bg-odin-forest text-odin-cream border-b border-[#21281B] px-4 sm:px-6 lg:px-8 flex items-center justify-between z-50 sticky top-0 shadow-sm flex-shrink-0">
      {/* Left: Brand mark & telemetric status */}
      <div className="flex items-center gap-6">
        <div
          onClick={() => navigate('/dashboard')}
          className="flex items-center gap-3 cursor-pointer group"
          title="ODIN Command Center"
        >
          <div className="w-8 h-8 rounded bg-[#252E1F] border border-odin-sage/40 flex items-center justify-center text-odin-cream font-bold font-mono text-sm shadow-inner group-hover:border-odin-palesage transition-colors">
            <span
              className="material-symbols-outlined text-odin-palesage text-base"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
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

        {/* Navigation Links (Desktop/Tablet) */}
        <nav className="hidden lg:flex items-center gap-1 font-mono text-xs whitespace-nowrap">
          <button
            onClick={() => navigate('/')}
            className={`px-3 py-1.5 rounded transition-colors flex items-center gap-1.5 cursor-pointer ${
              activePage === 'home'
                ? 'bg-[#3D4B33] text-white font-semibold shadow-sm border border-odin-sage/30'
                : 'text-odin-cream/80 hover:text-white hover:bg-[#38452F]'
            }`}
          >
            Overview
          </button>

          <button
            onClick={() => navigate('/dashboard')}
            className={`px-3 py-1.5 rounded transition-colors flex items-center gap-1.5 cursor-pointer ${
              activePage === 'dashboard'
                ? 'bg-[#3D4B33] text-white font-semibold shadow-sm border border-odin-sage/30'
                : 'text-odin-cream/80 hover:text-white hover:bg-[#38452F]'
            }`}
          >
            {activePage === 'dashboard' && (
              <span className="w-1.5 h-1.5 rounded-full bg-odin-palesage"></span>
            )}
            Dashboard
          </button>

          <button
            onClick={() => navigate('/odin')}
            className={`px-3 py-1.5 rounded transition-colors flex items-center gap-1 cursor-pointer ${
              activePage === 'odin'
                ? 'bg-[#3D4B33] text-white font-semibold shadow-sm border border-odin-sage/30'
                : 'text-odin-cream/80 hover:text-white hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-palesage">account_tree</span>
            ODIN<span className="hidden 2xl:inline"> — Pipeline</span>
          </button>

          <button
            onClick={() => navigate('/thor')}
            className={`px-3 py-1.5 rounded transition-colors flex items-center gap-1 cursor-pointer ${
              activePage === 'thor' || activePage === 'contracts'
                ? 'bg-[#3D4B33] text-white font-semibold shadow-sm border border-odin-sage/30'
                : 'text-odin-cream/80 hover:text-white hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-amber">bolt</span>
            THOR<span className="hidden 2xl:inline"> — Extraction</span>
          </button>

          <button
            onClick={() => navigate('/norns')}
            className={`px-3 py-1.5 rounded transition-colors flex items-center gap-1 cursor-pointer ${
              activePage === 'norns'
                ? 'bg-[#3D4B33] text-white font-semibold shadow-sm border border-odin-sage/30'
                : 'text-odin-cream/80 hover:text-white hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-palesage">schedule</span>
            NORNS<span className="hidden 2xl:inline"> — Timeline</span>
          </button>

          <button
            onClick={() => navigate('/loki')}
            className={`px-3 py-1.5 rounded transition-colors flex items-center gap-1 cursor-pointer ${
              activePage === 'loki'
                ? 'bg-[#3D4B33] text-white font-semibold shadow-sm border border-odin-sage/30'
                : 'text-odin-cream/80 hover:text-white hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-amber">gavel</span>
            LOKI<span className="hidden 2xl:inline"> — Review</span>
          </button>

          <button
            onClick={() => navigate('/heimdall')}
            className={`px-3 py-1.5 rounded transition-colors flex items-center gap-1 cursor-pointer ${
              activePage === 'heimdall'
                ? 'bg-[#3D4B33] text-white font-semibold shadow-sm border border-odin-sage/30'
                : 'text-odin-cream/80 hover:text-white hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-palesage">radar</span>
            HEIMDALL<span className="hidden 2xl:inline"> — Events</span>
          </button>

          <button
            onClick={() => {
              navigate('/dashboard');
              setTimeout(() => {
                const el = document.getElementById('agents');
                if (el) el.scrollIntoView({ behavior: 'smooth' });
              }, 100);
            }}
            className="hidden 2xl:block px-2.5 py-1.5 rounded text-odin-cream/80 hover:text-white hover:bg-[#38452F] transition-colors cursor-pointer whitespace-nowrap"
          >
            Agent Activity
          </button>

          <button
            onClick={() => {
              navigate('/dashboard');
              setTimeout(() => {
                const el = document.getElementById('actions');
                if (el) el.scrollIntoView({ behavior: 'smooth' });
              }, 100);
            }}
            className="hidden 2xl:block px-2.5 py-1.5 rounded text-odin-cream/80 hover:text-white hover:bg-[#38452F] transition-colors cursor-pointer whitespace-nowrap"
          >
            Actions &amp; Notices
          </button>
        </nav>
      </div>

      {/* Right utility controls */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* Search Input */}
        <div className="relative hidden 2xl:block w-52 lg:w-64">
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
        <div className="hidden 2xl:flex items-center gap-1.5 px-2.5 py-1 rounded bg-odin-panel border border-odin-sage/25 text-[11px] font-mono text-odin-cream/90">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>Deterministic Engine v2.4</span>
        </div>

        {/* Worst-Case Timeline High-Contrast Red Button */}
        <button
          onClick={() => navigate('/norns')}
          className="inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded bg-odin-red hover:bg-odin-darkred text-white text-xs font-mono font-semibold transition-all shadow-sm active:scale-95 cursor-pointer"
          title="Open Worst-Case Exposure Matrix in NORNS"
        >
          <span className="material-symbols-outlined text-xs">warning</span>
          <span className="hidden sm:inline">Worst-Case</span> Timeline
          <span className="text-xs">↗</span>
        </button>

        {/* Deploy Agent / Trigger Audit Action */}
        <button
          onClick={onDeployClick || (() => navigate('/thor'))}
          className="hidden md:inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-odin-palesage text-odin-dark hover:bg-white text-xs font-mono font-semibold transition-all shadow-sm active:scale-95 cursor-pointer"
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

        {/* Mobile / Tablet Menu Toggle */}
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="lg:hidden flex items-center justify-center w-8 h-8 rounded bg-odin-panel border border-odin-sage/40 text-odin-cream hover:bg-[#38452F] transition-colors cursor-pointer"
          aria-label="Toggle Navigation Menu"
        >
          <span className="material-symbols-outlined text-base">
            {mobileMenuOpen ? 'close' : 'menu'}
          </span>
        </button>
      </div>

      {/* Mobile / Tablet Navigation Drawer */}
      {mobileMenuOpen && (
        <div className="lg:hidden absolute top-16 left-0 w-full bg-odin-forest border-b border-[#21281B] px-4 py-3 flex flex-col gap-2 font-mono text-xs shadow-xl animate-fade-slide-up z-50">
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              navigate('/');
            }}
            className={`w-full text-left px-3 py-2 rounded transition-colors ${
              activePage === 'home' ? 'bg-[#3D4B33] text-white font-bold' : 'text-odin-cream/90 hover:bg-[#38452F]'
            }`}
          >
            Overview (Landing Page)
          </button>
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              navigate('/dashboard');
            }}
            className={`w-full text-left px-3 py-2 rounded transition-colors ${
              activePage === 'dashboard' ? 'bg-[#3D4B33] text-white font-bold' : 'text-odin-cream/90 hover:bg-[#38452F]'
            }`}
          >
            Command Dashboard
          </button>
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              navigate('/odin');
            }}
            className={`w-full text-left px-3 py-2 rounded transition-colors flex items-center gap-1.5 ${
              activePage === 'odin' ? 'bg-[#3D4B33] text-white font-bold' : 'text-odin-cream/90 hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-palesage">account_tree</span>
            ODIN — Pipeline &amp; Workstreams
          </button>
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              navigate('/thor');
            }}
            className={`w-full text-left px-3 py-2 rounded transition-colors flex items-center gap-1.5 ${
              activePage === 'thor' || activePage === 'contracts' ? 'bg-[#3D4B33] text-white font-bold' : 'text-odin-cream/90 hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-amber">bolt</span>
            THOR — Extraction &amp; War Room
          </button>
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              navigate('/norns');
            }}
            className={`w-full text-left px-3 py-2 rounded transition-colors flex items-center gap-1.5 ${
              activePage === 'norns' ? 'bg-[#3D4B33] text-white font-bold' : 'text-odin-cream/90 hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-palesage">schedule</span>
            NORNS — Obligations &amp; Timeline
          </button>
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              navigate('/loki');
            }}
            className={`w-full text-left px-3 py-2 rounded transition-colors flex items-center gap-1.5 ${
              activePage === 'loki' ? 'bg-[#3D4B33] text-white font-bold' : 'text-odin-cream/90 hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-amber">gavel</span>
            LOKI — Adversarial Review
          </button>
          <button
            onClick={() => {
              setMobileMenuOpen(false);
              navigate('/heimdall');
            }}
            className={`w-full text-left px-3 py-2 rounded transition-colors flex items-center gap-1.5 ${
              activePage === 'heimdall' ? 'bg-[#3D4B33] text-white font-bold' : 'text-odin-cream/90 hover:bg-[#38452F]'
            }`}
          >
            <span className="material-symbols-outlined text-xs text-odin-palesage">radar</span>
            HEIMDALL — Events &amp; Task Board
          </button>
          <div className="pt-2 border-t border-odin-sage/20 flex flex-col gap-2">
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/norns');
              }}
              className="w-full py-2 px-3 rounded bg-odin-red text-white font-bold flex items-center justify-center gap-1.5"
            >
              <span className="material-symbols-outlined text-xs">warning</span>
              <span>Worst-Case Timeline Matrix</span>
            </button>
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/thor');
              }}
              className="w-full py-2 px-3 rounded bg-odin-palesage text-odin-dark font-bold flex items-center justify-center gap-1.5"
            >
              <span className="material-symbols-outlined text-xs text-odin-forest">smart_toy</span>
              <span>Intake New Agreement (THOR)</span>
            </button>
          </div>
        </div>
      )}
    </header>
  );
}

