import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Activity, ArrowLeft, Cpu } from 'lucide-react';

export default function NornsNavbar({ activeNav, setActiveNav }) {
  const navigate = useNavigate();

  const navLinks = [
    { id: 'overview', label: 'Overview' },
    { id: 'contracts', label: 'Contracts' },
    { id: 'thor', label: 'THOR — Extraction', href: '/thor' },
    { id: 'norns', label: 'NORNS — Timeline', active: true },
    { id: 'activity', label: 'Agent Activity' },
  ];

  return (
    <header
      className="sticky top-0 z-40 border-b shadow-sm"
      style={{
        background: 'rgba(252,250,243,0.92)',
        backdropFilter: 'blur(12px)',
        borderColor: 'rgba(220,220,203,0.7)',
      }}
    >
      <div className="w-full max-w-7xl mx-auto flex items-center justify-between px-4 sm:px-6 py-2.5">
        {/* Left: Logo & Breadcrumb */}
        <div className="flex items-center gap-4">
          <Link to="/" className="flex items-center gap-1.5 group">
            <div
              className="w-7 h-7 flex items-center justify-center rounded font-bold text-sm text-white tracking-tighter"
              style={{ background: '#303B28' }}
            >
              Ω
            </div>
            <span className="font-bold tracking-wider text-sm" style={{ color: '#303B28' }}>
              ODIN
            </span>
          </Link>
          <span className="text-sm" style={{ color: '#DCDCCB' }}>/</span>
          <div className="flex items-center gap-2">
            <span
              className="text-xs font-mono uppercase tracking-wider"
              style={{ color: '#727665' }}
            >
              Agent 02
            </span>
            <span className="text-sm font-semibold" style={{ color: '#303B28' }}>
              NORNS · Timeline Intelligence
            </span>
          </div>
        </div>

        {/* Center Nav */}
        <nav className="hidden md:flex items-center gap-6 text-sm font-medium">
          {navLinks.map((link) =>
            link.href ? (
              <Link
                key={link.id}
                to={link.href}
                className="transition-colors duration-150 flex items-center gap-1"
                style={{ color: '#727665' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = '#303B28')}
                onMouseLeave={(e) => (e.currentTarget.style.color = '#727665')}
              >
                <span>{link.label}</span>
                <span className="text-[10px] font-mono opacity-60">↗</span>
              </Link>
            ) : link.active ? (
              <span
                key={link.id}
                className="font-semibold border-b-2 pb-0.5"
                style={{ color: '#303B28', borderColor: '#303B28' }}
              >
                {link.label}
              </span>
            ) : (
              <button
                key={link.id}
                onClick={() => setActiveNav && setActiveNav(link.id)}
                className="transition-colors duration-150"
                style={{ color: '#727665' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = '#303B28')}
                onMouseLeave={(e) => (e.currentTarget.style.color = '#727665')}
              >
                {link.label}
              </button>
            )
          )}
        </nav>

        {/* Right: Agent status + back */}
        <div className="flex items-center gap-3">
          <div
            className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded border text-xs font-mono"
            style={{
              background: '#F5F1E6',
              border: '1px solid #DCDCCB',
              color: '#303B28',
            }}
          >
            <span
              className="w-2 h-2 rounded-full animate-pulse"
              style={{ background: '#527A54' }}
            />
            <span className="font-semibold">NORNS v2.4-CORP · Operational</span>
          </div>
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-1 text-xs font-mono transition-colors"
            style={{ color: '#727665' }}
            onMouseEnter={(e) => (e.currentTarget.style.color = '#303B28')}
            onMouseLeave={(e) => (e.currentTarget.style.color = '#727665')}
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>ODIN System</span>
          </button>
        </div>
      </div>
    </header>
  );
}
