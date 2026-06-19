// Small presentational primitives shared across panels.

import { Link2 } from "lucide-react";
import { compactStatusText } from "../format";

export function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="json-block">
      <div><span>{title}</span><button onClick={() => navigator.clipboard?.writeText(JSON.stringify(value, null, 2))}><Link2 size={13} /></button></div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

export function StatusBadge({ text }: { text: string }) {
  const n = text.toLowerCase();
  const tone = n.includes("active") || n.includes("ok") || n.includes("page") ? "good"
    : n.includes("draft") || n.includes("candidate") ? "blue"
    : n.includes("reject") || n.includes("tomb") || n.includes("delete") ? "bad"
    : n.includes("conflict") ? "warn"
    : "neutral";
  return <span className={`badge ${tone}`} title={text}>{compactStatusText(text)}</span>;
}

export function StatusDot({ ok }: { ok: boolean }) { return <span className={ok ? "dot ok" : "dot"} />; }

export function EmptyState({ text }: { text: string }) { return <div className="empty-state">{text}</div>; }
