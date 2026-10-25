import React, { useState, useEffect } from 'react';
import ThorNavbar from './thor/ThorNavbar';
import ThorHeroIntro from './thor/ThorHeroIntro';
import ContractUploadPanel from './thor/ContractUploadPanel';
import FindingsList from './thor/FindingsList';
import EvidenceInspector from './thor/EvidenceInspector';
import Footer from './Footer';
import { fetchDocuments, fetchDocumentReport, fetchSummary } from '../services/api';
import { Loader2, Hash, FileText } from 'lucide-react';

export default function ThorPage() {
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState('A1');
  const [docData, setDocData] = useState(null);
  const [selectedExtraction, setSelectedExtraction] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeNav, setActiveNav] = useState('contracts');

  // Load available documents list
  useEffect(() => {
    fetchDocuments()
      .then((docs) => {
        setDocuments(docs);
        if (docs.length > 0) {
          // If A1 exists, default to A1 for clear demo
          const defaultDoc = docs.find((d) => d.doc_id === 'A1') || docs[0];
          setSelectedDocId(defaultDoc.doc_id);
        }
      })
      .catch((err) => console.error('Failed to load documents list:', err));
  }, []);

  // Load report for selected document
  useEffect(() => {
    if (!selectedDocId) return;
    setLoading(true);
    fetchDocumentReport(selectedDocId)
      .then((data) => {
        setDocData(data);
        if (data.extractions && data.extractions.length > 0) {
          setSelectedExtraction(data.extractions[0]);
        } else {
          setSelectedExtraction(null);
        }
        setLoading(false);
      })
      .catch((err) => {
        console.error(`Failed to load document report for ${selectedDocId}:`, err);
        setLoading(false);
      });
  }, [selectedDocId]);

  const handleUploadComplete = (uploadResult) => {
    // Add uploaded document and switch to it
    if (uploadResult?.doc_id) {
      const newDoc = {
        doc_id: uploadResult.doc_id,
        title: uploadResult.filename,
        status: uploadResult.extraction_status,
        clause_count: uploadResult.clauses,
      };
      setDocuments((prev) => [newDoc, ...prev]);
      setSelectedDocId(uploadResult.doc_id);
    }
  };

  const handleReextractionSuccess = (res) => {
    // Refresh document report to show the updated extractions
    fetchDocumentReport(selectedDocId)
      .then((data) => {
        setDocData(data);
        if (res.new_ids && res.new_ids.length > 0) {
          const updated = data.extractions.find((e) => e.id === res.new_ids[0]);
          if (updated) setSelectedExtraction(updated);
        }
      })
      .catch(console.error);
  };

  const doc = docData?.document;
  const extractions = docData?.extractions || [];

  return (
    <div className="min-h-screen bg-cream text-dark-olive selection:bg-sage/40 selection:text-dark-olive flex flex-col">
      {/* Top Application Navbar */}
      <ThorNavbar activeNav={activeNav} setActiveNav={setActiveNav} />

      {/* Main Workspace Container */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8 space-y-6">
        {/* Workspace Hero / Capability Header */}
        <ThorHeroIntro />

        {/* Intake & Contract Upload Pipeline */}
        <ContractUploadPanel
          onUploadComplete={handleUploadComplete}
          activeDocName={doc?.title || selectedDocId}
        />

        {/* Document Switcher Strip */}
        <div className="bg-ivory border border-border-subtle rounded-xl p-3 shadow-xs">
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-border-subtle/50 font-mono text-xs">
            <span className="text-secondary-olive font-semibold uppercase tracking-wider text-[11px]">
              Available Contract Documents in War Room:
            </span>
            <span className="text-primary font-bold">
              {documents.length} Registered Agreements
            </span>
          </div>

          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
            {documents.map((d) => (
              <button
                key={d.doc_id}
                onClick={() => setSelectedDocId(d.doc_id)}
                className={`shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg font-mono text-xs transition-all border ${
                  selectedDocId === d.doc_id
                    ? 'bg-primary-dark text-cream border-primary-dark shadow-sm'
                    : 'bg-cream/70 hover:bg-cream text-dark-olive border-border-subtle'
                }`}
              >
                <FileText className="w-3.5 h-3.5 shrink-0" />
                <span className="font-bold">{d.doc_id}</span>
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded font-medium ${
                    selectedDocId === d.doc_id
                      ? 'bg-sage/40 text-cream'
                      : 'bg-primary/15 text-primary-dark'
                  }`}
                >
                  {d.coverage ? `${d.coverage.toFixed(0)}%` : d.status || 'Ready'}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Document Metadata Bar */}
        {doc && (
          <div className="bg-ivory border border-border-subtle rounded-xl p-4 sm:p-5 shadow-xs flex flex-wrap items-center justify-between gap-4 font-mono text-xs">
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="px-2 py-0.5 rounded bg-cream border border-border-subtle text-secondary-olive uppercase text-[10px] font-semibold">
                  {doc.kind || 'Contract'}
                </span>
                {doc.external_id && (
                  <span className="text-primary font-bold flex items-center gap-1">
                    <Hash className="w-3 h-3" />
                    {doc.external_id}
                  </span>
                )}
              </div>
              <h2 className="font-sans text-lg font-bold text-dark-olive">{doc.title}</h2>
              <p className="text-secondary-olive text-[11px]">
                Source File: {doc.path} · SHA-256: <code className="text-dark-olive">{doc.sha256?.substring(0, 16)}...</code>
              </p>
            </div>

            <div className="flex items-center gap-4 text-center">
              <div>
                <div className="text-lg font-bold text-primary-dark">{extractions.length}</div>
                <div className="text-[10px] text-secondary-olive uppercase">Extracted Terms</div>
              </div>
              <div className="h-7 w-px bg-border-subtle" />
              <div>
                <div className="text-lg font-bold text-primary">{docData?.clauses?.length || 0}</div>
                <div className="text-[10px] text-secondary-olive uppercase">Clauses Mapped</div>
              </div>
              <div className="h-7 w-px bg-border-subtle" />
              <div>
                <div className="text-lg font-bold text-accent-gold">{docData?.flags?.length || 0}</div>
                <div className="text-[10px] text-secondary-olive uppercase">Risk Flags</div>
              </div>
            </div>
          </div>
        )}

        {/* Two-Column Master-Detail Workspace */}
        {loading ? (
          <div className="p-16 text-center font-mono text-xs text-secondary-olive space-y-3 bg-ivory rounded-xl border border-border-subtle">
            <Loader2 className="w-6 h-6 animate-spin text-primary mx-auto" />
            <p>Loading contractual intelligence and verified evidence for {selectedDocId}...</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Column (8 cols): Findings List */}
            <div className="lg:col-span-8">
              <FindingsList
                extractions={extractions}
                selectedExtraction={selectedExtraction}
                onSelectExtraction={(item) => setSelectedExtraction(item)}
                onQuickRecheck={(item) => setSelectedExtraction(item)}
              />
            </div>

            {/* Right Column (4 cols): Evidence Inspector & Re-extraction */}
            <div className="lg:col-span-4">
              <EvidenceInspector
                docId={selectedDocId}
                selectedItem={selectedExtraction}
                onReextractionSuccess={handleReextractionSuccess}
              />
            </div>
          </div>
        )}
      </main>

      {/* Global Footer */}
      <Footer />
    </div>
  );
}
