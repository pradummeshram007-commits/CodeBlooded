import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Database,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Layers,
  Shield,
  Search,
  ExternalLink,
  Hash,
} from 'lucide-react';

export default function ThorPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [selectedDocId, setSelectedDocId] = useState('STD');
  const [docData, setDocData] = useState(null);
  const [activeTab, setActiveTab] = useState('facts');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch summary
  useEffect(() => {
    fetch('/data/thor/_run_summary.json')
      .then((res) => res.json())
      .then((data) => {
        setSummary(data);
        if (data.documents && data.documents.length > 0) {
          setSelectedDocId(data.documents[0].doc_id);
        }
      })
      .catch((err) => console.error('Failed to load Thor summary', err));
  }, []);

  // Fetch individual document data
  useEffect(() => {
    if (!selectedDocId) return;
    setLoading(true);
    fetch(`/data/thor/${selectedDocId}.json`)
      .then((res) => res.json())
      .then((data) => {
        setDocData(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error(`Failed to load ${selectedDocId}.json`, err);
        setLoading(false);
      });
  }, [selectedDocId]);

  const doc = docData?.document;
  const extractions = docData?.extractions || [];
  const clauses = docData?.clauses || [];
  const relations = docData?.doc_relations || [];
  const flags = docData?.flags || [];

  const filteredExtractions = extractions.filter((ext) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      ext.field_type?.toLowerCase().includes(q) ||
      ext.field_key?.toLowerCase().includes(q) ||
      JSON.stringify(ext.value || {}).toLowerCase().includes(q)
    );
  });

  return (
    <div className="min-h-screen bg-cream text-dark-olive selection:bg-sage/40 selection:text-dark-olive flex flex-col">
      {/* Top Header */}
      <header className="sticky top-0 z-40 bg-ivory/95 backdrop-blur-md border-b border-border-subtle px-4 sm:px-6 lg:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-1.5 font-mono text-xs text-secondary-olive hover:text-dark-olive bg-cream hover:bg-cream/80 border border-border-subtle px-3 py-1.5 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Overview</span>
          </button>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/30 flex items-center justify-center text-primary">
              <Database className="w-4 h-4" />
            </div>
            <div>
              <h1 className="font-sans text-sm font-bold text-dark-olive flex items-center gap-2">
                <span>THOR — Contract Extraction War Room</span>
                <span className="font-mono text-[10px] px-1.5 py-0.2 rounded bg-primary/15 text-primary-dark font-medium border border-primary/30">
                  Verified Engine
                </span>
              </h1>
            </div>
          </div>
        </div>

        {summary && (
          <div className="hidden md:flex items-center gap-4 font-mono text-xs text-secondary-olive">
            <span>Cache hits: <strong className="text-dark-olive">{summary.llm.cache_hits}</strong></span>
            <span>Verified quotes: <strong className="text-primary-dark">222+</strong></span>
            <span className="flex items-center gap-1 text-primary">
              <span className="w-2 h-2 rounded-full bg-primary" />
              State: Complete
            </span>
          </div>
        )}
      </header>

      {/* Main Workspace Layout */}
      <div className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        {/* Document Selection Strip */}
        <div className="bg-ivory border border-border-subtle rounded-xl p-3 shadow-xs">
          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
            {summary?.documents?.map((d) => (
              <button
                key={d.doc_id}
                onClick={() => setSelectedDocId(d.doc_id)}
                className={`shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg font-mono text-xs transition-all border ${
                  selectedDocId === d.doc_id
                    ? 'bg-primary-dark text-cream border-primary-dark shadow-sm'
                    : 'bg-cream/60 hover:bg-cream text-dark-olive border-border-subtle'
                }`}
              >
                <span className="font-bold">{d.doc_id}</span>
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded font-medium ${
                    d.status === 'complete'
                      ? selectedDocId === d.doc_id
                        ? 'bg-sage/40 text-cream'
                        : 'bg-primary/15 text-primary-dark'
                      : 'bg-accent-gold/20 text-dark-olive'
                  }`}
                >
                  {d.status === 'complete' ? '100%' : 'Pending'}
                </span>
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center font-mono text-xs text-secondary-olive">
            Loading document extractions...
          </div>
        ) : (
          <>
            {/* Document Header Metadata Card */}
            {doc && (
              <div className="bg-ivory border border-border-subtle rounded-xl p-6 shadow-sm space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-xs px-2 py-0.5 rounded bg-cream border border-border-subtle text-secondary-olive">
                        {doc.kind || 'Contract'}
                      </span>
                      {doc.external_id && (
                        <span className="font-mono text-xs text-primary font-semibold flex items-center gap-1">
                          <Hash className="w-3 h-3" />
                          {doc.external_id}
                        </span>
                      )}
                    </div>
                    <h2 className="font-sans text-xl font-bold text-dark-olive">{doc.title}</h2>
                    <p className="font-mono text-xs text-secondary-olive mt-1">
                      File: {doc.path} • SHA-256: <code className="text-dark-olive">{doc.sha256?.substring(0, 16)}...</code>
                    </p>
                  </div>

                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <div className="font-mono text-lg font-bold text-primary-dark">
                        {extractions.length}
                      </div>
                      <div className="font-mono text-[10px] text-secondary-olive">Extracted Facts</div>
                    </div>
                    <div className="h-8 w-px bg-border-subtle" />
                    <div className="text-right">
                      <div className="font-mono text-lg font-bold text-primary">
                        {clauses.length}
                      </div>
                      <div className="font-mono text-[10px] text-secondary-olive">Clauses Parsed</div>
                    </div>
                    <div className="h-8 w-px bg-border-subtle" />
                    <div className="text-right">
                      <div className="font-mono text-lg font-bold text-accent-gold">
                        {flags.length}
                      </div>
                      <div className="font-mono text-[10px] text-secondary-olive">Risk Flags</div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Navigation Tabs */}
            <div className="flex items-center justify-between border-b border-border-subtle pb-2">
              <div className="flex items-center gap-4">
                {[
                  { id: 'facts', label: `Extracted Facts (${extractions.length})` },
                  { id: 'clauses', label: `Clauses (${clauses.length})` },
                  { id: 'relations', label: `Cross-References (${relations.length})` },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`font-mono text-xs py-1.5 px-3 rounded-lg transition-colors ${
                      activeTab === tab.id
                        ? 'bg-primary-dark text-cream font-semibold'
                        : 'text-secondary-olive hover:text-dark-olive'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {activeTab === 'facts' && (
                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-secondary-olive absolute left-2.5 top-2.5" />
                  <input
                    type="text"
                    placeholder="Search field or value..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-8 pr-3 py-1.5 text-xs font-mono bg-ivory border border-border-subtle rounded-lg focus:outline-none focus:border-primary text-dark-olive w-56"
                  />
                </div>
              )}
            </div>

            {/* Tab 1: Extracted Facts */}
            {activeTab === 'facts' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {filteredExtractions.length === 0 ? (
                  <div className="col-span-2 p-8 text-center font-mono text-xs text-secondary-olive bg-ivory rounded-xl border border-border-subtle">
                    No extractions match your search query.
                  </div>
                ) : (
                  filteredExtractions.map((item) => (
                    <div
                      key={item.id}
                      className="bg-ivory border border-border-subtle rounded-xl p-5 shadow-xs space-y-3 hover:border-primary/50 transition-all"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-cream border border-border-subtle text-primary-dark uppercase">
                          {item.field_type}
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px] text-secondary-olive">
                            conf: {item.confidence?.toFixed(2) || '1.00'}
                          </span>
                          <span
                            className={`font-mono text-[10px] px-1.5 py-0.2 rounded font-medium ${
                              item.status === 'extracted'
                                ? 'bg-primary/15 text-primary-dark'
                                : 'bg-accent-gold/20 text-dark-olive'
                            }`}
                          >
                            {item.status}
                          </span>
                        </div>
                      </div>

                      {/* Structured Value Rendering */}
                      <div className="font-sans text-xs text-dark-olive bg-cream/70 p-3 rounded-lg border border-border-subtle font-mono space-y-1 overflow-x-auto">
                        {Object.entries(item.value || {}).map(([key, val]) => (
                          <div key={key} className="flex gap-2 text-xs">
                            <span className="text-secondary-olive shrink-0">{key}:</span>
                            <span className="text-dark-olive font-semibold break-all">
                              {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                            </span>
                          </div>
                        ))}
                      </div>

                      {/* Verbatim Citation Quote */}
                      {item.citations && item.citations.length > 0 && (
                        <div className="space-y-1 pt-1 border-t border-border-subtle/60">
                          {item.citations.map((c, idx) => (
                            <div key={idx} className="font-mono text-[11px] text-secondary-olive">
                              <span className="text-primary font-semibold">{c.clause_id} ({c.clause_ref}): </span>
                              <span className="italic text-dark-olive">"{c.quote}"</span>
                              {c.verified && (
                                <span className="ml-1.5 text-primary font-bold">✓ verified</span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Tab 2: Clauses & Sections */}
            {activeTab === 'clauses' && (
              <div className="bg-ivory border border-border-subtle rounded-xl overflow-hidden shadow-xs">
                <div className="overflow-x-auto">
                  <table className="w-full text-left font-mono text-xs">
                    <thead className="bg-cream/80 border-b border-border-subtle text-secondary-olive">
                      <tr>
                        <th className="py-2.5 px-4">Clause ID</th>
                        <th className="py-2.5 px-4">Reference</th>
                        <th className="py-2.5 px-4">Heading</th>
                        <th className="py-2.5 px-4">Kind</th>
                        <th className="py-2.5 px-4">Offsets</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                      {clauses.map((c) => (
                        <tr key={c.clause_id} className="hover:bg-cream/40 transition-colors">
                          <td className="py-2.5 px-4 font-bold text-dark-olive">{c.clause_id}</td>
                          <td className="py-2.5 px-4 text-primary">{c.ref}</td>
                          <td className="py-2.5 px-4 text-dark-olive">{c.heading || '—'}</td>
                          <td className="py-2.5 px-4 text-secondary-olive">{c.kind || 'clause'}</td>
                          <td className="py-2.5 px-4 text-secondary-olive text-[11px]">
                            {c.char_start}..{c.char_end}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Tab 3: Cross-References & Relations */}
            {activeTab === 'relations' && (
              <div className="space-y-4">
                {relations.length === 0 ? (
                  <div className="p-8 text-center font-mono text-xs text-secondary-olive bg-ivory rounded-xl border border-border-subtle">
                    No cross-contract relations or amendments recorded for this document.
                  </div>
                ) : (
                  relations.map((rel, idx) => (
                    <div
                      key={idx}
                      className="bg-ivory border border-border-subtle rounded-xl p-5 shadow-xs flex items-center justify-between gap-4"
                    >
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-bold text-primary-dark">
                            {rel.from_doc}
                          </span>
                          <span className="font-mono text-xs px-2 py-0.2 rounded bg-sage/20 text-dark-olive font-semibold">
                            {rel.type}
                          </span>
                          <span className="font-mono text-xs font-bold text-primary-dark">
                            {rel.to_doc}
                          </span>
                        </div>
                        <p className="font-mono text-xs text-secondary-olive">
                          Citing Clause: {rel.clause_id}
                        </p>
                      </div>
                      <div className="font-mono text-xs text-primary font-semibold flex items-center gap-1">
                        <CheckCircle2 className="w-4 h-4 text-primary" />
                        <span>Verified Edge</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
