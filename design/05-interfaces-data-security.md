# Interfaces, Data And Security

> SDK/MCP/CLI/Adapter、SQLite schema、目录结构、安全模型和外部 harness 最小披露。

## 8. 接口与集成层

### 8.1 Mnemo SDK（核心 API）

Mnemo 对外提供的不是插件适配器，而是一个**完整的个人 AI OS API**。任何 Agent 框架通过以下接口与 Mnemo 交互——无论是 Rust、TypeScript、Python、CLI 还是 MCP。

核心协议应采用语言无关的 IDL / OpenAPI / MCP schema 描述；Python 只是参考 SDK，不是架构约束。

```ts
interface MnemoCore {
  context(req: ContextRequest): ContextBlock;
  update(req: UpdateRequest): UpdateResult;
  recall(req: RecallRequest): AssociativeCluster;
  run(req: AgentRequest): AgentRunResult;
  replay(req: ReplayRequest): ReplayResult;
  evaluate(req: EvalRequest): EvalReport;
}
```

```python
# Mnemo Python SDK (reference binding)

class MnemoClient:
    """
    Mnemo AgenticOS 的主客户端。代表一个用户身份实例。
    
    配置: ~/.mnemo/config.yaml
    传输: 本地 Unix socket (低延迟) 或 HTTP (远程部署)
    """
    
    def context(
        self,
        intent: str = "",           # 本次请求意图（引导联想和路由）
        agent_role: str = "general", # coding|writing|planning|general
        budget_tokens: int = 4000,
        include_associations: bool = True,
    ) -> ContextBlock:
        """
        核心接口：获取个人上下文块，可直接注入 system prompt。
        
        返回内容:
          · Profile Card (L0, ~300 tokens)
          · Memory Index (L1, ~800 tokens)
          · Routed Pages (L2, 0-3 pages, budget-aware)
          · Association Cluster (联想块, 由 intent 驱动)
          · Active Watches (当前关注点状态)
          · Skills Index (高优先级个人技能摘要)
        """
    
    def update(
        self,
        facts: list[MemoryFact],      # 本次交互中验证的新事实
        observations: list[Observation], # 交互行为观察（用于技能演进）
        source: str = "agent",
    ) -> UpdateResult:
        """
        会话结束后批量更新：
          · 新事实 → 写入对应 wiki 页面
          · 观察 → 进入 learning packet 候选
          · 触发受影响 L1 段落的重新编译
        """
    
    def recall(
        self,
        seed: str,
        depth: int = 2,
        context: str = "",
    ) -> AssociativeCluster:
        """联想召回——从种子概念出发涟漪扩散"""
    
    def search(self, query: str, limit: int = 5) -> list[WikiPage]:
        """语义搜索记忆库（BM25 + 可选向量）"""
    
    def watch(
        self,
        name: str,
        description: str,
        schedule: str | None = None,
        keywords: list[str] | None = None,
    ) -> Watch:
        """注册关注点——支持定时和关键词触发两种模式"""
    
    def skills(self, query: str = "") -> list[Skill]:
        """搜索个人技能库"""
    
    def sense(self) -> DeviceSnapshot:
        """获取当前感知快照（如 Android Companion 已连接）"""

    def run(
        self,
        request: AgentRequest,
        runtime: str = "native",  # native|openclaw|codex|acp
    ) -> AgentRunResult:
        """
        通过 Continuous Runtime Harness 执行一次 agent turn。
        不直接绕过 Mnemo 的记忆、技能、审批和 trace 机制。
        """

    def capsule(
        self,
        task: str,
        runtime: str = "external",  # external|openclaw|codex|acp
        agent_type: str = "general",
        requested_pages: list[str] | None = None,
        allowed_pages: list[str] | None = None,
    ) -> ContextCapsule:
        """为外部 runtime 构建最小披露 context capsule；不是执行入口"""

    def external_run(
        self,
        task: str,
        command: list[str],
        runtime: str = "external-command",
        agent_type: str = "general",
    ) -> ExternalRuntimeResult:
        """
        用显式 argv 命令执行外部 runtime。
        输入仅为 context capsule；输出只接受 proposal 字段并写入 RunLedger。
        """

    def replay(
        self,
        run_id: str,
        mode: str = "deterministic",  # deterministic|live_tools|dry_run
    ) -> ReplayResult:
        """按 RunLedger 重放一次历史 run，用于调试、回归和事故复盘"""

    def evaluate(
        self,
        suite: str,
        variants: list[str] | None = None,
        release_gate: bool = False,
    ) -> EvalReport:
        """
        运行 harness eval、变体对比或固定 release gate。
        默认 variants: no_memory, skills_only, full_mnemo。
        """
```

### 8.1.1 HTTP Core API（语言无关传输）

HTTP 入口只是 `MnemoClient` 的轻量 transport，不定义独立 workflow：

```text
GET  /api/core/schema
GET  /api/core/openapi.json
POST /api/core/context
POST /api/core/recall
POST /api/core/capsule
POST /api/core/external-run
POST /api/core/run
POST /api/core/replay
POST /api/core/evaluate
```

返回结构统一为：

```json
{
  "method": "context",
  "result": {}
}
```

`external-run` 仍然只接受显式 `command: string[]`，不接受 shell 字符串；输出继续遵守 proposal-only 边界。

### 8.2 MCP Server（Agent 生态互联）

Mnemo 内置 MCP Server，任何支持 MCP 的 Agent（包括 Claude Code、Cursor、自定义 Agent）无需任何 SDK 即可接入：

```bash
mnemo mcp config --client claude --state-dir .mnemo --json
mnemo mcp serve --state-dir .mnemo
```

`mcp config` 只生成 stdio 客户端配置片段，指向本地 `mnemo mcp serve`，并附带紧凑工具名/数量；不会启动服务、写状态或暴露原始 tool schema。

```python
# 暴露的 MCP Tools

mnemo_context(intent, agent_role, budget_tokens)
  → 返回: system_prompt_block (可直接插入)

mnemo_update(facts, observations)
  → 返回: {updated_pages, triggered_compilations}

mnemo_capsule(task, runtime, requested_pages?, allowed_pages?)
  → 返回: ContextCapsule（task、mission_brief、L1 pointers、allowed summaries、return_contract）

mnemo_external_run(task, command, runtime?, requested_pages?, allowed_pages?)
  → 返回: ExternalRuntimeResult（run_id、capsule summary、proposal、ignored_fields）

mnemo_recall(seed, depth, context)
  → 返回: AssociativeCluster

mnemo_search(query, limit)
  → 返回: [{path, summary, confidence}]

mnemo_watch(name, description, schedule, keywords)
  → 返回: Watch

mnemo_watch_feedback(item_id, outcome, decision?)
  → 记录 Watch 反馈；按模型显式 decision 稀疏、暂停或禁用 Watch

mnemo_skills(query)
  → 返回: [{name, summary, priority}]

mnemo_tools(profile, task, platform)
  → 返回: {profile, tool_cards≤20行, denied_tools, risk_policy}

mnemo_cron(action, job)
  → 创建/更新/暂停/恢复/运行/删除长期任务；可绑定 skills 和 delivery

mnemo_dream_schedule(schedule?, limit?, min_confidence?)
  → 创建 bounded Dream memory maintenance 触发器；到期后通过 scheduler 运行 MemoryEngine

mnemo_run(request, runtime)
  → 返回: {run_id, trace_id, response, tool_summary, memory_delta, skill_delta}

mnemo_replay(run_id, mode)
  → 返回: {original, replayed, diff, determinism_score}

mnemo_eval(suite, variants?, release_gate?)
  → 返回: 紧凑 SuiteReport、HarnessVariantReport 或 HarnessReleaseReport（cases/metrics/gates）

mnemo_runtime_status()
  → 返回: {daemon, queues, active_runs, pending_inbox, watch_lag_seconds}
```

### 8.3 CLI（命令行直接使用）

```bash
# 获取上下文（输出可直接粘贴给任何 LLM）
mnemo context --intent "writing a Rust async module"

# 更新记忆（任务完成后）
mnemo update goals/learn-rust "完成了 tokio 基础，下一步 channels" --confidence 0.9

# 添加关注点
mnemo watch add "rust-progress" --schedule "每周一早上" --keywords "rust,lifetime,async"
mnemo schedule feedback <watch_id> --outcome no_feedback --action sparsify --policy-schedule weekly

# 联想召回
mnemo recall "deadline pressure" --depth 2
mnemo memory search "apple" --debug-query  # 展示 QueryPlanner 多路 query 和召回来源
mnemo memory tombstone <memory_id> --reason low_usefulness --replacement-id <new_id>
mnemo memory tombstone <memory_id> --reason harmful --eval-run-id <run_id>
mnemo memory forget <memory_id>          # private-delete：redact 原文，只保留最小 tombstone hash

# 记忆养成与健康度
mnemo stats                              # Memory Health Score + 十维覆盖率
mnemo card                               # 模型选择一张低打扰记忆卡
mnemo lint --fix                         # 修复孤儿页面、缺失链接、过期 context

# 查看主动推送
mnemo inbox

# 强制编译
mnemo compile

# 空闲期记忆整理（默认由 daemon 自动调度）
mnemo dream --now
mnemo dream status
mnemo dream report --latest

# 查看 Soul
mnemo soul show
mnemo soul edit

# 持续运行 daemon
mnemo daemon start
mnemo daemon status
mnemo daemon stop

# 通过 Runtime Harness 执行一轮
mnemo run "整理今天会议纪要并更新相关记忆" --runtime native
mnemo run "让 Codex 检查这个 repo 的测试失败" --runtime codex
mnemo api external-run "让外部 Codex adapter 检查测试失败" \
  --runtime codex \
  --command-json '["python3","external_adapter.py"]' \
  --json

# 回放/评测/质量门禁
mnemo harness replay <run_id> --mode deterministic
mnemo harness eval personalization-core
mnemo harness eval external-harness
mnemo harness smoke
mnemo harness release
mnemo harness report <report_id>
```

### 8.4 Adapter 模式（接入其他 Agent 框架）

Mnemo 提供了 `SessionAdapter` 抽象，可以让任何 Agent 框架的会话生命周期自动同步到 Mnemo：

```python
class MnemoSessionAdapter:
    """
    让任意 Agent 框架获得 Mnemo 的记忆能力，
    只需实现三个钩子：
    """
    
    def on_session_start(self, agent_type: str) -> str:
        """返回 system prompt 注入块"""
        return self.client.context(agent_role=agent_type).to_prompt_block()
    
    def on_turn_end(self, user_msg: str, assistant_response: str) -> None:
        """每轮对话后触发观察分析"""
        observations = self._extract_observations(user_msg, assistant_response)
        self._pending_observations.extend(observations)
    
    def on_mission_idle(self, messages: list) -> None:
        """Mission 空闲或结束后批量同步"""
        facts = self._extract_facts(messages)
        self.client.update(facts=facts, observations=self._pending_observations)

# 使用示例 (伪代码，适用于任意 Agent 框架):
adapter = MnemoSessionAdapter(client=MnemoClient())

# 会话开始
system_prompt = adapter.on_session_start(agent_type="coding")

# 每轮之后
adapter.on_turn_end(user_msg, assistant_response)

# Mission 空闲或结束
adapter.on_mission_idle(all_messages)
```

---
---

## 9. 数据模型

### 9.1 SQLite Schema

```sql
-- 记忆页面元数据 (文件系统存 Markdown, DB 存索引)
CREATE TABLE wiki_pages (
    id TEXT PRIMARY KEY,    -- 相对路径: "goals/learn-rust"
    dimension TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active|paused|completed|stale|archived|tombstoned
    confidence REAL NOT NULL DEFAULT 0.9,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    decay_days INTEGER DEFAULT 90,
    content_hash TEXT,      -- 用于编译器变化检测
    l1_summary TEXT,        -- 缓存的 L1 段落
    l1_compiled_at TEXT
);

CREATE TABLE memory_tombstones (
    id TEXT PRIMARY KEY,
    target_path TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    reason TEXT NOT NULL,          -- stale|superseded|rejected|harmful|private_delete|low_usefulness
    evidence_run_id TEXT,
    rule TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_memory_tombstones_target ON memory_tombstones(target_path, created_at DESC);

-- 技能注册表
CREATE TABLE skills (
    id TEXT PRIMARY KEY,    -- "sop/github-pr-review"
    name TEXT NOT NULL,     -- frontmatter name
    type TEXT NOT NULL,     -- always_on|interaction|task|tool_use|domain|sop
    status TEXT NOT NULL DEFAULT 'draft', -- draft|shadow|active|promoted|deprecated|rejected|rolled_back
    source_scope TEXT NOT NULL, -- native_user|native_project|agents_user|agents_project|claude|hermes|openclaw|bundled
    path TEXT NOT NULL,     -- absolute SKILL.md path
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    confidence REAL NOT NULL DEFAULT 0.5,
    priority TEXT NOT NULL DEFAULT 'medium',  -- high|medium|low
    source TEXT NOT NULL DEFAULT 'generated', -- user-defined|generated|observed|imported|crystallized_run
    observation_count INTEGER DEFAULT 0,
    last_reinforced TEXT,
    content_hash TEXT,
    manifest_json TEXT,     -- parsed frontmatter incl. metadata.mnemo
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_skills_name ON skills(name);
CREATE INDEX idx_skills_status ON skills(status, updated_at DESC);
CREATE INDEX idx_skills_scope ON skills(source_scope, name);

-- 技能观察记录 (用于自演进)
CREATE TABLE skill_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT,          -- NULL 表示未归类的新观察
    session_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,  -- explicit_correction|explicit_approval|implicit_positive|...
    signal_strength REAL NOT NULL,
    user_quote TEXT,        -- 触发信号的用户原话
    context TEXT,           -- 上下文摘要
    created_at TEXT NOT NULL
);

-- 关注点 (Watches)
CREATE TABLE watches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dimension TEXT,
    linked_page TEXT,
    trigger_type TEXT NOT NULL,  -- periodic|context_match|event
    schedule TEXT,           -- cron expression (周期型)
    keywords TEXT,           -- JSON array (上下文匹配型)
    check_prompt TEXT NOT NULL,
    last_run TEXT,
    last_status TEXT,
    last_summary TEXT,
    streak_on_track INTEGER DEFAULT 0,
    silent_threshold INTEGER DEFAULT 0,  -- 连续正常多少次后静默
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- 编译缓存 & 会话日志
CREATE TABLE compile_cache (
    level TEXT NOT NULL,      -- L0|L1|L1_skills
    content TEXT NOT NULL,
    compiled_at TEXT NOT NULL,
    source_hash TEXT NOT NULL,  -- 所有输入页面的 hash 合并
    token_count INTEGER
);

CREATE TABLE session_log (
    id TEXT PRIMARY KEY,
    agent_type TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    message_count INTEGER DEFAULT 0,
    observations_extracted INTEGER DEFAULT 0,
    memories_updated INTEGER DEFAULT 0
);
```

### 9.2 目录结构

```
~/.mnemo/
├── wiki/
│   ├── _compiled/
│   │   ├── L0-profile-card.md
│   │   └── L1-index.md
│   ├── identity/
│   │   └── core.md
│   ├── cognition/
│   │   ├── programming-languages.md
│   │   └── learning-style.md
│   ├── values/
│   ├── goals/
│   ├── preferences/
│   ├── relationships/
│   ├── context/
│   ├── history/
│   ├── patterns/
│   └── _archive/
├── policy/
│   ├── boundaries.yaml     ← 十维本体中的 boundaries 治理层
│   └── exposure.yaml       ← 平台/Agent 类型信任矩阵
├── skills/
│   ├── always_on/
│   ├── interaction/
│   ├── task/
│   ├── tool_use/
│   ├── domain/
│   ├── workflow/
│   ├── sop/              ← SOP 晶化任务路径，每项为 SKILL.md 目录 (§4.7)
│   └── _generated/
├── watches/
├── patterns/             ← learning packet 的观察归档
├── runs/                 ← RunLedger JSONL trace mirror
├── evals/                ← Harness suites, fixtures, reports
├── state.db              ← 包含 FTS5 indexes (§18)
└── config.yaml
```

### 9.3 扩展 SQLite Schema（§17-18 补充）

```sql
-- 完整会话消息表 (L4 存储，§18.2)
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'cli',     -- cli|mcp|telegram|discord|cron
    agent_type TEXT DEFAULT 'general',
    title TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    message_count INTEGER DEFAULT 0,
    memory_writes INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    parent_session_id TEXT REFERENCES sessions(id)  -- 子 Agent 溯源
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    mission_id TEXT REFERENCES missions(id),
    role TEXT NOT NULL,           -- user|assistant|tool_result
    content TEXT,
    tool_name TEXT,
    token_count INTEGER,
    timestamp REAL NOT NULL
);

CREATE INDEX idx_messages_session   ON messages(session_id, timestamp);
CREATE INDEX idx_messages_mission   ON messages(mission_id, timestamp);
CREATE INDEX idx_messages_role      ON messages(role, timestamp DESC);
CREATE INDEX idx_sessions_started   ON sessions(started_at DESC);
CREATE INDEX idx_sessions_source    ON sessions(source);

-- FTS5 全文索引
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id,
    tokenize="unicode61 remove_diacritics 1"
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages
    BEGIN INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END;
CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages
    BEGIN INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content); END;
CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages
    BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
        INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
    END;

-- Mission 是跨多轮持续存在的用户委托；Session 只是某个入口通道
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    root_session_id TEXT REFERENCES sessions(id),
    title TEXT,
    user_goal TEXT NOT NULL,
    status TEXT NOT NULL,         -- queued|understanding|working|waiting|blocked|ready|done|cancelled|archived
    summary TEXT,
    current_plan_json TEXT,
    constraints_json TEXT,
    w0_checkpoint_json TEXT,
    active_artifact_ids_json TEXT,
    open_decision_ids_json TEXT,
    notification_policy TEXT DEFAULT 'state_changes', -- silent|done_only|state_changes|live
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    closed_at REAL
);

CREATE TABLE IF NOT EXISTS mission_turns (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id),
    session_id TEXT REFERENCES sessions(id),
    run_id TEXT,
    turn_index INTEGER NOT NULL,
    user_input TEXT,
    assistant_summary TEXT,
    state_delta_json TEXT,
    created_at REAL NOT NULL,
    UNIQUE(mission_id, turn_index)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    mission_id TEXT REFERENCES missions(id),
    type TEXT NOT NULL,           -- doc|message|plan|code_change|table|decision_brief|image|file
    title TEXT,
    status TEXT NOT NULL,         -- draft|ready|sent|applied|archived
    current_version INTEGER DEFAULT 1,
    uri TEXT,
    content_hash TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id),
    risk TEXT NOT NULL,           -- write|external|admin
    status TEXT NOT NULL,         -- open|approved|rejected|edited|expired
    prompt TEXT NOT NULL,
    options_json TEXT,
    evidence_json TEXT,
    created_at REAL NOT NULL,
    resolved_at REAL
);

CREATE INDEX idx_missions_status ON missions(status, updated_at DESC);
CREATE INDEX idx_mission_turns_mission ON mission_turns(mission_id, turn_index);
CREATE INDEX idx_artifacts_mission ON artifacts(mission_id, updated_at DESC);
CREATE INDEX idx_decisions_mission ON decisions(mission_id, status, created_at DESC);

-- 记忆写入溯源日志 (§3.11)
CREATE TABLE IF NOT EXISTS memory_write_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_path TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    operation TEXT NOT NULL,      -- create|update|conflict_resolve|stale|archive
    old_content_hash TEXT,
    new_content_hash TEXT NOT NULL,
    confidence_before REAL,
    confidence_after REAL,
    trigger_type TEXT NOT NULL,   -- user_confirmed|agent_inferred|session_reflect|daily_compile
    evidence_quote TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_mwl_page    ON memory_write_log(page_path, created_at DESC);
CREATE INDEX idx_mwl_session ON memory_write_log(session_id);
CREATE INDEX idx_mwl_trigger ON memory_write_log(trigger_type, created_at DESC);
```

### 9.4 Runtime Harness Schema

持续运行系统需要独立于业务记忆的 run ledger。SQLite 存索引和可查询字段，`~/.mnemo/runs/*.jsonl` 存完整事件流镜像，避免大型工具输出撑爆主库。

```sql
-- 每次 agent turn / daemon task / watch execution 都是一条 run
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,                  -- ulid
    session_id TEXT REFERENCES sessions(id),
    mission_id TEXT REFERENCES missions(id),
    turn_id TEXT REFERENCES mission_turns(id),
    turn_index INTEGER,
    parent_run_id TEXT REFERENCES runs(id),
    source TEXT NOT NULL,                 -- cli|mcp|android|watch|daemon|subagent|external
    runtime TEXT NOT NULL DEFAULT 'native', -- native|openclaw|codex|acp
    status TEXT NOT NULL,                 -- queued|running|succeeded|failed|cancelled|timeout
    intent TEXT,
    agent_type TEXT DEFAULT 'general',
    model TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    trace_path TEXT,                      -- ~/.mnemo/runs/YYYY/MM/<run_id>.jsonl
    error_class TEXT,
    error_message TEXT
);

CREATE INDEX idx_runs_session ON runs(session_id, started_at DESC);
CREATE INDEX idx_runs_mission ON runs(mission_id, started_at DESC);
CREATE INDEX idx_runs_status ON runs(status, started_at DESC);
CREATE INDEX idx_runs_runtime ON runs(runtime, started_at DESC);

-- 轻量事件索引；完整 payload 写入 JSONL trace mirror
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,      -- prompt.assembled|tool.called|tool.result|memory.queued|...
    summary TEXT,
    payload_hash TEXT,
    timestamp REAL NOT NULL,
    UNIQUE(run_id, seq)
);

CREATE INDEX idx_run_events_run ON run_events(run_id, seq);
CREATE INDEX idx_run_events_type ON run_events(event_type, timestamp DESC);

-- 工具调用用于效率评测、失败分析和 SOP 晶化
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    provider TEXT,                  -- openai|anthropic|gemini|local|...
    provider_call_id TEXT,          -- provider-native call id / tool_use_id
    tool_name TEXT NOT NULL,
    args_hash TEXT,
    risk TEXT NOT NULL,             -- read|write|external|admin
    status TEXT NOT NULL,         -- success|error|blocked|approved|timeout
    started_at REAL NOT NULL,
    ended_at REAL,
    output_chars INTEGER DEFAULT 0,
    error_message TEXT,
    sop_candidate_id TEXT
);

-- Harness 评测用例：真实回放和合成用户画像共用
CREATE TABLE IF NOT EXISTS harness_eval_cases (
    id TEXT PRIMARY KEY,
    suite TEXT NOT NULL,          -- personalization-core|memory-safety|skill-evolution|runtime-smoke
    case_type TEXT NOT NULL,      -- replay|synthetic|redteam|golden
    user_profile_ref TEXT,        -- 指向 fixture 或 anonymized profile
    prompt TEXT NOT NULL,
    expected_behavior TEXT NOT NULL,
    forbidden_behavior TEXT,
    judge_rubric TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS harness_eval_results (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES harness_eval_cases(id),
    run_id TEXT REFERENCES runs(id),
    variant TEXT NOT NULL,        -- no_memory|skills_only|full_mnemo
    score REAL NOT NULL,
    pass INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    judge_notes TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX idx_eval_results_case ON harness_eval_results(case_id, created_at DESC);
CREATE INDEX idx_eval_results_variant ON harness_eval_results(variant, created_at DESC);
```

**RunLedger 事件类型最小集合**:

| event_type | 说明 | 是否进 prompt |
|------------|------|--------------|
| `request.received` | 原始入口请求标准化完成 | 否 |
| `mission.created` | 新用户委托创建，记录 goal/status/session 绑定 | 否 |
| `mission.hydrated` | 已恢复 Mission summary、checkpoint、artifact、open decisions | 仅摘要 |
| `mission.turn.started` | 用户在同一 Mission 内开启新一轮输入 | 否 |
| `mission.state.updated` | goal/plan/status/checkpoint/artifact 指针变化 | 仅摘要 |
| `mission.paused` | 用户或调度器暂停 Mission | 否 |
| `mission.resumed` | Mission 从 pause/waiting 恢复执行 | 否 |
| `mission.closed` | Mission 完成、取消或归档 | 否 |
| `candidates.built` | 候选上下文/技能/工具/Watch 已生成 | 否 |
| `decision.recorded` | 高风险、外部 runtime、fork/压缩或 harness 场景的关键选择记录 | 否 |
| `skill.selected` | 模型选择或用户显式激活 skill，记录来源和依据 | 否 |
| `skill.loaded` | SkillLoader 注入 summary/full/assets 的具体版本 | 否 |
| `skill.verified` | SkillHarness 或任务验证步骤产出结果 | 否 |
| `skill.patch.proposed` | skill candidate tool 生成 skill 创建/修改候选 | 否 |
| `skill.available` | skill 通过 lint/smoke 后进入低优先级候选集 | 否 |
| `skill.activated` | skill 从 draft/shadow 晋升 active/promoted | 否 |
| `skill.rolled_back` | skill 版本因回归或用户拒绝被回滚 | 否 |
| `model.selected` | runtime 选择模型和 fallback 信息 | 否 |
| `prompt.assembled` | L1/L2/L3 组装摘要和 token 分布 | 否 |
| `model.called` | 模型调用开始，记录 runtime/model/budget | 否 |
| `model.delta` | 用户可见模型输出增量；不包含 chain-of-thought | 否 |
| `tool.called` | 工具调用名、参数 hash、审批状态 | 仅摘要 |
| `tool.result` | 工具结果 hash、截断摘要、错误类别 | 仅摘要 |
| `tool.loop_detected` | ToolLoopGuard 发现重复调用、无效重试或 runaway scheduling | 否 |
| `tool.policy.applied` | profile + deny + risk 四级策略的生效结果 | 否 |
| `task.scheduled` | cron/watch/flow 创建或更新长期任务 | 否 |
| `task.flow.updated` | 多步任务状态、revision、cancel intent 变化 | 否 |
| `artifact.created` | 文档、diff、表格、消息草稿等产物创建 | 否 |
| `artifact.updated` | 产物流式更新或版本变化 | 否 |
| `decision.required` | 高风险动作需要用户确认 | 否 |
| `decision.resolved` | 用户批准、拒绝或编辑确认项 | 否 |
| `dream.started` | DreamCycle 空闲维护任务开始，记录预算和 delta 范围 | 否 |
| `dream.delta_collected` | 收集到的 W0、recent runs、changed pages 摘要 | 否 |
| `dream.completed` | DreamCycle 输出、跳过项、耗时、token/cost | 否 |
| `memory.query_planned` | MemoryQueryPlanner 生成多路 query 和澄清判断 | 否 |
| `memory.recalled` | BM25/vector/temporal/wiki fusion 的候选摘要 | 仅摘要 |
| `memory.queued` | 候选记忆进入 W0 或 write batch | 否 |
| `skill.observed` | 技能信号进入 observation queue | 否 |
| `inbox.pushed` | 异步通知或确认项创建 | 否 |
| `run.completed` | 最终回复、状态、token/cost | 否 |

---
---

## 10. 安全模型

### 10.1 Prompt Injection 防御

```python
# 安全扫描机制
# 扩展到记忆写入路径

MEMORY_INJECTION_PATTERNS = [
    r'ignore\s+(previous|all)\s+instructions',
    r'system\s+prompt\s+override',
    r'disregard\s+(your|all)\s+(instructions|rules)',
    # 针对记忆系统的特定攻击
    r'update\s+memory.*confidence.*1\.0',  # 强制高置信度注入
    r'set\s+exposure.*L0',                 # 强制最高暴露级别
]

def validate_memory_write(content: str, source: str) -> ValidationResult:
    """
    所有记忆写入路径的安全验证.
    
    'agent' 来源: 全部扫描
    'user' 来源: 扫描 + 提示用户确认高置信度写入
    """
```

Regex scanner 只是 cheap prefilter。真正的防线是 taint tracking + schema gate + policy gate：

```ts
type TaintSource =
  | "user"
  | "web"
  | "file"
  | "tool_result"
  | "external_runtime"
  | "imported_skill"
  | "mcp";

type TaintLevel = "trusted_user" | "local" | "external" | "untrusted" | "synthetic";

interface TaintedPayload<T> {
  value: T;
  source: TaintSource;
  taint: TaintLevel;
  evidenceRefs: string[];
  runRefs: string[];
  allowedSinks: Array<"prompt_context" | "memory_candidate" | "skill_candidate" | "tool_candidate" | "artifact_candidate">;
}
```

Taint 规则：
- 外部网页、工具结果、导入 skill、外部 runtime 返回值默认 `taint=external`，只能作为 quoted context。
- tainted payload 不能直接成为 system/developer prompt、active memory、active skill 或 executable tool。
- 写入 memory/skill/tool 前必须通过：schema validation → P60/安全审查 → evidence/provenance check → ActionEngine risk/profile check → RunLedger event。
- tainted 内容生成的 tool call 不能直接执行；必须重新走 ToolHarness 的 allowlist、schema parse、risk guard。
- 安全扫描命中不一定丢弃内容，但要降级为 safe summary 或候选，不能作为高置信事实。

### 10.2 暴露边界

```yaml
# config.yaml — 全局暴露控制

exposure_policy:
  # 页面级隐私: content dimension 决定默认暴露, privacy 决定上限
  privacy_levels:
    public: any_authenticated  # 可暴露给任何已认证 Agent
    standard: standard         # 默认级别
    sensitive: trusted         # 仅 trusted_agents 或本地高信任 runtime
    private: never             # 永不暴露给 Agent

  # 平台/运行时信任等级: 与页面 privacy 共同决定可见范围
  platform_trust:
    local_cli: sensitive
    native: sensitive
    codex: standard
    openclaw: standard
    web_api: public

  # 默认: 外部 Agent 最多看到 L1
  external_agents_max_level: L1
  
  # 例外: 可信 Agent 列表 (可读 L2)
  trusted_agents:
    - my-primary-agent
    - my-coding-assistant
  
  # 绝对私密 (从不暴露给任何 Agent)
  never_expose:
    - relationships/personal
    - patterns/sensitive
    
  # 高置信度写入需要用户确认
  require_confirmation_above: 0.85
  
  # 审计日志
  audit_all_reads: true
  audit_all_writes: true
```

### 10.3 外部 Harness 最小披露

当 Mnemo 调用 OpenClaw、Codex、ACP 或其他外部 runtime 时，安全边界按“外部 Agent”处理，即使它们运行在本机。

```python
class ContextCapsuleBuilder:
    """
    为外部 harness 构建最小披露上下文。
    默认只允许 L0 摘要 + L1 指针 + 本任务明确需要的 L2 片段。
    """

    def build(
        self,
        task: str,
        runtime: str,
        agent_type: str,
        requested_pages: list[str],
    ) -> ContextCapsule:
        """
        策略:
        1. never_expose 命中 → 拒绝
        2. requested_pages 未在 allowlist → 只给页面标题/摘要，不给正文
        3. runtime 未受信任 → max_level=L1
        4. 所有 capsule 写入 RunLedger，供 external-harness eval 检查
        """
```

外部 harness 禁止：
- 读取 `~/.mnemo/wiki/**` 原始目录，除非通过 Mnemo MCP tool 且通过 exposure policy。
- 接收完整 L4 session transcript；只能通过 `memory_search(scope="sessions")` 获取 bounded snippet。
- 写入长期记忆；只能提交 `MemoryFactCandidate`，由 Mnemo 的 MemoryWritePipeline 决定。
- 修改 Soul.md、skills、tools；只能提交候选变更进入 Inbox 或 `_generated/`。

---
