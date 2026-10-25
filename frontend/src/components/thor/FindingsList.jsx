import React, { useState, useMemo } from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  HelpCircle,
  MapPin,
  ArrowRight,
  ArrowUpRight,
  RotateCw,
  Search,
  Zap,
} from 'lucide-react';

const CATEGORY_MAP = {
  parties: ['party'],
  durations: ['term', 'effective_date'],
  renewals: ['renewal'],
  payments: ['payment'],
  obligations: ['obligation'],
  penalties: ['penalty'],
  compliance: ['compliance'],
  termination: ['termination'],
};

export default function FindingsList({
  extractions = [],
  selectedExtraction,
  onSelectExtraction,
  onQuickRecheck,
}) {
  const [statusFilter, setStatusFilter] = useState('all'); // all | verified | ambiguous | contradictory | missing
  const [activeCategory, setActiveCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Calculate status counts
  const counts = useMemo(() => {
    let verified = 0;
    let ambiguous = 0;
    let contradictory = 0;
    let missing = 0;

    extractions.forEach((e) => {
      if (e.status === 'ambiguous') ambiguous++;
      else if (e.status === 'contradictory') contradictory++;
      else if (e.status === 'missing') missing++;
      else if (e.citations && e.citations.some((c) => c.verified)) verified++;
      else verified++;
    });

    return {
      all: extractions.length,
      verified,
      ambiguous,
      contradictory,
      missing,
    };
  }, [extractions]);

  // Filter extractions
  const filtered = useMemo(() => {
    return extractions.filter((item) => {
      // Status filter
      if (statusFilter === 'verified') {
        if (item.status === 'ambiguous' || item.status === 'contradictory' || item.status === 'missing') {
          return false;
        }
      } else if (statusFilter === 'ambiguous' && item.status !== 'ambiguous') {
        return false;
      } else if (statusFilter === 'contradictory' && item.status !== 'contradictory') {
        return false;
      } else if (statusFilter === 'missing' && item.status !== 'missing') {
        return false;
      }

      // Category filter
      if (activeCategory !== 'all') {
        const allowedTypes = CATEGORY_MAP[activeCategory] || [];
        if (!allowedTypes.includes(item.field_type)) {
          return false;
        }
      }

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const strVal = JSON.stringify(item.value || {}).toLowerCase();
        const typeStr = (item.field_type || '').toLowerCase();
        const keyStr = (item.field_key || '').toLowerCase();
        return strVal.includes(q) || typeStr.includes(q) || keyStr.includes(q);
      }

      return true;
    });
  }, [extractions, statusFilter, activeCategory, searchQuery]);

  const formatKeyLabel = (type, key) => {
    const cleanKey = (key || type || 'FINDING')
      .replace(/^[a-z]+_/, '')
      .replace(/_/g, ' ')
      .toUpperCase();
    return cleanKey;
  };

  const getDisplayValue = (item) => {
    if (item.status === 'missing') {
      return 'Not Found / Unstated in Contract';
    }
    const val = item.value;
    if (!val || typeof val !== 'object') {
      return String(val || '—');
    }

    // Party
    if (val.name) return `${val.name} (${val.role || 'Party'})`;
    // Term
    if (val.duration_raw) return val.duration_raw;
    // Renewal
    if (val.notice_period_raw) {
      return `${val.notice_period_raw} Prior to Expiry${val.auto_renew ? ' (Auto-Renews)' : ''}`;
    }
    if (val.auto_renew !== undefined) {
      return val.auto_renew ? 'Automatic Renewal Enabled' : 'No Automatic Renewal';
    }
    // Payment
    if (val.amount !== undefined && val.currency) {
      return `${val.currency} ${val.amount} (${val.frequency || 'period'})`;
    }
    if (val.due_rule) return val.due_rule;
    if (val.adjustment_raw) return val.adjustment_raw;
    // Obligation
    if (val.action) {
      return `${val.obligor ? val.obligor + ': ' : ''}${val.action}`;
    }
    // Penalty
    if (val.formula || val.amount_raw) return val.formula || val.amount_raw;
    // Compliance
    if (val.requirement) return val.requirement;
    // Termination
    if (val.notice_period_raw) {
      return `${val.notice_period_raw} Notice Required${val.cure_period_raw ? ` (${val.cure_period_raw} Cure Window)` : ''}`;
    }
    if (val.trigger) return val.trigger;
    // Governing law
    if (val.law) return `${val.law}${val.courts ? ` (${val.courts})` : ''}`;
    // Liability cap
    if (val.cap_raw) return val.cap_raw;

    // Fallback: first primitive value or raw text
    for (const v of Object.values(val)) {
      if (typeof v === 'string' || typeof v === 'number') return String(v);
    }
    return item.raw_text || JSON.stringify(val);
  };

  const getConfidenceBadge = (confidence) => {
    const num = confidence !== undefined ? confidence : 0.95;
    const pct = Math.round(num * 100);
    if (pct >= 85) {
      return { label: `${pct}% High`, style: 'text-primary bg-primary/10 border-primary/20' };
    }
    if (pct >= 60) {
      return { label: `${pct}% Moderate`, style: 'text-accent-gold bg-accent-gold/10 border-accent-gold/20' };
    }
    return { label: `${pct}% Low`, style: 'text-red-700 bg-red-50 border-red-200' };
  };

  return (
    <section className="space-y-4">
      {/* Categorical Filters & Search Bar */}
      <div className="bg-ivory border border-border-subtle rounded-xl p-3 flex flex-wrap items-center justify-between gap-2 shadow-xs font-mono text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setStatusFilter('all')}
            className={`px-3 py-1.5 rounded-lg transition-colors font-semibold ${
              statusFilter === 'all'
                ? 'bg-primary-dark text-cream'
                : 'text-dark-olive hover:bg-cream'
            }`}
          >
            All Findings ({counts.all})
          </button>
          <button
            onClick={() => setStatusFilter('verified')}
            className={`px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 ${
              statusFilter === 'verified'
                ? 'bg-primary-dark text-cream font-semibold'
                : 'text-dark-olive hover:bg-cream'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-primary" />
            Verified ({counts.verified})
          </button>
          <button
            onClick={() => setStatusFilter('ambiguous')}
            className={`px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 ${
              statusFilter === 'ambiguous'
                ? 'bg-primary-dark text-cream font-semibold'
                : 'text-dark-olive hover:bg-cream'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-accent-gold" />
            Needs Review / Ambiguous ({counts.ambiguous})
          </button>
          <button
            onClick={() => setStatusFilter('contradictory')}
            className={`px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 ${
              statusFilter === 'contradictory'
                ? 'bg-primary-dark text-cream font-semibold'
                : 'text-dark-olive hover:bg-cream'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-red-500" />
            Conflicting Evidence ({counts.contradictory})
          </button>
          <button
            onClick={() => setStatusFilter('missing')}
            className={`px-3 py-1.5 rounded-lg transition-colors ${
              statusFilter === 'missing'
                ? 'bg-primary-dark text-cream font-semibold'
                : 'text-secondary-olive hover:bg-cream'
            }`}
          >
            Not Found ({counts.missing})
          </button>
        </div>

        {/* Search */}
        <div className="flex items-center gap-2 px-2 py-1 bg-cream rounded-lg border border-border-subtle">
          <Search className="w-3.5 h-3.5 text-secondary-olive" />
          <input
            type="text"
            placeholder="Filter terms (⌘K)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-transparent border-none text-xs text-dark-olive placeholder-secondary-olive focus:ring-0 p-0 w-32 sm:w-44 focus:outline-none"
          />
        </div>
      </div>

      {/* Category Section Navigation Tabs */}
      <div className="flex border-b border-border-subtle space-x-6 px-2 overflow-x-auto font-mono text-xs no-scrollbar">
        {[
          { id: 'all', label: 'All Fields' },
          { id: 'parties', label: '1. Parties' },
          { id: 'durations', label: '2. Durations' },
          { id: 'renewals', label: '3. Renewal Dates' },
          { id: 'payments', label: '4. Payment Schedules' },
          { id: 'obligations', label: '5. Obligations' },
          { id: 'penalties', label: '6. Penalty Clauses' },
          { id: 'compliance', label: '7. Compliance' },
          { id: 'termination', label: '8. Termination' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveCategory(tab.id)}
            className={`pb-3 whitespace-nowrap transition-colors relative ${
              activeCategory === tab.id
                ? 'text-primary-dark font-bold'
                : 'text-secondary-olive hover:text-dark-olive font-medium'
            }`}
          >
            {tab.label}
            {activeCategory === tab.id && (
              <span className="absolute bottom-0 left-0 w-full h-[2px] bg-primary-dark rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* Structured Fact Cards List */}
      <div className="space-y-3">
        {filtered.length === 0 ? (
          <div className="p-12 text-center bg-ivory rounded-xl border border-border-subtle font-mono text-xs text-secondary-olive">
            No contractual terms found matching your filter criteria.
          </div>
        ) : (
          filtered.map((item) => {
            const isSelected = selectedExtraction?.id === item.id;
            const conf = getConfidenceBadge(item.confidence);
            const firstCite = item.citations?.[0];
            const isAmbiguous = item.status === 'ambiguous';
            const isContradictory = item.status === 'contradictory';
            const isMissing = item.status === 'missing';

            return (
              <div
                key={item.id}
                onClick={() => onSelectExtraction(item)}
                className={`bg-ivory rounded-xl p-5 shadow-xs transition-all cursor-pointer relative overflow-hidden border ${
                  isSelected
                    ? 'border-2 border-primary shadow-olive-glow'
                    : isContradictory
                    ? 'border-red-300 hover:border-red-400'
                    : isAmbiguous
                    ? 'border-accent-gold/60 hover:border-accent-gold'
                    : 'border-border-subtle hover:border-sage'
                }`}
              >
                {/* Accent line on selected item */}
                {isSelected && (
                  <div className="absolute top-0 left-0 w-1.5 h-full bg-primary" />
                )}

                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 pl-1">
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-[11px] text-secondary-olive uppercase tracking-wider font-semibold">
                        {formatKeyLabel(item.field_type, item.field_key)}
                      </span>

                      {/* Status Badges */}
                      {isContradictory ? (
                        <span className="px-2 py-0.5 rounded bg-red-100 text-red-700 font-mono text-[10px] font-semibold flex items-center gap-1 border border-red-200">
                          <AlertCircle className="w-3 h-3 text-red-600" />
                          Conflicting Evidence
                        </span>
                      ) : isAmbiguous ? (
                        <span className="px-2 py-0.5 rounded bg-accent-gold/20 text-dark-olive font-mono text-[10px] font-semibold flex items-center gap-1 border border-accent-gold/30">
                          <AlertTriangle className="w-3 h-3 text-accent-gold" />
                          Needs Review
                        </span>
                      ) : isMissing ? (
                        <span className="px-2 py-0.5 rounded bg-gray-100 text-secondary-olive font-mono text-[10px] font-medium border border-border-subtle">
                          Not Found
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded bg-sage/20 text-primary-dark font-mono text-[10px] font-semibold flex items-center gap-1 border border-sage/40">
                          <CheckCircle2 className="w-3 h-3 text-primary" />
                          Verified
                        </span>
                      )}

                      {/* Confidence */}
                      <span
                        className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${conf.style}`}
                      >
                        {conf.label}
                      </span>
                    </div>

                    {/* Headline Extracted Value */}
                    <div className="font-sans text-base sm:text-lg font-bold text-dark-olive">
                      {getDisplayValue(item)}
                    </div>

                    {/* Ambiguity or Contradiction Details Callout */}
                    {isAmbiguous && item.readings && item.readings.length > 0 && (
                      <div className="text-xs font-mono text-accent-gold flex items-center gap-1.5 bg-accent-gold/10 p-2 rounded border border-accent-gold/20">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        <span>
                          Ambiguity: {item.readings.map((r) => r.reading).join(' vs. ')}
                        </span>
                      </div>
                    )}

                    {isContradictory && (
                      <div className="text-xs font-mono text-red-700 flex items-center gap-1.5 bg-red-50 p-2 rounded border border-red-200">
                        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                        <span>
                          Collision detected between competing clauses in this agreement.
                        </span>
                      </div>
                    )}

                    {/* Clause Citation Locator */}
                    {firstCite && (
                      <div className="flex items-center gap-2 font-mono text-xs text-secondary-olive pt-0.5">
                        <MapPin className="w-3.5 h-3.5 text-primary shrink-0" />
                        <span className="truncate">
                          {firstCite.clause_ref || firstCite.clause_id} · Clause {firstCite.clause_id}
                          {firstCite.char_start !== undefined && (
                            <span className="text-secondary-olive/70 ml-1">
                              (Offsets: {firstCite.char_start}..{firstCite.char_end})
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Action Buttons */}
                  <div
                    className="flex items-center gap-2 self-end sm:self-center shrink-0 pt-2 sm:pt-0"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {isSelected ? (
                      <button
                        onClick={() => onSelectExtraction(item)}
                        className="px-3 py-1.5 rounded-lg bg-primary-dark text-cream font-mono text-xs font-semibold flex items-center gap-1 shadow-sm"
                      >
                        <span>Inspecting</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    ) : isContradictory ? (
                      <button
                        onClick={() => onSelectExtraction(item)}
                        className="px-3 py-1.5 rounded-lg bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 font-mono text-xs font-medium flex items-center gap-1 transition-colors"
                      >
                        <span>Resolve Conflict</span>
                        <Zap className="w-3.5 h-3.5 text-red-600" />
                      </button>
                    ) : isAmbiguous ? (
                      <button
                        onClick={() => onSelectExtraction(item)}
                        className="px-3 py-1.5 rounded-lg border border-accent-gold text-dark-olive hover:bg-accent-gold/10 font-mono text-xs font-medium flex items-center gap-1 transition-colors"
                      >
                        <span>Inspect Discrepancy</span>
                        <ArrowUpRight className="w-3.5 h-3.5" />
                      </button>
                    ) : (
                      <button
                        onClick={() => onSelectExtraction(item)}
                        className="px-3 py-1.5 rounded-lg border border-border-subtle text-dark-olive hover:bg-cream font-mono text-xs font-medium flex items-center gap-1 transition-colors"
                      >
                        <span>View Evidence</span>
                        <ArrowUpRight className="w-3.5 h-3.5" />
                      </button>
                    )}

                    {/* Quick Recheck button */}
                    <button
                      onClick={() => onQuickRecheck(item)}
                      className="p-2 rounded-lg border border-border-subtle hover:bg-cream text-secondary-olive hover:text-dark-olive transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                      title="Recheck / Re-extract Clause"
                      aria-label="Recheck Clause"
                    >
                      <RotateCw className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
