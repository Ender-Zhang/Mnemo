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
  Edit3,
  Eye,
  FileClock,
  Gauge,
  GitMerge,
  History,
  Home,
  Link2,
  ListTodo,
  Loader2,
  MessageSquare,
  Play,
  Plus,
  RefreshCcw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  User,
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

// ─── Types ───────────────────────────────────────────────────────────────────

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
  conflict_card?: ConflictCard | null;
};

type ConflictCard = {
  candidate_id?: string;
  existing_page_id?: string;
  candidate_claim?: string;
  existing_content?: string;
  options?: ConflictOption[];
};

type ConflictOption = {
  resolution: string;
  label: string;
  description?: string;
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

type L0Profile = {
  kind?: string;
  summary?: string;
  dimensions?: Record<string, unknown>;
  page_count?: number;
};

type ContextCardItem = {
  type?: string;
  id?: string;
  title?: string;
  content?: string;
  claim?: string;
  scope?: string;
  dimension?: string;
  confidence?: number;
  [key: string]: unknown;
};

type ContextPreviewResult = {
  kind?: string;
  intent?: string;
  cards?: ContextCardItem[];
  profile?: L0Profile | null;
  snapshot?: Record<string, unknown> | null;
};

type RecallPreviewResult = {
  kind?: string;
  seed?: string;
  items?: Array<Record<string, unknown>>;
  query_plan?: Record<string, unknown>;
};

type PageVersion = {
  id?: string;
  page_id?: string;
  change_reason?: string;
  changed_by?: string;
  snapshot_data?: Record<string, unknown>;
  created_at?: number;
};

type VersionsResult = {
  kind?: string;
  memory_id?: string;
  versions?: PageVersion[];
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

type TabKey = "memories" | "preview" | "plans" | "candidates" | "tombstones" | "maintenance" | "settings";

type Notice = {
  tone: "ok" | "warn" | "error";
  text: string;
};

// ─── Constants ───────────────────────────────────────────────────────────────

const navItems: Array<{ key: TabKey; label: string; icon: LucideIcon }> = [
  { key: "memories", label: "记忆工作台", icon: Home },
  { key: "preview", label: "记忆预览", icon: Eye },
  { key: "plans", label: "计划", icon: ListTodo },
  { key: "maintenance", label: "模型与维护", icon: Activity },
  { key: "settings", label: "设置", icon: Settings },
  { key: "candidates", label: "候选审核", icon: ClipboardList },
  { key: "tombstones", label: "墓碑 / 删除", icon: Archive }
];

const defaultNavKeys = new Set<TabKey>(["memories", "preview", "plans", "maintenance", "settings"]);
const advancedNavKeys = new Set<TabKey>(["memories", "preview", "plans", "maintenance", "settings", "candidates", "tombstones"]);

const DIMENSIONS = [
  "identity", "cognition", "values", "goals", "preferences",
  "relationships", "context", "history", "patterns", "boundaries"
];

// Granular refresh slices so a single mutation only refetches what it affects,
// instead of firing every endpoint on every action.
type RefreshPart = "service" | "inventory" | "candidates" | "maintenance" | "tombstones" | "config" | "plans" | "profile" | "health";
const ALL_REFRESH_PARTS: RefreshPart[] = ["service", "inventory", "candidates", "maintenance", "tombstones", "config", "plans", "profile", "health"];

const defaultApiBase = window.location.origin;

// ─── App ─────────────────────────────────────────────────────────────────────

function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("memories");
  const [apiBase, setApiBase] = useState(() => localStorage.getItem("mnemo.apiBase") || defaultApiBase);
  const [serviceOk, setServiceOk] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [advancedMode, setAdvancedMode] = useState(() => localStorage.getItem("mnemo.advancedMode") === "true");
  const [composerOpen, setComposerOpen] = useState(false);
  const [ingestOpen, setIngestOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorItem, setEditorItem] = useState<MemoryItem | null>(null);
  const [query, setQuery] = useState("");
  const [uidFilter, setUidFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [kindFilter, setKindFilter] = useState<"all" | "candidate" | "page">("page");
  const [searchScope, setSearchScope] = useState<string>("memory");
  const [dimensionFilter, setDimensionFilter] = useState("");
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
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);
  const [planProposals, setPlanProposals] = useState<PlanProposal[]>([]);
  const [planForm, setPlanForm] = useState<PlanFormState>(() => emptyPlanForm());
  const [planRejectReason, setPlanRejectReason] = useState("operator_rejected");
  const [proposalRejectReason, setProposalRejectReason] = useState("operator_rejected");
  const [tombstoneReason, setTombstoneReason] = useState("manual_curation");
  const [dreamStartedAtMs, setDreamStartedAtMs] = useState<number | null>(null);
  const [clockNowMs, setClockNowMs] = useState(() => Date.now());
  const [profile, setProfile] = useState<L0Profile | null>(null);
  const [versions, setVersions] = useState<PageVersion[]>([]);
  const [showVersions, setShowVersions] = useState(false);
  // memory preview (agent view)
  const [previewIntent, setPreviewIntent] = useState("");
  const [previewScope, setPreviewScope] = useState("memory");
  const [previewContext, setPreviewContext] = useState<ContextPreviewResult | null>(null);
  const [previewRecall, setPreviewRecall] = useState<RecallPreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  // pagination
  const [page, setPage] = useState(0);
  const pageSize = 20;

  const activeItems = useMemo(() => {
    let items = searchMode ? searchItems : [...inventory].sort(compareMemoryItems);
    if (dimensionFilter) {
      items = items.filter((item) => item.dimension === dimensionFilter);
    }
    return items;
  }, [inventory, searchItems, searchMode, dimensionFilter]);
  const pagedItems = useMemo(() => activeItems.slice(page * pageSize, (page + 1) * pageSize), [activeItems, page]);
  const totalPages = Math.max(1, Math.ceil(activeItems.length / pageSize));
  const pendingCandidates = useMemo(() => filterReviewableCandidates(candidates), [candidates]);
  const candidateReviewItems = useMemo(() => filterCandidateReviewItems(candidates), [candidates]);
  const conflictCandidates = useMemo(() => candidates.filter((c) => String(c.status || "").includes("conflict")), [candidates]);
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
    [apiBase]
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

  const refresh = useCallback(async (options: { parts?: RefreshPart[]; clearNotice?: boolean } = {}) => {
    const parts = new Set(options.parts ?? ALL_REFRESH_PARTS);
    setLoading(true);
    try {
      const scopedUid = uidFilter.trim() || undefined;
      const tasks: Array<Promise<unknown>> = [];
      if (parts.has("service")) {
        tasks.push(requestJson<Record<string, unknown>>("/api/health").then((r) => setServiceOk(Boolean(r.ok))));
      }
      if (parts.has("inventory")) {
        tasks.push(callMemory<MemoryListResult>("list", { kind: kindFilter, status: statusFilter || null, uid: scopedUid, limit: 200 }).then((r) => setInventory(r.items || [])));
      }
      if (parts.has("candidates")) {
        tasks.push(callMemory<MemoryListResult>("list", { kind: "candidate", status: null, uid: scopedUid, limit: 50 }).then((r) => setCandidates(r.items || [])));
      }
      if (parts.has("maintenance")) {
        tasks.push(callMemory<DreamStatusResult>("dream-status", { limit: 20 }).then(setDreamStatus));
        tasks.push(callMemory<SnapshotResult>("snapshot", { limit: 50 }).then(setSnapshot));
        tasks.push(callMemory<DreamProposalsResult>("dream-proposals", { status: null, limit: 50 }).then((r) => setDreamProposals(r.proposals || [])));
      }
      if (parts.has("tombstones")) {
        tasks.push(callMemory<TombstonesResult>("tombstones", { limit: 500 }).then((r) => setTombstones(r.tombstones || [])));
      }
      if (parts.has("config")) {
        tasks.push(callMemory<ProviderConfigResult>("provider-config", {}).then((r) => { setProviderConfig(r); setProviderForm(providerFormFromConfig(r)); }));
        tasks.push(callMemory<AutoDreamStatusResult>("auto-dream-status", {}).then((r) => { setAutoDreamStatus(r); setAutoDreamForm(autoDreamFormFromStatus(r)); }));
      }
      if (parts.has("plans")) {
        tasks.push(callMemory<PlanListResult>("plan-list", { uid: scopedUid, include_archived: false, limit: 100 }).then((r) => setPlanItems(r.items || [])));
        tasks.push(callMemory<PlanProposalsResult>("plan-proposals", { status: "pending", uid: scopedUid, limit: 50 }).then((r) => setPlanProposals(r.proposals || [])));
      }
      if (parts.has("profile")) {
        tasks.push(callMemory<L0Profile>("profile", {}).then(setProfile).catch(() => setProfile(null)));
      }
      if (parts.has("health")) {
        tasks.push(callMemory<MemoryHealthResult>("health", { limit: 20 }).then(setHealth).catch(() => setHealth(null)));
      }
      await Promise.all(tasks);
      if (options.clearNotice !== false) {
        setNotice(null);
      }
    } catch (error) {
      if (parts.has("service")) {
        setServiceOk(false);
      }
      setError(error);
    } finally {
      setLoading(false);
    }
  }, [callMemory, kindFilter, requestJson, statusFilter, uidFilter]);

  const refreshInventory = useCallback(async (options: { clearNotice?: boolean } = {}) => {
    setSearchItems([]);
    setSearchMode(false);
    setPage(0);
    await refresh(options);
  }, [refresh]);

  useEffect(() => { localStorage.setItem("mnemo.apiBase", apiBase); }, [apiBase]);
  useEffect(() => { localStorage.setItem("mnemo.useProvider", useProvider ? "true" : "false"); }, [useProvider]);
  useEffect(() => { localStorage.setItem("mnemo.advancedDreaming", advancedDreaming ? "true" : "false"); }, [advancedDreaming]);
  useEffect(() => { localStorage.setItem("mnemo.advancedMode", advancedMode ? "true" : "false"); }, [advancedMode]);

  useEffect(() => {
    const allowedTabs = advancedMode ? advancedNavKeys : defaultNavKeys;
    if (!allowedTabs.has(activeTab)) { setActiveTab("memories"); }
  }, [activeTab, advancedMode]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (dreamStartedAtMs === null) return undefined;
    setClockNowMs(Date.now());
    const timerId = window.setInterval(() => setClockNowMs(Date.now()), 500);
    return () => window.clearInterval(timerId);
  }, [dreamStartedAtMs]);

  useEffect(() => {
    if (activeTab !== "memories") return;
    if (activeItems.length === 0) { if (selected) setSelected(null); return; }
    const selectedStillVisible = selected ? activeItems.some((item) => item.id === selected.id && item.type === selected.type) : false;
    if (!selectedStillVisible) setSelected(activeItems[0]);
  }, [activeItems, activeTab, selected]);

  useEffect(() => {
    const visibleIds = new Set(tombstones.map((t) => t.id));
    setSelectedTombstoneIds((prev) => {
      const next = new Set([...prev].filter((id) => visibleIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [tombstones]);

  // ─── Actions ─────────────────────────────────────────────────────────────

  const searchMemory = async () => {
    const cleanQuery = query.trim();
    const cleanUid = uidFilter.trim();
    if (!cleanQuery && !cleanUid) { await refreshInventory(); return; }
    if (cleanUid && !cleanQuery) {
      await refreshInventory({ clearNotice: false });
      setOk(`UID 过滤已应用：${cleanUid}`);
      return;
    }
    setLoading(true);
    setPage(0);
    try {
      if (cleanUid) {
        const result = await callMemory<MemoryListResult>("list", { kind: kindFilter, status: statusFilter || null, uid: cleanUid, limit: 200 });
        const mapped = (result.items || []).filter((item) => itemMatchesQuery(item, cleanQuery));
        setSearchMode(true);
        setSearchItems(mapped);
        setSelected(mapped[0] || null);
        setOk(`UID 检索完成：${mapped.length} 条结果`);
        return;
      }
      const result = await callMemory<MemorySearchResult>("search", { query: cleanQuery, scope: searchScope, limit: 30 });
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
    setVersions([]);
    setShowVersions(false);
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

  const loadVersions = async (memoryId: string) => {
    try {
      const result = await callMemory<VersionsResult>("versions", { memory_id: memoryId, limit: 20 });
      setVersions(result.versions || []);
      setShowVersions(true);
    } catch (error) {
      setError(error);
    }
  };

  const runPreview = async () => {
    const intent = previewIntent.trim();
    setPreviewLoading(true);
    try {
      const ctx = await callMemory<ContextPreviewResult>("context", { intent, scope: previewScope, limit: 8 });
      setPreviewContext(ctx);
      if (intent) {
        try {
          setPreviewRecall(await callMemory<RecallPreviewResult>("recall", { seed: intent, limit: 8 }));
        } catch {
          setPreviewRecall(null);
        }
      } else {
        setPreviewRecall(null);
      }
      setOk("已生成 Agent 视角预览");
    } catch (error) {
      setError(error);
    } finally {
      setPreviewLoading(false);
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
      await refresh({ parts: ["inventory", "candidates"], clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const ingestEvent = async (form: IngestEventForm) => {
    setLoading(true);
    try {
      await callMemory("ingest-event", {
        text: form.text,
        source: form.source || "webui",
        actor: form.actor || undefined,
        event_type: form.eventType || "message",
        scope: form.scope || undefined,
        auto_promote: form.autoPromote,
        use_provider: form.useProvider
      });
      setIngestOpen(false);
      setOk("事件已录入，已提取记忆候选");
      await refresh({ parts: ["inventory", "candidates", "plans"], clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const stableCreate = async (form: PageEditorForm) => {
    setLoading(true);
    try {
      await callMemory("stable-create", {
        title: form.title,
        content: form.content,
        scope: form.scope || "global",
        confidence: parseFloat(form.confidence) || 0.7,
        dimension: form.dimension || undefined
      });
      setEditorOpen(false);
      setEditorItem(null);
      setOk("稳定记忆页已创建");
      await refresh({ parts: ["inventory", "profile", "maintenance"], clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const stableUpdate = async (memoryId: string, form: PageEditorForm) => {
    setLoading(true);
    try {
      await callMemory("stable-update", {
        memory_id: memoryId,
        title: form.title,
        content: form.content,
        scope: form.scope || undefined,
        confidence: parseFloat(form.confidence) || undefined,
        dimension: form.dimension || undefined
      });
      setEditorOpen(false);
      setEditorItem(null);
      setOk("稳定记忆页已更新");
      await refresh({ parts: ["inventory", "profile", "maintenance"], clearNotice: false });
      // reload detail
      if (selected?.id === memoryId) {
        await readMemory({ ...selected, id: memoryId } as MemoryItem);
      }
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const resolveConflict = async (candidateId: string, resolution: string) => {
    setLoading(true);
    try {
      await callMemory("resolve-conflict", { candidate_id: candidateId, resolution });
      setOk(`冲突已解决：${resolution}`);
      await refresh({ parts: ["candidates", "inventory", "profile"], clearNotice: false });
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
      if (result.decision === "promoted" || result.status === "promoted") { setOk(message); }
      else { setWarn(message); }
      await refresh({ parts: ["candidates", "inventory", "profile", "maintenance", "tombstones"], clearNotice: false });
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
      await refresh({ parts: ["candidates", "tombstones"], clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const batchPromoteCandidates = async (ids: string[]) => {
    setLoading(true);
    let promoted = 0;
    let failed = 0;
    try {
      for (const id of ids) {
        try {
          await callMemory("promote-candidate", { candidate_id: id, min_confidence: 0.7 });
          promoted++;
        } catch {
          failed++;
        }
      }
      await refresh({ parts: ["candidates", "inventory", "profile", "maintenance", "tombstones"], clearNotice: false });
      setOk(`批量审核完成：通过 ${promoted} 条${failed ? `，失败 ${failed} 条` : ""}`);
    } finally {
      setLoading(false);
    }
  };

  const batchRejectCandidates = async (ids: string[]) => {
    setLoading(true);
    let rejected = 0;
    try {
      for (const id of ids) {
        try {
          await callMemory("reject-candidate", { candidate_id: id, reason: rejectReason.trim() || "batch_reject" });
          rejected++;
        } catch { /* skip */ }
      }
      await refresh({ parts: ["candidates", "tombstones"], clearNotice: false });
      setOk(`批量拒绝完成：${rejected} 条`);
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
        await callMemory("tombstone", { memory_id: selected.id, target_type: selected.type, reason: tombstoneReason.trim() || "manual_curation" });
        setOk("记忆已标记 tombstone");
      }
      setSelected(null);
      await refresh({ parts: ["inventory", "tombstones", "profile"], clearNotice: false });
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  };

  const forgetTombstoneTarget = async (tombstone: MemoryTombstone) => {
    setLoading(true);
    try {
      await callMemory("forget", { memory_id: tombstone.target_id, target_type: tombstone.target_type, reason: "private_delete" });
      setOk("目标记忆已 Forget 擦除，删除痕迹仍会保留");
      await refresh({ parts: ["tombstones", "inventory", "profile"], clearNotice: false });
    } catch (error) { setError(error); }
    finally { setLoading(false); }
  };

  const hardDeleteTombstoneTarget = async (tombstone: MemoryTombstone) => {
    const confirmed = window.confirm(`彻底删除 ${tombstone.target_type}:${tombstone.target_id} 及相关 tombstone/link/wiki 记录？`);
    if (!confirmed) return;
    setLoading(true);
    try {
      await callMemory("hard-delete", { tombstone_id: tombstone.id, memory_id: tombstone.target_id, target_type: tombstone.target_type, delete_related: true });
      setSelected(null);
      setOk("目标记忆和相关 tombstone 记录已彻底删除");
      await refresh({ parts: ["tombstones", "inventory"], clearNotice: false });
    } catch (error) { setError(error); }
    finally { setLoading(false); }
  };

  const toggleTombstoneSelection = (tombstoneId: string, sel: boolean) => {
    setSelectedTombstoneIds((prev) => {
      const next = new Set(prev);
      if (sel) next.add(tombstoneId); else next.delete(tombstoneId);
      return next;
    });
  };

  const toggleAllTombstones = (sel: boolean) => {
    setSelectedTombstoneIds(sel ? new Set(tombstones.map((t) => t.id)) : new Set());
  };

  const hardDeleteSelectedTombstones = async () => {
    const selectedTs = tombstones.filter((t) => selectedTombstoneIds.has(t.id));
    if (selectedTs.length === 0) { setWarn("请先选择要彻底删除的 tombstone"); return; }
    const confirmed = window.confirm(`彻底删除选中的 ${selectedTs.length} 条 tombstone 及相关记忆/link/wiki 记录？`);
    if (!confirmed) return;
    setLoading(true);
    let deletedCount = 0;
    let skippedCount = 0;
    const failures: string[] = [];
    try {
      for (const t of selectedTs) {
        try {
          await callMemory("hard-delete", { tombstone_id: t.id, memory_id: t.target_id, target_type: t.target_type, delete_related: true });
          deletedCount += 1;
        } catch (error) {
          const msg = error instanceof Error ? error.message : String(error);
          if (msg.includes("not found")) { skippedCount += 1; }
          else { failures.push(`${compactId(t.id) || t.id}: ${msg}`); }
        }
      }
      setSelected(null);
      setSelectedTombstoneIds(new Set());
      await refresh({ parts: ["tombstones", "inventory"], clearNotice: false });
      if (failures.length > 0) {
        setWarn(`已彻底删除 ${deletedCount} 条，跳过 ${skippedCount} 条，失败 ${failures.length} 条：${failures.slice(0, 2).join("；")}`);
      } else {
        setOk(`已彻底删除 ${deletedCount} 条 tombstone${skippedCount ? `，跳过 ${skippedCount} 条已删除项` : ""}`);
      }
    } finally { setLoading(false); }
  };

  const runDream = async () => {
    setLoading(true);
    setDreamStartedAtMs(Date.now());
    try {
      const report = await callMemory<DreamRunReport>("dream-run", {
        limit: 20, min_confidence: 0.7, use_provider: useProvider,
        advanced_dreaming: advancedDreaming, execution_policy: "semi_auto"
      });
      await refresh({ clearNotice: false });
      setOk(dreamRunMessage(report, useProvider, advancedDreaming));
    } catch (error) { setError(error); }
    finally { setDreamStartedAtMs(null); setLoading(false); }
  };

  const applyDreamProposal = async (proposalId: string) => {
    setLoading(true);
    try {
      await callMemory("apply-dream-proposal", { proposal_id: proposalId });
      setOk("整理提案已应用");
      await refresh({ parts: ["maintenance", "inventory", "profile"], clearNotice: false });
    } catch (error) { setError(error); }
    finally { setLoading(false); }
  };

  const rejectDreamProposal = async (proposalId: string) => {
    setLoading(true);
    try {
      await callMemory("reject-dream-proposal", { proposal_id: proposalId, reason: proposalRejectReason.trim() || "operator_rejected" });
      setOk("整理提案已拒绝");
      await refresh({ parts: ["maintenance"], clearNotice: false });
    } catch (error) { setError(error); }
    finally { setLoading(false); }
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
      await refresh({ parts: ["plans"], clearNotice: false });
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
      await refresh({ parts: ["plans"], clearNotice: false });
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
      await refresh({ parts: ["plans"], clearNotice: false });
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
      await refresh({ parts: ["plans"], clearNotice: false });
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
      await refresh({ parts: ["plans"], clearNotice: false });
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
      await refresh({ parts: ["plans"], clearNotice: false });
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
    } catch (error) { setError(error); }
    finally { setLoading(false); }
  };

  const saveProviderConfig = async () => {
    setLoading(true);
    try {
      const result = await callMemory<ProviderConfigResult>("save-provider-config", providerSavePayload(providerForm));
      setProviderConfig(result);
      setProviderForm(providerFormFromConfig(result));
      setOk("Provider 配置已保存；Run Dream 将使用服务端配置。");
    } catch (error) { setError(error); }
    finally { setLoading(false); }
  };

  const saveAutoDreamConfig = async () => {
    setLoading(true);
    try {
      const result = await callMemory<AutoDreamStatusResult>("save-auto-dream-config", autoDreamSavePayload(autoDreamForm));
      setAutoDreamStatus(result);
      setAutoDreamForm(autoDreamFormFromStatus(result));
      setOk("自动 Dreaming 配置已保存。");
    } catch (error) { setError(error); }
    finally { setLoading(false); }
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

  const navItemClass = (key: TabKey) => {
    const classes = ["nav-item"];
    if (activeTab === key) classes.push("active");
    return classes.join(" ");
  };

  const openEditor = (item: MemoryItem | null) => {
    setEditorItem(item);
    setEditorOpen(true);
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
              {item.key === "candidates" && conflictCandidates.length > 0 ? <span className="badge bad" style={{marginLeft: 4, fontSize: 11}}>{conflictCandidates.length} 冲突</span> : null}
              {item.key === "tombstones" && tombstones.length > 0 ? <b>{tombstones.length}</b> : null}
            </button>
          ))}
        </nav>
        {/* Show conflict badge in default mode too */}
        {!advancedMode && conflictCandidates.length > 0 ? (
          <button className="nav-item conflict-alert" onClick={() => { setAdvancedMode(true); setActiveTab("candidates"); }}>
            <GitMerge size={18} />
            <span>{conflictCandidates.length} 条冲突待解决</span>
          </button>
        ) : null}
        <div className="mode-card">
          <div>
            <strong>高级模式</strong>
            <span>{advancedMode ? "显示候选、Dream、墓碑和 JSON" : "默认隐藏调试和维护细节"}</span>
          </div>
          <label className="switch">
            <input type="checkbox" checked={advancedMode} onChange={(e) => setAdvancedMode(e.target.checked)} />
            <span />
          </label>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="status-row">
            <StatusDot ok={serviceOk} />
            <strong>Service:</strong>
            <span>{serviceOk ? "Running" : "服务离线"}</span>
          </div>
          <div className="divider" />
          <div className="endpoint">HTTP: {apiBase}</div>
          <button className="ghost-button" onClick={() => refreshInventory()} disabled={loading}>
            {loading ? <Loader2 className="spin" size={16} /> : <RefreshCcw size={16} />}
            Refresh
          </button>
          <button className="ghost-button" onClick={() => setIngestOpen(true)}>
            <MessageSquare size={16} />
            录入事件
          </button>
          <button className="ghost-button" onClick={() => openEditor(null)}>
            <Edit3 size={16} />
            新建记忆
          </button>
          <button className="primary-button" onClick={() => setComposerOpen(true)}>
            <Plus size={16} />
            保存记忆
          </button>
        </header>

        {notice ? (
          <div className={`notice ${notice.tone}`}>
            <span>{notice.text}</span>
            <button onClick={() => setNotice(null)}><X size={14} /></button>
          </div>
        ) : null}

        <section className={advancedMode ? "dashboard-grid advanced-layout" : "dashboard-grid workbench-layout"}>
          <div className="main-column">
            {/* L0 Profile Card */}
            {activeTab === "memories" && profile?.summary ? (
              <ProfileCard profile={profile} />
            ) : null}

            {activeTab === "memories" ? (
              <SearchPanel
                query={query}
                setQuery={setQuery}
                uidFilter={uidFilter}
                setUidFilter={setUidFilter}
                kindFilter={kindFilter}
                setKindFilter={setKindFilter}
                statusFilter={statusFilter}
                setStatusFilter={setStatusFilter}
                searchScope={searchScope}
                setSearchScope={setSearchScope}
                dimensionFilter={dimensionFilter}
                setDimensionFilter={setDimensionFilter}
                onSearch={searchMemory}
                onRefresh={refreshInventory}
              />
            ) : null}
            {activeTab === "memories" ? (
              <>
                <MemoryTable items={pagedItems} selectedId={selected?.id} uidFilter={uidFilter} dreamStatus={dreamStatus} advancedMode={advancedMode} onSelect={readMemory} onEdit={openEditor} />
                <Pagination page={page} totalPages={totalPages} totalItems={activeItems.length} onPageChange={setPage} />
              </>
            ) : null}
            {activeTab === "preview" ? (
              <PreviewPanel
                intent={previewIntent}
                setIntent={setPreviewIntent}
                scope={previewScope}
                setScope={setPreviewScope}
                context={previewContext}
                recall={previewRecall}
                loading={previewLoading}
                onRun={runPreview}
              />
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
                loading={loading}
                onPromote={promoteCandidate}
                onReject={rejectCandidate}
                onSelect={readMemory}
                onResolveConflict={resolveConflict}
                onBatchPromote={batchPromoteCandidates}
                onBatchReject={batchRejectCandidates}
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
                apiBase={apiBase} setApiBase={setApiBase}
                source={source} setSource={setSource}
                useProvider={useProvider} setUseProvider={setUseProvider}
                advancedDreaming={advancedDreaming} setAdvancedDreaming={setAdvancedDreaming}
                providerConfig={providerConfig} providerForm={providerForm} setProviderForm={setProviderForm}
                autoDreamStatus={autoDreamStatus} autoDreamForm={autoDreamForm} setAutoDreamForm={setAutoDreamForm}
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
              versions={versions}
              showVersions={showVersions}
              onTombstone={() => curateSelected("tombstone")}
              onForget={() => curateSelected("forget")}
              onLoadVersions={loadVersions}
              onEdit={openEditor}
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
          factText={factText} setFactText={setFactText}
          observationText={observationText} setObservationText={setObservationText}
          source={source} setSource={setSource}
          uidFilter={uidFilter} loading={loading}
          onSubmit={submitMemory} onClose={() => setComposerOpen(false)}
        />
        <IngestEventDrawer
          open={ingestOpen}
          loading={loading}
          useProvider={useProvider}
          onSubmit={ingestEvent}
          onClose={() => setIngestOpen(false)}
        />
        <PageEditorDrawer
          open={editorOpen}
          item={editorItem}
          loading={loading}
          onCreate={stableCreate}
          onUpdate={stableUpdate}
          onClose={() => { setEditorOpen(false); setEditorItem(null); }}
        />
      </main>
    </div>
  );
}

// ─── Profile Card ────────────────────────────────────────────────────────────

function ProfileCard({ profile }: { profile: L0Profile }) {
  const [expanded, setExpanded] = useState(false);
  const lines = (profile.summary || "").split("\n").filter(Boolean);
  const preview = lines.slice(0, 4);
  const hasMore = lines.length > 4;
  return (
    <section className="panel profile-card">
      <div className="panel-header compact">
        <div style={{display: "flex", alignItems: "center", gap: 8}}>
          <User size={18} />
          <h2>记忆画像</h2>
          <span className="badge blue">{profile.page_count || 0} 页</span>
        </div>
        {hasMore ? (
          <button className="ghost-button" onClick={() => setExpanded(!expanded)}>
            {expanded ? "收起" : "展开"}
          </button>
        ) : null}
      </div>
      <div className="profile-summary">
        {(expanded ? lines : preview).map((line, i) => (
          <div key={i} className="profile-line">{line}</div>
        ))}
      </div>
    </section>
  );
}

// ─── Memory Preview (Agent View) ─────────────────────────────────────────────

function PreviewPanel(props: {
  intent: string;
  setIntent: (v: string) => void;
  scope: string;
  setScope: (v: string) => void;
  context: ContextPreviewResult | null;
  recall: RecallPreviewResult | null;
  loading: boolean;
  onRun: () => void;
}) {
  const profileSummary = props.context?.profile?.summary || "";
  const snapshot = props.context?.snapshot || null;
  const cards = props.context?.cards || [];
  const recallItems = props.recall?.items || [];
  const pointers = snapshotPointers(snapshot);
  const hubs = snapshotHubs(snapshot);
  const tokenEstimate = estimateContextTokens(profileSummary, snapshot, cards);
  return (
    <section className="panel preview-panel">
      <div className="panel-header">
        <div>
          <h2>记忆预览 · Agent 视角</h2>
          <p>输入一个查询，查看 agent 实际会被注入的记忆上下文：L0 画像（每轮）+ L1 快照（默认）+ 召回卡片（按需）。</p>
        </div>
      </div>
      <div className="search-line">
        <div className="input-with-icon">
          <Eye size={18} />
          <input value={props.intent} onChange={(e) => props.setIntent(e.target.value)}
            placeholder="例如：用户偏好怎样的进度更新？（留空查看默认上下文）"
            onKeyDown={(e) => { if (e.key === "Enter") props.onRun(); }} />
        </div>
        <label className="preview-scope">
          范围
          <select value={props.scope} onChange={(e) => props.setScope(e.target.value)}>
            <option value="memory">记忆</option>
            <option value="sessions">会话</option>
            <option value="all">全部</option>
          </select>
        </label>
        <button className="primary-button" onClick={props.onRun} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
          预览
        </button>
      </div>

      {!props.context ? (
        <EmptyState text="点击预览，查看 agent 在这个查询下会拿到什么记忆。" />
      ) : (
        <>
          <div className="preview-token-strip">
            <Gauge size={16} />
            <span>预计注入</span>
            <strong>≈ {tokenEstimate} tokens</strong>
            <small>粗略估算；L0 每轮注入、L1 默认注入、卡片按需召回</small>
          </div>

          <div className="preview-layer">
            <div className="preview-layer-head">
              <span className="badge blue">L0 · 每轮注入</span>
              <h3>记忆画像</h3>
              <StatusBadge text={`${props.context.profile?.page_count || 0} 页`} />
            </div>
            {profileSummary ? (
              <div className="profile-summary">
                {profileSummary.split("\n").filter(Boolean).map((line, i) => (
                  <div className="profile-line" key={i}>{line}</div>
                ))}
              </div>
            ) : <EmptyState text="暂无画像。promote 一些稳定记忆后会自动蒸馏。" />}
          </div>

          <div className="preview-layer">
            <div className="preview-layer-head">
              <span className="badge good">L1 · 默认注入</span>
              <h3>快照路标</h3>
              <StatusBadge text={`${pointers.length} pointers · ${hubs.length} hubs`} />
            </div>
            {pointers.length === 0 && hubs.length === 0 ? (
              <EmptyState text="快照为空。运行一次 Dream 或刷新快照后生成。" />
            ) : (
              <div className="preview-pointer-list">
                {pointers.slice(0, 12).map((p, i) => (
                  <div className="preview-pointer" key={i}>
                    <code>{p.trigger || "—"}</code>
                    <ChevronRight size={13} />
                    <span>{p.title || p.target}</span>
                  </div>
                ))}
                {hubs.length > 0 ? <div className="preview-hubs">联想热点：{hubs.slice(0, 8).join("、")}</div> : null}
              </div>
            )}
          </div>

          <div className="preview-layer">
            <div className="preview-layer-head">
              <span className="badge neutral">L2 · 按需召回</span>
              <h3>上下文卡片</h3>
              <StatusBadge text={`${cards.length} cards`} />
            </div>
            {cards.length === 0 ? (
              <EmptyState text="没有命中上下文卡片。换个查询，或先写入/promote 相关记忆。" />
            ) : (
              <div className="preview-card-list">
                {cards.map((card, i) => (
                  <article className="preview-card" key={card.id || i}>
                    <div className="preview-card-head">
                      <strong>{card.title || card.claim || card.id}</strong>
                      <StatusBadge text={previewCardType(card)} />
                    </div>
                    <p>{card.content || card.claim || "-"}</p>
                    <small>{[card.dimension, card.scope, typeof card.confidence === "number" ? `conf ${card.confidence.toFixed(2)}` : ""].filter(Boolean).join(" · ")}</small>
                  </article>
                ))}
              </div>
            )}
          </div>

          {recallItems.length > 0 ? (
            <div className="preview-layer">
              <div className="preview-layer-head">
                <span className="badge">recall</span>
                <h3>联想召回</h3>
                <StatusBadge text={`${recallItems.length} items`} />
              </div>
              <div className="preview-card-list">
                {recallItems.slice(0, 8).map((item, i) => {
                  const it = item as ContextCardItem;
                  return (
                    <article className="preview-card" key={it.id || i}>
                      <div className="preview-card-head">
                        <strong>{it.title || it.claim || it.id}</strong>
                        <StatusBadge text={previewCardType(it)} />
                      </div>
                      <p>{it.content || it.claim || "-"}</p>
                      <small>{[it.dimension, it.scope].filter(Boolean).join(" · ")}</small>
                    </article>
                  );
                })}
              </div>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function previewCardType(card: ContextCardItem) {
  const t = String(card.type || "");
  if (t.includes("candidate")) return "candidate";
  if (t.includes("page")) return "page";
  return t || "memory";
}

function snapshotPointers(snapshot: Record<string, unknown> | null): Array<{ trigger: string; target: string; title: string }> {
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

function snapshotHubs(snapshot: Record<string, unknown> | null): string[] {
  const raw = snapshot ? (snapshot as { association_hubs?: unknown }).association_hubs : null;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((h) => {
      const obj = (h || {}) as Record<string, unknown>;
      return String(obj.title ?? obj.target ?? obj.page_id ?? "");
    })
    .filter(Boolean);
}

function estimateContextTokens(profileSummary: string, snapshot: Record<string, unknown> | null, cards: ContextCardItem[]): number {
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

// ─── Search Panel ────────────────────────────────────────────────────────────

function SearchPanel(props: {
  query: string;
  setQuery: (v: string) => void;
  uidFilter: string;
  setUidFilter: (v: string) => void;
  kindFilter: "all" | "candidate" | "page";
  setKindFilter: (v: "all" | "candidate" | "page") => void;
  statusFilter: string;
  setStatusFilter: (v: string) => void;
  searchScope: string;
  setSearchScope: (v: string) => void;
  dimensionFilter: string;
  setDimensionFilter: (v: string) => void;
  onSearch: () => void;
  onRefresh: () => void;
}) {
  return (
    <section className="panel search-panel">
      <div className="search-line">
        <div className="input-with-icon">
          <Search size={18} />
          <input value={props.query} onChange={(e) => props.setQuery(e.target.value)} placeholder="搜索记忆、偏好、事实..."
            onKeyDown={(e) => { if (e.key === "Enter") props.onSearch(); }} />
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
          搜索范围
          <select value={props.searchScope} onChange={(e) => props.setSearchScope(e.target.value)}>
            <option value="memory">记忆</option>
            <option value="sessions">会话</option>
            <option value="all">全部</option>
          </select>
        </label>
        <label>
          类型
          <select value={props.kindFilter} onChange={(e) => props.setKindFilter(e.target.value as "all" | "candidate" | "page")}>
            <option value="all">全部</option>
            <option value="page">稳定记忆</option>
            <option value="candidate">候选</option>
          </select>
        </label>
        <label>
          状态
          <select value={props.statusFilter} onChange={(e) => props.setStatusFilter(e.target.value)}>
            <option value="">全部</option>
            <option value="active">active</option>
            <option value="draft">draft</option>
            <option value="promoted">promoted</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <label>
          维度
          <select value={props.dimensionFilter} onChange={(e) => props.setDimensionFilter(e.target.value)}>
            <option value="">全部维度</option>
            {DIMENSIONS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label>
          UID
          <input value={props.uidFilter} onChange={(e) => props.setUidFilter(e.target.value)} placeholder="user_123 或 user:user_123" />
        </label>
      </div>
    </section>
  );
}

// ─── Pagination ──────────────────────────────────────────────────────────────

function Pagination({ page, totalPages, totalItems, onPageChange }: {
  page: number; totalPages: number; totalItems: number; onPageChange: (p: number) => void;
}) {
  if (totalItems <= 20) return null;
  return (
    <div className="pagination">
      <button className="ghost-button" disabled={page <= 0} onClick={() => onPageChange(page - 1)}>上一页</button>
      <span>{page + 1} / {totalPages} ({totalItems} 条)</span>
      <button className="ghost-button" disabled={page >= totalPages - 1} onClick={() => onPageChange(page + 1)}>下一页</button>
    </div>
  );
}

// ─── Memory Table ────────────────────────────────────────────────────────────

function MemoryTable({
  items, selectedId, uidFilter, dreamStatus, advancedMode, onSelect, onEdit
}: {
  items: MemoryItem[];
  selectedId?: string;
  uidFilter: string;
  dreamStatus: DreamStatusResult | null;
  advancedMode: boolean;
  onSelect: (item: MemoryItem) => void;
  onEdit: (item: MemoryItem) => void;
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
          <div className={selectedId === item.id ? "table-row active" : "table-row"} key={`${item.type}:${item.id}`}>
            <button className="table-row-main" onClick={() => onSelect(item)}>
              <span className="score">{formatConfidence(item.confidence)}</span>
              <span>
                <strong>{itemTitle(item)}</strong>
                <small>{item.dimension ? `[${item.dimension}] ` : ""}{item.scope || item.id}</small>
              </span>
              <StatusBadge text={item.type} />
              {advancedMode ? <AuditResultBadge item={item} review={reviewForItem(item, reviewResults)} /> : null}
              <StatusBadge text={item.status || "unknown"} />
              <span className="time">{formatTime(item.updated_at || item.created_at)}</span>
              <ChevronRight size={16} />
            </button>
            {item.type === "page" ? (
              <button className="table-row-edit" onClick={(e) => { e.stopPropagation(); onEdit(item); }} title="编辑">
                <Edit3 size={14} />
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── Memory Detail ───────────────────────────────────────────────────────────

function MemoryDetail(props: {
  selected: MemoryItem | null;
  links: MemoryLinksResult | null;
  provenance: MemoryProvenanceResult | null;
  dreamStatus: DreamStatusResult | null;
  advancedMode: boolean;
  tombstoneReason: string;
  setTombstoneReason: (v: string) => void;
  versions: PageVersion[];
  showVersions: boolean;
  onTombstone: () => void;
  onForget: () => void;
  onLoadVersions: (id: string) => void;
  onEdit: (item: MemoryItem) => void;
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
            <label>类型</label><strong>{item.type}</strong>
            <label>状态</label><strong>{item.status || "-"}</strong>
            <label>范围</label><strong>{item.scope || "-"}</strong>
            <label>置信度</label><strong>{formatConfidence(item.confidence)}</strong>
            {item.dimension ? <><label>维度</label><strong>{item.dimension}</strong></> : null}
            <label>更新时间</label><strong>{formatDate(item.updated_at || item.created_at)}</strong>
          </div>
          <div className="content-box">{item.content || item.claim || item.title || "-"}</div>
          <ProvenanceTimeline provenance={props.provenance} />
          <div className="detail-actions">
            <button className="ghost-button" onClick={() => navigator.clipboard?.writeText(item.content || item.claim || item.title || item.id)}>
              <ClipboardList size={15} />
              复制内容
            </button>
            {item.type === "page" ? (
              <>
                <button className="ghost-button" onClick={() => props.onEdit(item)}>
                  <Edit3 size={15} />
                  编辑
                </button>
                <button className="ghost-button" onClick={() => props.onLoadVersions(item.id)}>
                  <History size={15} />
                  版本历史
                </button>
              </>
            ) : null}
          </div>
          {/* Version History */}
          {props.showVersions ? (
            <VersionHistory versions={props.versions} />
          ) : null}
          {props.advancedMode ? (
            <>
              <AuditDetail item={item} review={review} />
              <SourceIds item={item} />
              <JsonBlock title="Metadata / Evidence" value={item.metadata || item.evidence || {}} />
              <JsonBlock title="Links" value={props.links || { outgoing: [], incoming: [] }} />
              <div className="danger-actions">
                <input value={props.tombstoneReason} onChange={(e) => props.setTombstoneReason(e.target.value)} placeholder="tombstone reason" />
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

// ─── Version History ─────────────────────────────────────────────────────────

function VersionHistory({ versions }: { versions: PageVersion[] }) {
  if (versions.length === 0) {
    return (
      <div className="version-history">
        <h3>版本历史</h3>
        <div className="timeline-empty">暂无版本记录。</div>
      </div>
    );
  }
  return (
    <div className="version-history">
      <h3>版本历史 ({versions.length})</h3>
      <div className="version-list">
        {versions.map((v, i) => (
          <details key={v.id || i} className="version-entry">
            <summary>
              <span className="badge neutral">{v.change_reason || "unknown"}</span>
              <span>{v.changed_by || "system"}</span>
              <span className="time">{formatDate(v.created_at)}</span>
            </summary>
            <pre className="version-snapshot">{JSON.stringify(v.snapshot_data || {}, null, 2)}</pre>
          </details>
        ))}
      </div>
    </div>
  );
}

// ─── Ingest Event Drawer ─────────────────────────────────────────────────────

type IngestEventForm = {
  text: string;
  source: string;
  actor: string;
  eventType: string;
  scope: string;
  autoPromote: boolean;
  useProvider: boolean;
};

function IngestEventDrawer({ open, loading, useProvider, onSubmit, onClose }: {
  open: boolean;
  loading: boolean;
  useProvider: boolean;
  onSubmit: (form: IngestEventForm) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<IngestEventForm>({
    text: "", source: "webui", actor: "", eventType: "message", scope: "",
    autoPromote: false, useProvider: false
  });
  const set = <K extends keyof IngestEventForm>(k: K, v: IngestEventForm[K]) => setForm({ ...form, [k]: v });

  if (!open) return null;
  return (
    <div className="drawer-layer" role="dialog" aria-modal="true" aria-label="录入事件">
      <button className="drawer-backdrop" aria-label="关闭" onClick={onClose} />
      <aside className="memory-drawer">
        <div className="drawer-header">
          <div>
            <h2>录入事件</h2>
            <p>输入对话或事件文本，系统会自动提取 fact/observation 生成记忆候选。</p>
          </div>
          <button className="ghost-button icon-only" onClick={onClose}><X size={16} /></button>
        </div>
        <label>
          事件内容 *
          <textarea value={form.text} onChange={(e) => set("text", e.target.value)}
            placeholder="例如：用户说他喜欢简洁的代码风格，不要过度封装。" rows={5} />
        </label>
        <div className="provider-grid">
          <label>
            事件类型
            <select value={form.eventType} onChange={(e) => set("eventType", e.target.value)}>
              <option value="message">message</option>
              <option value="observation">observation</option>
              <option value="feedback">feedback</option>
              <option value="system">system</option>
            </select>
          </label>
          <label>来源 <input value={form.source} onChange={(e) => set("source", e.target.value)} /></label>
          <label>Actor <input value={form.actor} onChange={(e) => set("actor", e.target.value)} placeholder="user / assistant" /></label>
          <label>Scope <input value={form.scope} onChange={(e) => set("scope", e.target.value)} placeholder="user:xxx 或留空" /></label>
        </div>
        <label className="checkbox-row">
          <input type="checkbox" checked={form.autoPromote} onChange={(e) => set("autoPromote", e.target.checked)} />
          <span><strong>自动提升</strong><small>高置信候选自动进入稳定记忆</small></span>
        </label>
        <label className="checkbox-row">
          <input type="checkbox" checked={form.useProvider} onChange={(e) => set("useProvider", e.target.checked)} />
          <span><strong>使用模型提取</strong><small>调用 provider 进行智能记忆提取{useProvider ? "" : "（需先在设置中配置）"}</small></span>
        </label>
        <div className="settings-actions">
          <button className="primary-button" onClick={() => onSubmit(form)} disabled={loading || !form.text.trim()}>
            {loading ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
            录入事件
          </button>
        </div>
      </aside>
    </div>
  );
}

// ─── Page Editor Drawer ──────────────────────────────────────────────────────

type PageEditorForm = {
  title: string;
  content: string;
  scope: string;
  confidence: string;
  dimension: string;
};

function PageEditorDrawer({ open, item, loading, onCreate, onUpdate, onClose }: {
  open: boolean;
  item: MemoryItem | null;
  loading: boolean;
  onCreate: (form: PageEditorForm) => void;
  onUpdate: (id: string, form: PageEditorForm) => void;
  onClose: () => void;
}) {
  const isEdit = item !== null;
  const [form, setForm] = useState<PageEditorForm>({
    title: "", content: "", scope: "global", confidence: "0.7", dimension: ""
  });
  const set = <K extends keyof PageEditorForm>(k: K, v: PageEditorForm[K]) => setForm({ ...form, [k]: v });

  useEffect(() => {
    if (item) {
      setForm({
        title: item.title || item.claim || "",
        content: item.content || item.claim || "",
        scope: item.scope || "global",
        confidence: String(item.confidence ?? 0.7),
        dimension: item.dimension || ""
      });
    } else {
      setForm({ title: "", content: "", scope: "global", confidence: "0.7", dimension: "" });
    }
  }, [item, open]);

  if (!open) return null;
  return (
    <div className="drawer-layer" role="dialog" aria-modal="true" aria-label={isEdit ? "编辑记忆" : "新建记忆"}>
      <button className="drawer-backdrop" aria-label="关闭" onClick={onClose} />
      <aside className="memory-drawer">
        <div className="drawer-header">
          <div>
            <h2>{isEdit ? "编辑稳定记忆" : "新建稳定记忆"}</h2>
            <p>{isEdit ? `正在编辑 ${compactId(item.id)}` : "直接创建稳定记忆页，跳过候选流程。"}</p>
          </div>
          <button className="ghost-button icon-only" onClick={onClose}><X size={16} /></button>
        </div>
        <label>标题 * <input value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="记忆标题" /></label>
        <label>内容 * <textarea value={form.content} onChange={(e) => set("content", e.target.value)} placeholder="记忆内容" rows={5} /></label>
        <div className="provider-grid">
          <label>Scope <input value={form.scope} onChange={(e) => set("scope", e.target.value)} placeholder="global" /></label>
          <label>置信度 <input type="number" min="0" max="1" step="0.1" value={form.confidence} onChange={(e) => set("confidence", e.target.value)} /></label>
          <label>
            维度
            <select value={form.dimension} onChange={(e) => set("dimension", e.target.value)}>
              <option value="">未指定</option>
              {DIMENSIONS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
        </div>
        <div className="settings-actions">
          <button className="primary-button" onClick={() => isEdit ? onUpdate(item.id, form) : onCreate(form)} disabled={loading || !form.title.trim() || !form.content.trim()}>
            {loading ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
            {isEdit ? "保存修改" : "创建记忆"}
          </button>
        </div>
      </aside>
    </div>
  );
}

// ─── Candidate Review with Conflict Resolution ──────────────────────────────

function CandidateReview(props: {
  candidates: MemoryItem[];
  dreamStatus: DreamStatusResult | null;
  rejectReason: string;
  setRejectReason: (v: string) => void;
  loading: boolean;
  onPromote: (id: string) => void;
  onReject: (id: string) => void;
  onSelect: (item: MemoryItem) => void;
  onResolveConflict: (candidateId: string, resolution: string) => void;
  onBatchPromote: (ids: string[]) => void;
  onBatchReject: (ids: string[]) => void;
}) {
  const reviewResults = dreamReviewResultMap(props.dreamStatus);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const reviewable = props.candidates.filter((c) => isReviewableCandidate(c));
  const conflicts = props.candidates.filter((c) => String(c.status || "").includes("conflict"));
  const toggleId = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  };
  const toggleAll = (checked: boolean) => {
    setSelectedIds(checked ? new Set(reviewable.map((c) => c.id)) : new Set());
  };
  const selArray = [...selectedIds].filter((id) => reviewable.some((c) => c.id === id));

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>候选审核</h2>
          <p>Promote 通过后会进入记忆页；这里保留待审核、拒绝和需复核的候选。</p>
        </div>
        <input value={props.rejectReason} onChange={(e) => props.setRejectReason(e.target.value)} placeholder="reject reason" />
      </div>

      {/* Conflict Resolution Section */}
      {conflicts.length > 0 ? (
        <div className="conflict-section">
          <div className="conflict-section-header">
            <GitMerge size={18} />
            <h3>冲突待解决 ({conflicts.length})</h3>
          </div>
          {conflicts.map((candidate) => (
            <ConflictCard
              key={candidate.id}
              candidate={candidate}
              loading={props.loading}
              onResolve={props.onResolveConflict}
              onSelect={() => props.onSelect(candidate)}
            />
          ))}
        </div>
      ) : null}

      {/* Batch Actions */}
      {reviewable.length > 0 ? (
        <div className="batch-actions">
          <label className="tombstone-select-all">
            <input type="checkbox" checked={selectedIds.size > 0 && selectedIds.size >= reviewable.length}
              onChange={(e) => toggleAll(e.target.checked)} />
            <span>全选待审 ({reviewable.length})</span>
          </label>
          {selArray.length > 0 ? (
            <>
              <button className="success-button" onClick={() => props.onBatchPromote(selArray)} disabled={props.loading}>
                <Check size={15} /> 批量通过 ({selArray.length})
              </button>
              <button className="danger-button" onClick={() => props.onBatchReject(selArray)} disabled={props.loading}>
                <Trash2 size={15} /> 批量拒绝 ({selArray.length})
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      <div className="candidate-list">
        {props.candidates.length === 0 ? <EmptyState text="暂无待处理或需查看原因的候选记忆。" /> : null}
        {props.candidates.map((candidate) => {
          const isConflict = String(candidate.status || "").includes("conflict");
          if (isConflict) return null; // already shown in conflict section
          const reviewableItem = isReviewableCandidate(candidate);
          return (
            <article className="candidate-row" key={candidate.id}>
              {reviewableItem ? (
                <input type="checkbox" checked={selectedIds.has(candidate.id)}
                  onChange={(e) => toggleId(candidate.id, e.target.checked)} />
              ) : <span style={{width: 18}} />}
              <button onClick={() => props.onSelect(candidate)}>
                <strong>{candidate.claim || candidate.title || candidate.id}</strong>
                <span>{candidate.dimension || candidate.scope || "global"} · {formatTime(candidate.created_at)}</span>
                <AuditResultBadge item={candidate} review={reviewForItem(candidate, reviewResults)} />
              </button>
              <div className="candidate-actions">
                {reviewableItem ? (
                  <>
                    <button className="success-button" onClick={() => props.onPromote(candidate.id)}>
                      <Check size={15} /> Promote
                    </button>
                    <button className="danger-button" onClick={() => props.onReject(candidate.id)}>
                      <Trash2 size={15} /> Reject
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

// ─── Conflict Card ───────────────────────────────────────────────────────────

function ConflictCard({ candidate, loading, onResolve, onSelect }: {
  candidate: MemoryItem;
  loading: boolean;
  onResolve: (candidateId: string, resolution: string) => void;
  onSelect: () => void;
}) {
  const card = candidate.conflict_card || candidate.metadata?.conflict_card as ConflictCard | undefined;
  const options: ConflictOption[] = card?.options || [
    { resolution: "keep_new", label: "保留新记忆", description: "用候选替换现有记忆" },
    { resolution: "keep_old", label: "保留旧记忆", description: "拒绝此候选" },
    { resolution: "keep_both", label: "都保留", description: "两条记忆都保留" }
  ];
  return (
    <div className="conflict-card">
      <div className="conflict-card-header">
        <button className="ghost-button" onClick={onSelect}>
          <strong>{candidate.claim || candidate.title || candidate.id}</strong>
        </button>
        <StatusBadge text="conflict" />
      </div>
      {card ? (
        <div className="conflict-comparison">
          {card.candidate_claim ? (
            <div className="conflict-side">
              <span className="badge blue">新候选</span>
              <p>{card.candidate_claim}</p>
            </div>
          ) : null}
          {card.existing_content ? (
            <div className="conflict-side">
              <span className="badge good">现有记忆</span>
              <p>{card.existing_content}</p>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="conflict-actions">
        {options.map((opt) => (
          <button key={opt.resolution}
            className={opt.resolution === "keep_new" ? "success-button" : opt.resolution === "keep_old" ? "ghost-button" : "ghost-button"}
            onClick={() => onResolve(candidate.id, opt.resolution)}
            disabled={loading}
            title={opt.description}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Remaining Components (unchanged logic, cleaned formatting) ──────────────

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

function SourceIds({ item }: { item: MemoryItem }) {
  const ids = [["run_id", item.run_id], ["source_candidate_id", item.source_candidate_id]].filter(([, v]) => Boolean(v));
  if (ids.length === 0) return null;
  return (
    <div className="source-ids">
      {ids.map(([label, value]) => <div key={label}><span>{label}</span><code>{value}</code></div>)}
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
            <small>{event.source || "unknown"} · 发生 {formatDate(event.event_at)} · 记录 {formatDate(event.observed_at)}</small>
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
  open: boolean; factText: string; setFactText: (v: string) => void;
  observationText: string; setObservationText: (v: string) => void;
  source: string; setSource: (v: string) => void;
  uidFilter: string; loading: boolean; onSubmit: () => void; onClose: () => void;
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
          <button className="ghost-button icon-only" onClick={props.onClose}><X size={16} /></button>
        </div>
        <Composer
          factText={props.factText} setFactText={props.setFactText}
          observationText={props.observationText} setObservationText={props.setObservationText}
          source={props.source} setSource={props.setSource}
          uidFilter={props.uidFilter} loading={props.loading} onSubmit={props.onSubmit}
        />
      </aside>
    </div>
  );
}

function Composer(props: {
  factText: string; setFactText: (v: string) => void;
  observationText: string; setObservationText: (v: string) => void;
  source: string; setSource: (v: string) => void;
  uidFilter: string; loading?: boolean; onSubmit: () => void;
}) {
  const writeScope = scopeFromUidFilter(props.uidFilter) || "global";
  return (
    <section className="panel composer">
      <div className="panel-header compact">
        <h2>写入记忆</h2>
        <StatusBadge text={writeScope} />
      </div>
      <label>Fact <textarea value={props.factText} onChange={(e) => props.setFactText(e.target.value)} placeholder="例如：用户偏好简洁的实现进度更新。" /></label>
      <label>Observation <textarea value={props.observationText} onChange={(e) => props.setObservationText(e.target.value)} placeholder="例如：本次任务需要保留 WebUI 构建产物。" /></label>
      <div className="composer-row">
        <input value={props.source} onChange={(e) => props.setSource(e.target.value)} placeholder="source" />
        <button className="primary-button" onClick={props.onSubmit} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
          Add Memory
        </button>
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
  tombstones: MemoryTombstone[]; selectedTombstoneIds: Set<string>; loading: boolean;
  onToggleSelection: (id: string, sel: boolean) => void; onToggleAll: (sel: boolean) => void;
  onSelectTarget: (item: MemoryItem) => void; onForget: (t: MemoryTombstone) => void;
  onHardDelete: (t: MemoryTombstone) => void; onHardDeleteSelected: () => void;
}) {
  const selectedCount = props.tombstones.filter((t) => props.selectedTombstoneIds.has(t.id)).length;
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
          <input type="checkbox" checked={allSelected} disabled={props.loading || props.tombstones.length === 0} onChange={(e) => props.onToggleAll(e.target.checked)} />
          <span>全选</span>
        </label>
        <button className="danger-button strong-danger" onClick={props.onHardDeleteSelected} disabled={props.loading || selectedCount === 0}>
          <X size={15} /> 彻底删除选中
        </button>
      </div>
      <div className="tombstone-list">
        {props.tombstones.length === 0 ? <EmptyState text="暂无 tombstone。" /> : null}
        {props.tombstones.map((t) => (
          <article className="tombstone-card" key={t.id}>
            <label className="tombstone-select" title="选择 tombstone">
              <input type="checkbox" aria-label={`选择 tombstone ${t.id}`} checked={props.selectedTombstoneIds.has(t.id)} disabled={props.loading}
                onChange={(e) => props.onToggleSelection(t.id, e.target.checked)} />
            </label>
            <div className="tombstone-main">
              <div className="tombstone-title">
                <StatusBadge text={t.target_type} />
                <strong>{t.reason || "unspecified"}</strong>
                <span>{formatDate(t.created_at)}</span>
              </div>
              <div className="tombstone-target"><span>Target</span><code>{t.target_id}</code></div>
              <p>{t.summary || t.rule || t.target_hash || "No tombstone summary."}</p>
              <div className="tombstone-meta">
                <code>{t.id}</code>
                {t.evidence_run_id ? <code>{t.evidence_run_id}</code> : null}
                {t.rule ? <span>{t.rule}</span> : null}
              </div>
              <JsonBlock title="Metadata" value={t.metadata || {}} />
            </div>
            <div className="tombstone-actions">
              <button className="ghost-button" onClick={() => props.onSelectTarget(tombstoneTargetItem(t))} disabled={props.loading}>
                <ChevronRight size={15} /> 查看目标
              </button>
              <button className="danger-button" onClick={() => props.onForget(t)} disabled={props.loading}>
                <Trash2 size={15} /> Forget 擦除
              </button>
              <button className="danger-button strong-danger" onClick={() => props.onHardDelete(t)} disabled={props.loading}>
                <X size={15} /> 彻底删除
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function MaintenancePanel(props: {
  health: MemoryHealthResult | null; dreamStatus: DreamStatusResult | null;
  snapshot: SnapshotResult | null; tombstones: MemoryTombstone[];
  proposals: DreamProposal[]; useProvider: boolean; advancedDreaming: boolean;
  advancedMode: boolean; loading: boolean; dreamElapsedS: number | null;
  proposalRejectReason: string; setProposalRejectReason: (v: string) => void;
  onRunDream: () => void; onCompileSnapshot: () => void;
  onApplyProposal: (id: string) => void; onRejectProposal: (id: string) => void;
}) {
  const latestDurationS = latestDreamDurationS(props.dreamStatus);
  const pendingProposals = props.proposals.filter((p) => p.status === "pending");
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
            {props.dreamElapsedS !== null ? `运行中 ${formatDuration(props.dreamElapsedS)}` : props.useProvider ? "模型 Dream" : "运行 Dream"}
          </button>
          <button className="ghost-button" onClick={props.onCompileSnapshot} disabled={props.loading}>
            <RefreshCcw size={16} /> 刷新快照
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
            proposals={props.proposals} rejectReason={props.proposalRejectReason}
            setRejectReason={props.setProposalRejectReason} loading={props.loading}
            onApply={props.onApplyProposal} onReject={props.onRejectProposal}
          />
          <div className="maintenance-grid">
            <JsonBlock title="Health" value={props.health || {}} />
            <JsonBlock title="Dream Status" value={props.dreamStatus || {}} />
            <JsonBlock title="Snapshot" value={props.snapshot || {}} />
            <JsonBlock title="Tombstones" value={props.tombstones} />
          </div>
        </>
      ) : (
        <MaintenanceSummary health={props.health} dreamStatus={props.dreamStatus} snapshot={props.snapshot}
          tombstones={props.tombstones} proposals={props.proposals} useProvider={props.useProvider} />
      )}
    </section>
  );
}

function DreamProposalsPanel(props: {
  proposals: DreamProposal[]; rejectReason: string; setRejectReason: (v: string) => void;
  loading: boolean; onApply: (id: string) => void; onReject: (id: string) => void;
}) {
  return (
    <div className="dream-proposals">
      <div className="dream-proposals-header">
        <div><h3>整理提案</h3><p>高级 Dreaming 的高风险整理动作会停在这里，确认后才会改稳定记忆。</p></div>
        <StatusBadge text={`${props.proposals.length} 条提案`} />
      </div>
      <label>拒绝原因 <input value={props.rejectReason} onChange={(e) => props.setRejectReason(e.target.value)} /></label>
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
                    <Check size={15} /> 通过
                  </button>
                  <button className="danger-button" disabled={props.loading} onClick={() => props.onReject(proposal.id)}>
                    <X size={15} /> 拒绝
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
  health: MemoryHealthResult | null; dreamStatus: DreamStatusResult | null;
  snapshot: SnapshotResult | null; tombstones: MemoryTombstone[];
  proposals: DreamProposal[]; useProvider: boolean;
}) {
  const healthCards = Array.isArray(props.health?.cards) ? props.health.cards.length : 0;
  const latestDuration = latestDreamDurationS(props.dreamStatus);
  const pendingProposals = props.proposals.filter((p) => p.status === "pending").length;
  return (
    <div className="maintenance-summary">
      <div className="summary-card"><Sparkles size={18} /><span>模型审核</span><strong>{props.useProvider ? "已启用" : "未启用"}</strong><small>{props.useProvider ? "Run Dream 会调用 provider" : "Dream 只生成报告和快照"}</small></div>
      <div className="summary-card"><FileClock size={18} /><span>最近 Dream</span><strong>{latestDuration === null ? "暂无" : formatDuration(latestDuration)}</strong><small>高级模式可查看完整报告</small></div>
      <div className="summary-card"><Gauge size={18} /><span>健康卡片</span><strong>{healthCards}</strong><small>用于发现重复、冲突和维护 backlog</small></div>
      <div className="summary-card"><Archive size={18} /><span>整理提案</span><strong>{pendingProposals}</strong><small>{props.tombstones.length} 条删除痕迹 · {props.snapshot?.exists ? "Snapshot 已存在" : "Snapshot 未生成"}</small></div>
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
      <div className="dream-rejects-header"><h3>审核原因</h3><StatusBadge text={`${items.length} reviewed`} /></div>
      <div className="dream-reject-list">
        {items.map((item, i) => (
          <div className="dream-reject-row" key={`${item.action_id || item.candidate_id || "reject"}:${i}`}>
            <code>{auditReviewLabel(item)} · {item.candidate_id || item.page_id || item.action_id || "unknown candidate"}</code>
            <p>{item.reason || "unspecified"}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function SettingsPanel(props: {
  apiBase: string; setApiBase: (v: string) => void;
  source: string; setSource: (v: string) => void;
  useProvider: boolean; setUseProvider: (v: boolean) => void;
  advancedDreaming: boolean; setAdvancedDreaming: (v: boolean) => void;
  providerConfig: ProviderConfigResult | null;
  providerForm: ProviderFormState; setProviderForm: (v: ProviderFormState) => void;
  autoDreamStatus: AutoDreamStatusResult | null;
  autoDreamForm: AutoDreamFormState; setAutoDreamForm: (v: AutoDreamFormState) => void;
  onSaveProviderConfig: () => void; onSaveAutoDreamConfig: () => void; loading: boolean;
}) {
  const setProviderField = <K extends keyof ProviderFormState>(field: K, value: ProviderFormState[K]) => {
    props.setProviderForm({ ...props.providerForm, [field]: value });
  };
  const setAutoDreamField = <K extends keyof AutoDreamFormState>(field: K, value: AutoDreamFormState[K]) => {
    props.setAutoDreamForm({ ...props.autoDreamForm, [field]: value });
  };
  return (
    <section className="panel settings-panel">
      <div className="panel-header"><div><h2>设置</h2><p>本地 API、Source 和维护模型配置。</p></div><ShieldCheck size={22} /></div>
      <label>API Base <input value={props.apiBase} onChange={(e) => props.setApiBase(e.target.value)} /></label>
      <label>默认 Source <input value={props.source} onChange={(e) => props.setSource(e.target.value)} /></label>
      <div className="settings-hint">HTTP API 默认绑定 127.0.0.1 且不做鉴权，请仅在可信本地网络使用，不要把端口暴露到公网。</div>
      <div className="provider-status-row">
        <StatusBadge text={providerStatusText(props.providerConfig)} />
        <code>{props.providerConfig?.save_path || "config.json"}</code>
      </div>
      <div className="provider-grid">
        <label>Provider <select value={props.providerForm.provider} onChange={(e) => setProviderField("provider", e.target.value)}><option value="openai-compatible">openai-compatible</option></select></label>
        <label>Base URL <input value={props.providerForm.baseUrl} onChange={(e) => setProviderField("baseUrl", e.target.value)} placeholder="https://api.openai.com/v1" /></label>
        <label>Model <input value={props.providerForm.model} onChange={(e) => setProviderField("model", e.target.value)} placeholder="gpt-4.1-mini" /></label>
        <label>API Key <input type="password" autoComplete="off" value={props.providerForm.apiKey} onChange={(e) => setProviderField("apiKey", e.target.value)} placeholder={props.providerConfig?.api_key_configured ? "已保存；留空保持不变" : "sk-..."} /></label>
        <label>API Key Env <input value={props.providerForm.apiKeyEnv} onChange={(e) => setProviderField("apiKeyEnv", e.target.value)} placeholder="OPENAI_API_KEY" /></label>
        <label>Timeout <input type="number" min="0.1" step="0.1" value={props.providerForm.timeoutS} onChange={(e) => setProviderField("timeoutS", e.target.value)} /></label>
      </div>
      <label className="checkbox-row">
        <input type="checkbox" checked={props.useProvider} onChange={(e) => props.setUseProvider(e.target.checked)} />
        <span><strong>使用模型审核</strong><small>Run Dream 时调用服务端 provider；这里保存的配置会写入 state config。</small></span>
      </label>
      <label className="checkbox-row">
        <input type="checkbox" checked={props.advancedDreaming} onChange={(e) => props.setAdvancedDreaming(e.target.checked)} />
        <span><strong>高级 Dreaming</strong><small>开启后 Dream 会生成稳定记忆整理提案；高风险合并、拆分、重写需要在维护页确认。</small></span>
      </label>
      <label className="checkbox-row">
        <input type="checkbox" checked={props.providerForm.thinkingEnabled} onChange={(e) => setProviderField("thinkingEnabled", e.target.checked)} />
        <span><strong>开启 Thinking</strong><small>保存后 provider 请求会携带 thinking 参数；关闭时不发送该字段。</small></span>
      </label>
      <div className="settings-actions">
        <button className="primary-button" onClick={props.onSaveProviderConfig} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Check size={16} />} 保存 Provider
        </button>
      </div>
      <div className="settings-divider" />
      <div className="settings-section-header">
        <div><h3>自动 Dreaming</h3><p>服务进程内定时维护，默认每 180 分钟检查一次。</p></div>
        <StatusBadge text={autoDreamStatusText(props.autoDreamStatus)} />
      </div>
      <div className="provider-status-row">
        <StatusBadge text={props.autoDreamStatus?.last_outcome || "scheduled"} />
        <code>{props.autoDreamStatus?.status_path || "auto-dream-status.json"}</code>
      </div>
      <label className="checkbox-row">
        <input type="checkbox" checked={props.autoDreamForm.enabled} onChange={(e) => setAutoDreamField("enabled", e.target.checked)} />
        <span><strong>启用自动 Dreaming</strong><small>有 backlog 时自动整理；默认仅在 provider 已配置时调用模型维护。</small></span>
      </label>
      <label className="checkbox-row">
        <input type="checkbox" checked={props.autoDreamForm.localFallback} onChange={(e) => setAutoDreamField("localFallback", e.target.checked)} />
        <span><strong>本地确定性整理（无需模型）</strong><small>未配置 provider 时也自动跑确定性维护：高置信 promote、去重、低质拒绝、自动建链；冲突等高风险动作仍留给人工或模型。</small></span>
      </label>
      <div className="provider-grid">
        <label>间隔分钟 <input type="number" min="5" step="5" value={props.autoDreamForm.intervalMinutes} onChange={(e) => setAutoDreamField("intervalMinutes", e.target.value)} /></label>
        <label>下次运行 <input readOnly value={formatDate(props.autoDreamStatus?.next_run_at ?? undefined)} /></label>
        <label>上次检查 <input readOnly value={formatDate(props.autoDreamStatus?.last_checked_at ?? undefined)} /></label>
        <label>上次用时 <input readOnly value={props.autoDreamStatus?.last_duration_s == null ? "-" : formatDuration(props.autoDreamStatus.last_duration_s)} /></label>
      </div>
      {props.autoDreamStatus?.last_error ? (
        <div className="auto-dream-error"><strong>最近错误</strong><span>{props.autoDreamStatus.last_error}</span></div>
      ) : null}
      <div className="settings-actions">
        <button className="primary-button" onClick={props.onSaveAutoDreamConfig} disabled={props.loading}>
          {props.loading ? <Loader2 className="spin" size={16} /> : <Check size={16} />} 保存自动 Dreaming
        </button>
      </div>
    </section>
  );
}

function OperationsQueue(props: {
  candidates: MemoryItem[]; dreamStatus: DreamStatusResult | null;
  snapshot: SnapshotResult | null; useProvider: boolean; loading: boolean;
  dreamElapsedS: number | null;
  onPromote: (id: string) => void; onReject: (id: string) => void; onRunDream: () => void;
}) {
  return (
    <div className="ops-stack">
      <section className="panel ops-panel">
        <div className="panel-header compact"><h2>Operations Queue</h2><StatusBadge text={`${props.candidates.length} candidates`} /></div>
        {props.candidates.length === 0 ? <EmptyState text="没有待审候选。" /> : null}
        {props.candidates.slice(0, 6).map((c) => (
          <article className="queue-item" key={c.id}>
            <div>
              <span className="score">{formatConfidence(c.confidence)}</span>
              <strong>{c.claim || c.id}</strong>
              <small>{c.scope || c.dimension || "global"}</small>
            </div>
            <div>
              <button className="success-button" onClick={() => props.onPromote(c.id)} disabled={props.loading}>Promote</button>
              <button className="danger-button" onClick={() => props.onReject(c.id)} disabled={props.loading}>Reject</button>
            </div>
          </article>
        ))}
      </section>
      <section className="panel ops-panel">
        <div className="panel-header compact"><h2>Dream Run</h2><Sparkles size={18} /></div>
        <JsonBlock title="Status" value={props.dreamStatus || {}} />
        <button className="primary-button full" onClick={props.onRunDream} disabled={props.loading}>
          {props.dreamElapsedS !== null ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
          {props.dreamElapsedS !== null ? `Running ${formatDuration(props.dreamElapsedS)}` : props.useProvider ? "Run Model" : "Run Now"}
        </button>
      </section>
      <section className="panel ops-panel">
        <div className="panel-header compact"><h2>Snapshot</h2><StatusBadge text={props.snapshot?.exists ? "OK" : "Missing"} /></div>
        <JsonBlock title="Latest" value={props.snapshot || { exists: false }} />
      </section>
    </div>
  );
}

// ─── Shared Components ───────────────────────────────────────────────────────

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="json-block">
      <div><span>{title}</span><button onClick={() => navigator.clipboard?.writeText(JSON.stringify(value, null, 2))}><Link2 size={13} /></button></div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function StatusBadge({ text }: { text: string }) {
  const n = text.toLowerCase();
  const tone = n.includes("active") || n.includes("ok") || n.includes("page") ? "good"
    : n.includes("draft") || n.includes("candidate") ? "blue"
    : n.includes("reject") || n.includes("tomb") || n.includes("delete") ? "bad"
    : n.includes("conflict") ? "warn"
    : "neutral";
  return <span className={`badge ${tone}`} title={text}>{compactStatusText(text)}</span>;
}

function compactStatusText(text: string) {
  const clean = text.trim();
  const sep = clean.indexOf(":");
  return sep > 0 ? clean.slice(0, sep) : clean;
}

function StatusDot({ ok }: { ok: boolean }) { return <span className={ok ? "dot ok" : "dot"} />; }
function EmptyState({ text }: { text: string }) { return <div className="empty-state">{text}</div>; }

// ─── Utilities ───────────────────────────────────────────────────────────────

function searchMatchToItem(match: Record<string, unknown>): MemoryItem | null {
  const rawType = String(match.type || match.item_type || "page");
  if (rawType.includes("plan")) {
    return null;
  }
  const type = rawType.includes("candidate") ? "candidate" : "page";
  return { ...(match as MemoryItem), type, id: String(match.id || match.memory_id || ""), title: String(match.title || match.claim || ""), content: String(match.content || match.claim || match.summary || "") };
}

function itemMatchesQuery(item: MemoryItem, query: string) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = [item.id, item.type, item.status, item.claim, item.title, item.content, item.scope, item.dimension, item.run_id, item.source_candidate_id].filter(Boolean).join(" ").toLowerCase();
  return terms.every((t) => haystack.includes(t));
}

function compareMemoryItems(left: MemoryItem, right: MemoryItem) {
  const typeRank = (item: MemoryItem) => (item.type === "page" ? 0 : 1);
  const lr = typeRank(left), rr = typeRank(right);
  if (lr !== rr) return lr - rr;
  return (right.updated_at || right.created_at || 0) - (left.updated_at || left.created_at || 0);
}

function scopeFromUidFilter(uid: string) {
  const clean = uid.trim();
  if (!clean) return "";
  return clean.toLowerCase().startsWith("user:") ? clean : `user:${clean}`;
}

function memoryFactPayload(claim: string, scope: string) {
  return scope ? { claim, scope, confidence: 0.9 } : { claim, confidence: 0.9 };
}

function memoryObservationPayload(content: string, scope: string) {
  return scope ? { content, retention: "memory_candidate", scope } : content;
}

function tombstoneTargetItem(t: MemoryTombstone): MemoryItem {
  return { id: t.target_id, type: t.target_type, status: `tombstoned:${t.reason || "unknown"}`, title: t.summary || t.reason || t.target_id, content: t.summary || "", updated_at: t.created_at };
}

function itemTitle(item: MemoryItem) { return item.title || item.claim || item.content || item.id; }
function formatConfidence(value?: number) { if (typeof value !== "number") return "-"; return value.toFixed(2); }

function formatTime(value?: number) {
  if (!value) return "-";
  const diff = Date.now() - value * 1000;
  const minute = 60 * 1000, hour = 60 * minute, day = 24 * hour;
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
      if (key && !map.has(key)) map.set(key, result);
    }
  }
  return map;
}

function normalizeDreamReviewResults(items: unknown) {
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is DreamReviewResult => {
    if (!item || typeof item !== "object") return false;
    const r = item as DreamReviewResult;
    return Boolean(r.candidate_id || r.page_id) && Boolean(r.decision || r.status || r.reason);
  }).slice(0, 20);
}

function reviewForItem(item: MemoryItem, results: Map<string, DreamReviewResult>) {
  return results.get(item.id) || (item.source_candidate_id ? results.get(item.source_candidate_id) : undefined);
}

function auditResultForItem(item: MemoryItem, review?: DreamReviewResult) {
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

function auditResultFromDreamReview(review: DreamReviewResult) {
  const decision = String(review.decision || "").toLowerCase();
  const status = String(review.status || "");
  const n = status.toLowerCase();
  if (decision === "promoted" || n === "promoted") return auditResult("模型通过", review.reason || promotedReviewFallbackReason(review), "good");
  if (decision === "rejected" || n.startsWith("rejected")) return auditResult("模型拒绝", review.reason || statusReason(status), "bad");
  if (decision === "skipped") return auditResult("模型跳过", review.reason || statusReason(status), "neutral");
  if (decision === "conflict" || n.includes("conflict")) return auditResult("需复核", review.reason || "conflict", "warn");
  return auditResult("模型已审", review.reason || status || decision, "blue");
}

function detailedAuditReason(item: MemoryItem, review: DreamReviewResult | undefined, fallback: string) {
  if (review) {
    if (review.reason) return review.reason;
    if (String(review.decision || "").toLowerCase() === "promoted" || String(review.status || "").toLowerCase() === "promoted") return promotedReviewFallbackReason(review);
    return fallback || review.status || review.decision || "审核结果没有附带详细原因。";
  }
  if (item.type === "page" && String(item.status || "").toLowerCase() === "active") return stableMemoryFallbackReason(item);
  return fallback || statusReason(String(item.status || "")) || "暂无详细审核原因。";
}

function promotedReviewFallbackReason(review: DreamReviewResult) {
  const actionText = review.page_action === "merged" ? "已合并到已有稳定记忆页" : review.page_action === "created" ? "已新建稳定记忆页" : "已进入稳定记忆";
  const pageText = review.page_title ? `「${review.page_title}」` : review.page_id ? compactId(review.page_id) : "";
  const sourceText = review.candidate_id ? `；来源候选 ${compactId(review.candidate_id)}` : "";
  return `${actionText}${pageText ? ` ${pageText}` : ""}${sourceText}`;
}

function stableMemoryFallbackReason(item: MemoryItem) {
  const parts = ["已进入稳定记忆，可用于后续检索和上下文召回"];
  if (item.source_candidate_id) parts.push(`来源候选 ${compactId(item.source_candidate_id)}`);
  if (typeof item.confidence === "number") parts.push(`置信度 ${formatConfidence(item.confidence)}`);
  return parts.join("；");
}

function auditReviewLabel(review: DreamReviewResult) { return auditResultFromDreamReview(review).label; }

function auditResult(label: string, detail: string, tone: "good" | "bad" | "warn" | "blue" | "neutral") {
  return { label, detail, tone, title: detail ? `${label}: ${detail}` : label };
}

function statusReason(status: string) {
  const sep = status.indexOf(":");
  if (sep < 0) return "";
  return status.slice(sep + 1).replace(/[_-]+/g, " ");
}

function latestDreamDurationS(status: DreamStatusResult | null) {
  const v = status?.latest?.duration_s;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function formatDuration(value: number) {
  if (!Number.isFinite(value) || value < 0) return "0.0s";
  if (value < 10) return `${value.toFixed(1)}s`;
  if (value < 60) return `${Math.round(value)}s`;
  const m = Math.floor(value / 60), s = Math.round(value % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function dreamStatusReviewReasons(status: DreamStatusResult | null) {
  return normalizeDreamReviewResults(status?.latest?.execution?.review_results).filter((i) => Boolean(i.reason));
}

function dreamRunRejectReasons(report: DreamRunReport) {
  return normalizeDreamRejectReasons(report.execution?.result?.actions?.applied);
}

function normalizeDreamRejectReasons(items: unknown) {
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is DreamRejectReason => {
    if (!item || typeof item !== "object") return false;
    const a = item as DreamRejectReason;
    const tool = String(a.tool || ""), decision = String(a.decision || ""), status = String(a.status || "");
    return Boolean(a.reason) && (tool === "memory_reject_candidate" || decision === "rejected" || status.startsWith("rejected"));
  }).slice(0, 10);
}

function dreamRejectReasonText(items: DreamRejectReason[]) {
  if (items.length === 0) return "";
  const details = items.slice(0, 3).map((i) => `${compactId(i.candidate_id || i.action_id)}: ${i.reason || "unspecified"}`).join("；");
  const more = items.length > 3 ? `；另有 ${items.length - 3} 条` : "";
  return ` Reject 原因：${details}${more}`;
}

function dreamDurationText(report: DreamRunReport) {
  return typeof report.duration_s === "number" && Number.isFinite(report.duration_s) ? `用时 ${formatDuration(report.duration_s)}。` : "";
}

function dreamRunMessage(report: DreamRunReport, useProvider: boolean, advancedDreaming = false) {
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

// ─── Plan Helpers ───────────────────────────────────────────────────────────

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

// ─── Mount ───────────────────────────────────────────────────────────────────

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
