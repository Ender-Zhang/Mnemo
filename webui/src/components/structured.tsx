// Structured, readable replacements for the raw JSON dumps that used to fill the
// advanced views (health, snapshot, links, metadata). Raw JSON is still available
// behind a collapsible DeveloperJson for debugging.

import { ChevronRight } from "lucide-react";
import { compactId, formatDate, snapshotHubs, snapshotPointers } from "../format";
import type { MemoryHealthResult, MemoryLinksResult, SnapshotResult } from "../types";
import { EmptyState, JsonBlock, StatusBadge } from "./shared";

function renderScalar(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function DeveloperJson({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="dev-json">
      <summary>{title} · 原始 JSON</summary>
      <JsonBlock title={title} value={value} />
    </details>
  );
}

export function KeyValueGrid({ title, value }: { title: string; value: Record<string, unknown> | null | undefined }) {
  const entries = Object.entries(value || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <div className="kv-grid">
      <div className="kv-grid-head">{title}</div>
      {entries.length === 0 ? (
        <EmptyState text="无数据。" />
      ) : (
        entries.map(([k, v]) => (
          <div className="kv-row" key={k}>
            <span className="kv-key">{k}</span>
            <span className="kv-val">{renderScalar(v)}</span>
          </div>
        ))
      )}
    </div>
  );
}

export function HealthView({ health }: { health: MemoryHealthResult | null }) {
  const cards = Array.isArray(health?.cards) ? (health!.cards as Array<Record<string, unknown>>) : [];
  const summary = health?.summary && typeof health.summary === "object" ? (health.summary as Record<string, unknown>) : null;
  return (
    <div className="structured-block">
      <div className="structured-head"><h3>记忆健康</h3><StatusBadge text={`${cards.length} cards`} /></div>
      {summary ? <KeyValueGrid title="概要" value={summary} /> : null}
      {cards.length === 0 ? (
        <EmptyState text="暂无健康卡片。" />
      ) : (
        <div className="health-card-list">
          {cards.map((card, i) => <HealthCard card={card} key={i} />)}
        </div>
      )}
      <DeveloperJson title="Health" value={health || {}} />
    </div>
  );
}

function HealthCard({ card }: { card: Record<string, unknown> }) {
  const title = String(card.title || card.kind || card.id || "card");
  const badge = String(card.severity || card.status || card.kind || "info");
  const detail = String(card.detail || card.summary || card.reason || card.message || "");
  const count = card.count ?? card.size ?? card.value;
  return (
    <article className="health-card">
      <div className="health-card-head">
        <strong>{title}</strong>
        <StatusBadge text={badge} />
        {count !== undefined && count !== null ? <span className="health-count">{String(count)}</span> : null}
      </div>
      {detail ? <p>{detail}</p> : null}
    </article>
  );
}

export function SnapshotView({ snapshot }: { snapshot: SnapshotResult | null }) {
  const snap = snapshot?.snapshot || null;
  const pointers = snapshotPointers(snap);
  const hubs = snapshotHubs(snap);
  const generatedAt = snap ? (snap as { generated_at?: number }).generated_at : undefined;
  const pageCount = snap ? (snap as { page_count?: number }).page_count : undefined;
  return (
    <div className="structured-block">
      <div className="structured-head"><h3>L1 快照</h3><StatusBadge text={snapshot?.exists ? "已生成" : "未生成"} /></div>
      {!snap ? (
        <EmptyState text="快照未生成。运行 Dream 或刷新快照。" />
      ) : (
        <>
          <div className="snapshot-meta">
            <span>页数 {pageCount ?? "-"}</span>
            <span>{pointers.length} pointers · {hubs.length} hubs</span>
            {generatedAt ? <span>生成于 {formatDate(generatedAt)}</span> : null}
          </div>
          {pointers.length > 0 ? (
            <div className="preview-pointer-list">
              {pointers.slice(0, 12).map((p, i) => (
                <div className="preview-pointer" key={i}><code>{p.trigger || "—"}</code><ChevronRight size={13} /><span>{p.title || p.target}</span></div>
              ))}
            </div>
          ) : null}
          {hubs.length > 0 ? <div className="preview-hubs">联想热点：{hubs.slice(0, 8).join("、")}</div> : null}
        </>
      )}
      <DeveloperJson title="Snapshot" value={snapshot || {}} />
    </div>
  );
}

export function LinksView({ links }: { links: MemoryLinksResult | null }) {
  const outgoing = Array.isArray(links?.outgoing) ? (links!.outgoing as Array<Record<string, unknown>>) : [];
  const incoming = Array.isArray(links?.incoming) ? (links!.incoming as Array<Record<string, unknown>>) : [];
  return (
    <div className="structured-block">
      <div className="structured-head"><h3>关联</h3><StatusBadge text={`${outgoing.length}→ · ←${incoming.length}`} /></div>
      {outgoing.length === 0 && incoming.length === 0 ? (
        <EmptyState text="暂无关联边。" />
      ) : (
        <div className="link-list">
          {outgoing.map((edge, i) => <LinkRow edge={edge} dir="out" key={`o${i}`} />)}
          {incoming.map((edge, i) => <LinkRow edge={edge} dir="in" key={`i${i}`} />)}
        </div>
      )}
    </div>
  );
}

function LinkRow({ edge, dir }: { edge: Record<string, unknown>; dir: "out" | "in" }) {
  const relation = String(edge.relation || edge.relation_type || "related");
  const otherId = String(dir === "out" ? (edge.target_id || edge.target || "") : (edge.source_id || edge.source || ""));
  const weight = edge.weight;
  return (
    <div className="link-row">
      <span className={`link-dir ${dir}`}>{dir === "out" ? "→" : "←"}</span>
      <StatusBadge text={relation} />
      <code>{compactId(otherId) || otherId || "-"}</code>
      {typeof weight === "number" ? <span className="link-weight">{weight.toFixed(2)}</span> : null}
    </div>
  );
}
