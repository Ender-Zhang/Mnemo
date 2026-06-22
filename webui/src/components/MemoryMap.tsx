// Ten-dimension distribution + a lightweight association graph over memory_links.

import type { MemoryGraphResult } from "../types";
import { EmptyState } from "./shared";

const DIM_COLORS: Record<string, string> = {
  identity: "#1f5edb",
  cognition: "#0e9f6e",
  values: "#9333ea",
  goals: "#e8590c",
  preferences: "#0891b2",
  relationships: "#db2777",
  context: "#65a30d",
  history: "#a16207",
  patterns: "#4f46e5",
  boundaries: "#dc2626"
};

function dimColor(dimension: string): string {
  return DIM_COLORS[dimension] || "#7b8494";
}

export function MemoryMap({ graph }: { graph: MemoryGraphResult | null }) {
  const dimensions = graph?.dimensions || [];
  const nodes = graph?.nodes || [];
  const edges = graph?.edges || [];
  const maxCount = dimensions.reduce((max, row) => Math.max(max, row.count), 0) || 1;

  return (
    <section className="panel memory-map">
      <div className="panel-header compact">
        <h2>记忆地图</h2>
        <span>{graph?.page_count ?? 0} 页 · {edges.length} 关联</span>
      </div>

      <div className="map-dimensions">
        {dimensions.length === 0 ? (
          <EmptyState text="暂无稳定记忆。promote 一些候选后这里会显示维度分布。" />
        ) : (
          dimensions.map((row) => (
            <div className="dim-row" key={row.dimension}>
              <span className="dim-label" style={{ color: dimColor(row.dimension) }}>{row.dimension}</span>
              <span className="dim-bar-track">
                <span className="dim-bar" style={{ width: `${Math.round((row.count / maxCount) * 100)}%`, background: dimColor(row.dimension) }} />
              </span>
              <span className="dim-count">{row.count}</span>
            </div>
          ))
        )}
      </div>

      <AssociationGraph nodes={nodes} edges={edges} />
    </section>
  );
}

function AssociationGraph({ nodes, edges }: { nodes: NonNullable<MemoryGraphResult["nodes"]>; edges: NonNullable<MemoryGraphResult["edges"]> }) {
  const display = [...nodes].sort((a, b) => b.degree - a.degree).slice(0, 36);
  if (display.length === 0) {
    return <div className="map-graph-empty"><EmptyState text="暂无关联边。运行 Dream 自动建链，或在记忆间建立联系后显示关系图。" /></div>;
  }

  const size = 360;
  const center = size / 2;
  const radius = size / 2 - 30;
  const index = new Map(display.map((node, i) => [node.id, i]));
  const pos = (i: number) => {
    const angle = (2 * Math.PI * i) / display.length - Math.PI / 2;
    return { x: center + radius * Math.cos(angle), y: center + radius * Math.sin(angle) };
  };
  const visibleEdges = edges.filter((edge) => index.has(edge.source) && index.has(edge.target));

  return (
    <div className="map-graph">
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label="记忆关联关系图">
        {visibleEdges.map((edge, i) => {
          const a = pos(index.get(edge.source)!);
          const b = pos(index.get(edge.target)!);
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="map-edge" />;
        })}
        {display.map((node, i) => {
          const point = pos(i);
          const r = 4 + Math.min(7, node.degree);
          const color = dimColor(node.dimension);
          return (
            <circle
              key={node.id}
              cx={point.x}
              cy={point.y}
              r={r}
              fill={node.orphan ? "transparent" : color}
              stroke={color}
              strokeWidth={node.orphan ? 1.5 : 1}
              strokeDasharray={node.orphan ? "3 2" : undefined}
            >
              <title>{`${node.title}\n[${node.dimension}] · ${node.degree} 关联${node.orphan ? " · 孤岛" : ""}`}</title>
            </circle>
          );
        })}
      </svg>
      <div className="map-legend">
        {[...new Set(display.map((node) => node.dimension))].map((dimension) => (
          <span className="map-legend-item" key={dimension}>
            <span className="map-legend-dot" style={{ background: dimColor(dimension) }} />
            {dimension}
          </span>
        ))}
        <span className="map-legend-item"><span className="map-legend-dot hollow" /> 孤岛页（无关联）</span>
      </div>
    </div>
  );
}
