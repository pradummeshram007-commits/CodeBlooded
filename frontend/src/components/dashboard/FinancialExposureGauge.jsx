import React from 'react';

export default function FinancialExposureGauge({ exposureData }) {
  const data = exposureData || {
    percentage: 0,
    needle_rotation: -90,
    tier: '0% / LOW RISK',
    total_formatted: '$0',
    itemized: [],
  };

  const rotation = data.needle_rotation ?? -90;

  return (
    <div className="bg-odin-ivory border border-odin-border rounded-lg p-5 flex flex-col justify-between shadow-sm">
      <div className="flex items-center justify-between border-b border-odin-border-subtle pb-2 mb-3">
        <div>
          <h3 className="text-sm font-bold text-odin-dark">Financial Exposure Gauge</h3>
          <span className="text-[10px] font-mono text-odin-muted uppercase">Risk Calibration</span>
        </div>
        <span className="font-mono text-xs font-bold text-odin-red px-2 py-0.5 rounded bg-[#FBEBEB] border border-odin-red/25">
          {data.tier || '68% / Guarded-High'}
        </span>
      </div>

      {/* Gauge Semicircle SVG */}
      <div className="flex flex-col items-center justify-center my-2">
        <div className="relative w-56 h-28 flex items-end justify-center">
          <svg className="w-56 h-28 overflow-visible" viewBox="0 0 200 100">
            {/* Base Gray Arc */}
            <path
              d="M 20 100 A 80 80 0 0 1 180 100"
              fill="none"
              stroke="#E5E3D5"
              strokeLinecap="round"
              strokeWidth="14"
            ></path>
            {/* Low Risk Band (Pale Sage #7D866E) */}
            <path
              d="M 20 100 A 80 80 0 0 1 70 35"
              fill="none"
              stroke="#7D866E"
              strokeDasharray="1 1000"
              strokeLinecap="round"
              strokeWidth="14"
            ></path>
            {/* Guarded Band (Gold/Amber #B79A59) */}
            <path
              d="M 68 37 A 80 80 0 0 1 132 37"
              fill="none"
              stroke="#B79A59"
              strokeWidth="14"
            ></path>
            {/* Critical Band (Deep Alert Red #C83D3D) */}
            <path
              d="M 130 35 A 80 80 0 0 1 180 100"
              fill="none"
              stroke="#C83D3D"
              strokeLinecap="round"
              strokeWidth="14"
            ></path>
            {/* Needle Pointer */}
            <g
              transform={`translate(100, 100) rotate(${rotation})`}
              className="transition-transform duration-700 ease-out"
            >
              <line stroke="#252E1F" strokeLinecap="round" strokeWidth="2.5" x1="0" x2="0" y1="0" y2="-72"></line>
              <circle cx="0" cy="0" fill="#252E1F" r="6"></circle>
              <circle cx="0" cy="0" fill="#FCFAF3" r="2.5"></circle>
            </g>
          </svg>
          <div className="absolute bottom-0 text-center">
            <span className="text-2xl font-extrabold text-odin-dark block tracking-tight font-sans">
              {data.total_formatted || '$148.7k'}
            </span>
            <span className="text-[10px] font-mono text-odin-muted uppercase">Portfolio Total</span>
          </div>
        </div>

        {/* Legend Markers */}
        <div className="w-full flex justify-between px-6 text-[10px] font-mono text-odin-muted mt-3">
          <span className="text-odin-forest font-semibold">LOW ($0)</span>
          <span className="text-odin-darkamber font-semibold">GUARDED</span>
          <span className="text-odin-red font-semibold">CRITICAL ($200k+)</span>
        </div>
      </div>

      {/* Itemized Breakdown */}
      <div className="flex flex-col gap-2 mt-3 pt-3 border-t border-odin-border-subtle text-xs">
        {(data.itemized || []).map((item, idx) => (
          <div key={idx} className="flex flex-col gap-1">
            <div className="flex justify-between font-mono">
              <span className="text-odin-muted">{item.name}</span>
              <span className={`${item.text_class || 'text-odin-dark'} font-bold`}>{item.formatted}</span>
            </div>
            <div className="w-full bg-[#EFECE0] h-1.5 rounded-full overflow-hidden">
              <div
                className={`${item.bar_class || 'bg-odin-forest'} h-full rounded-full transition-all duration-500`}
                style={{ width: `${item.percentage}%` }}
              ></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
