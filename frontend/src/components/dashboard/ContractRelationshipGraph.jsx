import React, { useState } from 'react';

export default function ContractRelationshipGraph({ graphData }) {
  const [zoom, setZoom] = useState(1);
  const [filterContracts, setFilterContracts] = useState(true);
  const [filterClauses, setFilterClauses] = useState(true);
  const [filterParties, setFilterParties] = useState(true);
  
  const nodes = graphData?.nodes || [];
  const edges = graphData?.edges || [];
  const beacon = graphData?.beacon || { x: 385, y: 185, active: true };
  const telemetry = graphData?.telemetry || {};

  // Find first contract node or collision edge for default selection
  const defaultContractNode = nodes.find((n) => n.type === 'contract') || nodes[0] || {
    id: 'STD',
    label: 'STD',
    obligations_count: 0,
    risk_level: 'low',
  };
  const defaultCollisionEdge = edges.find((e) => e.is_collision) || edges[0];

  // Interaction state
  // CRITICAL RULE: Node click only provides visual emphasis (pop forward, outline/shadow), NO modal/popup, NO navigation away.
  const [selectedNodeId, setSelectedNodeId] = useState(defaultContractNode.id);
  // Edge click highlights edge and shows a concise 1-sentence popover
  const [activeEdgeId, setActiveEdgeId] = useState(defaultCollisionEdge?.id || null);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) || defaultContractNode;
  const activeEdge = edges.find((e) => e.id === activeEdgeId);

  const handleZoomIn = () => setZoom((z) => Math.min(z + 0.15, 1.8));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 0.15, 0.6));
  const handleResetZoom = () => {
    setZoom(1);
    setSelectedNodeId(defaultContractNode.id);
    setActiveEdgeId(defaultCollisionEdge?.id || null);
  };

  const handleNodeClick = (nodeId, e) => {
    e.stopPropagation();
    // Visual emphasis only
    setSelectedNodeId(nodeId);
  };

  const handleEdgeClick = (edgeId, e) => {
    e.stopPropagation();
    setActiveEdgeId((prev) => (prev === edgeId ? null : edgeId));
  };

  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const contractNodes = nodes.filter((n) => n.type === 'contract');
  const partyNodes = nodes.filter((n) => n.type === 'party');
  const clauseNodes = nodes.filter((n) => n.type === 'clause');

  return (
    <div className="lg:col-span-8 bg-odin-ivory border border-odin-border rounded-lg p-5 flex flex-col justify-between shadow-sm relative">
      {/* Top bar controls inside graph card */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-odin-border-subtle mb-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold text-odin-dark">Contract Relationship Graph</h2>
            <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-odin-palesage text-odin-forest border border-odin-sage/30 font-semibold">
              Interactive Canvas
            </span>
          </div>
          <p className="text-xs text-odin-muted">
            Contracts · Clauses · Parties — Dependency &amp; Collision Mapping
          </p>
        </div>

        {/* Canvas Controls & Filter Toggles */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Zoom Controls */}
          <div className="flex items-center bg-white border border-odin-border rounded p-0.5 shadow-xs font-mono text-xs">
            <button
              onClick={handleZoomIn}
              className="px-2 py-1 text-odin-dark hover:bg-odin-cream rounded font-bold cursor-pointer transition-colors"
              title="Zoom in"
            >
              +
            </button>
            <button
              onClick={handleZoomOut}
              className="px-2 py-1 text-odin-dark hover:bg-odin-cream rounded font-bold cursor-pointer transition-colors"
              title="Zoom out"
            >
              −
            </button>
            <button
              onClick={handleResetZoom}
              className="px-2 py-1 text-odin-muted hover:text-odin-dark hover:bg-odin-cream rounded text-[11px] cursor-pointer transition-colors"
              title="Reset Canvas Zoom & Selection"
            >
              Reset
            </button>
          </div>

          {/* Filter Toggles */}
          <div className="flex items-center gap-1 font-mono text-xs">
            <button
              onClick={() => setFilterContracts((f) => !f)}
              className={`px-2 py-1 rounded transition-colors cursor-pointer ${
                filterContracts
                  ? 'bg-odin-forest text-white font-medium'
                  : 'bg-white text-odin-muted hover:text-odin-dark border border-odin-border'
              }`}
            >
              Contracts ({contractNodes.length})
            </button>
            <button
              onClick={() => setFilterClauses((f) => !f)}
              className={`px-2 py-1 rounded transition-colors cursor-pointer ${
                filterClauses
                  ? 'bg-odin-forest text-white font-medium'
                  : 'bg-white text-odin-muted hover:text-odin-dark border border-odin-border'
              }`}
            >
              Clauses ({clauseNodes.length})
            </button>
            <button
              onClick={() => setFilterParties((f) => !f)}
              className={`px-2 py-1 rounded transition-colors cursor-pointer ${
                filterParties
                  ? 'bg-odin-forest text-white font-medium'
                  : 'bg-white text-odin-muted hover:text-odin-dark border border-odin-border'
              }`}
            >
              Parties ({partyNodes.length})
            </button>
          </div>
        </div>
      </div>

      {/* SVG Visual Graph Canvas */}
      <div 
        className="w-full h-96 relative bg-white rounded border border-odin-border overflow-hidden flex items-center justify-center shadow-inner cursor-default select-none"
        onClick={() => {
          // Clicking empty canvas clears edge popover
          setActiveEdgeId(null);
        }}
      >
        <svg
          className="w-full h-full transition-transform duration-300 origin-center"
          style={{ transform: `scale(${zoom})` }}
          fill="none"
          viewBox="0 0 820 400"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <pattern height="30" id="graph-grid" patternUnits="userSpaceOnUse" width="30">
              <circle cx="15" cy="15" fill="#D5CEBE" r="0.8"></circle>
            </pattern>
            {/* Filter for emphasized/popped node */}
            <filter id="node-pop-shadow" x="-30%" y="-30%" width="160%" height="160%">
              <feDropShadow dx="0" dy="4" stdDeviation="6" floodColor="#303B28" floodOpacity="0.35" />
            </filter>
            <filter id="collision-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#C83D3D" floodOpacity="0.4" />
            </filter>
          </defs>

          {/* Grid backdrop */}
          <rect fill="url(#graph-grid)" height="100%" width="100%"></rect>

          {/* Subtle radial orientation rings */}
          <circle cx="410" cy="200" fill="none" r="170" stroke="#DCDCCB" strokeDasharray="4 4"></circle>
          <circle cx="410" cy="200" fill="none" r="90" stroke="#DCDCCB" strokeDasharray="3 3"></circle>

          {/* EDGES (Dynamic Connectors) */}
          <g className="edges-layer">
            {edges.map((edge) => {
              const src = nodeMap[edge.source];
              const tgt = nodeMap[edge.target];
              if (!src || !tgt) return null;

              if (edge.type === 'involves' && !filterParties) return null;
              if (edge.type === 'contains' && !filterClauses) return null;
              if (['incorporates', 'amends', 'references'].includes(edge.type) && !filterContracts) return null;

              const isEdgeActive = activeEdgeId === edge.id;

              if (edge.is_collision) {
                if (!filterClauses) return null;
                const midX = (src.x + tgt.x) / 2;
                const midY = (src.y + tgt.y) / 2 - 30;
                return (
                  <path
                    key={edge.id}
                    d={`M ${src.x} ${src.y} Q ${midX} ${midY} ${tgt.x} ${tgt.y}`}
                    stroke="#C83D3D"
                    strokeDasharray="6 4"
                    strokeLinecap="round"
                    strokeWidth={isEdgeActive ? 3.5 : 2.5}
                    filter={isEdgeActive ? 'url(#collision-glow)' : undefined}
                    className="cursor-pointer hover:stroke-width-4 transition-all"
                    onClick={(e) => handleEdgeClick(edge.id, e)}
                  >
                    <animate attributeName="stroke-dashoffset" dur="4s" from="80" repeatCount="indefinite" to="0" />
                  </path>
                );
              }

              return (
                <path
                  key={edge.id}
                  d={`M ${src.x} ${src.y} L ${tgt.x} ${tgt.y}`}
                  stroke={isEdgeActive ? '#303B28' : edge.type === 'involves' ? '#7D866E' : '#303B28'}
                  strokeOpacity={isEdgeActive ? 1 : 0.55}
                  strokeWidth={isEdgeActive ? 3 : 1.5}
                  className="cursor-pointer hover:stroke-opacity-100 transition-all"
                  onClick={(e) => handleEdgeClick(edge.id, e)}
                />
              );
            })}
          </g>

          {/* Conflict Marker Beacon */}
          {filterClauses && beacon?.active && (
            <g
              transform={`translate(${beacon.x}, ${beacon.y})`}
              className="cursor-pointer"
              onClick={(e) => defaultCollisionEdge && handleEdgeClick(defaultCollisionEdge.id, e)}
            >
              <circle className="animate-ping" cx="0" cy="0" fill="#C83D3D" fillOpacity="0.2" r="15" stroke="#C83D3D" strokeWidth="1.5"></circle>
              <circle cx="0" cy="0" fill="#8F2929" r="10" stroke="#FCFAF3" strokeWidth="1.5"></circle>
              <text fill="#FCFAF3" fontFamily="JetBrains Mono" fontSize="10" fontWeight="bold" textAnchor="middle" x="0" y="3.5">
                !
              </text>
            </g>
          )}

          {/* PARTY NODES */}
          {filterParties && (
            <g className="parties-layer">
              {partyNodes.map((p) => {
                const isSelected = selectedNodeId === p.id;
                const boxW = Math.max(90, Math.min(p.label.length * 7 + 20, 150));
                const boxH = 26;
                return (
                  <g
                    key={p.id}
                    transform={`translate(${p.x}, ${p.y})`}
                    onClick={(e) => handleNodeClick(p.id, e)}
                    className="cursor-pointer"
                    filter={isSelected ? 'url(#node-pop-shadow)' : undefined}
                  >
                    <rect
                      fill="#FCFAF3"
                      height={boxH}
                      rx="4"
                      stroke={isSelected ? '#303B28' : '#DCDCCB'}
                      strokeWidth={isSelected ? 2 : 1.2}
                      width={boxW}
                      x={-boxW / 2}
                      y={-boxH / 2}
                    />
                    <text
                      fill={isSelected ? '#252E1F' : '#727665'}
                      fontFamily="JetBrains Mono"
                      fontSize="9.5"
                      fontWeight={isSelected ? 'bold' : 'normal'}
                      textAnchor="middle"
                      x="0"
                      y="3.5"
                    >
                      {p.label.length > 18 ? p.label.substring(0, 16) + '...' : p.label}
                    </text>
                  </g>
                );
              })}
            </g>
          )}

          {/* CLAUSE NODES */}
          {filterClauses && (
            <g className="clauses-layer">
              {clauseNodes.map((c) => {
                const isSelected = selectedNodeId === c.id;
                const boxW = Math.max(80, Math.min(c.label.length * 7 + 16, 140));
                const boxH = 24;
                const isConflict = c.is_conflict;

                return (
                  <g
                    key={c.id}
                    transform={`translate(${c.x}, ${c.y})`}
                    onClick={(e) => handleNodeClick(c.id, e)}
                    className="cursor-pointer"
                    filter={isSelected ? 'url(#node-pop-shadow)' : undefined}
                  >
                    <rect
                      fill={isConflict ? '#FBEBEB' : '#F5F1E6'}
                      height={boxH}
                      rx="4"
                      stroke={isConflict ? '#C83D3D' : isSelected ? '#303B28' : '#7D866E'}
                      strokeWidth={isSelected || isConflict ? 2 : 1.2}
                      width={boxW}
                      x={-boxW / 2}
                      y={-boxH / 2}
                    />
                    {isConflict && (
                      <circle cx={-boxW / 2 + 8} cy="0" fill="#C83D3D" r="3" />
                    )}
                    <text
                      fill={isConflict ? '#8F2929' : '#252E1F'}
                      fontFamily="JetBrains Mono"
                      fontSize="9"
                      fontWeight={isSelected || isConflict ? 'bold' : 'normal'}
                      textAnchor="middle"
                      x={isConflict ? 4 : 0}
                      y="3.5"
                    >
                      {c.label.length > 16 ? c.label.substring(0, 14) + '..' : c.label}
                    </text>
                  </g>
                );
              })}
            </g>
          )}

          {/* CONTRACT NODES */}
          {filterContracts && (
            <g className="contracts-layer">
              {contractNodes.map((c) => {
                const isSelected = selectedNodeId === c.id;
                const isCritical = c.risk_level === 'critical';
                const boxW = Math.max(90, Math.min(c.label.length * 8 + 40, 160));
                const boxH = 34;

                return (
                  <g
                    key={c.id}
                    transform={`translate(${c.x}, ${c.y})`}
                    onClick={(e) => handleNodeClick(c.id, e)}
                    className="cursor-pointer"
                    filter={isSelected ? 'url(#node-pop-shadow)' : undefined}
                  >
                    <rect
                      fill={isSelected ? '#1B2218' : '#252E1F'}
                      height={boxH}
                      rx="6"
                      stroke={isSelected ? '#DDF1E6' : isCritical ? '#C83D3D' : '#7D866E'}
                      strokeWidth={isSelected ? 3 : isCritical ? 2 : 1.5}
                      width={boxW}
                      x={-boxW / 2}
                      y={-boxH / 2}
                    />
                    <circle
                      cx={-boxW / 2 + 12}
                      cy="0"
                      fill={isCritical ? '#C83D3D' : '#4ADE80'}
                      r="4"
                      className={isCritical ? 'animate-pulse' : ''}
                    />
                    <text
                      fill="#FCFAF3"
                      fontFamily="Plus Jakarta Sans"
                      fontSize="11"
                      fontWeight="bold"
                      textAnchor="middle"
                      x="6"
                      y="4"
                    >
                      {c.label.length > 15 ? c.label.substring(0, 13) + '..' : c.label}
                    </text>
                  </g>
                );
              })}
            </g>
          )}
        </svg>

        {/* Edge Description Popover (When an edge is clicked) */}
        {activeEdge && (
          <div 
            className="absolute top-12 left-1/2 -translate-x-1/2 bg-odin-panel text-odin-cream border border-odin-amber/50 rounded-lg p-3 max-w-md shadow-xl z-20 animate-fade-slide-up"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-2 border-b border-odin-sage/30 pb-1.5 mb-1.5">
              <span className="font-mono text-[10px] font-bold text-odin-amber flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">schema</span>
                RELATIONSHIP INSPECTION
              </span>
              <button 
                onClick={() => setActiveEdgeId(null)}
                className="text-odin-muted hover:text-white text-xs font-mono px-1 rounded cursor-pointer"
              >
                ✕
              </button>
            </div>
            <p className="text-xs text-odin-cream leading-relaxed font-sans">
              {activeEdge.description}
            </p>
          </div>
        )}

        {/* Floating Inspector Pill (Reflects selected entity visual telemetry) */}
        <div className="absolute bottom-3 left-3 bg-odin-forest text-white rounded p-3 max-w-xs shadow-md border border-odin-sage/30 flex items-center justify-between gap-3 pointer-events-none">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-odin-palesage animate-pulse"></span>
            <div className="flex flex-col">
              <span className="text-xs font-bold font-sans">Selected: {selectedNode.label}</span>
              <span className="text-[10px] font-mono text-odin-palesage">
                {selectedNode.type === 'contract' 
                  ? `${selectedNode.obligations_count || 0} Clauses / Obligations`
                  : selectedNode.type === 'clause'
                  ? `Clause Ref: ${selectedNode.clause_ref || '§ Reference'}`
                  : `Role: ${selectedNode.role || 'Contracting Legal Party'}`}
              </span>
            </div>
          </div>
          <span
            className={`font-mono text-[10px] px-1.5 py-0.5 rounded font-bold ${
              selectedNode.risk_level === 'critical' || selectedNode.is_conflict
                ? 'bg-odin-red text-white'
                : 'bg-odin-palesage text-odin-forest'
            }`}
          >
            {selectedNode.risk_level === 'critical' || selectedNode.is_conflict ? 'CRITICAL' : 'VERIFIED'}
          </span>
        </div>

        {/* Collision Legend Tag */}
        <div className="absolute top-3 right-3 bg-white border border-odin-border rounded px-2.5 py-1 flex items-center gap-2 font-mono text-xs shadow-xs pointer-events-none">
          <span className="w-4 h-0.5 border-b-2 border-dashed border-odin-red inline-block"></span>
          <span className="text-odin-red font-semibold text-[11px]">LOKI Collision Edge</span>
        </div>
      </div>

      {/* Graph Telemetry Footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-2 text-odin-muted font-mono text-[11px]">
        <span>
          {telemetry.entity_summary || `ENTITIES: ${contractNodes.length} CONTRACTS · ${clauseNodes.length} CLAUSES · ${partyNodes.length} PARTIES`}
        </span>
        <span className="text-odin-forest font-semibold">
          GRAPH ENGINE: {telemetry.engine || 'DETERMINISTIC_RELATIONAL_SYNCED'}
        </span>
      </div>
    </div>
  );
}
