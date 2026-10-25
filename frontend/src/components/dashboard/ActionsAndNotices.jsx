import React from 'react';

export default function ActionsAndNotices({ notices, onOpenDraft }) {
  const drafts = notices || [];

  return (
    <div id="actions" className="bg-odin-ivory border border-odin-border rounded-lg p-5 flex flex-col justify-between shadow-sm">
      <div>
        <div className="flex items-center justify-between border-b border-odin-border-subtle pb-2.5 mb-4">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-odin-forest text-lg">edit_document</span>
            <h3 className="text-sm font-bold text-odin-dark">Actions &amp; Notices</h3>
          </div>
          <span className="font-mono text-[10px] text-odin-forest font-semibold px-2 py-0.5 rounded bg-odin-palesage">
            {drafts.length} DRAFTS READY
          </span>
        </div>

        {/* Drafts List */}
        <div className="flex flex-col gap-3 font-sans">
          {drafts.map((draft, idx) => (
            <div key={draft.id || idx} className="p-3 rounded bg-white border border-odin-border flex flex-col gap-2 shadow-xs">
              <div className="flex items-start justify-between">
                <div>
                  <span className="text-xs font-bold text-odin-dark block">{draft.title}</span>
                  <span className="text-[11px] text-odin-muted font-mono">
                    {draft.clause_ref} · {draft.contract}
                  </span>
                </div>
                <span
                  className={`font-mono text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                    draft.status === 'Ready'
                      ? 'bg-odin-palesage text-odin-forest'
                      : 'bg-[#F4ECDB] text-odin-darkamber'
                  }`}
                >
                  {draft.status}
                </span>
              </div>
              <div className="flex items-center justify-between pt-2 border-t border-odin-border-subtle font-mono text-[11px]">
                <span className="text-odin-muted text-[10px]">
                  Status: {draft.status_detail || 'Counsel Review'}
                </span>
                <button
                  onClick={() => onOpenDraft && onOpenDraft(draft)}
                  className="text-odin-forest hover:underline font-bold flex items-center gap-0.5 cursor-pointer"
                >
                  <span>Review Draft</span>
                  <span className="material-symbols-outlined text-xs">north_east</span>
                </button>
              </div>
            </div>
          ))}

          {/* Dispatch Action Box */}
          <div className="p-3.5 rounded bg-[#FAF6EC] border border-odin-sage/30 flex flex-col gap-2 shadow-xs">
            <div className="flex items-center justify-between font-mono text-xs">
              <span className="flex items-center gap-1.5 font-bold text-odin-forest">
                <span className="material-symbols-outlined text-odin-forest text-sm">mark_email_read</span>
                Email Dispatch Action
              </span>
              <span className="font-mono text-[10px] text-odin-red font-bold">DUAL KEY REQ.</span>
            </div>
            <p className="text-xs text-odin-muted">
              Certified E-Notice dispatch requires cryptographic sign-off from Lead Counsel and General Risk Officer.
            </p>
            <button
              onClick={() => onOpenDraft && onOpenDraft(drafts[0] || null)}
              className="w-full mt-1 py-2 px-3 rounded bg-odin-forest hover:bg-odin-dark text-white font-mono text-xs font-bold flex items-center justify-center gap-1.5 transition-all shadow-sm active:scale-95 cursor-pointer"
              type="button"
            >
              <span className="material-symbols-outlined text-xs text-odin-palesage">key</span>
              <span>Dispatch via Certified E-Notice</span>
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 pt-2 border-t border-odin-border-subtle flex items-center justify-between font-mono text-[10px] text-odin-muted">
        <span>SECURE ENCLAVE ACTIVE</span>
        <span>RSA-4096 SIGNED</span>
      </div>
    </div>
  );
}
