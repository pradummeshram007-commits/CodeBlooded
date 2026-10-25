import React, { useEffect } from 'react';
import Navbar from './Navbar';
import HeroSection from './HeroSection';
import ScrollingText from './ScrollingText';
import AgentCards from './AgentCards';
import HowItWorks from './HowItWorks';
import EvidenceTrustSection from './EvidenceTrustSection';
import FinalCTA from './FinalCTA';
import Footer from './Footer';

export default function LandingPage() {
  // If navigated with a hash, smooth scroll to it
  useEffect(() => {
    if (window.location.hash) {
      const id = window.location.hash.replace('#', '');
      const el = document.getElementById(id);
      if (el) {
        setTimeout(() => {
          el.scrollIntoView({ behavior: 'smooth' });
        }, 100);
      }
    }
  }, []);

  return (
    <div className="relative min-h-screen bg-cream text-dark-olive selection:bg-sage/40 selection:text-dark-olive overflow-x-hidden">
      {/* Ambient Background Atmosphere */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -top-40 left-1/4 w-[600px] h-[600px] bg-sage/20 rounded-full blur-[140px]" />
        <div className="absolute top-1/3 -right-20 w-[500px] h-[500px] bg-accent-gold/10 rounded-full blur-[160px]" />
        <div className="absolute bottom-10 left-10 w-[600px] h-[600px] bg-primary/10 rounded-full blur-[180px]" />
        <div className="absolute inset-0 bg-grid-matrix opacity-70" />
      </div>

      {/* Main Navigation */}
      <Navbar />

      {/* Page Content Landmark */}
      <main className="relative z-10 pt-16">
        <HeroSection />
        <ScrollingText />
        <AgentCards />
        <HowItWorks />
        <EvidenceTrustSection />
        <FinalCTA />
      </main>

      {/* Footer Landmark */}
      <Footer />
    </div>
  );
}
