import React, { useState } from 'react';

export default function AgentActivityPanel({ activityData }) {
  const [expandedStep, setExpandedStep] = useState(null);

  const data = activityData || {
    pipeline_status: 'TRIPARTITE CONSENSUS',
    sync_note: 'Consensus protocol synchronized.',
    approval_note: 'Human approval req.',
    steps: [
      {
        step: '01',
        agent: 'LOKI',
        role: 'Challenge',
        severity_label: 'Adversarial Scan',
        severity_class: 'bg-[#FBEBEB] text-odin-red border-l-odin-red',
        text_class: 'text-odin-red',
        summary: 'Scanning contract graph for cross-reference collisions and unverified citations.',
        details: 'Loki runs adversarial verification across all relational links and extraction confidence scores in Supabase.',
      },
      {
        step: '02',
        agent: 'HEIMDALL',
        role: 'Verification',
        severity_label: 'Relational Check',
        severity_class: 'bg-[#F4ECDB] text-odin-darkamber border-l-odin-amber',
        text_class: 'text-odin-darkamber',
        summary: 'Cross-referencing payment obligations and clause citations against relational store.',
        details: 'Heimdall confirms extraction veracity by matching verbatim quotes against underlying documents.',
      },
      {
        step: '03',
        agent: 'TYR',
        role: 'Ruling',
        severity_label: 'Enforcement Ready',
        severity_class: 'bg-odin-palesage text-odin-forest border-l-odin-forest',
        text_class: 'text-odin-forest',
        summary: 'Formulating legal remedies and certified notices based on Order of Precedence.',
        details: 'Tyr prepares binding notices and risk calibrations according to established contractual precedence.',
      },
    ],
  };

  return (
    <div id="agents" className="bg-odin-ivory border border-odin-border rounded-lg p-5 flex flex-col justify-between shadow-sm">
      <div>
        <div className="flex items-center justify-between border-b border-odin-border-subtle pb-2.5 mb-4">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-odin-forest text-lg">psychology</span>
            <h3 className="text-sm font-bold text-odin-dark">Agent Deliberation</h3>
          </div>
          <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-odin-panel text-odin-palesage font-semibold">
            {data.pipeline_status || 'TRIPARTITE CONSENSUS'}
          </span>
        </div>

        {/* Stepper Pipeline */}
        <div className="flex flex-col gap-3 font-mono">
          {(data.steps || []).map((stepItem, idx) => {
            const isExpanded = expandedStep === idx;
            return (
              <div
                key={idx}
                onClick={() => setExpandedStep(isExpanded ? null : idx)}
                className={`p-3 rounded bg-white border border-odin-border border-l-4 shadow-xs transition-all cursor-pointer hover:border-odin-sage ${
                  stepItem.severity_class || 'border-l-odin-forest'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className={`flex items-center gap-1.5 text-xs font-bold ${stepItem.text_class || 'text-odin-dark'}`}>
                    <span>{stepItem.step}</span>
                    <span>{stepItem.agent} · {stepItem.role}</span>
                  </div>
                  <span
                    className={`text-[10px] px-1.5 py-0.2 rounded font-semibold ${
                      idx === 0
                        ? 'bg-[#FBEBEB] text-odin-red'
                        : idx === 1
                        ? 'bg-[#F4ECDB] text-odin-darkamber'
                        : 'bg-odin-palesage text-odin-forest'
                    }`}
                  >
                    {stepItem.severity_label}
                  </span>
                </div>
                <p className="text-xs text-odin-muted font-sans mt-0.5">
                  {stepItem.summary}
                </p>

                {/* Expanded Deliberation Notes */}
                {isExpanded && stepItem.details && (
                  <div className="mt-2 pt-2 border-t border-odin-border-subtle font-mono text-[11px] text-odin-dark bg-[#FCFAF3] p-2 rounded">
                    <strong className="block text-odin-forest mb-0.5">Evidence Chain:</strong>
                    {stepItem.details}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-4 pt-2 border-t border-odin-border-subtle flex items-center justify-between font-mono text-[11px]">
        <span className="text-odin-muted flex items-center gap-1.5 font-sans">
          <span className="w-2 h-2 rounded-full bg-emerald-600 animate-pulse"></span>
          {data.sync_note || 'Consensus protocol synchronized.'}
        </span>
        <span className="text-odin-forest font-semibold">{data.approval_note || 'Human approval req.'}</span>
      </div>
    </div>
  );
}
