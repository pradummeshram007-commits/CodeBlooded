import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDashboard } from '../../services/api';
import OdinTopNav from '../common/OdinTopNav';
import PriorityAlertStrip from './PriorityAlertStrip';
import SummaryIndicators from './SummaryIndicators';
import ContractRelationshipGraph from './ContractRelationshipGraph';
import FinancialExposureGauge from './FinancialExposureGauge';
import RiskHeatmap from './RiskHeatmap';
import AgentActivityPanel from './AgentActivityPanel';
import PriorityQueue from './PriorityQueue';
import ActionsAndNotices from './ActionsAndNotices';
import NoticeReviewModal from './NoticeReviewModal';

const DEFAULT_NOTICES = [
  {
    id: "draft-non-renewal",
    title: "Notice of Non-Renewal",
    contract: "Cloud Service Agreement (StratoNode / Quillhub)",
    doc_id: "A1",
    clause_ref: "§ A3:3 Written Notice",
    status: "Ready",
    status_detail: "Awaiting Lead Counsel Sign-off",
    recipient: "kartikranekar2006@gmail.com",
    subject: "Formal Notice of Non-Renewal — StratoNode Inc. Cloud Service Agreement",
    body: "To: StratoNode Inc. Legal Department\nAttn: General Counsel\n\nRE: Formal Written Notice of Non-Renewal pursuant to Section A3:3\n\nPlease accept this correspondence as formal written notification pursuant to Section A3:3 (Renewal) that Customer hereby exercises its right NOT to renew the Agreement upon the expiration of the current Subscription Period.\n\nIn accordance with Section A3:3, this notice is delivered more than sixty (60) days prior to the expiration date, thereby superseding any automatic renewal provision. We request written confirmation of receipt and coordination regarding scheduled post-termination data transition protocols under Section 16.",
    citations: [
      {
        clause_ref: "A3:3 Renewal",
        quote: "The Agreement will automatically renew for successive Renewal Periods of 12 months each, unless either party delivers written notice of non-renewal to the other party's Notice Address at least 60 days before the end of the then-current Subscription Period.",
      },
    ],
  },
  {
    id: "draft-breach-dispute",
    title: "Service Level Credit Demand & Dispute Notice",
    contract: "StratoNode CloudCore SLA / Cover Page",
    doc_id: "A2",
    clause_ref: "§ A2:3.1 Recourse",
    status: "In Review",
    status_detail: "LOKI Adversarial Verification Active",
    recipient: "kartikranekar2006@gmail.com",
    subject: "SLA Service Credit Demand & Billing Dispute Notice",
    body: "To: StratoNode Inc. / Provider Legal Department\nAttn: VP of Legal & Corporate Compliance\n\nRE: Formal Notice of Service Level Deficit and Credit Demand under Section A2:3.1\n\nThis letter serves as formal notice of service availability default and associated credit claim pursuant to the Service Level Agreement. Independent monitoring confirmed monthly uptime availability deficits triggering mandatory service credits.\n\nCustomer hereby demands immediate issuance of an adjusted revised invoice reflecting verified service credits prior to final milestone disbursement.",
    citations: [
      {
        clause_ref: "A2:3.1 Service Credits",
        quote: "If the Monthly Uptime Percentage falls below 99.5%, Customer is entitled to a service credit of 10% of monthly recurring fees upon written claim.",
      },
    ],
  },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeDraft, setActiveDraft] = useState(null);

  const loadData = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      const res = await fetchDashboard();
      if (res) {
        setData(res);
      }
    } catch (err) {
      console.error('Error loading dashboard data:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Flag for when data is being loaded the very first time (no data yet)
  const isInitialLoad = loading && !data;

  useEffect(() => {
    loadData();

    // Auto-refresh interval (every 30 seconds) to pull newly uploaded documents automatically
    // Note: each /api/dashboard call takes ~3-5s (NORNS engine), so 30s avoids cascading timeouts
    const interval = setInterval(() => {
      loadData(true);
    }, 30000);

    // Event listener for document upload or re-extraction in THOR
    const handleDocUpdated = () => {
      loadData(true);
    };

    // Re-fetch when switching back to dashboard tab
    const handleFocus = () => {
      loadData(true);
    };

    // Cross-tab storage change listener
    const handleStorage = (e) => {
      if (e.key === 'odin_last_upload' || e.key === 'odin_doc_updated') {
        loadData(true);
      }
    };

    window.addEventListener('odin-doc-updated', handleDocUpdated);
    window.addEventListener('focus', handleFocus);
    window.addEventListener('storage', handleStorage);

    return () => {
      clearInterval(interval);
      window.removeEventListener('odin-doc-updated', handleDocUpdated);
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('storage', handleStorage);
    };
  }, []);

  const handleInspectConflict = () => {
    const el = document.getElementById('agents');
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  };

  const handleSelectDraftById = (draftId) => {
    const list = data?.notices?.length ? data.notices : DEFAULT_NOTICES;
    const found = list.find((n) => n.id === draftId) || list[0];
    setActiveDraft(found);
  };

  const currentNotices = data?.notices?.length ? data.notices : DEFAULT_NOTICES;

  if (isInitialLoad) {
    return (
      <div className="bg-odin-cream text-odin-dark antialiased font-sans min-h-screen flex flex-col bg-grid-warm">
        <OdinTopNav activePage="dashboard" searchQuery={searchQuery} onSearchChange={setSearchQuery} onDeployClick={() => navigate('/thor')} />
        <div className="flex-1 flex flex-col items-center justify-center gap-6 p-12">
          <div className="w-12 h-12 border-4 border-odin-forest border-t-transparent rounded-full animate-spin" />
          <div className="text-center space-y-1">
            <p className="font-bold text-odin-dark text-sm">Loading Contract Intelligence</p>
            <p className="font-mono text-xs text-odin-muted">Querying Supabase database · Computing NORNS worst-case exposure · Syncing 10 agreements</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-odin-cream text-odin-dark antialiased font-sans min-h-screen flex flex-col bg-grid-warm selection:bg-odin-forest selection:text-odin-ivory">
      {/* Universal Top Application Navbar present on all pages */}
      <OdinTopNav
        activePage="dashboard"
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onDeployClick={() => navigate('/thor')}
      />

      {/* Main Full-Width Workspace Canvas */}
      <main className="flex-1 w-full max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col gap-6">
        {/* 1. DASHBOARD HEADER & WORKSPACE SCOPE */}
        <section className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-odin-border">
          <div>
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className="font-mono text-[11px] font-semibold text-odin-forest uppercase tracking-widest">
                ODIN COMMAND // ENTERPRISE CONTRACT INTELLIGENCE
              </span>
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-odin-ivory text-odin-dark font-medium border border-odin-border">
                SUPABASE LIVE
              </span>
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-odin-palesage text-odin-forest font-medium border border-odin-sage/30">
                PARALLEL VERIFIED
              </span>
            </div>
            <h1 className="text-2xl lg:text-3xl font-extrabold text-odin-dark tracking-tight">
              Contract Command Center
            </h1>
            <p className="text-xs lg:text-sm text-odin-muted mt-0.5">
              Live database telemetry · Surface multi-agent conflicts · Act before critical deadlines
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 self-stretch lg:self-auto">
            {/* Scope Selector */}
            <div className="flex items-center gap-2 px-3 py-1.5 bg-odin-ivory border border-odin-border rounded shadow-sm text-xs text-odin-dark font-medium">
              <span className="material-symbols-outlined text-odin-forest text-sm">hub</span>
              <span>Global Portfolio ({data?.documents?.length || 0} Registered Agreements)</span>
            </div>

            {/* Freshness Pill */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-odin-ivory border border-odin-border rounded font-mono text-xs text-odin-muted">
              <span className="w-2 h-2 rounded-full bg-emerald-600 animate-pulse"></span>
              <span>Synced {refreshing ? 'updating...' : 'live'} · Supabase Deterministic Sync</span>
            </div>

            {/* Trigger Portfolio Audit Button */}
            <button
              onClick={() => loadData(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded bg-odin-forest hover:bg-odin-dark text-white text-xs font-mono font-semibold transition-all shadow-sm active:scale-95 disabled:opacity-60 cursor-pointer"
              type="button"
            >
              <span className={`material-symbols-outlined text-xs text-odin-palesage ${refreshing ? 'animate-spin' : ''}`}>
                sync
              </span>
              <span>{refreshing ? 'Auditing Portfolio...' : 'Trigger Portfolio Audit'}</span>
            </button>
          </div>
        </section>

        {/* 2. PRIORITY ALERT STRIP (High-Contrast Red Accent) */}
        <PriorityAlertStrip
          alerts={data?.priority_alerts}
          onInspectConflict={handleInspectConflict}
        />

        {/* 3. SUMMARY INDICATOR CARDS (4-Column Bento Grid) */}
        <SummaryIndicators summary={data?.summary} />

        {/* 4. VISUALIZATION GRID: Graph Canvas (8 cols) & Analytical Gauges (4 cols) */}
        <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <ContractRelationshipGraph graphData={data?.graph} />

          <div className="lg:col-span-4 flex flex-col gap-6">
            <FinancialExposureGauge exposureData={data?.exposure_gauge} />
            <RiskHeatmap heatmapData={data?.heatmap} />
          </div>
        </section>

        {/* 5. LOWER OPERATIONAL SECTION: Deliberation, Priority Queue, Actions & Notices */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          <AgentActivityPanel activityData={data?.agent_activity} />
          <PriorityQueue
            queueItems={data?.priority_queue}
            onSelectDraft={handleSelectDraftById}
          />
          <ActionsAndNotices
            notices={currentNotices}
            onOpenDraft={(draft) => setActiveDraft(draft || DEFAULT_NOTICES[0])}
          />
        </section>
      </main>

      {/* Notice Review and Email Dispatch Modal */}
      {activeDraft && (
        <NoticeReviewModal
          draft={activeDraft}
          onClose={() => setActiveDraft(null)}
          onDispatched={(res) => {
            console.log('Notice dispatched:', res);
          }}
        />
      )}
    </div>
  );
}
