import React, { useState } from 'react';
import { sendCertifiedNotice } from '../../services/api';

export default function NoticeReviewModal({ draft, onClose, onDispatched }) {
  const [recipient, setRecipient] = useState(draft?.recipient || 'kartikranekar2006@gmail.com');
  const [subject, setSubject] = useState(draft?.subject || '');
  const [body, setBody] = useState(draft?.body || '');
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  if (!draft) return null;

  const handleDispatch = async () => {
    setSending(true);
    setError(null);
    try {
      const response = await sendCertifiedNotice({
        notice_id: draft.id || 'notice-draft',
        recipient: recipient,
        subject: subject,
        body: body,
        doc_id: draft.doc_id,
        clause_ref: draft.clause_ref,
        citations: (draft.citations || []).map((c) => (typeof c === 'string' ? c : `${c.clause_ref}: "${c.quote}"`)),
      });
      setResult(response);
      if (onDispatched) onDispatched(response);
    } catch (err) {
      setError(err.message || 'Dispatch failed.');
    } finally {
      setSending(false);
    }
  };

  return (
    <div 
      className="fixed inset-0 z-[9999] bg-[#10131B]/80 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-2xl bg-odin-ivory border border-odin-border rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh] animate-fade-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="bg-odin-forest text-odin-cream px-6 py-4 flex items-center justify-between border-b border-[#21281B]">
          <div className="flex items-center gap-2.5">
            <span className="material-symbols-outlined text-odin-palesage text-lg">mark_email_read</span>
            <div>
              <h3 className="text-sm font-bold text-white font-sans">{draft.title}</h3>
              <span className="text-[11px] font-mono text-odin-palesage">
                {draft.contract} · {draft.clause_ref}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded bg-[#252E1F] text-odin-cream hover:bg-[#38452F] flex items-center justify-center font-mono text-xs cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-4">
          {/* Dispatch Feedback Banner */}
          {result && (
            <div className="p-4 rounded-lg bg-[#FAF6EC] border border-odin-sage text-xs font-mono space-y-2">
              <div className="flex items-center gap-2 text-odin-forest font-bold text-sm">
                <span className="material-symbols-outlined text-base text-emerald-600">verified</span>
                <span>Certified E-Notice Successfully Dispatched</span>
              </div>
              <p className="text-odin-dark font-sans leading-relaxed">
                {result.message}
              </p>
              <div className="pt-2 border-t border-odin-border-subtle grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px]">
                <div>
                  <span className="text-odin-muted block">Recipient:</span>
                  <strong className="text-odin-dark">{result.recipient}</strong>
                </div>
                <div>
                  <span className="text-odin-muted block">Delivery Mode:</span>
                  <span className="text-odin-forest font-bold uppercase">{result.delivery_mode}</span>
                </div>
                <div className="sm:col-span-2">
                  <span className="text-odin-muted block">SHA-256 Audit Signature:</span>
                  <code className="text-odin-forest break-all bg-white p-1 rounded border border-odin-border block mt-0.5">
                    {result.audit_hash}
                  </code>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="p-3 rounded bg-[#FBEBEB] border border-odin-red text-xs text-odin-red font-mono">
              ⚠️ {error}
            </div>
          )}

          {/* Test Recipient Input */}
          <div className="space-y-1">
            <label className="block text-xs font-mono font-semibold text-odin-dark">
              Recipient Email (Defaulted to Lead Counsel test enclave)
            </label>
            <div className="flex items-center gap-2">
              <input
                type="email"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-white text-odin-dark border border-odin-border rounded font-mono focus:outline-none focus:border-odin-forest"
                placeholder="kartikranekar2006@gmail.com"
              />
              <span className="text-[10px] font-mono px-2 py-1 rounded bg-[#FBEBEB] text-odin-red border border-odin-red/20 font-bold whitespace-nowrap">
                TEST MODE ACTIVE
              </span>
            </div>
          </div>

          {/* Subject Line */}
          <div className="space-y-1">
            <label className="block text-xs font-mono font-semibold text-odin-dark">
              Subject Line
            </label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full px-3 py-2 text-xs bg-white text-odin-dark border border-odin-border rounded font-sans font-medium focus:outline-none focus:border-odin-forest"
            />
          </div>

          {/* Verbatim Citations Box */}
          {draft.citations && draft.citations.length > 0 && (
            <div className="space-y-1.5">
              <span className="block text-xs font-mono font-semibold text-odin-forest">
                Authoritative Contract Clause Citations (§)
              </span>
              <div className="space-y-2 bg-white p-3 rounded border border-odin-border">
                {draft.citations.map((c, idx) => (
                  <div key={idx} className="border-l-2 border-odin-sage pl-2.5 text-xs">
                    <span className="font-mono text-[10px] font-bold text-odin-forest block">
                      {typeof c === 'string' ? `Citation ${idx + 1}` : c.clause_ref}
                    </span>
                    <blockquote className="italic text-odin-muted text-[11px] font-serif mt-0.5">
                      "{typeof c === 'string' ? c : c.quote}"
                    </blockquote>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Notice Body */}
          <div className="space-y-1">
            <label className="block text-xs font-mono font-semibold text-odin-dark">
              Certified Legal Notice Body
            </label>
            <textarea
              rows={7}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="w-full p-3 text-xs bg-white text-odin-dark border border-odin-border rounded font-sans leading-relaxed focus:outline-none focus:border-odin-forest resize-y"
            />
          </div>
        </div>

        {/* Footer Actions */}
        <div className="bg-[#FAF6EC] px-6 py-3.5 border-t border-odin-border-subtle flex items-center justify-between gap-3">
          <div className="font-mono text-[10px] text-odin-muted flex items-center gap-1.5">
            <span className="material-symbols-outlined text-xs text-odin-forest">lock</span>
            <span>RSA-4096 SIGNED ENCLAVE</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded bg-white border border-odin-border text-xs font-mono text-odin-dark hover:bg-odin-cream transition-colors cursor-pointer"
            >
              Close
            </button>
            <button
              onClick={handleDispatch}
              disabled={sending}
              className="px-4 py-2 rounded bg-odin-forest hover:bg-odin-dark text-white font-mono text-xs font-bold flex items-center gap-1.5 transition-all shadow-sm active:scale-95 disabled:opacity-50 cursor-pointer"
            >
              <span className="material-symbols-outlined text-xs text-odin-palesage">
                {sending ? 'sync' : 'mark_email_read'}
              </span>
              <span>{sending ? 'Encrypting & Dispatching...' : 'Dispatch via Certified E-Notice'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
