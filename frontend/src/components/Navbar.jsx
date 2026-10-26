import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Network, Menu, X, ArrowUpRight, ShieldCheck } from 'lucide-react';

export default function Navbar() {
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('hero');

  // Scrollspy logic
  useEffect(() => {
    if (location.pathname !== '/') return;

    const handleScroll = () => {
      const sections = ['hero', 'agents', 'how-it-works', 'evidence-trust'];
      const scrollPosition = window.scrollY + 120;

      for (let i = sections.length - 1; i >= 0; i--) {
        const el = document.getElementById(sections[i]);
        if (el && el.offsetTop <= scrollPosition) {
          setActiveSection(sections[i]);
          break;
        }
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [location.pathname]);

  const scrollTo = (id) => {
    setMobileMenuOpen(false);
    if (location.pathname !== '/') {
      navigate('/#' + id);
      return;
    }
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <header className="fixed top-0 left-0 w-full z-50 bg-[#F5F1E6]/90 backdrop-blur-md border-b border-border-subtle transition-all duration-200">
      <div className="w-full max-w-7xl mx-auto flex items-center justify-between px-4 sm:px-6 lg:px-8 py-3">
        {/* Brand Logo */}
        <button
          onClick={() => scrollTo('hero')}
          className="flex items-center gap-2.5 group text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-lg"
          aria-label="ODIN Home"
        >
          <div className="relative w-8 h-8 flex items-center justify-center rounded-lg bg-ivory border border-border-subtle group-hover:border-primary transition-colors shadow-sm">
            <Network className="w-4 h-4 text-primary group-hover:scale-105 transition-transform" />
            <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-accent-gold animate-ping" />
          </div>
          <div className="flex items-center gap-2">
            <span className="font-sans text-lg font-bold tracking-wider text-dark-olive">ODIN</span>
            <span className="hidden sm:inline-block font-mono text-[10px] px-1.5 py-0.5 rounded bg-ivory text-primary-dark font-medium border border-border-subtle">
              v2.4-CORP
            </span>
          </div>
        </button>

        {/* Desktop Nav Links */}
        <nav aria-label="Main Navigation" className="hidden lg:flex items-center gap-6">
          {[
            { id: 'hero', label: 'Overview' },
            { id: 'agents', label: 'Agent Network' },
            { id: 'how-it-works', label: 'How It Works' },
            { id: 'evidence-trust', label: 'Evidence & Trust' },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id)}
              className={`font-mono text-xs tracking-wide transition-colors py-1 relative focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded ${
                activeSection === item.id
                  ? 'text-primary font-bold'
                  : 'text-secondary-olive hover:text-dark-olive font-medium'
              }`}
            >
              {item.label}
              {activeSection === item.id && (
                <span className="absolute bottom-0 left-0 w-full h-[2px] bg-primary rounded-full animate-fade-slide-up" />
              )}
            </button>
          ))}

          <div className="h-4 w-px bg-border-subtle" />

          {/* Quick Page Jump Links */}
          <button
            onClick={() => navigate('/dashboard')}
            className="font-mono text-xs font-semibold text-primary hover:text-primary-dark transition-colors"
          >
            Dashboard
          </button>
          <button
            onClick={() => navigate('/odin')}
            className="font-mono text-xs font-medium text-secondary-olive hover:text-dark-olive transition-colors hidden xl:flex items-center gap-1"
          >
            <span>ODIN</span>
          </button>
          <button
            onClick={() => navigate('/thor')}
            className="font-mono text-xs font-medium text-secondary-olive hover:text-dark-olive transition-colors hidden xl:flex items-center gap-1"
          >
            <span>THOR</span>
          </button>
          <button
            onClick={() => navigate('/norns')}
            className="font-mono text-xs font-medium text-secondary-olive hover:text-dark-olive transition-colors hidden xl:flex items-center gap-1"
          >
            <span>NORNS</span>
          </button>
          <button
            onClick={() => navigate('/loki')}
            className="font-mono text-xs font-medium text-secondary-olive hover:text-dark-olive transition-colors hidden xl:flex items-center gap-1"
          >
            <span>LOKI</span>
          </button>
          <button
            onClick={() => navigate('/heimdall')}
            className="font-mono text-xs font-medium text-secondary-olive hover:text-dark-olive transition-colors hidden xl:flex items-center gap-1"
          >
            <span>HEIMDALL</span>
          </button>
        </nav>

        {/* Action Button */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/dashboard')}
            className="inline-flex items-center gap-1.5 font-mono text-xs font-semibold px-4 py-2 rounded-lg bg-primary-dark text-cream hover:bg-dark-olive transition-all duration-200 active:scale-95 shadow-sm hover:shadow-[0_2px_12px_rgba(48,59,40,0.3)] focus:outline-none focus-visible:ring-2 focus-visible:ring-primary cursor-pointer"
            id="nav-launch-site"
          >
            <span>Launch Dashboard</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </button>

          {/* Mobile Menu Toggle */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle navigation menu"
            className="md:hidden flex items-center justify-center w-9 h-9 rounded-lg bg-ivory border border-border-subtle text-dark-olive focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Menu Dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-border-subtle bg-ivory px-6 py-4 space-y-3 animate-fade-slide-up shadow-lg">
          {[
            { id: 'hero', label: 'Overview' },
            { id: 'agents', label: 'Agent Network' },
            { id: 'how-it-works', label: 'How It Works' },
            { id: 'evidence-trust', label: 'Evidence & Trust' },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id)}
              className="block w-full text-left font-mono text-xs py-2 text-secondary-olive hover:text-dark-olive font-medium border-b border-border-subtle/50"
            >
              {item.label}
            </button>
          ))}
          <div className="pt-2 flex flex-col gap-2">
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/dashboard');
              }}
              className="w-full text-center flex items-center justify-center gap-2 font-mono text-xs py-2.5 rounded-lg bg-primary-dark text-cream font-semibold"
            >
              <span>Dashboard</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/thor');
              }}
              className="w-full text-center flex items-center justify-center gap-2 font-mono text-xs py-2 rounded-lg bg-ivory border border-border-subtle text-dark-olive font-semibold hover:bg-cream"
            >
              <span>THOR — Extraction</span>
            </button>
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/odin');
              }}
              className="w-full text-center flex items-center justify-center gap-2 font-mono text-xs py-2 rounded-lg bg-ivory border border-border-subtle text-dark-olive font-semibold hover:bg-cream"
            >
              <span>ODIN — Pipeline</span>
            </button>
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/norns');
              }}
              className="w-full text-center flex items-center justify-center gap-2 font-mono text-xs py-2 rounded-lg bg-ivory border border-border-subtle text-dark-olive font-semibold hover:bg-cream"
            >
              <span>NORNS — Timeline</span>
            </button>
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/loki');
              }}
              className="w-full text-center flex items-center justify-center gap-2 font-mono text-xs py-2 rounded-lg bg-ivory border border-border-subtle text-dark-olive font-semibold hover:bg-cream"
            >
              <span>LOKI — Review</span>
            </button>
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                navigate('/heimdall');
              }}
              className="w-full text-center flex items-center justify-center gap-2 font-mono text-xs py-2 rounded-lg bg-ivory border border-border-subtle text-dark-olive font-semibold hover:bg-cream"
            >
              <span>HEIMDALL — Events</span>
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
