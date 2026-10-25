import React from 'react';
import { useNavigate } from 'react-router-dom';

export default function PriorityAlertStrip({ alerts, onInspectConflict }) {
  const navigate = useNavigate();
  const alertList = alerts || [];

  if (alertList.length === 0) {
    return (
      <section className="bg-odin-ivory border border-odin-border rounded-lg p-4 shadow-sm relative overflow-hidden">
        <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-odin-forest"></div>
        <div className="flex items-center justify-between gap-4 pl-2">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-odin-palesage border border-odin-sage/40 flex items-center justify-center flex-shrink-0 text-odin-forest shadow-sm">
              <span className="material-symbols-outlined text-lg">verified</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-odin-dark">Portfolio Obligations Synchronized</span>
                <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-odin-palesage text-odin-forest uppercase font-bold tracking-wider">
                  Verified
                </span>
              </div>
              <p className="text-xs text-odin-muted mt-0.5">
                Autonomous multi-agent consensus active. No critical contractual defaults or breach triggers pending.
              </p>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="bg-odin-ivory border border-odin-red/40 rounded-lg p-4 shadow-sm relative overflow-hidden">
      <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-odin-red"></div>
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4 pl-2">
        <div className="flex items-start lg:items-center gap-3">
          <div className="w-9 h-9 rounded bg-[#FBEBEB] border border-odin-red/30 flex items-center justify-center flex-shrink-0 text-odin-red shadow-sm animate-pulse">
            <span className="material-symbols-outlined text-lg">emergency</span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm lg:text-base font-bold text-odin-red">
                {alertList.length} Critical {alertList.length === 1 ? 'Item Requires' : 'Items Require'} Action
              </span>
              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-odin-red text-white uppercase font-bold tracking-wider">
                Immediate
              </span>
            </div>
            <p className="text-xs text-odin-muted mt-0.5">
              Autonomous agents detected contract liability violations and multi-clause collisions requiring counsel intervention.
            </p>
          </div>
        </div>

        {/* Actionable alert tiles */}
        <div className="flex flex-col sm:flex-row gap-3">
          {alertList.map((alert, idx) => {
            const isNorns = alert.action_link?.includes('/norns');
            const isScroll = alert.action_link?.startsWith('#');

            const handleClick = () => {
              if (isNorns) {
                navigate(alert.action_link);
              } else if (isScroll) {
                const targetId = alert.action_link.replace('#', '');
                const el = document.getElementById(targetId);
                if (el) el.scrollIntoView({ behavior: 'smooth' });
                else if (onInspectConflict) onInspectConflict();
              } else if (alert.action_link) {
                navigate(alert.action_link);
              }
            };

            return (
              <button
                key={alert.id || idx}
                onClick={handleClick}
                className="flex items-center justify-between gap-4 px-3.5 py-2.5 rounded bg-white border border-odin-red/25 hover:border-odin-red transition-all shadow-sm group text-left cursor-pointer"
              >
                <div className="flex flex-col">
                  <span className="text-xs font-semibold text-odin-dark group-hover:text-odin-red transition-colors">
                    {alert.title}
                  </span>
                  <span className="font-mono text-[11px] text-odin-red font-semibold">
                    {alert.amount} — {alert.detail}
                  </span>
                </div>
                <span className="font-mono text-xs text-odin-forest font-semibold flex items-center gap-1 group-hover:underline ml-2">
                  {alert.action_text || 'Review'}{' '}
                  <span className="material-symbols-outlined text-xs">arrow_forward</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
