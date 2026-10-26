import React from 'react';
import OdinTopNav from './common/OdinTopNav';
import LokiReviewWorkspace from './loki/LokiReviewWorkspace';
import Footer from './Footer';

export default function LokiPage() {
  return (
    <div className="min-h-screen bg-cream text-dark-olive selection:bg-sage/40 selection:text-dark-olive flex flex-col bg-grid-warm">
      {/* Universal Top Navigation */}
      <OdinTopNav activePage="loki" />

      {/* Main workspace */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 sm:py-6 space-y-5">
        <LokiReviewWorkspace />
      </main>

      {/* Footer */}
      <Footer />
    </div>
  );
}
