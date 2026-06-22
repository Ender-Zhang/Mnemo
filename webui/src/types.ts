// Shared API + view types for the Mnemo WebUI.

export type ApiEnvelope<T> = {
  method?: string;
  result?: T;
  error?: string;
};

export type MemoryItem = {
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
  match_signals?: Array<Record<string, unknown>>;
  vector_score?: number;
};

export type ConflictCard = {
  candidate_id?: string;
  existing_page_id?: string;
  candidate_claim?: string;
  existing_content?: string;
  options?: ConflictOption[];
};

export type ConflictOption = {
  resolution: string;
  label: string;
  description?: string;
};

export type MemoryListResult = {
  kind: "memory_list";
  count: number;
  uid?: string | null;
  items: MemoryItem[];
};

export type MemorySearchResult = {
  kind: "memory_search";
  matches?: Array<Record<string, unknown>>;
};

export type MemoryReadResult = {
  kind: "memory_item";
  type: "candidate" | "page";
  item: MemoryItem;
};

export type MemoryLinksResult = {
  outgoing?: Array<Record<string, unknown>>;
  incoming?: Array<Record<string, unknown>>;
};

export type MemoryEvent = {
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

export type MemoryProvenanceResult = {
  kind: "memory_provenance";
  memory_id: string;
  memory_type: "candidate" | "page";
  page?: MemoryItem | null;
  candidates?: MemoryItem[];
  events?: MemoryEvent[];
};

export type MemoryHealthResult = {
  kind?: string;
  summary?: Record<string, unknown>;
  cards?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type DreamStatusResult = {
  kind?: string;
  latest?: DreamReportSummary | null;
  latest_report?: Record<string, unknown> | null;
  backlog?: Record<string, unknown>;
  [key: string]: unknown;
};

export type DreamRejectReason = {
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

export type DreamReviewResult = DreamRejectReason;

export type DreamReportSummary = {
  duration_s?: number;
  execution?: {
    review_results?: DreamReviewResult[];
    reject_reasons?: DreamRejectReason[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

export type DreamRunReport = {
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

export type DreamProposal = {
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

export type DreamProposalsResult = {
  kind: "dream_proposals";
  status?: string | null;
  count: number;
  proposals: DreamProposal[];
};

export type SnapshotResult = {
  kind?: string;
  exists?: boolean;
  snapshot?: Record<string, unknown> | null;
};

export type MemoryTombstone = {
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

export type TombstonesResult = {
  tombstones?: MemoryTombstone[];
};

export type L0ProfileEntry = { dimension: string; text: string; page_id: string; title: string };

export type L0Profile = {
  kind?: string;
  summary?: string;
  dimensions?: Record<string, unknown>;
  entries?: L0ProfileEntry[];
  page_count?: number;
};

export type ContextCardItem = {
  type?: string;
  id?: string;
  title?: string;
  content?: string;
  claim?: string;
  scope?: string;
  dimension?: string;
  confidence?: number;
  match_signals?: Array<Record<string, unknown>>;
  vector_score?: number;
  [key: string]: unknown;
};

export type ContextPreviewResult = {
  kind?: string;
  intent?: string;
  cards?: ContextCardItem[];
  profile?: L0Profile | null;
  snapshot?: Record<string, unknown> | null;
};

export type RecallPreviewResult = {
  kind?: string;
  seed?: string;
  items?: Array<Record<string, unknown>>;
  query_plan?: Record<string, unknown>;
};

export type PageVersion = {
  id?: string;
  page_id?: string;
  change_reason?: string;
  changed_by?: string;
  snapshot_data?: Record<string, unknown>;
  created_at?: number;
};

export type VersionsResult = {
  kind?: string;
  memory_id?: string;
  versions?: PageVersion[];
};

export type PlanItem = {
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

export type PlanListResult = {
  kind: "plan_item_list";
  count: number;
  items: PlanItem[];
};

export type PlanProposal = {
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

export type PlanProposalsResult = {
  kind: "plan_proposals";
  count: number;
  proposals: PlanProposal[];
};

export type PlanUserGroup = {
  key: string;
  uid: string;
  scope: string;
  label: string;
  items: PlanItem[];
  proposals: PlanProposal[];
  openCount: number;
  pendingCount: number;
  latestAt: number;
};

export type PlanFormState = {
  kind: "goal" | "todo";
  title: string;
  detail: string;
  parentId: string;
  priority: "low" | "normal" | "high";
  dueAt: string;
};

export type TabKey = "memories" | "preview" | "plans" | "candidates" | "tombstones" | "maintenance" | "settings";

export type Notice = {
  tone: "ok" | "warn" | "error";
  text: string;
};

export type Toast = {
  id: number;
  tone: "ok" | "warn" | "error";
  text: string;
};

export type MemoryGraphNode = { id: string; title: string; dimension: string; degree: number; orphan: boolean };
export type MemoryGraphEdge = { source: string; target: string; relation?: string };
export type MemoryGraphResult = {
  kind?: string;
  page_count?: number;
  dimensions?: Array<{ dimension: string; count: number }>;
  nodes?: MemoryGraphNode[];
  edges?: MemoryGraphEdge[];
};

export type EffectiveConfigRow = { field: string; value: string; source: string };

export type EffectiveConfigResult = {
  kind?: string;
  config_path?: string | null;
  rows?: EffectiveConfigRow[];
};
