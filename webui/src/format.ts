// Pure helpers: formatters, item mappers, audit-result derivation, snapshot/token
// utilities and plan helpers. No React, no side effects.

import type {
  ContextCardItem,
  DreamRejectReason,
  DreamReviewResult,
  DreamRunReport,
  DreamStatusResult,
  MemoryItem,
  MemoryTombstone,
  PlanFormState,
  PlanItem
} from "./types";

// ─── Item mapping / search ─────────────────────────────────────────────────

export function searchMatchToItem(match: Record<string, unknown>): MemoryItem | null {
  const rawType = String(match.type || match.item_type || "page");
  if (rawType.includes("plan")) {
    return null;
  }
  const type = rawType.includes("candidate") ? "candidate" : "page";
  return { ...(match as MemoryItem), type, id: String(match.id || match.memory_id || ""), title: String(match.title || match.claim || ""), content: String(match.content || match.claim || match.summary || "") };
}

export function itemMatchesQuery(item: MemoryItem, query: string) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = [item.id, item.type, item.status, item.claim, item.title, item.content, item.scope, item.dimension, item.run_id, item.source_candidate_id].filter(Boolean).join(" ").toLowerCase();
  return terms.every((t) => haystack.includes(t));
}

export function compareMemoryItems(left: MemoryItem, right: MemoryItem) {
  const typeRank = (item: MemoryItem) => (item.type === "page" ? 0 : 1);
  const lr = typeRank(left), rr = typeRank(right);
  if (lr !== rr) return lr - rr;
  return (right.updated_at || right.created_at || 0) - (left.updated_at || left.created_at || 0);
}

export function scopeFromUidFilter(uid: string) {
  const clean = uid.trim();
  if (!clean) return "";
  return clean.toLowerCase().startsWith("user:") ? clean : `user:${clean}`;
}

export function memoryFactPayload(claim: string, scope: string) {
  return scope ? { claim, scope, confidence: 0.9 } : { claim, confidence: 0.9 };
}

export function memoryObservationPayload(content: string, scope: string) {
  return scope ? { content, retention: "memory_candidate", scope } : content;
}

export function tombstoneTargetItem(t: MemoryTombstone): MemoryItem {
  return { id: t.target_id, type: t.target_type, status: `tombstoned:${t.reason || "unknown"}`, title: t.summary || t.reason || t.target_id, content: t.summary || "", updated_at: t.created_at };
}

export function itemTitle(item: MemoryItem) { return item.title || item.claim || item.content || item.id; }

// ─── Formatters ──────────────────────────────────────────────────────────────

export function formatConfidence(value?: number) { if (typeof value !== "number") return "-"; return value.toFixed(2); }

export function formatTime(value?: number) {
  if (!value) return "-";
  const diff = Date.now() - value * 1000;
  const minute = 60 * 1000, hour = 60 * minute, day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.round(diff / minute))}m`;
  if (diff < day) return `${Math.round(diff / hour)}h`;
  return `${Math.round(diff / day)}d`;
}

export function formatDate(value?: number) {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleString("zh-CN");
}

export function compactId(value?: string) {
  if (!value) return "";
  return value.length > 24 ? `${value.slice(0, 21)}...` : value;
}

export function compactStatusText(text: string) {
  const clean = text.trim();
  const sep = clean.indexOf(":");
  return sep > 0 ? clean.slice(0, sep) : clean;
}

export function formatDuration(value: number) {
  if (!Number.isFinite(value) || value < 0) return "0.0s";
  if (value < 10) return `${value.toFixed(1)}s`;
  if (value < 60) return `${Math.round(value)}s`;
  const m = Math.floor(value / 60), s = Math.round(value % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

// ─── Audit-result derivation ───────────────────────────────────────────────

export function dreamReviewResultMap(status: DreamStatusResult | null) {
  const map = new Map<string, DreamReviewResult>();
  for (const result of normalizeDreamReviewResults(status?.latest?.execution?.review_results)) {
    for (const key of [result.candidate_id, result.page_id]) {
      if (key && !map.has(key)) map.set(key, result);
    }
  }
  return map;
}

export function normalizeDreamReviewResults(items: unknown) {
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is DreamReviewResult => {
    if (!item || typeof item !== "object") return false;
    const r = item as DreamReviewResult;
    return Boolean(r.candidate_id || r.page_id) && Boolean(r.decision || r.status || r.reason);
  }).slice(0, 20);
}

export function reviewForItem(item: MemoryItem, results: Map<string, DreamReviewResult>) {
  return results.get(item.id) || (item.source_candidate_id ? results.get(item.source_candidate_id) : undefined);
}

export function auditResultForItem(item: MemoryItem, review?: DreamReviewResult) {
  if (review) return auditResultFromDreamReview(review);
  const status = String(item.status || "").trim();
  const n = status.toLowerCase();
  if (n === "promoted") return auditResult("审核通过", "候选已进入稳定记忆", "good");
  if (n === "draft") return auditResult("待审核", "等待模型或人工审核", "blue");
  if (n.startsWith("rejected")) return auditResult("审核拒绝", statusReason(status), "bad");
  if (n.startsWith("needs_review")) return auditResult("待复核", statusReason(status), "warn");
  if (n.startsWith("skipped")) return auditResult("已跳过", statusReason(status), "neutral");
  if (item.type === "page" && n === "active") return auditResult("稳定记忆", stableMemoryFallbackReason(item), "good");
  if (n.includes("tombstone") || n.includes("delete")) return auditResult("已删除", statusReason(status), "bad");
  if (n.includes("conflict")) return auditResult("冲突", statusReason(status), "warn");
  return auditResult("未审核", status || "unknown", "neutral");
}

export function auditResultFromDreamReview(review: DreamReviewResult) {
  const decision = String(review.decision || "").toLowerCase();
  const status = String(review.status || "");
  const n = status.toLowerCase();
  if (decision === "promoted" || n === "promoted") return auditResult("模型通过", review.reason || promotedReviewFallbackReason(review), "good");
  if (decision === "rejected" || n.startsWith("rejected")) return auditResult("模型拒绝", review.reason || statusReason(status), "bad");
  if (decision === "skipped") return auditResult("模型跳过", review.reason || statusReason(status), "neutral");
  if (decision === "conflict" || n.includes("conflict")) return auditResult("需复核", review.reason || "conflict", "warn");
  return auditResult("模型已审", review.reason || status || decision, "blue");
}

export function detailedAuditReason(item: MemoryItem, review: DreamReviewResult | undefined, fallback: string) {
  if (review) {
    if (review.reason) return review.reason;
    if (String(review.decision || "").toLowerCase() === "promoted" || String(review.status || "").toLowerCase() === "promoted") return promotedReviewFallbackReason(review);
    return fallback || review.status || review.decision || "审核结果没有附带详细原因。";
  }
  if (item.type === "page" && String(item.status || "").toLowerCase() === "active") return stableMemoryFallbackReason(item);
  return fallback || statusReason(String(item.status || "")) || "暂无详细审核原因。";
}

export function promotedReviewFallbackReason(review: DreamReviewResult) {
  const actionText = review.page_action === "merged" ? "已合并到已有稳定记忆页" : review.page_action === "created" ? "已新建稳定记忆页" : "已进入稳定记忆";
  const pageText = review.page_title ? `「${review.page_title}」` : review.page_id ? compactId(review.page_id) : "";
  const sourceText = review.candidate_id ? `；来源候选 ${compactId(review.candidate_id)}` : "";
  return `${actionText}${pageText ? ` ${pageText}` : ""}${sourceText}`;
}

export function stableMemoryFallbackReason(item: MemoryItem) {
  const parts = ["已进入稳定记忆，可用于后续检索和上下文召回"];
  if (item.source_candidate_id) parts.push(`来源候选 ${compactId(item.source_candidate_id)}`);
  if (typeof item.confidence === "number") parts.push(`置信度 ${formatConfidence(item.confidence)}`);
  return parts.join("；");
}

export function auditReviewLabel(review: DreamReviewResult) { return auditResultFromDreamReview(review).label; }

export function auditResult(label: string, detail: string, tone: "good" | "bad" | "warn" | "blue" | "neutral") {
  return { label, detail, tone, title: detail ? `${label}: ${detail}` : label };
}

export function statusReason(status: string) {
  const sep = status.indexOf(":");
  if (sep < 0) return "";
  return status.slice(sep + 1).replace(/[_-]+/g, " ");
}

// ─── Dream report summaries ──────────────────────────────────────────────────

export function latestDreamDurationS(status: DreamStatusResult | null) {
  const v = status?.latest?.duration_s;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function dreamStatusReviewReasons(status: DreamStatusResult | null) {
  return normalizeDreamReviewResults(status?.latest?.execution?.review_results).filter((i) => Boolean(i.reason));
}

export function dreamRunRejectReasons(report: DreamRunReport) {
  return normalizeDreamRejectReasons(report.execution?.result?.actions?.applied);
}

export function normalizeDreamRejectReasons(items: unknown) {
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is DreamRejectReason => {
    if (!item || typeof item !== "object") return false;
    const a = item as DreamRejectReason;
    const tool = String(a.tool || ""), decision = String(a.decision || ""), status = String(a.status || "");
    return Boolean(a.reason) && (tool === "memory_reject_candidate" || decision === "rejected" || status.startsWith("rejected"));
  }).slice(0, 10);
}

export function dreamRejectReasonText(items: DreamRejectReason[]) {
  if (items.length === 0) return "";
  const details = items.slice(0, 3).map((i) => `${compactId(i.candidate_id || i.action_id)}: ${i.reason || "unspecified"}`).join("；");
  const more = items.length > 3 ? `；另有 ${items.length - 3} 条` : "";
  return ` Reject 原因：${details}${more}`;
}

export function dreamDurationText(report: DreamRunReport) {
  return typeof report.duration_s === "number" && Number.isFinite(report.duration_s) ? `用时 ${formatDuration(report.duration_s)}。` : "";
}

export function dreamRunMessage(report: DreamRunReport, useProvider: boolean, advancedDreaming = false) {
  const counts = report.execution?.result?.actions?.counts || {};
  const deltaCounts = report.delta?.counts || {};
  const requested = Number(counts.requested || 0), applied = Number(counts.applied || 0), skipped = Number(counts.skipped || 0);
  const proposals = report.execution?.result?.actions?.proposals || [];
  const pendingProposals = proposals.filter((p) => p.status === "pending").length;
  const draftCandidates = Number(deltaCounts.draft_candidates || deltaCounts.memory_candidates || 0);
  const rejectReasonText = dreamRejectReasonText(dreamRunRejectReasons(report));
  const durationText = dreamDurationText(report);
  const proposalText = advancedDreaming ? `整理提案 ${pendingProposals} 条。` : "";
  if (!useProvider && requested === 0) {
    return `Dream 已运行：已生成报告和快照；未开启模型审核，所以没有维护动作。待审候选 ${draftCandidates} 条。${proposalText}${durationText}`;
  }
  return `Dream 已运行：请求 ${requested} 个动作，应用 ${applied} 个，跳过 ${skipped} 个。${proposalText}${durationText}${rejectReasonText}`;
}

// ─── Snapshot / token helpers (memory preview) ───────────────────────────────

export function isSemanticHit(item: { match_signals?: unknown; vector_score?: unknown }): boolean {
  if (typeof item.vector_score === "number") return true;
  const signals = item.match_signals;
  return Array.isArray(signals) && signals.some((signal) => signal && typeof signal === "object" && (signal as { route?: unknown }).route === "vector");
}

export function previewCardType(card: ContextCardItem) {
  const t = String(card.type || "");
  if (t.includes("candidate")) return "candidate";
  if (t.includes("page")) return "page";
  return t || "memory";
}

export function snapshotPointers(snapshot: Record<string, unknown> | null): Array<{ trigger: string; target: string; title: string }> {
  const raw = snapshot ? (snapshot as { pointers?: unknown }).pointers : null;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((p) => {
      const obj = (p || {}) as Record<string, unknown>;
      return {
        trigger: String(obj.trigger ?? ""),
        target: String(obj.target ?? ""),
        title: String(obj.title ?? "")
      };
    })
    .filter((p) => p.trigger || p.target || p.title);
}

export function snapshotHubs(snapshot: Record<string, unknown> | null): string[] {
  const raw = snapshot ? (snapshot as { association_hubs?: unknown }).association_hubs : null;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((h) => {
      const obj = (h || {}) as Record<string, unknown>;
      return String(obj.title ?? obj.target ?? obj.page_id ?? "");
    })
    .filter(Boolean);
}

export function estimateContextTokens(profileSummary: string, snapshot: Record<string, unknown> | null, cards: ContextCardItem[]): number {
  const cardText = cards.map((c) => `${c.title || ""}${c.content || c.claim || ""}`).join("");
  const snapshotText = snapshot ? JSON.stringify(snapshot) : "";
  const total = `${profileSummary}${snapshotText}${cardText}`;
  let cjk = 0;
  let other = 0;
  for (const ch of total) {
    if (/[一-鿿぀-ヿ가-힯]/.test(ch)) cjk += 1;
    else other += 1;
  }
  return Math.max(0, Math.round(cjk + other / 4));
}

// ─── Plan helpers ─────────────────────────────────────────────────────────────

export function emptyPlanForm(): PlanFormState {
  return {
    kind: "todo",
    title: "",
    detail: "",
    parentId: "",
    priority: "normal",
    dueAt: ""
  };
}

export function datetimeLocalToUnix(value: string) {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? Math.round(ms / 1000) : null;
}

export function isClosedPlan(item: PlanItem) {
  return ["completed", "done", "cancelled", "archived"].includes(String(item.status || "").toLowerCase());
}

export function planTitleById(items: PlanItem[], id: string) {
  return items.find((item) => item.id === id)?.title || compactId(id);
}
