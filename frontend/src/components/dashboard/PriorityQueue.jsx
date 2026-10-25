import React from 'react';
import { useNavigate } from 'react-router-dom';

export default function PriorityQueue({ queueItems, onSelectDraft }) {
  const navigate = useNavigate();

  const items = queueItems || [];

  return (
    <div className="bg-odin-ivory border border-odin-border rounded-lg p-5 flex flex-col justify-between shadow-sm">
      <div>
        <div className="flex items-center justify-between border-b border-odin-border-subtle pb-2.5 mb-4">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-odin-forest text-lg">format_list_numbered</span>
            <h3 className="text-sm font-bold text-odin-dark">Priority Queue</h3>
          </div>
          <span className="font-mono text-[10px] text-odin-muted">{items.length} IN FLIGHT</span>
        </div>

        {/* Queue Stream */}
        <div className="flex flex-col gap-2.5">
          {items.length === 0 ? (
            <div className="p-4 rounded bg-white border border-odin-border text-center text-xs text-odin-muted font-mono">
              No pending obligations in current cycle. All milestones synchronized.
            </div>
          ) : (
            items.map((item, idx) => (
              <div
                key={item.id || idx}
                onClick={() => {
                  if (item.link) {
                    navigate(item.link);
                  } else if (item.draft_id && onSelectDraft) {
                    onSelectDraft(item.draft_id);
                  }
                }}
                className={`p-3 rounded bg-white border transition-all shadow-xs flex flex-col gap-0.5 cursor-pointer ${
                  item.border_class || 'border-odin-border hover:border-odin-forest'
                }`}
              >
                <div className="flex items-center justify-between font-mono text-[11px]">
                  <span className={`px-1.5 py-0.5 rounded font-bold text-[10px] ${item.type_class || 'bg-odin-panel text-odin-palesage'}`}>
                    {item.type_label}
                  </span>
                  <span className={item.time_class || 'text-odin-muted'}>{item.time_badge}</span>
                </div>
                <div className="text-xs font-bold text-odin-dark mt-1 font-sans">{item.title}</div>
                <span className="text-[11px] text-odin-muted font-sans">{item.subtitle}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="mt-4 pt-2 border-t border-odin-border-subtle flex justify-end">
        <button
          onClick={() => navigate('/norns')}
          className="font-mono text-xs text-odin-forest hover:text-odin-dark flex items-center gap-1 font-semibold hover:underline cursor-pointer"
        >
          <span>View complete timeline in NORNS</span>
          <span className="material-symbols-outlined text-xs">open_in_new</span>
        </button>
      </div>
    </div>
  );
}
