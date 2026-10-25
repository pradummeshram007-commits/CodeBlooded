import React from 'react';
import { Network } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="bg-primary-dark border-t border-[#3D4B33] text-cream">
      <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 flex flex-col md:flex-row justify-between items-center gap-8">
        {/* Left Anchor & Tagline */}
        <div className="space-y-2 text-center md:text-left">
          <div className="flex items-center justify-center md:justify-start gap-2">
            <div className="w-6 h-6 rounded bg-[#252E1F] border border-[#3D4B33] flex items-center justify-center">
              <Network className="w-3.5 h-3.5 text-sage" />
            </div>
            <span className="font-sans text-base font-bold tracking-wider text-cream">ODIN</span>
          </div>
          <p className="font-sans text-xs text-[#DCDCCB] max-w-sm leading-relaxed">
            Contract intelligence for decisions that stand up to scrutiny. Autonomous legal determinism engine.
          </p>
          <p className="font-mono text-[11px] text-[#A4B18A]">
            © 2025 ODIN Systems Inc. Autonomous Legal Intelligence. High-stakes determinism engine.
          </p>
        </div>

        {/* Footer Navigation Links */}
        <div className="flex flex-col items-center md:items-end space-y-3">
          <div className="flex flex-wrap justify-center gap-x-6 gap-y-2">
            {['Architecture Spec', 'Privacy Protocol', 'Security & Audit', 'Model Ethics Disclaimer', 'Terms of Service'].map((link) => (
              <a
                key={link}
                href="#"
                onClick={(e) => e.preventDefault()}
                className="font-mono text-xs text-[#DCDCCB] hover:text-cream transition-colors"
              >
                {link}
              </a>
            ))}
          </div>
          <div className="font-mono text-xs text-[#A4B18A] flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-sage" />
            <span>Multi-agent contract risk intelligence • Air-gapped deployment available</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
