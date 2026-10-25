import React from 'react';
import OdinTopNav from './common/OdinTopNav';
import NornsObligationsWorkspace from './norns/NornsObligationsWorkspace';
import Footer from './Footer';

export default function NornsPage() {
  return (
    <div
      className="min-h-screen flex flex-col antialiased"
      style={{
        background: '#F5F1E6',
        color: '#252B20',
        fontFamily: 'Plus Jakarta Sans, sans-serif',
        // Subtle dot grid texture from design spec
        backgroundImage: 'radial-gradient(rgba(48,59,40,0.09) 1px, transparent 1px)',
        backgroundSize: '24px 24px',
      }}
    >
      {/* Universal Top Navigation */}
      <OdinTopNav activePage="norns" />

      {/* Main workspace */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 space-y-5">
        <NornsObligationsWorkspace />
      </main>

      {/* Footer */}
      <Footer />
    </div>
  );
}
