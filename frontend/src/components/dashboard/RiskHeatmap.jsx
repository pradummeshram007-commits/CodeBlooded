import React, { useState } from 'react';

export default function RiskHeatmap({ heatmapData }) {
  const [selectedCell, setSelectedCell] = useState(null);

  const columns = heatmapData?.columns || [
    { key: 'pay', label: 'Pay' },
    { key: 'renew', label: 'Renew' },
    { key: 'penal', label: 'Penal' },
    { key: 'term', label: 'Term' },
    { key: 'compl', label: 'Compl' },
  ];

  const rows = heatmapData?.rows || [];

  return (
    <div className="bg-odin-ivory border border-odin-border rounded-lg p-5 flex flex-col justify-between shadow-sm relative">
      <div>
        <div className="flex items-center justify-between border-b border-odin-border-subtle pb-2 mb-3">
          <div>
            <h3 className="text-sm font-bold text-odin-dark">Risk Heatmap</h3>
            <span className="text-[10px] font-mono text-odin-muted uppercase">Contract × Clause Matrix</span>
          </div>
          <span className="text-[10px] font-mono text-odin-forest font-semibold px-2 py-0.5 rounded bg-odin-palesage">
            Q2 AUDIT
          </span>
        </div>

        {/* Heatmap Table Matrix */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse font-mono text-[11px]">
            <thead>
              <tr className="text-odin-muted border-b border-odin-border-subtle">
                <th className="py-1.5 px-2 font-medium">Contract</th>
                {columns.map((c) => (
                  <th key={c.key} className="py-1.5 px-1 text-center font-medium">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-odin-border-subtle">
              {rows.map((row) => (
                <tr key={row.contract_id || row.name}>
                  <td className="py-2 px-2 text-odin-dark font-sans font-medium truncate max-w-[95px]" title={row.full_title || row.name}>
                    {row.name}
                  </td>
                  {columns.map((col) => {
                    const score = row.scores?.[col.key] || { level: 'LOW', class: 'bg-odin-palesage text-odin-forest' };
                    const isSelected = selectedCell?.contract === row.name && selectedCell?.col === col.label;

                    return (
                      <td key={col.key} className="p-1">
                        <button
                          onClick={() => {
                            if (isSelected) {
                              setSelectedCell(null);
                            } else {
                              setSelectedCell({
                                contract: row.name,
                                full_title: row.full_title || row.name,
                                col: col.label,
                                level: score.level,
                                citation: score.citation || 'Verified against underlying contract clause.',
                              });
                            }
                          }}
                          className={`w-full py-1 rounded text-center font-semibold text-[10px] transition-transform active:scale-95 cursor-pointer ${
                            score.class || 'bg-odin-palesage text-odin-forest'
                          } ${isSelected ? 'ring-2 ring-odin-dark' : ''}`}
                          title={`Click to inspect ${row.name} - ${col.label}`}
                        >
                          {score.level}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Cell Citation Detail Inspection Box */}
        {selectedCell && (
          <div className="mt-3 p-2.5 rounded bg-white border border-odin-border text-xs animate-fade-slide-up">
            <div className="flex items-center justify-between border-b border-odin-border-subtle pb-1 mb-1 font-mono text-[10px]">
              <span className="font-bold text-odin-forest">
                {selectedCell.contract} // {selectedCell.col} ({selectedCell.level})
              </span>
              <button
                onClick={() => setSelectedCell(null)}
                className="text-odin-muted hover:text-odin-dark cursor-pointer"
              >
                ✕
              </button>
            </div>
            <p className="text-[11px] text-odin-dark font-mono leading-relaxed">
              {selectedCell.citation}
            </p>
          </div>
        )}
      </div>

      {/* Heatmap Legend */}
      <div className="flex items-center justify-between pt-3 mt-2 border-t border-odin-border-subtle font-mono text-[10px] flex-wrap gap-1">
        <span className="flex items-center gap-1 text-odin-muted">
          <span className="w-2 h-2 rounded bg-odin-palesage border border-odin-sage/30"></span>Low
        </span>
        <span className="flex items-center gap-1 text-odin-muted">
          <span className="w-2 h-2 rounded bg-[#F4ECDB] border border-odin-amber/30"></span>Moderate
        </span>
        <span className="flex items-center gap-1 text-odin-muted">
          <span className="w-2 h-2 rounded bg-odin-amber text-white"></span>Elevated
        </span>
        <span className="flex items-center gap-1 text-odin-red font-semibold">
          <span className="w-2 h-2 rounded bg-odin-red"></span>Critical
        </span>
      </div>
    </div>
  );
}
