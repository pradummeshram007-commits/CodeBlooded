import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, ArrowLeft } from 'lucide-react';

export default function ThorNavbar({ activeNav = 'contracts', setActiveNav }) {
  const navigate = useNavigate();

  return (
    <header className="bg-primary-dark text-cream sticky top-0 z-50 shadow-md border-b border-[#3D4B33]">
      <div className="w-full max-w-7xl mx-auto flex items-center justify-between px-4 sm:px-6 lg:px-8 py-3">
        {/* Brand & Breadcrumb */}
        <div className="flex items-center space-x-3 sm:space-x-4">
          <button
            onClick={() => navigate('/')}
            className="flex items-center space-x-2 text-cream hover:opacity-90 transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-sage rounded"
            aria-label="Return to ODIN Home"
          >
            <div className="w-7 h-7 rounded-lg bg-[#252E1F] border border-sage/40 flex items-center justify-center text-sage">
              <Network className="w-4 h-4 text-sage" />
            </div>
            <span className="font-sans text-base font-bold tracking-wider text-cream">ODIN</span>
          </button>

          <span className="text-sage/40">|</span>

          <div className="flex items-center font-mono text-xs text-[#DCDCCB] space-x-1.5">
            <span className="hidden sm:inline">ODIN</span>
            <span className="text-sage/60 hidden sm:inline">/</span>
            <span className="text-cream font-semibold">THOR · Contract Extraction</span>
          </div>
        </div>

        {/* Center Nav Links */}
        <nav className="hidden md:flex items-center space-x-6 font-mono text-xs">
          <button
            onClick={() => navigate('/')}
            className="text-sage hover:text-cream transition-colors py-1"
          >
            Overview
          </button>
          <button
            onClick={() => setActiveNav && setActiveNav('contracts')}
            className={`transition-colors py-1 relative ${
              activeNav === 'contracts'
                ? 'text-cream font-semibold'
                : 'text-sage hover:text-cream'
            }`}
          >
            Contracts
            {activeNav === 'contracts' && (
              <span className="absolute bottom-0 left-0 w-full h-[2px] bg-sage rounded-full" />
            )}
          </button>
          <button
            onClick={() => setActiveNav && setActiveNav('activity')}
            className={`transition-colors py-1 relative ${
              activeNav === 'activity'
                ? 'text-cream font-semibold'
                : 'text-sage hover:text-cream'
            }`}
          >
            Agent Activity
            {activeNav === 'activity' && (
              <span className="absolute bottom-0 left-0 w-full h-[2px] bg-sage rounded-full" />
            )}
          </button>
        </nav>

        {/* Status Badge & ODIN Back Link */}
        <div className="flex items-center space-x-3 sm:space-x-4">
          <div className="hidden sm:flex items-center px-2.5 py-1 rounded-lg bg-[#252E1F] border border-sage/30 font-mono text-[11px] text-sage">
            <span className="w-2 h-2 rounded-full bg-sage mr-2 animate-pulse" />
            <span>THOR v2.4-CORP · Operational Agent 01</span>
          </div>

          <button
            onClick={() => navigate('/')}
            className="font-mono text-xs text-sage hover:text-cream transition-colors flex items-center gap-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-sage rounded px-1.5 py-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>ODIN System</span>
          </button>
        </div>
      </div>
    </header>
  );
}
