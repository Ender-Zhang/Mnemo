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
  PlanItem,
  PlanProposal,
  PlanUserGroup
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

// A page kept-both out of a conflict is flagged disputed in its metadata until
// the contradiction is reconciled (by the model or the user).
export function isDisputed(item: MemoryItem) { return item.type === "page" && Boolean(item.metadata?.disputed); }

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

// Maps terse decision codes (low_quality / duplicate / ...) to a detailed,
// human-readable Chinese explanation of why a memory was kept or dropped.
const DECISION_REASON_LABELS: Array<[RegExp, string]> = [
  [/^low_quality/, "质量分过低：内容太笼统或缺乏具体信息，被判为低价值，未融入。"],
  [/^below_quality_threshold/, "质量分低于阈值，暂缓融入、留待复核。"],
  [/^below_confidence_threshold/, "置信度低于融入门槛，暂不固化为稳定记忆。"],
  [/^duplicate/, "与已有稳定记忆重复，已并入原记忆、不重复保存。"],
  [/^empty/, "内容为空，无法形成记忆。"],
  [/^conflicts?_with_active_memory/, "与一条现有记忆冲突，需要裁决保留哪条。"],
  [/^conflict_resolved:keep_old/, "冲突自动消解：保留旧记忆，拒绝此候选。"],
  [/^conflict_resolved:keep_new/, "冲突自动消解：用新记忆替换旧记忆。"],
  [/^conflict_resolved:keep_both/, "冲突自动消解：同时保留新旧两条记忆（已补充到同一页）。"],
  [/^conflict_resolved:merge/, "冲突由模型消解：合并为一条消歧后的记忆。"],
  [/^conflict_resolved/, "冲突已自动消解。"],
  [/^conflict/, "与现有记忆冲突，需要复核。"],
  [/^deterministic_fallback/, "本地自动整理规则处理（未调用模型）。"],
  [/^operator_/, "人工操作。"]
];

export function humanizeDecisionReason(reason?: string): string {
  const raw = String(reason || "").trim();
  if (!raw) return "";
  const lower = raw.toLowerCase();
  for (const [pattern, label] of DECISION_REASON_LABELS) {
    if (pattern.test(lower)) return label;
  }
  // Backend promote reasons are descriptive English; translate the common phrasing.
  if (/passed quality and confidence gates/i.test(raw)) {
    const merged = /merged into an existing/i.test(raw);
    const conf = raw.match(/confidence\s+([0-9.]+)\s*>=\s*([0-9.]+)/i);
    const confText = conf ? `（置信度 ${conf[1]} ≥ 门槛 ${conf[2]}）` : "";
    return `${merged ? "通过质量与置信门槛，已合并到已有稳定记忆" : "通过质量与置信门槛，已新建稳定记忆"}${confText}。`;
  }
  return raw;
}

export function auditResultForItem(item: MemoryItem, review?: DreamReviewResult) {
  if (review) return auditResultFromDreamReview(review);
  const status = String(item.status || "").trim();
  const n = status.toLowerCase();
  if (n === "promoted") return auditResult("审核通过", "候选已进入稳定记忆", "good");
  if (n === "draft") return auditResult("待审核", "等待模型或人工审核", "blue");
  if (n.startsWith("rejected")) return auditResult("审核拒绝", reasonFromStatus(status), "bad");
  if (n.startsWith("needs_review")) return auditResult("待复核", reasonFromStatus(status), "warn");
  if (n.startsWith("skipped")) return auditResult("已跳过", reasonFromStatus(status), "neutral");
  if (item.type === "page" && n === "active") return auditResult("稳定记忆", stableMemoryFallbackReason(item), "good");
  if (n.includes("tombstone") || n.includes("delete")) return auditResult("已删除", reasonFromStatus(status), "bad");
  if (n.includes("conflict")) return auditResult("冲突", reasonFromStatus(status), "warn");
  return auditResult("未审核", status || "unknown", "neutral");
}

export function auditResultFromDreamReview(review: DreamReviewResult) {
  const decision = String(review.decision || "").toLowerCase();
  const status = String(review.status || "");
  const n = status.toLowerCase();
  if (decision === "promoted" || n === "promoted") return auditResult("已融入", humanizeDecisionReason(review.reason) || promotedReviewFallbackReason(review), "good");
  if (decision === "rejected" || n.startsWith("rejected")) return auditResult("已拒绝", humanizeDecisionReason(review.reason) || reasonFromStatus(status), "bad");
  if (decision === "skipped") return auditResult("已跳过", humanizeDecisionReason(review.reason) || reasonFromStatus(status), "neutral");
  if (decision === "conflict" || n.includes("conflict")) return auditResult("需复核", humanizeDecisionReason(review.reason) || "与现有记忆冲突，需要复核。", "warn");
  return auditResult("已处理", humanizeDecisionReason(review.reason) || status || decision, "blue");
}

export function detailedAuditReason(item: MemoryItem, review: DreamReviewResult | undefined, fallback: string) {
  if (review) {
    if (review.reason) return humanizeDecisionReason(review.reason);
    if (String(review.decision || "").toLowerCase() === "promoted" || String(review.status || "").toLowerCase() === "promoted") return promotedReviewFallbackReason(review);
    return fallback || reasonFromStatus(review.status || "") || review.decision || "审核结果没有附带详细原因。";
  }
  if (item.type === "page" && String(item.status || "").toLowerCase() === "active") return stableMemoryFallbackReason(item);
  return fallback || reasonFromStatus(String(item.status || "")) || "暂无详细审核原因。";
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

// Like statusReason but returns a detailed Chinese explanation when the status
// suffix is a known decision code (rejected:duplicate → "与已有稳定记忆重复…").
export function reasonFromStatus(status: string) {
  const suffix = statusReason(status);
  if (!suffix) return "";
  return humanizeDecisionReason(suffix.replace(/\s+/g, "_")) || suffix;
}

export type DreamDecisionEntry = {
  id: string;
  decision: string;
  label: string;
  tone: "good" | "bad" | "warn" | "blue" | "neutral";
  reason: string;
  pageTitle?: string;
};

// Unified, human-readable log of why each candidate was promoted or rejected in
// the latest Dream run — the "为什么融入/为什么拒绝" view.
export function dreamDecisionLog(status: DreamStatusResult | null): DreamDecisionEntry[] {
  const results = normalizeDreamReviewResults(status?.latest?.execution?.review_results);
  return results.map((r) => {
    const audit = auditResultFromDreamReview(r);
    return {
      id: compactId(r.candidate_id || r.page_id || r.action_id || ""),
      decision: String(r.decision || r.status || ""),
      label: audit.label,
      tone: audit.tone,
      reason: humanizeDecisionReason(r.reason) || audit.detail,
      pageTitle: r.page_title
    };
  });
}

// ─── Dream report summaries ──────────────────────────────────────────────────

export function latestDreamDurationS(status: DreamStatusResult | null) {
  const v = status?.latest?.duration_s;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function dreamBacklogParts(status: DreamStatusResult | null): Array<{ label: string; count: number }> {
  const backlog = status?.backlog && typeof status.backlog === "object" ? (status.backlog as Record<string, unknown>) : {};
  const mapping: Array<[string, string]> = [
    ["draft_candidates", "候选"],
    ["memory_candidates", "候选"],
    ["w0_pending", "笔记"],
    ["changed_pages", "变更页"],
    ["review_cards", "复核"],
    ["tombstones", "墓碑"]
  ];
  const seen = new Set<string>();
  const parts: Array<{ label: string; count: number }> = [];
  for (const [key, label] of mapping) {
    if (seen.has(label)) continue;
    const count = Number(backlog[key] ?? 0);
    if (Number.isFinite(count) && count > 0) {
      parts.push({ label, count });
      seen.add(label);
    }
  }
  return parts;
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

export function isPendingPlanProposal(proposal: PlanProposal) {
  const status = String(proposal.proposal_status || "pending").toLowerCase();
  return status === "pending";
}

export function planItemTime(item: PlanItem) {
  return item.updated_at || item.created_at || 0;
}

export function planProposalTime(proposal: PlanProposal) {
  return proposal.decided_at || proposal.created_at || 0;
}

export function uidFromScope(scope: string) {
  const clean = (scope || "").trim();
  return clean.toLowerCase().startsWith("user:") ? clean.slice("user:".length) : "";
}

export function buildPlanUserGroups(
  items: PlanItem[],
  proposals: PlanProposal[],
  uidFilter: string
): PlanUserGroup[] {
  const groups = new Map<string, PlanUserGroup>();
  const ensureGroup = (rawScope: string): PlanUserGroup => {
    const scope = (rawScope || "global").trim() || "global";
    const existing = groups.get(scope);
    if (existing) return existing;
    const uid = uidFromScope(scope);
    const group: PlanUserGroup = {
      key: scope,
      uid,
      scope,
      label: uid || (scope === "global" ? "全局" : scope),
      items: [],
      proposals: [],
      openCount: 0,
      pendingCount: 0,
      latestAt: 0
    };
    groups.set(scope, group);
    return group;
  };

  const filteredUid = uidFilter.trim();
  if (filteredUid) {
    ensureGroup(scopeFromUidFilter(filteredUid));
  }
  for (const item of items) {
    ensureGroup(String(item.scope || "global")).items.push(item);
  }
  for (const proposal of proposals) {
    ensureGroup(String(proposal.scope || "global")).proposals.push(proposal);
  }
  if (groups.size === 0) {
    ensureGroup("global");
  }

  return [...groups.values()]
    .map((group) => {
      const sortedItems = [...group.items].sort((left, right) => planItemTime(right) - planItemTime(left));
      const sortedProposals = [...group.proposals].sort((left, right) => planProposalTime(right) - planProposalTime(left));
      return {
        ...group,
        items: sortedItems,
        proposals: sortedProposals,
        openCount: sortedItems.filter((item) => !isClosedPlan(item)).length,
        pendingCount: sortedProposals.filter((proposal) => isPendingPlanProposal(proposal)).length,
        latestAt: Math.max(...sortedItems.map(planItemTime), ...sortedProposals.map(planProposalTime), 0)
      };
    })
    .sort((left, right) => right.latestAt - left.latestAt);
}
