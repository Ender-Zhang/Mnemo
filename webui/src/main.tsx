import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Archive,
  Brain,
  Check,
  ChevronRight,
  ClipboardList,
  Database,
  FileClock,
  Gauge,
  Home,
  Link2,
  ListTodo,
  Loader2,
  Lock,
  Play,
  Plus,
  RefreshCcw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { filterCandidateReviewItems, filterReviewableCandidates, isReviewableCandidate } from "./candidateFilters";
import {
  autoDreamFormFromStatus,
  autoDreamSavePayload,
  autoDreamStatusText,
  emptyAutoDreamForm,
  emptyProviderForm,
  providerFormFromConfig,
  providerSavePayload,
  providerStatusText
} from "./providerSettings";
import { promotionReviewMessage } from "./promotionMessages";
import "./styles.css";
import type { AutoDreamFormState, AutoDreamStatusResult, ProviderConfigResult, ProviderFormState } from "./providerSettings";
import type { PromotionReviewResult } from "./promotionMessages";

type ApiEnvelope<T> = {
  method?: string;
  result?: T;
  error?: string;
};

type MemoryItem = {
  id: string;
  type: "candidate" | "page";
  status?: string;
  claim?: string;
  title?: string;
  content?: string;
  scope?: string;
  confidence?: number;
  dimension?: string;
  run_id?: string;
  source_candidate_id?: string;
  created_at?: number;
  updated_at?: number;
  evidence?: unknown[];
  metadata?: Record<string, unknown>;
};

type MemoryListResult = {
  kind: "memory_list";
  count: number;
  uid?: string | null;
  items: MemoryItem[];
};

type MemorySearchResult = {
  kind: "memory_search";
  matches?: Array<Record<string, unknown>>;
};

type MemoryReadResult = {
  kind: "memory_item";
  type: "candidate" | "page";
  item: MemoryItem;
};

type MemoryLinksResult = {
  outgoing?: Array<Record<string, unknown>>;
  incoming?: Array<Record<string, unknown>>;
};

type MemoryEvent = {
  id: string;
  event_at?: number;
  observed_at?: number;
  source?: string;
  agent_id?: string;
  run_id?: string;
  mission_id?: string;
  conversation_id?: string;
  message_id?: string;
  actor?: string;
  excerpt?: string;
  raw_hash?: string;
};

type MemoryProvenanceResult = {
  kind: "memory_provenance";
  memory_id: string;
  memory_type: "candidate" | "page";
  page?: MemoryItem | null;
  candidates?: MemoryItem[];
  events?: MemoryEvent[];
};

type MemoryHealthResult = {
  kind?: string;
  summary?: Record<string, unknown>;
  cards?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

type DreamStatusResult = {
  kind?: string;
  latest?: DreamReportSummary | null;
  latest_report?: Record<string, unknown> | null;
  backlog?: Record<string, unknown>;
  [key: string]: unknown;
};

type DreamRejectReason = {
  action_id?: string;
  candidate_id?: string;
  page_id?: string;
  page_title?: string;
  page_action?: string;
  tool?: string;
  status?: string;
  decision?: string;
  reason?: string;
  gate_reason?: string;
};

type DreamReviewResult = DreamRejectReason;

type DreamReportSummary = {
  duration_s?: number;
  execution?: {
    review_results?: DreamReviewResult[];
    reject_reasons?: DreamRejectReason[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

type DreamRunReport = {
  id?: string;
  duration_s?: number;
  delta?: {
    counts?: Record<string, number>;
  };
  execution?: {
    mode?: string;
    result?: {
      actions?: {
        counts?: {
          requested?: number;
          applied?: number;
          skipped?: number;
        };
        applied?: DreamRejectReason[];
        skipped?: DreamRejectReason[];
        proposals?: DreamProposal[];
      };
    };
  };
};

type DreamProposal = {
  id: string;
  report_id?: string | null;
  tool: string;
  title: string;
  rationale?: string;
  risk?: string;
  status: "pending" | "applied" | "rejected" | string;
  action?: Record<string, unknown>;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  decision?: Record<string, unknown>;
  created_at?: number;
  decided_at?: number;
};

type DreamProposalsResult = {
  kind: "dream_proposals";
  status?: string | null;
  count: number;
  proposals: DreamProposal[];
};

type SnapshotResult = {
  kind?: string;
  exists?: boolean;
  snapshot?: Record<string, unknown> | null;
};

type MemoryTombstone = {
  id: string;
  target_id: string;
  target_type: "candidate" | "page";
  target_hash?: string;
  reason?: string;
  summary?: string;
  evidence_run_id?: string;
  rule?: string;
  metadata?: Record<string, unknown>;
  created_at?: number;
};

type TombstonesResult = {
  tombstones?: MemoryTombstone[];
};

type PlanItem = {
  id: string;
  kind: "goal" | "todo" | string;
  parent_id?: string | null;
  title: string;
  detail?: string;
  scope?: string;
  status?: string;
  priority?: "low" | "normal" | "high" | string;
  due_at?: number | null;
  source?: string;
  source_event_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: number;
  updated_at?: number;
  completed_at?: number | null;
};

type PlanListResult = {
  kind: "plan_item_list";
  count: number;
  items: PlanItem[];
};

type PlanProposal = {
  id: string;
  kind: "goal" | "todo" | string;
  action?: string;
  target_id?: string | null;
  parent_id?: string | null;
  title: string;
  detail?: string;
  scope?: string;
  status?: string | null;
  priority?: string;
  due_at?: number | null;
  confidence?: number;
  reason?: string;
  source?: string;
  source_event_id?: string | null;
  metadata?: Record<string, unknown>;
  proposal_status?: "pending" | "accepted" | "rejected" | string;
  created_at?: number;
  decided_at?: number | null;
  decision_reason?: string | null;
};

type PlanProposalsResult = {
  kind: "plan_proposals";
  count: number;
  proposals: PlanProposal[];
};

type PlanFormState = {
  kind: "goal" | "todo";
  title: string;
  detail: string;
  parentId: string;
  priority: "low" | "normal" | "high";
  dueAt: string;
};

type TabKey = "overview" | "memories" | "plans" | "candidates" | "tombstones" | "maintenance" | "settings";

type Notice = {
  tone: "ok" | "warn" | "error";
  text: string;
};

const navItems: Array<{ key: TabKey; label: string; icon: LucideIcon }> = [
  { key: "memories", label: "记忆工作台", icon: Home },
  { key: "plans", label: "计划", icon: ListTodo },
  { key: "maintenance", label: "模型与维护", icon: Activity },
  { key: "settings", label: "设置", icon: Settings },
  { key: "candidates", label: "候选审核", icon: ClipboardList },
  { key: "tombstones", label: "墓碑 / 删除", icon: Archive }
];

const defaultNavKeys = new Set<TabKey>(["memories", "plans", "maintenance", "settings"]);
const advancedNavKeys = new Set<TabKey>(["memories", "plans", "maintenance", "settings", "candidates", "tombstones"]);

const defaultApiBase = window.location.origin;

function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("memories");
  const [apiBase, setApiBase] = useState(() => localStorage.getItem("mnemo.apiBase") || defaultApiBase);
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("mnemo.authToken") || "");
  const [serviceOk, setServiceOk] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [advancedMode, setAdvancedMode] = useState(() => localStorage.getItem("mnemo.advancedMode") === "true");
  const [composerOpen, setComposerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [uidFilter, setUidFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [kindFilter, setKindFilter] = useState<"all" | "candidate" | "page">("page");
  const [searchMode, setSearchMode] = useState(false);
  const [inventory, setInventory] = useState<MemoryItem[]>([]);
  const [searchItems, setSearchItems] = useState<MemoryItem[]>([]);
  const [candidates, setCandidates] = useState<MemoryItem[]>([]);
  const [selected, setSelected] = useState<MemoryItem | null>(null);
  const [links, setLinks] = useState<MemoryLinksResult | null>(null);
  const [provenance, setProvenance] = useState<MemoryProvenanceResult | null>(null);
  const [health, setHealth] = useState<MemoryHealthResult | null>(null);
  const [dreamStatus, setDreamStatus] = useState<DreamStatusResult | null>(null);
  const [snapshot, setSnapshot] = useState<SnapshotResult | null>(null);
  const [tombstones, setTombstones] = useState<MemoryTombstone[]>([]);
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);
  const [planProposals, setPlanProposals] = useState<PlanProposal[]>([]);
  const [planForm, setPlanForm] = useState<PlanFormState>(() => emptyPlanForm());
  const [planRejectReason, setPlanRejectReason] = useState("operator_rejected");
  const [selectedTombstoneIds, setSelectedTombstoneIds] = useState<Set<string>>(() => new Set());
  const [factText, setFactText] = useState("");
  const [observationText, setObservationText] = useState("");
  const [source, setSource] = useState("webui");
  const [useProvider, setUseProvider] = useState(() => localStorage.getItem("mnemo.useProvider") === "true");
  const [advancedDreaming, setAdvancedDreaming] = useState(() => localStorage.getItem("mnemo.advancedDreaming") === "true");
  const [providerConfig, setProviderConfig] = useState<ProviderConfigResult | null>(null);
  const [providerForm, setProviderForm] = useState<ProviderFormState>(() => emptyProviderForm());
  const [autoDreamStatus, setAutoDreamStatus] = useState<AutoDreamStatusResult | null>(null);
  const [autoDreamForm, setAutoDreamForm] = useState<AutoDreamFormState>(() => emptyAutoDreamForm());
  const [rejectReason, setRejectReason] = useState("not_useful");
  const [proposalRejectReason, setProposalRejectReason] = useState("operator_rejected");
  const [tombstoneReason, setTombstoneReason] = useState("manual_curation");
  const [dreamStartedAtMs, setDreamStartedAtMs] = useState<number | null>(null);
  const [clockNowMs, setClockNowMs] = useState(() => Date.now());

  const authed = authToken.trim().length > 0;
  const activeItems = useMemo(() => {
    if (searchMode) return searchItems;
    return [...inventory].sort(compareMemoryItems);
  }, [inventory, searchItems, searchMode]);
  const pendingCandidates = useMemo(() => filterReviewableCandidates(candidates), [candidates]);
  const candidateReviewItems = useMemo(() => filterCandidateReviewItems(candidates), [candidates]);
  const healthCards = Array.isArray(health?.cards) ? health.cards : [];
  const [dreamProposals, setDreamProposals] = useState<DreamProposal[]>([]);
  const dreamElapsedS = dreamStartedAtMs === null ? null : Math.max(0, (clockNowMs - dreamStartedAtMs) / 1000);
  const visibleNavItems = useMemo(
    () => navItems.filter((item, index, items) => items.findIndex((candidate) => candidate.key === item.key) === index)
      .filter((item) => (advancedMode ? advancedNavKeys : defaultNavKeys).has(item.key)),
    [advancedMode]
  );

  const requestJson = useCallback(
    async <T,>(path: string, options: RequestInit = {}) => {
      const headers = new Headers(options.headers);
      headers.set("Accept", "application/json");
      if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }
      if (authToken.trim()) {
        headers.set("Authorization", `Bearer ${authToken.trim()}`);
      }
      const response = await fetch(`${apiBase.replace(/\/$/, "")}${path}`, { ...options, headers });
      const payload = (await response.json()) as ApiEnvelope<T> | T;
      if (!response.ok) {
        const error = typeof (payload as ApiEnvelope<T>).error === "string" ? (payload as ApiEnvelope<T>).error : response.statusText;
        throw new Error(error || `HTTP ${response.status}`);
      }
      if (payload && typeof payload === "object" && "result" in payload) {
        return (payload as ApiEnvelope<T>).result as T;
      }
      return payload as T;
    },
    [apiBase, authToken]
  );

  const callMemory = useCallback(
    <T,>(method: string, body: Record<string, unknown> = {}) =>
      requestJson<T>(`/api/memory/${method}`, {
        method: "POST",
        body: JSON.stringify(body)
      }),
    [requestJson]
  );

  const setOk = (text: string) => setNotice({ tone: "ok", text });
  const setWarn = (text: string) => setNotice({ tone: "warn", text });
  const setError = (error: unknown) => {
    const text = error instanceof Error ? error.message : String(error);
    setNotice({ tone: "error", text });
  };

  const refresh = useCallback(async (options: { clearNotice?: boolean } = {}) => {
    setLoading(true);
    try {
      const scopedUid = uidFilter.trim() || undefined;
      const [
        healthResult,
        inventoryResult,
        candidateResult,
        dreamResult,
        snapshotResult,
        tombstoneResult,
        providerResult,
        autoDreamResult,
        proposalResult,
        planResult,
        planProposalResult
      ] = await Promise.all([
        requestJson<Record<string, unknown>>("/api/health"),
        callMemory<MemoryListResult>("list", { kind: kindFilter, status: statusFilter || null, uid: scopedUid, limit: 50 }),
        callMemory<MemoryListResult>("list", { kind: "candidate", status: null, uid: scopedUid, limit: 50 }),
        callMemory<DreamStatusResult>("dream-status", { limit: 20 }),
        callMemory<SnapshotResult>("snapshot", { limit: 50 }),
        callMemory<TombstonesResult>("tombstones", { limit: 500 }),
        callMemory<ProviderConfigResult>("provider-config", {}),
        callMemory<AutoDreamStatusResult>("auto-dream-status", {}),
        callMemory<DreamProposalsResult>("dream-proposals", { status: null, limit: 50 }),
        callMemory<PlanListResult>("plan-list", { uid: scopedUid, include_archived: false, limit: 100 }),
        callMemory<PlanProposalsResult>("plan-proposals", { status: "pending", uid: scopedUid, limit: 50 })
      ]);
      setServiceOk(Boolean(healthResult.ok));
      setInventory(inventoryResult.items || []);
      setCandidates(candidateResult.items || []);
      setDreamStatus(dreamResult);
      setSnapshot(snapshotResult);
      setTombstones(tombstoneResult.tombstones || []);
      setProviderConfig(providerResult);
      setProviderForm(providerFormFromConfig(providerResult));
      setAutoDreamStatus(autoDreamResult);
      setAutoDreamForm(autoDreamFormFromStatus(autoDreamResult));
      setDreamProposals(proposalResult.proposals || []);
      setPlanItems(planResult.items || []);
      setPlanProposals(planProposalResult.proposals || []);
      try {
        setHealth(await callMemory<MemoryHealthResult>("health", { limit: 20 }));
      } catch {
        setHealth(null);
      }
      if (options.clearNotice !== false) {
        setNotice(null);
      }
    } catch (error) {
      setServiceOk(false);
      setError(error);
    } finally {
      setLoading(false);
    }
  }, [callMemory, kindFilter, requestJson, statusFilter, uidFilter]);

  const refreshInventory = useCallback(async (options: { clearNotice?: boolean } = {}) => {
    setSearchItems([]);
    setSearchMode(false);
    await refresh(options);
  }, [refresh]);

  useEffect(() => {
    localStorage.setItem("mnemo.apiBase", apiBase);
  }, [apiBase]);

  useEffect(() => {
    if (authToken.trim()) {
      localStorage.setItem("mnemo.authToken", authToken);
    } else {
      localStorage.removeItem("mnemo.authToken");
    }
  }, [authToken]);

  useEffect(() => {
    localStorage.setItem("mnemo.useProvider", useProvider ? "true" : "false");
  }, [useProvider]);

  useEffect(() => {
    localStorage.setItem("mnemo.advancedDreaming", advancedDreaming ? "true" : "false");
  }, [advancedDreaming]);

  useEffect(() => {
    localStorage.setItem("mnemo.advancedMode", advancedMode ? "true" : "false");
  }, [advancedMode]);

  useEffect(() => {
    const allowedTabs = advancedMode ? advancedNavKeys : defaultNavKeys;
    if (!allowedTabs.has(activeTab)) {
      setActiveTab("memories");
    }
  }, [activeTab, advancedMode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (dreamStartedAtMs === null) return undefined;
    setClockNowMs(Date.now());
    const timerId = window.setInterval(() => setClockNowMs(Date.now()), 500);
    return () => window.clearInterval(timerId);
  }, [dreamStartedAtMs]);

  useEffect(() => {
    if (activeTab !== "memories" && activeTab !== "overview") {
      return;
    }
    if (activeItems.length === 0) {
      if (selected) {
        setSelected(null);
      }
      return;
    }
    const selectedStillVisible = selected ? activeItems.some((item) => item.id === selected.id && item.type === selected.type) : false;
    if (!selectedStillVisible) {
      setSelected(activeItems[0]);
    }
  }, [activeItems, activeTab, selected]);

  useEffect(() => {
    const visibleIds = new Set(tombstones.map((tombstone) => tombstone.id));
    setSelectedTombstoneIds((previous) => {
      const next = new Set([...previous].filter((id) => visibleIds.has(id)));
      return next.size === previous.size ? previous : next;
    });
  }, [tombstones]);

  const searchMemory = async () => {
    const cleanQuery = query.trim();
    const cleanUid = uidFilter.trim();
    if (!cleanQuery && !cleanUid) {
      await refreshInventory();
      return;
    }
    if (cleanUid && !cleanQuery) {
      await refreshInventory({ clearNotice: false });
      setOk(`UID 过滤已应用：${cleanUid}`);
      return;
    }
    setLoading(true);
    try {
      if (cleanUid) {
        const result = await callMemory<MemoryListResult>("list", {
          kind: kindFilter,
          status: statusFilter || null,
          uid: cleanUid,
          limit: 50
        });
        const mapped = (result.items || []).filter((item) => itemMatchesQuery(item, cleanQuery));
        setSearchMode(true);
        setSearchItems(mapped);
        setSelected(mapped[0] || null);
        setOk(`UID 检索完成：${mapped.length} 条结果`);
        return;
      }
      const result = await callMemory<MemorySearchResult>("search", {
        query: cleanQuery,
        scope: "memory",
        limit: 30
      });
      const mapped = (result.matches || [])
        .map(searchMatchToItem)
        .filter((item): item is MemoryItem => Boolean(item))
        .filter((item) => kindFilter === "all" || item.type === kindFilter)
        .filter((item) => !statusFilter || item.status === statusFilter);
      setSearchMode(true);
      setSearchItems(mapped);
      setSelected(mapped[0] || null);
      setOk(`搜索完成：${mapped.length} 条结果`);
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const readMemory = async (item: MemoryItem) => {
    setSelected(item);
    setLinks(null);
    setProvenance(null);
    try {
      const [readResult, linkResult, provenanceResult] = await Promise.all([
        callMemory<MemoryReadResult>("read", { memory_id: item.id }),
        callMemory<MemoryLinksResult>("links", { memory_id: item.id }),
        callMemory<MemoryProvenanceResult>("provenance", { memory_id: item.id })
      ]);
      setSelected({ ...readResult.item, type: readResult.type });
      setLinks(linkResult);
      setProvenance(provenanceResult);
    } catch (error) {
      setError(error);
    }
  };

  const submitMemory = async () => {
    const writeScope = scopeFromUidFilter(uidFilter);
    const facts = factText.trim() ? [memoryFactPayload(factText.trim(), writeScope)] : [];
    const observations = observationText.trim() ? [memoryObservationPayload(observationText.trim(), writeScope)] : [];
    if (facts.length === 0 && observations.length === 0) {
      setNotice({ tone: "warn", text: "请输入 fact 或 observation" });
      return;
    }
    setLoading(true);
    try {
      await callMemory("update", { facts, observations, source: source.trim() || "webui" });
      setFactText("");
      setObservationText("");
      setComposerOpen(false);
      setOk("已写入候选记忆");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const promoteCandidate = async (candidateId: string) => {
    setLoading(true);
    try {
      const result = await callMemory<PromotionReviewResult>("promote-candidate", { candidate_id: candidateId, min_confidence: 0.7 });
      const message = promotionReviewMessage(result);
      if (result.decision === "promoted" || result.status === "promoted") {
        setOk(message);
      } else {
        setWarn(message);
      }
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const rejectCandidate = async (candidateId: string) => {
    setLoading(true);
    try {
      await callMemory("reject-candidate", { candidate_id: candidateId, reason: rejectReason.trim() || "not_useful" });
      setOk("候选已拒绝");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const curateSelected = async (mode: "tombstone" | "forget") => {
    if (!selected) return;
    setLoading(true);
    try {
      if (mode === "forget") {
        await callMemory("forget", { memory_id: selected.id, target_type: selected.type, reason: "private_delete" });
        setOk("记忆已私密删除");
      } else {
        await callMemory("tombstone", {
          memory_id: selected.id,
          target_type: selected.type,
          reason: tombstoneReason.trim() || "manual_curation"
        });
        setOk("记忆已标记 tombstone");
      }
      setSelected(null);
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const forgetTombstoneTarget = async (tombstone: MemoryTombstone) => {
    setLoading(true);
    try {
      await callMemory("forget", {
        memory_id: tombstone.target_id,
        target_type: tombstone.target_type,
        reason: "private_delete"
      });
      setOk("目标记忆已 Forget 擦除，删除痕迹仍会保留");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const hardDeleteTombstoneTarget = async (tombstone: MemoryTombstone) => {
    const confirmed = window.confirm(`彻底删除 ${tombstone.target_type}:${tombstone.target_id} 及相关 tombstone/link/wiki 记录？`);
    if (!confirmed) return;
    setLoading(true);
    try {
      await callMemory("hard-delete", {
        tombstone_id: tombstone.id,
        memory_id: tombstone.target_id,
        target_type: tombstone.target_type,
        delete_related: true
      });
      setSelected(null);
      setOk("目标记忆和相关 tombstone 记录已彻底删除");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const toggleTombstoneSelection = (tombstoneId: string, selected: boolean) => {
    setSelectedTombstoneIds((previous) => {
      const next = new Set(previous);
      if (selected) {
        next.add(tombstoneId);
      } else {
        next.delete(tombstoneId);
      }
      return next;
    });
  };

  const toggleAllTombstones = (selected: boolean) => {
    setSelectedTombstoneIds(selected ? new Set(tombstones.map((tombstone) => tombstone.id)) : new Set());
  };

  const hardDeleteSelectedTombstones = async () => {
    const selectedTombstones = tombstones.filter((tombstone) => selectedTombstoneIds.has(tombstone.id));
    if (selectedTombstones.length === 0) {
      setWarn("请先选择要彻底删除的 tombstone");
      return;
    }
    const confirmed = window.confirm(`彻底删除选中的 ${selectedTombstones.length} 条 tombstone 及相关记忆/link/wiki 记录？`);
    if (!confirmed) return;
    setLoading(true);
    let deletedCount = 0;
    let skippedCount = 0;
    const failures: string[] = [];
    try {
      for (const tombstone of selectedTombstones) {
        try {
          await callMemory("hard-delete", {
            tombstone_id: tombstone.id,
            memory_id: tombstone.target_id,
            target_type: tombstone.target_type,
            delete_related: true
          });
          deletedCount += 1;
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          if (message.includes("not found")) {
            skippedCount += 1;
          } else {
            failures.push(`${compactId(tombstone.id) || tombstone.id}: ${message}`);
          }
        }
      }
      setSelected(null);
      setSelectedTombstoneIds(new Set());
      await refresh({ clearNotice: false });
      if (failures.length > 0) {
        setWarn(`已彻底删除 ${deletedCount} 条，跳过 ${skippedCount} 条，失败 ${failures.length} 条：${failures.slice(0, 2).join("；")}`);
      } else {
        setOk(`已彻底删除 ${deletedCount} 条 tombstone${skippedCount ? `，跳过 ${skippedCount} 条已删除项` : ""}`);
      }
    } finally {
      setLoading(false);
    }
  };

  const runDream = async () => {
    setLoading(true);
    setDreamStartedAtMs(Date.now());
    try {
      const report = await callMemory<DreamRunReport>("dream-run", {
        limit: 20,
        min_confidence: 0.7,
        use_provider: useProvider,
        advanced_dreaming: advancedDreaming,
        execution_policy: "semi_auto"
      });
      await refresh({ clearNotice: false });
      setOk(dreamRunMessage(report, useProvider, advancedDreaming));
    } catch (error) {
      setError(error);
    } finally {
      setDreamStartedAtMs(null);
      setLoading(false);
    }
  };

  const applyDreamProposal = async (proposalId: string) => {
    setLoading(true);
    try {
      await callMemory("apply-dream-proposal", { proposal_id: proposalId });
      setOk("整理提案已应用");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const rejectDreamProposal = async (proposalId: string) => {
    setLoading(true);
    try {
      await callMemory("reject-dream-proposal", {
        proposal_id: proposalId,
        reason: proposalRejectReason.trim() || "operator_rejected"
      });
      setOk("整理提案已拒绝");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const createPlanItem = async () => {
    const title = planForm.title.trim();
    if (!title) {
      setWarn("请输入计划标题");
      return;
    }
    setLoading(true);
    try {
      await callMemory("plan-create", {
        kind: planForm.kind,
        title,
        detail: planForm.detail.trim(),
        parent_id: planForm.parentId.trim() || null,
        priority: planForm.priority,
        due_at: datetimeLocalToUnix(planForm.dueAt),
        uid: uidFilter.trim() || null,
        scope: uidFilter.trim() ? undefined : "global",
        source: source.trim() || "webui"
      });
      setPlanForm(emptyPlanForm());
      setOk("计划已创建");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const completePlanItem = async (planId: string) => {
    setLoading(true);
    try {
      await callMemory("plan-complete", { plan_id: planId });
      setOk("计划已完成");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const cancelPlanItem = async (planId: string) => {
    setLoading(true);
    try {
      await callMemory("plan-cancel", { plan_id: planId, reason: "cancelled_from_webui" });
      setOk("计划已取消");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const archivePlanItem = async (planId: string) => {
    setLoading(true);
    try {
      await callMemory("plan-archive", { plan_id: planId });
      setOk("计划已归档");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const applyPlanProposal = async (proposalId: string) => {
    setLoading(true);
    try {
      await callMemory("apply-plan-proposal", { proposal_id: proposalId });
      setOk("计划提案已接受");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const rejectPlanProposal = async (proposalId: string) => {
    setLoading(true);
    try {
      await callMemory("reject-plan-proposal", {
        proposal_id: proposalId,
        reason: planRejectReason.trim() || "operator_rejected"
      });
      setOk("计划提案已拒绝");
      await refresh({ clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const compileSnapshot = async () => {
    setLoading(true);
    try {
      const result = await callMemory<SnapshotResult>("snapshot", { compile: true, limit: 50 });
      setSnapshot(result);
      setOk("快照已刷新");
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const saveProviderConfig = async () => {
    setLoading(true);
    try {
      const result = await callMemory<ProviderConfigResult>("save-provider-config", providerSavePayload(providerForm));
      setProviderConfig(result);
      setProviderForm(providerFormFromConfig(result));
      setOk("Provider 配置已保存；Run Dream 将使用服务端配置。");
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const saveAutoDreamConfig = async () => {
    setLoading(true);
    try {
      const result = await callMemory<AutoDreamStatusResult>("save-auto-dream-config", autoDreamSavePayload(autoDreamForm));
      setAutoDreamStatus(result);
      setAutoDreamForm(autoDreamFormFromStatus(result));
      setOk("自动 Dreaming 配置已保存。");
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const summaryStats = useMemo(() => {
    const pages = inventory.filter((item) => item.type === "page").length;
    const draft = pendingCandidates.length;
    const active = inventory.filter((item) => item.status === "active").length;
    return [
      { label: "稳定记忆页", value: pages || active, icon: Database, tone: "blue" },
      { label: "待审候选", value: draft, icon: ClipboardList, tone: "green" },
      { label: "健康卡片", value: healthCards.length, icon: Gauge, tone: "amber" },
      { label: "Tombstones", value: tombstones.length, icon: Archive, tone: "red" }
    ];
  }, [healthCards.length, inventory, pendingCandidates.length, tombstones.length]);

  const navItemClass = (key: TabKey, extra = "") => {
    const classes = ["nav-item"];
    if (activeTab === key) classes.push("active");
    if (extra) classes.push(extra);
    return classes.join(" ");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">M</div>
          <div>
            <strong>Mnemo Memory</strong>
            <span>Local Console</span>
          </div>
        </div>
        <nav className="nav-list">
          {visibleNavItems.map((item) => (
            <button className={navItemClass(item.key)} key={item.key} onClick={() => setActiveTab(item.key)}>
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.key === "plans" && planProposals.length > 0 ? <b>{planProposals.length}</b> : null}
              {item.key === "candidates" && pendingCandidates.length > 0 ? <b>{pendingCandidates.length}</b> : null}
              {item.key === "tombstones" && tombstones.length > 0 ? <b>{tombstones.length}</b> : null}
            </button>
          ))}
        </nav>
        <div className="mode-card">
          <div>
            <strong>高级模式</strong>
            <span>{advancedMode ? "显示候选、Dream、墓碑和 JSON" : "默认隐藏调试和维护细节"}</span>
          </div>
          <label className="switch">
            <input type="checkbox" checked={advancedMode} onChange={(event) => setAdvancedMode(event.target.checked)} />
            <span />
          </label>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="status-row">
            <StatusDot ok={serviceOk} />
            <strong>Service:</strong>
            <span>{serviceOk ? "Running" : "Needs token / offline"}</span>
          </div>
          <div className="divider" />
          <div className="endpoint">HTTP: {apiBase}</div>
          <div className="divider" />
          <div className={authed ? "auth-pill ok" : "auth-pill"}>
            <Lock size={14} />
            {authed ? "Token 已设置" : "未设置 Token"}
          </div>
          <button className="ghost-button" onClick={() => refreshInventory()} disabled={loading}>
            {loading ? <Loader2 className="spin" size={16} /> : <RefreshCcw size={16} />}
            Refresh
          </button>
          <button className="primary-button" onClick={() => setComposerOpen(true)}>
            <Plus size={16} />
            保存记忆
          </button>
        </header>

        {notice ? (
          <div className={`notice ${notice.tone}`}>
            <span>{notice.text}</span>
            <button onClick={() => setNotice(null)}>
              <X size={14} />
            </button>
          </div>
        ) : null}

        <section className={advancedMode ? "dashboard-grid advanced-layout" : "dashboard-grid workbench-layout"}>
          <div className="main-column">
            {activeTab === "overview" ? <Overview stats={summaryStats} health={health} dreamStatus={dreamStatus} snapshot={snapshot} /> : null}
            {activeTab === "memories" || activeTab === "overview" ? (
              <SearchPanel
                query={query}
                setQuery={setQuery}
                uidFilter={uidFilter}
                setUidFilter={setUidFilter}
                kindFilter={kindFilter}
                setKindFilter={setKindFilter}
                statusFilter={statusFilter}
                setStatusFilter={setStatusFilter}
                onSearch={searchMemory}
                onRefresh={refreshInventory}
              />
            ) : null}
            {activeTab === "memories" || activeTab === "overview" ? (
              <MemoryTable items={activeItems} selectedId={selected?.id} uidFilter={uidFilter} dreamStatus={dreamStatus} advancedMode={advancedMode} onSelect={readMemory} />
            ) : null}
            {activeTab === "plans" ? (
              <PlanPanel
                items={planItems}
                proposals={planProposals}
                form={planForm}
                setForm={setPlanForm}
                rejectReason={planRejectReason}
                setRejectReason={setPlanRejectReason}
                uidFilter={uidFilter}
                loading={loading}
                onCreate={createPlanItem}
                onComplete={completePlanItem}
                onCancel={cancelPlanItem}
                onArchive={archivePlanItem}
                onApplyProposal={applyPlanProposal}
                onRejectProposal={rejectPlanProposal}
              />
            ) : null}
            {activeTab === "candidates" ? (
              <CandidateReview
                candidates={candidateReviewItems}
                dreamStatus={dreamStatus}
                rejectReason={rejectReason}
                setRejectReason={setRejectReason}
                onPromote={promoteCandidate}
                onReject={rejectCandidate}
                onSelect={readMemory}
              />
            ) : null}
            {activeTab === "tombstones" ? (
              <TombstonePanel
                tombstones={tombstones}
                selectedTombstoneIds={selectedTombstoneIds}
                loading={loading}
                onToggleSelection={toggleTombstoneSelection}
                onToggleAll={toggleAllTombstones}
                onSelectTarget={(item) => readMemory(item)}
                onForget={forgetTombstoneTarget}
                onHardDelete={hardDeleteTombstoneTarget}
                onHardDeleteSelected={hardDeleteSelectedTombstones}
              />
            ) : null}
            {activeTab === "maintenance" ? (
              <MaintenancePanel
                health={health}
                dreamStatus={dreamStatus}
                snapshot={snapshot}
                tombstones={tombstones}
                proposals={dreamProposals}
                useProvider={useProvider}
                advancedDreaming={advancedDreaming}
                advancedMode={advancedMode}
                loading={loading}
                dreamElapsedS={dreamElapsedS}
                proposalRejectReason={proposalRejectReason}
                setProposalRejectReason={setProposalRejectReason}
                onRunDream={runDream}
                onCompileSnapshot={compileSnapshot}
                onApplyProposal={applyDreamProposal}
                onRejectProposal={rejectDreamProposal}
              />
            ) : null}
            {activeTab === "settings" ? (
              <SettingsPanel
                apiBase={apiBase}
                setApiBase={setApiBase}
                authToken={authToken}
                setAuthToken={setAuthToken}
                source={source}
                setSource={setSource}
                useProvider={useProvider}
                setUseProvider={setUseProvider}
                advancedDreaming={advancedDreaming}
                setAdvancedDreaming={setAdvancedDreaming}
                providerConfig={providerConfig}
                providerForm={providerForm}
                setProviderForm={setProviderForm}
                autoDreamStatus={autoDreamStatus}
                autoDreamForm={autoDreamForm}
                setAutoDreamForm={setAutoDreamForm}
                onSaveProviderConfig={saveProviderConfig}
                onSaveAutoDreamConfig={saveAutoDreamConfig}
                loading={loading}
              />
            ) : null}
          </div>

          <aside className="detail-column">
            <MemoryDetail
              selected={selected}
              links={links}
              provenance={provenance}
              dreamStatus={dreamStatus}
              advancedMode={advancedMode}
              tombstoneReason={tombstoneReason}
              setTombstoneReason={setTombstoneReason}
              onTombstone={() => curateSelected("tombstone")}
              onForget={() => curateSelected("forget")}
            />
          </aside>

          {advancedMode ? <aside className="ops-column">
            <OperationsQueue
              candidates={pendingCandidates}
              dreamStatus={dreamStatus}
              snapshot={snapshot}
              useProvider={useProvider}
              loading={loading}
              dreamElapsedS={dreamElapsedS}
              onPromote={promoteCandidate}
              onReject={rejectCandidate}
              onRunDream={runDream}
            />
          </aside> : null}
        </section>
        <SaveMemoryDrawer
          open={composerOpen}
          factText={factText}
          setFactText={setFactText}
          observationText={observationText}
          setObservationText={setObservationText}
          source={source}
          setSource={setSource}
          uidFilter={uidFilter}
          loading={loading}
          onSubmit={submitMemory}
          onClose={() => setComposerOpen(false)}
        />
      </main>
    </div>
  );
}

function Overview({
  stats,
  health,
  dreamStatus,
  snapshot
}: {
  stats: Array<{ label: string; value: number; icon: LucideIcon; tone: string }>;
  health: MemoryHealthResult | null;
  dreamStatus: DreamStatusResult | null;
  snapshot: SnapshotResult | null;
}) {
  return (
    <section className="panel overview-panel">
      <div className="panel-header">
        <div>
          <h2>服务总览</h2>
          <p>当前记忆库存、候选审核和维护状态。</p>
        </div>
        <Brain size={22} />
      </div>
      <div className="stat-grid">
        {stats.map((stat) => (
          <div className={`stat ${stat.tone}`} key={stat.label}>
            <stat.icon size={20} />
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </div>
        ))}
      </div>
      <div className="overview-split">
        <JsonBlock title="Health" value={health || { status: "no health report" }} />
        <JsonBlock title="Dream Status" value={dreamStatus || { status: "not loaded" }} />
        <JsonBlock title="Snapshot" value={snapshot || { exists: false }} />
      </div>
    </section>
  );
}

function SearchPanel(props: {
  query: string;
  setQuery: (value: string) => void;
  uidFilter: string;
  setUidFilter: (value: string) => void;
  kindFilter: "all" | "candidate" | "page";
  setKindFilter: (value: "all" | "candidate" | "page") => void;
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  onSearch: () => void;
  onRefresh: () => void;
}) {
  return (
    <section className="panel search-panel">
      <div className="search-line">
        <div className="input-with-icon">
          <Search size={18} />
          <input value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="搜索记忆、偏好、事实..." />
        </div>
        <button className="primary-button" onClick={props.onSearch}>
          <Search size={16} />
          搜索
        </button>
        <button className="ghost-button" onClick={props.onRefresh}>
          <RefreshCcw size={16} />
          刷新
        </button>
      </div>
      <div className="filters">
        <label>
          类型
          <select value={props.kindFilter} onChange={(event) => props.setKindFilter(event.target.value as "all" | "candidate" | "page")}>
            <option value="all">全部</option>
            <option value="page">稳定记忆</option>
            <option value="candidate">候选</option>
          </select>
        </label>
        <label>
          状态
          <select value={props.statusFilter} onChange={(event) => props.setStatusFilter(event.target.value)}>
            <option value="">全部</option>
            <option value="active">active</option>
            <option value="draft">draft</option>
            <option value="promoted">promoted</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <label>
          UID
          <input value={props.uidFilter} onChange={(event) => props.setUidFilter(event.target.value)} placeholder="user_123 或 user:user_123" />
        </label>
      </div>
    </section>
  );
}

function MemoryTable({
  items,
  selectedId,
  uidFilter,
  dreamStatus,
  advancedMode,
  onSelect
}: {
  items: MemoryItem[];
  selectedId?: string;
  uidFilter: string;
  dreamStatus: DreamStatusResult | null;
  advancedMode: boolean;
  onSelect: (item: MemoryItem) => void;
}) {
  const reviewResults = dreamReviewResultMap(dreamStatus);
  const uidLabel = uidFilter.trim() ? `UID: ${uidFilter.trim()}` : "全部 scope";
  return (
    <section className="panel table-panel">
      <div className="panel-header compact">
        <h2>记忆库存</h2>
        <span>{items.length} items · {uidLabel}</span>
      </div>
      <div className={advancedMode ? "memory-table advanced" : "memory-table simple"}>
        <div className="table-head">
          <span>Score</span>
          <span>Memory</span>
          <span>Type</span>
          {advancedMode ? <span>审核结果</span> : null}
          <span>Status</span>
          <span>Time</span>
        </div>
        {items.length === 0 ? <EmptyState text="暂无记忆。先写入 fact 或 observation。" /> : null}
        {items.map((item) => (
          <button className={selectedId === item.id ? "table-row active" : "table-row"} key={`${item.type}:${item.id}`} onClick={() => onSelect(item)}>
            <span className="score">{formatConfidence(item.confidence)}</span>
            <span>
              <strong>{itemTitle(item)}</strong>
              <small>{item.scope || item.dimension || item.id}</small>
            </span>
            <StatusBadge text={item.type} />
            {advancedMode ? <AuditResultBadge item={item} review={reviewForItem(item, reviewResults)} /> : null}
            <StatusBadge text={item.status || "unknown"} />
            <span className="time">{formatTime(item.updated_at || item.created_at)}</span>
            <ChevronRight size={16} />
          </button>
        ))}
      </div>
    </section>
  );
}

function AuditResultBadge({ item, review }: { item: MemoryItem; review?: DreamReviewResult }) {
  const result = auditResultForItem(item, review);
  return (
    <span className={`audit-result ${result.tone}`} title={result.title}>
      <strong>{result.label}</strong>
      {result.detail ? <small>{result.detail}</small> : null}
    </span>
  );
}

function AuditDetail({ item, review }: { item: MemoryItem; review?: DreamReviewResult }) {
  const result = auditResultForItem(item, review);
  const reason = detailedAuditReason(item, review, result.detail);
  return (
    <div className={`audit-detail ${result.tone}`}>
      <span>审核结果</span>
      <strong>{result.label}</strong>
      <p>{reason}</p>
      {review?.gate_reason && review.gate_reason !== review.reason ? <small>规则门槛：{review.gate_reason}</small> : null}
    </div>
  );
}

function MemoryDetail(props: {
  selected: MemoryItem | null;
  links: MemoryLinksResult | null;
  provenance: MemoryProvenanceResult | null;
  dreamStatus: DreamStatusResult | null;
  advancedMode: boolean;
  tombstoneReason: string;
  setTombstoneReason: (value: string) => void;
  onTombstone: () => void;
  onForget: () => void;
}) {
  const item = props.selected;
  const review = item ? reviewForItem(item, dreamReviewResultMap(props.dreamStatus)) : undefined;
  return (
    <section className="panel detail-panel">
      <div className="panel-header compact">
        <h2>记忆详情</h2>
        {item ? <StatusBadge text={item.status || item.type} /> : null}
      </div>
      {!item ? (
        <EmptyState text="选择一条记忆查看详情。" />
      ) : (
        <>
          <div className="detail-id">
            <span>Memory ID</span>
            <code>{item.id}</code>
          </div>
          <div className="detail-grid">
            <label>类型</label>
            <strong>{item.type}</strong>
            <label>状态</label>
            <strong>{item.status || "-"}</strong>
            <label>范围</label>
            <strong>{item.scope || "-"}</strong>
            <label>置信度</label>
            <strong>{formatConfidence(item.confidence)}</strong>
            <label>更新时间</label>
            <strong>{formatDate(item.updated_at || item.created_at)}</strong>
          </div>
          <div className="content-box">{item.content || item.claim || item.title || "-"}</div>
          <ProvenanceTimeline provenance={props.provenance} />
          <div className="detail-actions">
            <button className="ghost-button" onClick={() => navigator.clipboard?.writeText(item.content || item.claim || item.title || item.id)}>
              <ClipboardList size={15} />
              复制内容
            </button>
          </div>
          {props.advancedMode ? (
            <>
              <AuditDetail item={item} review={review} />
              <SourceIds item={item} />
              <JsonBlock title="Metadata / Evidence" value={item.metadata || item.evidence || {}} />
              <JsonBlock title="Links" value={props.links || { outgoing: [], incoming: [] }} />
              <div className="danger-actions">
                <input value={props.tombstoneReason} onChange={(event) => props.setTombstoneReason(event.target.value)} placeholder="tombstone reason" />
                <button className="danger-button" onClick={props.onTombstone}>
                  <Archive size={15} />
                  Tombstone
                </button>
                <button className="danger-button" onClick={props.onForget}>
                  <Trash2 size={15} />
                  Forget 擦除
                </button>
              </div>
            </>
          ) : null}
        </>
      )}
    </section>
  );
}

function SourceIds({ item }: { item: MemoryItem }) {
  const ids = [
    ["run_id", item.run_id],
    ["source_candidate_id", item.source_candidate_id]
  ].filter(([, value]) => Boolean(value));
  if (ids.length === 0) return null;
  return (
    <div className="source-ids">
      {ids.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <code>{value}</code>
        </div>
      ))}
    </div>
  );
}

function ProvenanceTimeline({ provenance }: { provenance: MemoryProvenanceResult | null }) {
  const events = provenance?.events || [];
  const candidates = provenance?.candidates || [];
  return (
    <div className="provenance-timeline">
      <div className="timeline-header">
        <h3>来源时间线</h3>
        <span>{events.length} events · {candidates.length} candidates</span>
      </div>
      {events.length === 0 && candidates.length === 0 ? (
        <div className="timeline-empty">暂无来源事件。旧记忆可能只有 Metadata / Evidence。</div>
      ) : null}
      {events.map((event) => (
        <div className="timeline-step" key={event.id}>
          <span className="timeline-kind">事件</span>
          <div>
            <strong>{event.excerpt || event.id}</strong>
            <small>
              {event.source || "unknown"} · 发生 {formatDate(event.event_at)} · 记录 {formatDate(event.observed_at)}
            </small>
            <code>{event.message_id || event.run_id || compactId(event.raw_hash) || event.id}</code>
          </div>
        </div>
      ))}
      {candidates.map((candidate) => (
        <div className="timeline-step" key={candidate.id}>
          <span className="timeline-kind">候选</span>
          <div>
            <strong>{candidate.claim || candidate.title || candidate.id}</strong>
            <small>{candidate.status || "unknown"} · {formatDate(candidate.created_at)}</small>
            <code>{candidate.id}</code>
          </div>
        </div>
      ))}
      {provenance?.page ? (
        <div className="timeline-step">
          <span className="timeline-kind">稳定</span>
          <div>
            <strong>{provenance.page.title || provenance.page.id}</strong>
            <small>{provenance.page.status || "active"} · {formatDate(provenance.page.updated_at || provenance.page.created_at)}</small>
            <code>{provenance.page.id}</code>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SaveMemoryDrawer(props: {
  open: boolean;
  factText: string;
  setFactText: (value: string) => void;
  observationText: string;
  setObservationText: (value: string) => void;
  source: string;
  setSource: (value: string) => void;
  uidFilter: string;
  loading: boolean;
  onSubmit: () => void;
  onClose: () => void;
}) {
  if (!props.open) return null;
  return (
    <div className="drawer-layer" role="dialog" aria-modal="true" aria-label="保存记忆">
      <button className="drawer-backdrop" aria-label="关闭保存记忆" onClick={props.onClose} />
      <aside className="memory-drawer">
        <div className="drawer-header">
          <div>
            <h2>保存记忆</h2>
            <p>写入后会先生成候选记忆，后续由模型审核或高级模式操作进入稳定记忆。</p>
          </div>
          <button className="ghost-button icon-only" onClick={props.onClose}>
            <X size={16} />
          </button>
        </div>
        <Composer
          factText={props.factText}
          setFactText={props.setFactText}
          observationText={props.observationText}
          setObservationText={props.setObservationText}
          source={props.source}
          setSource={props.setSource}
          uidFilter={props.uidFilter}
          loading={props.loading}
          onSubmit={props.onSubmit}
        />
      </aside>
    </div>
  );
}

function Composer(props: {
  factText: string;
  setFactText: (value: string) => void;
  observationText: string;
  setObservationText: (value: string) => void;
  source: string;
  setSource: (value: string) => void;
  uidFilter: string;
  loading?: boolean;
  onSubmit: () => void;
}) {
  const writeScope = scopeFromUidFilter(props.uidFilter) || "global";
  return (
    <section className="panel composer">
      <div className="panel-header compact">
        <h2>写入记忆</h2>
        <StatusBadge text={writeScope} />
      </div>
      <label>
        Fact
        <textarea value={props.factText} onChange={(event) => props.setFactText(event.target.value)} placeholder="例如：用户偏好简洁的实现进度更新。" />
      </label>
      <label>
        Observation
        <textarea
          value={props.observationText}
          onChange={(event) => props.setObservationText(event.target.value)}
          placeholder="例如：本次任务需要保留 WebUI 构建产物。"
        />
      </label>
      <div className="composer-row">
        <input value={props.source} onChange={(event) => props.setSource(event.target.value)} placeholder="source" />
        <button className="primary-button" onClick={props.onSubmit} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
          Add Memory
        </button>
      </div>
    </section>
  );
}

function CandidateReview(props: {
  candidates: MemoryItem[];
  dreamStatus: DreamStatusResult | null;
  rejectReason: string;
  setRejectReason: (value: string) => void;
  onPromote: (id: string) => void;
  onReject: (id: string) => void;
  onSelect: (item: MemoryItem) => void;
}) {
  const reviewResults = dreamReviewResultMap(props.dreamStatus);
  return (
    <section className="panel">
        <div className="panel-header">
            <div>
              <h2>候选审核</h2>
              <p>Promote 通过后会进入记忆页；这里保留待审核、拒绝和需复核的候选。</p>
          </div>
        <input value={props.rejectReason} onChange={(event) => props.setRejectReason(event.target.value)} placeholder="reject reason" />
      </div>
      <div className="candidate-list">
        {props.candidates.length === 0 ? <EmptyState text="暂无待处理或需查看原因的候选记忆。" /> : null}
        {props.candidates.map((candidate) => {
          const reviewable = isReviewableCandidate(candidate);
          return (
            <article className="candidate-row" key={candidate.id}>
              <button onClick={() => props.onSelect(candidate)}>
                <strong>{candidate.claim || candidate.title || candidate.id}</strong>
                <span>{candidate.dimension || candidate.scope || "global"} · {formatTime(candidate.created_at)}</span>
                <AuditResultBadge item={candidate} review={reviewForItem(candidate, reviewResults)} />
              </button>
              <div className="candidate-actions">
                {reviewable ? (
                  <>
                    <button className="success-button" onClick={() => props.onPromote(candidate.id)}>
                      <Check size={15} />
                      Promote
                    </button>
                    <button className="danger-button" onClick={() => props.onReject(candidate.id)}>
                      <Trash2 size={15} />
                      Reject
                    </button>
                  </>
                ) : (
                  <StatusBadge text={candidate.status || "reviewed"} />
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PlanPanel(props: {
  items: PlanItem[];
  proposals: PlanProposal[];
  form: PlanFormState;
  setForm: (value: PlanFormState) => void;
  rejectReason: string;
  setRejectReason: (value: string) => void;
  uidFilter: string;
  loading: boolean;
  onCreate: () => void;
  onComplete: (id: string) => void;
  onCancel: (id: string) => void;
  onArchive: (id: string) => void;
  onApplyProposal: (id: string) => void;
  onRejectProposal: (id: string) => void;
}) {
  const goals = props.items.filter((item) => item.kind === "goal");
  const todos = props.items.filter((item) => item.kind === "todo");
  const parentGoals = goals.filter((goal) => !["completed", "cancelled", "archived"].includes(String(goal.status || "")));
  const setField = <K extends keyof PlanFormState>(field: K, value: PlanFormState[K]) => {
    props.setForm({ ...props.form, [field]: value });
  };
  return (
    <section className="panel plan-panel">
      <div className="panel-header">
        <div>
          <h2>计划</h2>
          <p>Goal 和 Todo 使用同一套计划项；自动抽取会先进入候选计划。</p>
        </div>
        <StatusBadge text={props.uidFilter.trim() ? `UID ${props.uidFilter.trim()}` : "global"} />
      </div>
      <div className="plan-composer">
        <label>
          类型
          <select value={props.form.kind} onChange={(event) => setField("kind", event.target.value as "goal" | "todo")}>
            <option value="goal">Goal</option>
            <option value="todo">Todo</option>
          </select>
        </label>
        <label className="plan-title-field">
          标题
          <input value={props.form.title} onChange={(event) => setField("title", event.target.value)} placeholder="例如：完成 Mnemo 计划模块" />
        </label>
        <label>
          优先级
          <select value={props.form.priority} onChange={(event) => setField("priority", event.target.value as "low" | "normal" | "high")}>
            <option value="low">low</option>
            <option value="normal">normal</option>
            <option value="high">high</option>
          </select>
        </label>
        <label>
          截止时间
          <input type="datetime-local" value={props.form.dueAt} onChange={(event) => setField("dueAt", event.target.value)} />
        </label>
        <label>
          父 Goal
          <select value={props.form.parentId} onChange={(event) => setField("parentId", event.target.value)} disabled={props.form.kind === "goal"}>
            <option value="">无</option>
            {parentGoals.map((goal) => (
              <option value={goal.id} key={goal.id}>{goal.title}</option>
            ))}
          </select>
        </label>
        <label className="plan-detail-field">
          详情
          <textarea value={props.form.detail} onChange={(event) => setField("detail", event.target.value)} placeholder="补充范围、验收点或上下文" />
        </label>
        <button className="primary-button" onClick={props.onCreate} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
          新增计划
        </button>
      </div>
      <div className="plan-sections">
        <PlanSection
          title="Goals"
          items={goals}
          emptyText="暂无 goal。"
          onComplete={props.onComplete}
          onCancel={props.onCancel}
          onArchive={props.onArchive}
        />
        <PlanSection
          title="Todos"
          items={todos}
          emptyText="暂无 todo。"
          goals={goals}
          onComplete={props.onComplete}
          onCancel={props.onCancel}
          onArchive={props.onArchive}
        />
      </div>
      <div className="plan-proposals">
        <div className="plan-proposals-header">
          <div>
            <h3>候选计划</h3>
            <p>来自事件摄入或模型抽取，接受后才会进入正式计划。</p>
          </div>
          <StatusBadge text={`${props.proposals.length} pending`} />
        </div>
        <label>
          拒绝原因
          <input value={props.rejectReason} onChange={(event) => props.setRejectReason(event.target.value)} />
        </label>
        <div className="plan-proposal-list">
          {props.proposals.length === 0 ? <EmptyState text="暂无候选计划。" /> : null}
          {props.proposals.map((proposal) => (
            <article className="plan-proposal-card" key={proposal.id}>
              <div>
                <div className="plan-row-title">
                  <StatusBadge text={proposal.kind || "todo"} />
                  <StatusBadge text={proposal.priority || "normal"} />
                  <strong>{proposal.title || proposal.id}</strong>
                </div>
                <p>{proposal.detail || proposal.reason || "没有附带详情。"}</p>
                <small>{proposal.scope || "global"} · {formatConfidence(proposal.confidence)} · {formatDate(proposal.created_at)}</small>
                <code>{proposal.id}</code>
              </div>
              <div className="plan-actions">
                <button className="success-button" disabled={props.loading} onClick={() => props.onApplyProposal(proposal.id)}>
                  <Check size={15} />
                  接受
                </button>
                <button className="danger-button" disabled={props.loading} onClick={() => props.onRejectProposal(proposal.id)}>
                  <X size={15} />
                  拒绝
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function PlanSection(props: {
  title: string;
  items: PlanItem[];
  goals?: PlanItem[];
  emptyText: string;
  onComplete: (id: string) => void;
  onCancel: (id: string) => void;
  onArchive: (id: string) => void;
}) {
  return (
    <div className="plan-section">
      <div className="plan-section-header">
        <h3>{props.title}</h3>
        <StatusBadge text={`${props.items.length} items`} />
      </div>
      <div className="plan-list">
        {props.items.length === 0 ? <EmptyState text={props.emptyText} /> : null}
        {props.items.map((item) => (
          <article className="plan-card" key={item.id}>
            <div className="plan-card-main">
              <div className="plan-row-title">
                <StatusBadge text={item.status || "open"} />
                <StatusBadge text={item.priority || "normal"} />
                <strong>{item.title}</strong>
              </div>
              {item.detail ? <p>{item.detail}</p> : null}
              <div className="plan-meta">
                <span>{item.scope || "global"}</span>
                {item.parent_id ? <span>父级：{planTitleById(props.goals || [], item.parent_id)}</span> : null}
                {item.due_at ? <span>截止：{formatDate(item.due_at)}</span> : null}
                <code>{item.id}</code>
              </div>
            </div>
            <div className="plan-actions">
              <button className="success-button" onClick={() => props.onComplete(item.id)} disabled={isClosedPlan(item)}>
                <Check size={15} />
                完成
              </button>
              <button className="danger-button" onClick={() => props.onCancel(item.id)} disabled={isClosedPlan(item)}>
                <X size={15} />
                取消
              </button>
              <button className="ghost-button" onClick={() => props.onArchive(item.id)}>
                <Archive size={15} />
                归档
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function TombstonePanel(props: {
  tombstones: MemoryTombstone[];
  selectedTombstoneIds: Set<string>;
  loading: boolean;
  onToggleSelection: (tombstoneId: string, selected: boolean) => void;
  onToggleAll: (selected: boolean) => void;
  onSelectTarget: (item: MemoryItem) => void;
  onForget: (tombstone: MemoryTombstone) => void;
  onHardDelete: (tombstone: MemoryTombstone) => void;
  onHardDeleteSelected: () => void;
}) {
  const selectedCount = props.tombstones.filter((tombstone) => props.selectedTombstoneIds.has(tombstone.id)).length;
  const allSelected = props.tombstones.length > 0 && selectedCount === props.tombstones.length;
  return (
    <section className="panel tombstone-panel">
      <div className="panel-header">
        <div>
          <h2>Tombstones</h2>
          <p>Forget 会擦除目标内容并保留删除痕迹；彻底删除会移除目标和相关墓碑记录。</p>
        </div>
        <div className="tombstone-header-actions">
          <StatusBadge text={`${props.tombstones.length} tombstones`} />
          {selectedCount > 0 ? <StatusBadge text={`${selectedCount} selected`} /> : null}
        </div>
      </div>
      <div className="tombstone-toolbar">
        <label className="tombstone-select-all">
          <input
            type="checkbox"
            checked={allSelected}
            disabled={props.loading || props.tombstones.length === 0}
            onChange={(event) => props.onToggleAll(event.target.checked)}
          />
          <span>全选</span>
        </label>
        <button
          className="danger-button strong-danger"
          onClick={props.onHardDeleteSelected}
          disabled={props.loading || selectedCount === 0}
        >
          <X size={15} />
          彻底删除选中
        </button>
      </div>
      <div className="tombstone-list">
        {props.tombstones.length === 0 ? <EmptyState text="暂无 tombstone。" /> : null}
        {props.tombstones.map((tombstone) => (
          <article className="tombstone-card" key={tombstone.id}>
            <label className="tombstone-select" title="选择 tombstone">
              <input
                type="checkbox"
                aria-label={`选择 tombstone ${tombstone.id}`}
                checked={props.selectedTombstoneIds.has(tombstone.id)}
                disabled={props.loading}
                onChange={(event) => props.onToggleSelection(tombstone.id, event.target.checked)}
              />
            </label>
            <div className="tombstone-main">
              <div className="tombstone-title">
                <StatusBadge text={tombstone.target_type} />
                <strong>{tombstone.reason || "unspecified"}</strong>
                <span>{formatDate(tombstone.created_at)}</span>
              </div>
              <div className="tombstone-target">
                <span>Target</span>
                <code>{tombstone.target_id}</code>
              </div>
              <p>{tombstone.summary || tombstone.rule || tombstone.target_hash || "No tombstone summary."}</p>
              <div className="tombstone-meta">
                <code>{tombstone.id}</code>
                {tombstone.evidence_run_id ? <code>{tombstone.evidence_run_id}</code> : null}
                {tombstone.rule ? <span>{tombstone.rule}</span> : null}
              </div>
              <JsonBlock title="Metadata" value={tombstone.metadata || {}} />
            </div>
            <div className="tombstone-actions">
              <button className="ghost-button" onClick={() => props.onSelectTarget(tombstoneTargetItem(tombstone))} disabled={props.loading}>
                <ChevronRight size={15} />
                查看目标
              </button>
              <button className="danger-button" onClick={() => props.onForget(tombstone)} disabled={props.loading}>
                <Trash2 size={15} />
                Forget 擦除
              </button>
              <button className="danger-button strong-danger" onClick={() => props.onHardDelete(tombstone)} disabled={props.loading}>
                <X size={15} />
                彻底删除
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function MaintenancePanel(props: {
  health: MemoryHealthResult | null;
  dreamStatus: DreamStatusResult | null;
  snapshot: SnapshotResult | null;
  tombstones: MemoryTombstone[];
  proposals: DreamProposal[];
  useProvider: boolean;
  advancedDreaming: boolean;
  advancedMode: boolean;
  loading: boolean;
  dreamElapsedS: number | null;
  proposalRejectReason: string;
  setProposalRejectReason: (value: string) => void;
  onRunDream: () => void;
  onCompileSnapshot: () => void;
  onApplyProposal: (id: string) => void;
  onRejectProposal: (id: string) => void;
}) {
  const latestDurationS = latestDreamDurationS(props.dreamStatus);
  const pendingProposals = props.proposals.filter((proposal) => proposal.status === "pending");
  return (
    <section className="panel maintenance">
      <div className="panel-header">
        <div>
          <h2>模型与维护</h2>
          <p>运行 Dream maintenance、刷新快照并检查记忆健康状态。</p>
        </div>
        <div className="action-row">
          <button className="primary-button" onClick={props.onRunDream} disabled={props.loading}>
            {props.dreamElapsedS !== null ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
            {props.dreamElapsedS !== null
              ? `运行中 ${formatDuration(props.dreamElapsedS)}`
              : props.useProvider ? "模型 Dream" : "运行 Dream"}
          </button>
          <button className="ghost-button" onClick={props.onCompileSnapshot} disabled={props.loading}>
            <RefreshCcw size={16} />
            刷新快照
          </button>
        </div>
      </div>
      <DreamTiming elapsedS={props.dreamElapsedS} latestDurationS={latestDurationS} />
      <div className="dream-mode-strip">
        <StatusBadge text={props.useProvider ? "模型审核开启" : "模型审核关闭"} />
        <StatusBadge text={props.advancedDreaming ? "高级 Dreaming 开启" : "普通 Dreaming"} />
        {pendingProposals.length > 0 ? <StatusBadge text={`${pendingProposals.length} 条待确认提案`} /> : null}
      </div>
      {props.advancedMode ? <DreamReviewReasons items={dreamStatusReviewReasons(props.dreamStatus)} /> : null}
      {props.advancedMode ? (
        <>
          <DreamProposalsPanel
            proposals={props.proposals}
            rejectReason={props.proposalRejectReason}
            setRejectReason={props.setProposalRejectReason}
            loading={props.loading}
            onApply={props.onApplyProposal}
            onReject={props.onRejectProposal}
          />
          <div className="maintenance-grid">
            <JsonBlock title="Health" value={props.health || {}} />
            <JsonBlock title="Dream Status" value={props.dreamStatus || {}} />
            <JsonBlock title="Snapshot" value={props.snapshot || {}} />
            <JsonBlock title="Tombstones" value={props.tombstones} />
          </div>
        </>
      ) : (
        <MaintenanceSummary
          health={props.health}
          dreamStatus={props.dreamStatus}
          snapshot={props.snapshot}
          tombstones={props.tombstones}
          proposals={props.proposals}
          useProvider={props.useProvider}
        />
      )}
    </section>
  );
}

function DreamProposalsPanel(props: {
  proposals: DreamProposal[];
  rejectReason: string;
  setRejectReason: (value: string) => void;
  loading: boolean;
  onApply: (id: string) => void;
  onReject: (id: string) => void;
}) {
  return (
    <div className="dream-proposals">
      <div className="dream-proposals-header">
        <div>
          <h3>整理提案</h3>
          <p>高级 Dreaming 的高风险整理动作会停在这里，确认后才会改稳定记忆。</p>
        </div>
        <StatusBadge text={`${props.proposals.length} 条提案`} />
      </div>
      <label>
        拒绝原因
        <input value={props.rejectReason} onChange={(event) => props.setRejectReason(event.target.value)} />
      </label>
      <div className="dream-proposal-list">
        {props.proposals.length === 0 ? <EmptyState text="暂无整理提案。开启高级 Dreaming 并运行模型 Dream 后会显示在这里。" /> : null}
        {props.proposals.map((proposal) => (
          <article className="dream-proposal-card" key={proposal.id}>
            <div className="dream-proposal-main">
              <div className="dream-proposal-title">
                <StatusBadge text={proposal.status || "pending"} />
                <StatusBadge text={proposal.tool} />
                <strong>{proposal.title || proposal.id}</strong>
              </div>
              <p>{proposal.rationale || "没有附带 rationale。"}</p>
              <div className="dream-proposal-meta">
                <code>{proposal.id}</code>
                {proposal.report_id ? <code>{proposal.report_id}</code> : null}
                <span>{formatDate(proposal.created_at)}</span>
              </div>
              <details>
                <summary>Before / After</summary>
                <JsonBlock title="Before" value={proposal.before || {}} />
                <JsonBlock title="After" value={proposal.after || {}} />
              </details>
            </div>
            <div className="dream-proposal-actions">
              {proposal.status === "pending" ? (
                <>
                  <button className="success-button" disabled={props.loading} onClick={() => props.onApply(proposal.id)}>
                    <Check size={15} />
                    通过
                  </button>
                  <button className="danger-button" disabled={props.loading} onClick={() => props.onReject(proposal.id)}>
                    <X size={15} />
                    拒绝
                  </button>
                </>
              ) : (
                <StatusBadge text={proposal.status || "reviewed"} />
              )}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function MaintenanceSummary(props: {
  health: MemoryHealthResult | null;
  dreamStatus: DreamStatusResult | null;
  snapshot: SnapshotResult | null;
  tombstones: MemoryTombstone[];
  proposals: DreamProposal[];
  useProvider: boolean;
}) {
  const healthCards = Array.isArray(props.health?.cards) ? props.health.cards.length : 0;
  const latestDuration = latestDreamDurationS(props.dreamStatus);
  const pendingProposals = props.proposals.filter((proposal) => proposal.status === "pending").length;
  return (
    <div className="maintenance-summary">
      <div className="summary-card">
        <Sparkles size={18} />
        <span>模型审核</span>
        <strong>{props.useProvider ? "已启用" : "未启用"}</strong>
        <small>{props.useProvider ? "Run Dream 会调用 provider" : "Dream 只生成报告和快照"}</small>
      </div>
      <div className="summary-card">
        <FileClock size={18} />
        <span>最近 Dream</span>
        <strong>{latestDuration === null ? "暂无" : formatDuration(latestDuration)}</strong>
        <small>高级模式可查看完整报告</small>
      </div>
      <div className="summary-card">
        <Gauge size={18} />
        <span>健康卡片</span>
        <strong>{healthCards}</strong>
        <small>用于发现重复、冲突和维护 backlog</small>
      </div>
      <div className="summary-card">
        <Archive size={18} />
        <span>整理提案</span>
        <strong>{pendingProposals}</strong>
        <small>{props.tombstones.length} 条删除痕迹 · {props.snapshot?.exists ? "Snapshot 已存在" : "Snapshot 未生成"}</small>
      </div>
    </div>
  );
}

function DreamTiming({ elapsedS, latestDurationS }: { elapsedS: number | null; latestDurationS: number | null }) {
  if (elapsedS === null && latestDurationS === null) return null;
  return (
    <div className={elapsedS === null ? "dream-timing" : "dream-timing active"}>
      {elapsedS === null ? <FileClock size={16} /> : <Loader2 className="spin" size={16} />}
      <span>{elapsedS === null ? "上次用时" : "Dreaming 用时"}</span>
      <strong>{formatDuration(elapsedS ?? latestDurationS ?? 0)}</strong>
    </div>
  );
}

function DreamReviewReasons({ items }: { items: DreamReviewResult[] }) {
  if (items.length === 0) return null;
  return (
    <div className="dream-rejects">
      <div className="dream-rejects-header">
        <h3>审核原因</h3>
        <StatusBadge text={`${items.length} reviewed`} />
      </div>
      <div className="dream-reject-list">
        {items.map((item, index) => (
          <div className="dream-reject-row" key={`${item.action_id || item.candidate_id || "reject"}:${index}`}>
            <code>{auditReviewLabel(item)} · {item.candidate_id || item.page_id || item.action_id || "unknown candidate"}</code>
            <p>{item.reason || "unspecified"}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function SettingsPanel(props: {
  apiBase: string;
  setApiBase: (value: string) => void;
  authToken: string;
  setAuthToken: (value: string) => void;
  source: string;
  setSource: (value: string) => void;
  useProvider: boolean;
  setUseProvider: (value: boolean) => void;
  advancedDreaming: boolean;
  setAdvancedDreaming: (value: boolean) => void;
  providerConfig: ProviderConfigResult | null;
  providerForm: ProviderFormState;
  setProviderForm: (value: ProviderFormState) => void;
  autoDreamStatus: AutoDreamStatusResult | null;
  autoDreamForm: AutoDreamFormState;
  setAutoDreamForm: (value: AutoDreamFormState) => void;
  onSaveProviderConfig: () => void;
  onSaveAutoDreamConfig: () => void;
  loading: boolean;
}) {
  const setProviderField = <K extends keyof ProviderFormState>(field: K, value: ProviderFormState[K]) => {
    props.setProviderForm({ ...props.providerForm, [field]: value });
  };
  const setAutoDreamField = <K extends keyof AutoDreamFormState>(field: K, value: AutoDreamFormState[K]) => {
    props.setAutoDreamForm({ ...props.autoDreamForm, [field]: value });
  };

  return (
    <section className="panel settings-panel">
      <div className="panel-header">
        <div>
          <h2>设置</h2>
          <p>本地 API、Bearer token 和维护模型配置。</p>
        </div>
        <ShieldCheck size={22} />
      </div>
      <label>
        API Base
        <input value={props.apiBase} onChange={(event) => props.setApiBase(event.target.value)} />
      </label>
      <label>
        Bearer Token
        <input value={props.authToken} onChange={(event) => props.setAuthToken(event.target.value)} placeholder="mnemo-memory serve --auth-token ..." />
      </label>
      <label>
        默认 Source
        <input value={props.source} onChange={(event) => props.setSource(event.target.value)} />
      </label>
      <div className="provider-status-row">
        <StatusBadge text={providerStatusText(props.providerConfig)} />
        <code>{props.providerConfig?.save_path || "config.json"}</code>
      </div>
      <div className="provider-grid">
        <label>
          Provider
          <select value={props.providerForm.provider} onChange={(event) => setProviderField("provider", event.target.value)}>
            <option value="openai-compatible">openai-compatible</option>
          </select>
        </label>
        <label>
          Base URL
          <input
            value={props.providerForm.baseUrl}
            onChange={(event) => setProviderField("baseUrl", event.target.value)}
            placeholder="https://api.openai.com/v1"
          />
        </label>
        <label>
          Model
          <input
            value={props.providerForm.model}
            onChange={(event) => setProviderField("model", event.target.value)}
            placeholder="gpt-4.1-mini"
          />
        </label>
        <label>
          API Key
          <input
            type="password"
            autoComplete="off"
            value={props.providerForm.apiKey}
            onChange={(event) => setProviderField("apiKey", event.target.value)}
            placeholder={props.providerConfig?.api_key_configured ? "已保存；留空保持不变" : "sk-..."}
          />
        </label>
        <label>
          API Key Env
          <input
            value={props.providerForm.apiKeyEnv}
            onChange={(event) => setProviderField("apiKeyEnv", event.target.value)}
            placeholder="OPENAI_API_KEY"
          />
        </label>
        <label>
          Timeout
          <input
            type="number"
            min="0.1"
            step="0.1"
            value={props.providerForm.timeoutS}
            onChange={(event) => setProviderField("timeoutS", event.target.value)}
          />
        </label>
      </div>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={props.useProvider}
          onChange={(event) => props.setUseProvider(event.target.checked)}
        />
        <span>
          <strong>使用模型审核</strong>
          <small>Run Dream 时调用服务端 provider；这里保存的配置会写入 state config。</small>
        </span>
      </label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={props.advancedDreaming}
          onChange={(event) => props.setAdvancedDreaming(event.target.checked)}
        />
        <span>
          <strong>高级 Dreaming</strong>
          <small>开启后 Dream 会生成稳定记忆整理提案；高风险合并、拆分、重写需要在维护页确认。</small>
        </span>
      </label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={props.providerForm.thinkingEnabled}
          onChange={(event) => setProviderField("thinkingEnabled", event.target.checked)}
        />
        <span>
          <strong>开启 Thinking</strong>
          <small>保存后 provider 请求会携带 thinking 参数；关闭时不发送该字段。</small>
        </span>
      </label>
      <div className="settings-actions">
        <button className="primary-button" onClick={props.onSaveProviderConfig} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
          保存 Provider
        </button>
        <button className="ghost-button" onClick={() => props.setAuthToken("")}>
          <X size={15} />
          清除 Token
        </button>
      </div>
      <div className="settings-divider" />
      <div className="settings-section-header">
        <div>
          <h3>自动 Dreaming</h3>
          <p>服务进程内定时维护，默认每 180 分钟检查一次。</p>
        </div>
        <StatusBadge text={autoDreamStatusText(props.autoDreamStatus)} />
      </div>
      <div className="provider-status-row">
        <StatusBadge text={props.autoDreamStatus?.last_outcome || "scheduled"} />
        <code>{props.autoDreamStatus?.status_path || "auto-dream-status.json"}</code>
      </div>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={props.autoDreamForm.enabled}
          onChange={(event) => setAutoDreamField("enabled", event.target.checked)}
        />
        <span>
          <strong>启用自动 Dreaming</strong>
          <small>仅在有 backlog 且 provider 已配置时调用模型维护。</small>
        </span>
      </label>
      <div className="provider-grid">
        <label>
          间隔分钟
          <input
            type="number"
            min="5"
            step="5"
            value={props.autoDreamForm.intervalMinutes}
            onChange={(event) => setAutoDreamField("intervalMinutes", event.target.value)}
          />
        </label>
        <label>
          下次运行
          <input readOnly value={formatDate(props.autoDreamStatus?.next_run_at ?? undefined)} />
        </label>
        <label>
          上次检查
          <input readOnly value={formatDate(props.autoDreamStatus?.last_checked_at ?? undefined)} />
        </label>
        <label>
          上次用时
          <input
            readOnly
            value={props.autoDreamStatus?.last_duration_s == null ? "-" : formatDuration(props.autoDreamStatus.last_duration_s)}
          />
        </label>
      </div>
      {props.autoDreamStatus?.last_error ? (
        <div className="auto-dream-error">
          <strong>最近错误</strong>
          <span>{props.autoDreamStatus.last_error}</span>
        </div>
      ) : null}
      <div className="settings-actions">
        <button className="primary-button" onClick={props.onSaveAutoDreamConfig} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
          保存自动 Dreaming
        </button>
      </div>
    </section>
  );
}

function OperationsQueue(props: {
  candidates: MemoryItem[];
  dreamStatus: DreamStatusResult | null;
  snapshot: SnapshotResult | null;
  useProvider: boolean;
  loading: boolean;
  dreamElapsedS: number | null;
  onPromote: (id: string) => void;
  onReject: (id: string) => void;
  onRunDream: () => void;
}) {
  return (
    <div className="ops-stack">
      <section className="panel ops-panel">
        <div className="panel-header compact">
          <h2>Operations Queue</h2>
          <StatusBadge text={`${props.candidates.length} candidates`} />
        </div>
        {props.candidates.length === 0 ? <EmptyState text="没有待审候选。" /> : null}
        {props.candidates.slice(0, 6).map((candidate) => (
          <article className="queue-item" key={candidate.id}>
            <div>
              <span className="score">{formatConfidence(candidate.confidence)}</span>
              <strong>{candidate.claim || candidate.id}</strong>
              <small>{candidate.scope || candidate.dimension || "global"}</small>
            </div>
            <div>
              <button className="success-button" onClick={() => props.onPromote(candidate.id)} disabled={props.loading}>Promote</button>
              <button className="danger-button" onClick={() => props.onReject(candidate.id)} disabled={props.loading}>Reject</button>
            </div>
          </article>
        ))}
      </section>
      <section className="panel ops-panel">
        <div className="panel-header compact">
          <h2>Dream Run</h2>
          <Sparkles size={18} />
        </div>
        <JsonBlock title="Status" value={props.dreamStatus || {}} />
        <button className="primary-button full" onClick={props.onRunDream} disabled={props.loading}>
          {props.dreamElapsedS !== null ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
          {props.dreamElapsedS !== null ? `Running ${formatDuration(props.dreamElapsedS)}` : props.useProvider ? "Run Model" : "Run Now"}
        </button>
      </section>
      <section className="panel ops-panel">
        <div className="panel-header compact">
          <h2>Snapshot</h2>
          <StatusBadge text={props.snapshot?.exists ? "OK" : "Missing"} />
        </div>
        <JsonBlock title="Latest" value={props.snapshot || { exists: false }} />
      </section>
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="json-block">
      <div>
        <span>{title}</span>
        <button onClick={() => navigator.clipboard?.writeText(JSON.stringify(value, null, 2))}>
          <Link2 size={13} />
        </button>
      </div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function StatusBadge({ text }: { text: string }) {
  const normalized = text.toLowerCase();
  const tone = normalized.includes("active") || normalized.includes("ok") || normalized.includes("page")
    ? "good"
    : normalized.includes("draft") || normalized.includes("candidate")
      ? "blue"
      : normalized.includes("reject") || normalized.includes("tomb") || normalized.includes("delete")
        ? "bad"
        : "neutral";
  return <span className={`badge ${tone}`} title={text}>{compactStatusText(text)}</span>;
}

function compactStatusText(text: string) {
  const cleanText = text.trim();
  const separator = cleanText.indexOf(":");
  if (separator > 0) {
    return cleanText.slice(0, separator);
  }
  return cleanText;
}

function StatusDot({ ok }: { ok: boolean }) {
  return <span className={ok ? "dot ok" : "dot"} />;
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}

function emptyPlanForm(): PlanFormState {
  return {
    kind: "todo",
    title: "",
    detail: "",
    parentId: "",
    priority: "normal",
    dueAt: ""
  };
}

function datetimeLocalToUnix(value: string) {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? Math.round(ms / 1000) : null;
}

function isClosedPlan(item: PlanItem) {
  return ["completed", "done", "cancelled", "archived"].includes(String(item.status || "").toLowerCase());
}

function planTitleById(items: PlanItem[], id: string) {
  return items.find((item) => item.id === id)?.title || compactId(id);
}

function searchMatchToItem(match: Record<string, unknown>): MemoryItem | null {
  const rawType = String(match.type || match.item_type || "page");
  if (rawType.includes("plan")) {
    return null;
  }
  const type = rawType.includes("candidate") ? "candidate" : "page";
  return {
    ...(match as MemoryItem),
    type,
    id: String(match.id || match.memory_id || ""),
    title: String(match.title || match.claim || ""),
    content: String(match.content || match.claim || match.summary || "")
  };
}

function itemMatchesQuery(item: MemoryItem, query: string) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = [
    item.id,
    item.type,
    item.status,
    item.claim,
    item.title,
    item.content,
    item.scope,
    item.dimension,
    item.run_id,
    item.source_candidate_id
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

function compareMemoryItems(left: MemoryItem, right: MemoryItem) {
  const typeRank = (item: MemoryItem) => (item.type === "page" ? 0 : 1);
  const leftRank = typeRank(left);
  const rightRank = typeRank(right);
  if (leftRank !== rightRank) return leftRank - rightRank;
  return (right.updated_at || right.created_at || 0) - (left.updated_at || left.created_at || 0);
}

function scopeFromUidFilter(uid: string) {
  const cleanUid = uid.trim();
  if (!cleanUid) return "";
  return cleanUid.toLowerCase().startsWith("user:") ? cleanUid : `user:${cleanUid}`;
}

function memoryFactPayload(claim: string, scope: string) {
  return scope ? { claim, scope, confidence: 0.9 } : { claim, confidence: 0.9 };
}

function memoryObservationPayload(content: string, scope: string) {
  return scope ? { content, retention: "memory_candidate", scope } : content;
}

function tombstoneTargetItem(tombstone: MemoryTombstone): MemoryItem {
  return {
    id: tombstone.target_id,
    type: tombstone.target_type,
    status: `tombstoned:${tombstone.reason || "unknown"}`,
    title: tombstone.summary || tombstone.reason || tombstone.target_id,
    content: tombstone.summary || "",
    updated_at: tombstone.created_at
  };
}

function itemTitle(item: MemoryItem) {
  return item.title || item.claim || item.content || item.id;
}

function formatConfidence(value?: number) {
  if (typeof value !== "number") return "-";
  return value.toFixed(2);
}

function formatTime(value?: number) {
  if (!value) return "-";
  const diff = Date.now() - value * 1000;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.round(diff / minute))}m`;
  if (diff < day) return `${Math.round(diff / hour)}h`;
  return `${Math.round(diff / day)}d`;
}

function formatDate(value?: number) {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleString("zh-CN");
}

function compactId(value?: string) {
  if (!value) return "";
  return value.length > 24 ? `${value.slice(0, 21)}...` : value;
}

function dreamReviewResultMap(status: DreamStatusResult | null) {
  const map = new Map<string, DreamReviewResult>();
  for (const result of normalizeDreamReviewResults(status?.latest?.execution?.review_results)) {
    for (const key of [result.candidate_id, result.page_id]) {
      if (key && !map.has(key)) {
        map.set(key, result);
      }
    }
  }
  return map;
}

function normalizeDreamReviewResults(items: unknown) {
  if (!Array.isArray(items)) return [];
  return items
    .filter((item): item is DreamReviewResult => {
      if (!item || typeof item !== "object") return false;
      const result = item as DreamReviewResult;
      return Boolean(result.candidate_id || result.page_id) && Boolean(result.decision || result.status || result.reason);
    })
    .slice(0, 20);
}

function reviewForItem(item: MemoryItem, results: Map<string, DreamReviewResult>) {
  return results.get(item.id) || (item.source_candidate_id ? results.get(item.source_candidate_id) : undefined);
}

function auditResultForItem(item: MemoryItem, review?: DreamReviewResult) {
  if (review) {
    return auditResultFromDreamReview(review);
  }
  const status = String(item.status || "").trim();
  const normalized = status.toLowerCase();
  if (normalized === "promoted") {
    return auditResult("审核通过", "候选已进入稳定记忆", "good");
  }
  if (normalized === "draft") {
    return auditResult("待审核", "等待模型或人工审核", "blue");
  }
  if (normalized.startsWith("rejected")) {
    return auditResult("审核拒绝", statusReason(status), "bad");
  }
  if (normalized.startsWith("needs_review")) {
    return auditResult("待复核", statusReason(status), "warn");
  }
  if (normalized.startsWith("skipped")) {
    return auditResult("已跳过", statusReason(status), "neutral");
  }
  if (item.type === "page" && normalized === "active") {
    return auditResult("稳定记忆", stableMemoryFallbackReason(item), "good");
  }
  if (normalized.includes("tombstone") || normalized.includes("delete")) {
    return auditResult("已删除", statusReason(status), "bad");
  }
  return auditResult("未审核", status || "unknown", "neutral");
}

function auditResultFromDreamReview(review: DreamReviewResult) {
  const decision = String(review.decision || "").toLowerCase();
  const status = String(review.status || "");
  const normalizedStatus = status.toLowerCase();
  if (decision === "promoted" || normalizedStatus === "promoted") {
    return auditResult("模型通过", review.reason || promotedReviewFallbackReason(review), "good");
  }
  if (decision === "rejected" || normalizedStatus.startsWith("rejected")) {
    return auditResult("模型拒绝", review.reason || statusReason(status), "bad");
  }
  if (decision === "skipped") {
    return auditResult("模型跳过", review.reason || statusReason(status), "neutral");
  }
  if (decision === "conflict" || normalizedStatus.includes("conflict")) {
    return auditResult("需复核", review.reason || "conflict", "warn");
  }
  return auditResult("模型已审", review.reason || status || decision, "blue");
}

function detailedAuditReason(item: MemoryItem, review: DreamReviewResult | undefined, fallback: string) {
  if (review) {
    if (review.reason) return review.reason;
    if (String(review.decision || "").toLowerCase() === "promoted" || String(review.status || "").toLowerCase() === "promoted") {
      return promotedReviewFallbackReason(review);
    }
    return fallback || review.status || review.decision || "审核结果没有附带详细原因。";
  }
  if (item.type === "page" && String(item.status || "").toLowerCase() === "active") {
    return stableMemoryFallbackReason(item);
  }
  return fallback || statusReason(String(item.status || "")) || "暂无详细审核原因。";
}

function promotedReviewFallbackReason(review: DreamReviewResult) {
  const actionText =
    review.page_action === "merged"
      ? "已合并到已有稳定记忆页"
      : review.page_action === "created"
        ? "已新建稳定记忆页"
        : "已进入稳定记忆";
  const pageText = review.page_title
    ? `「${review.page_title}」`
    : review.page_id
      ? compactId(review.page_id)
      : "";
  const sourceText = review.candidate_id ? `；来源候选 ${compactId(review.candidate_id)}` : "";
  return `${actionText}${pageText ? ` ${pageText}` : ""}${sourceText}`;
}

function stableMemoryFallbackReason(item: MemoryItem) {
  const parts = ["已进入稳定记忆，可用于后续检索和上下文召回"];
  if (item.source_candidate_id) {
    parts.push(`来源候选 ${compactId(item.source_candidate_id)}`);
  }
  if (typeof item.confidence === "number") {
    parts.push(`置信度 ${formatConfidence(item.confidence)}`);
  }
  return parts.join("；");
}

function auditReviewLabel(review: DreamReviewResult) {
  return auditResultFromDreamReview(review).label;
}

function auditResult(label: string, detail: string, tone: "good" | "bad" | "warn" | "blue" | "neutral") {
  return {
    label,
    detail,
    tone,
    title: detail ? `${label}: ${detail}` : label
  };
}

function statusReason(status: string) {
  const separator = status.indexOf(":");
  if (separator < 0) return "";
  return status.slice(separator + 1).replace(/[_-]+/g, " ");
}

function latestDreamDurationS(status: DreamStatusResult | null) {
  const value = status?.latest?.duration_s;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatDuration(value: number) {
  if (!Number.isFinite(value) || value < 0) return "0.0s";
  if (value < 10) return `${value.toFixed(1)}s`;
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

function dreamStatusReviewReasons(status: DreamStatusResult | null) {
  return normalizeDreamReviewResults(status?.latest?.execution?.review_results).filter((item) => Boolean(item.reason));
}

function dreamRunRejectReasons(report: DreamRunReport) {
  return normalizeDreamRejectReasons(report.execution?.result?.actions?.applied);
}

function normalizeDreamRejectReasons(items: unknown) {
  if (!Array.isArray(items)) return [];
  return items
    .filter((item): item is DreamRejectReason => {
      if (!item || typeof item !== "object") return false;
      const action = item as DreamRejectReason;
      const tool = String(action.tool || "");
      const decision = String(action.decision || "");
      const status = String(action.status || "");
      return Boolean(action.reason) && (tool === "memory_reject_candidate" || decision === "rejected" || status.startsWith("rejected"));
    })
    .slice(0, 10);
}

function dreamRejectReasonText(items: DreamRejectReason[]) {
  if (items.length === 0) return "";
  const details = items
    .slice(0, 3)
    .map((item) => `${compactId(item.candidate_id || item.action_id)}: ${item.reason || "unspecified"}`)
    .join("；");
  const more = items.length > 3 ? `；另有 ${items.length - 3} 条` : "";
  return ` Reject 原因：${details}${more}`;
}

function dreamDurationText(report: DreamRunReport) {
  return typeof report.duration_s === "number" && Number.isFinite(report.duration_s) ? `用时 ${formatDuration(report.duration_s)}。` : "";
}

function dreamRunMessage(report: DreamRunReport, useProvider: boolean, advancedDreaming = false) {
  const counts = report.execution?.result?.actions?.counts || {};
  const deltaCounts = report.delta?.counts || {};
  const requested = Number(counts.requested || 0);
  const applied = Number(counts.applied || 0);
  const skipped = Number(counts.skipped || 0);
  const proposals = report.execution?.result?.actions?.proposals || [];
  const pendingProposals = proposals.filter((proposal) => proposal.status === "pending").length;
  const draftCandidates = Number(deltaCounts.draft_candidates || deltaCounts.memory_candidates || 0);
  const rejectReasonText = dreamRejectReasonText(dreamRunRejectReasons(report));
  const durationText = dreamDurationText(report);
  const proposalText = advancedDreaming ? `整理提案 ${pendingProposals} 条。` : "";
  if (!useProvider && requested === 0) {
    return `Dream 已运行：已生成报告和快照；未开启模型审核，所以没有维护动作。待审候选 ${draftCandidates} 条。${proposalText}${durationText}`;
  }
  return `Dream 已运行：请求 ${requested} 个动作，应用 ${applied} 个，跳过 ${skipped} 个。${proposalText}${durationText}${rejectReasonText}`;
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
