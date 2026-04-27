# Memory Engine

> 十维个人本体、W0、LLM Wiki、联想召回、DreamCycle、写入事务、L4 检索、并发和完整数据流。

## 3. 记忆子系统——活的本体论

Mnemo 的长期记忆以十维个人本体为主干：`identity`、`cognition`、`values`、`goals`、`preferences`、`relationships`、`context`、`history`、`patterns`、`boundaries`。前九维是可编译的 wiki 记忆，`boundaries` 是内部治理层，参与暴露、审批和外部 harness 安全策略。

### 3.1 记忆公理

```
╔════════════════════════════════════════════════════════════════╗
║                    Mnemo 记忆公理                               ║
╠════════════════════════════════════════════════════════════════╣
║  1. 验证原则：未被用户确认或工具验证的推断不能写为事实          ║
║                  ║
║  2. 时效原则：所有记忆携带置信度 [0.0-1.0] 和衰减函数          ║
║  3. 最小指针原则：L1 索引只留能定位 L2 的最短标识，零冗余      ║
║  4. 禁止易变状态：当前项目状态/临时配置不进本体，进 context    ║
║  5. 暴露最小化：Agent 看到的记忆 ∝ 任务相关性，非记忆总量      ║
║  6. 过时有害原则：标记为 stale 的记忆优先清理而非沉默保留      ║
║  7. 真相源原则：Wiki + SQLite metadata + RunLedger 是真相源；索引只是派生物║
║  8. 检索先于召回：错误 query 会让整条记忆链路失效，必须先规划 query║
║  9. 选择性遗忘：删除/否认/替代的记忆要有 tombstone，防止历史回流污染║
╚════════════════════════════════════════════════════════════════╝
```

**Source of Truth**:

Mnemo 的真相源是用户可审计、可版本化、可导出的文件和账本：

```text
Source of Truth = wiki/*.md + policy/*.yaml + state.db metadata + RunLedger
Derived Indexes = FTS5 / vector / wiki links / association index / compiled L0-L1 / cache
Not Source of Truth = embedding vectors, model hidden state, prompt cache
```

这意味着：

- 向量库、BM25、reranker 只加速召回，不能成为唯一事实。
- 任何索引都能从 wiki + state.db + runs 重建。
- 迁移到其他模型或 runtime 时，记忆仍然成立。
- 用户否认或删除的事实必须进入 tombstone，而不是只从索引里删掉。

### 3.2 十维个人本体

Mnemo 的长期记忆不是自由文本池，而是关于一个人的十维本体。十维结构的价值在于：它让 Agent 不只是“检索到事实”，而是能形成可行动的人格模型。

| # | 维度 | 英文 | 核心问题 | 内容示例 | 默认暴露 |
|---|------|------|----------|----------|----------|
| 1 | 身份 | `identity` | 我在跟谁说话？ | 姓名、角色、所在地、职业、长期身份 | L0/L1 |
| 2 | 认知 | `cognition` | 这个人如何理解世界和学习？ | 技能、知识边界、学习方式、思维模型 | L1 |
| 3 | 价值观 | `values` | 这个人做选择时在乎什么？ | 原则、底线、优先级、世界观 | L1 |
| 4 | 目标 | `goals` | 这个人正在追求什么？ | 短期/长期目标、阶段状态、里程碑 | L1 |
| 5 | 偏好 | `preferences` | 这个人喜欢怎样被服务？ | 工具、沟通、审美、工作流偏好 | L1 |
| 6 | 关系 | `relationships` | 哪些人和组织会影响他？ | 团队、朋友、家庭、协作关系 | L2 |
| 7 | 语境 | `context` | 此刻他处在什么局面？ | 当前项目、生活阶段、约束、近期挑战 | L1/L2 |
| 8 | 历史 | `history` | 哪些过去经历解释了现在？ | 重要决策、教训、成就、失败案例 | L2 |
| 9 | 模式 | `patterns` | 他反复表现出什么倾向？ | 日常习惯、卡点、能量节律、行为循环 | L2 |
| 10 | 边界 | `boundaries` | 什么不该被做或暴露？ | 隐私规则、授权范围、禁止事项、信任等级 | 内部 policy |

**维度职责**:
- `identity` 是入口，帮助 Agent 建立最低限度的身份上下文，但只放稳定事实。
- `cognition + preferences` 决定回答方式：解释深度、代码/文字比例、工具选择。
- `values + goals + context` 决定行动方向：什么值得推进、什么应该推迟。
- `relationships + history + patterns` 提供深度个性化：为什么这个人会这样选择，哪里容易重复卡住。
- `boundaries` 是治理层，不应作为普通 wiki 内容随意召回，而应参与 Memory Router、ContextCapsule、ApprovalGate 和外部暴露检查。

**Preferences 与 Skills 的边界**:

| 类型 | 存什么 | 示例 | 归属 |
|------|--------|------|------|
| `preferences` | 关于用户偏好的事实 | “用户偏好直接沟通，不喜欢长选项列表” | `wiki/preferences/*` |
| `interaction skill` | Agent 应如何执行该偏好 | “回答先给结论；超过 2 个选项时直接推荐一个” | `skills/interaction/*` |
| `workflow/SOP skill` | 可复用任务步骤 | “检查 PR 时先看 CI，再看 review，再总结 blocker” | `skills/workflow` / `skills/sop` |

**Context 的约束**:
- `context` 默认有 TTL，必须带 `status`、`updated`、`decay_days` 或 `expires`。
- 当前项目、近期压力、临时约束可以进入 `context`，但 cwd、PID、一次性 token、临时命令输出不得进入长期本体。
- `context` 中超过有效期的事实优先进入 stale review，而不是继续被 L1 摘要引用。

**十维交叉引用示例**:

```markdown
<!-- wiki/goals/learn-rust.md -->
---
dimension: goals
status: active
links:
  - cognition/programming-languages#rust
  - context/current-projects#mnemo
  - preferences/tools#editor
  - values/craft#systems-thinking
---

# 学好 Rust

目标: 2026 Q3 达到 Rust 生产力水平。
当前水平见 [[cognition/programming-languages#rust]]。
动机来自 [[context/current-projects#mnemo]] 对性能和本地优先的要求。
```

**默认暴露策略**:

```yaml
dimension_exposure:
  identity:       {default: L0, max_external: L1, ttl: permanent}
  cognition:      {default: L1, max_external: L1, ttl: slow_decay}
  values:         {default: L1, max_external: L1, ttl: slow_decay}
  goals:          {default: L1, max_external: L1, ttl: active_decay}
  preferences:    {default: L1, max_external: L1, ttl: slow_decay}
  relationships:  {default: L2, max_external: none, ttl: review_required}
  context:        {default: L1, max_external: L1, ttl: short_decay}
  history:        {default: L2, max_external: summary_only, ttl: archive}
  patterns:       {default: L2, max_external: summary_only, ttl: slow_decay}
  boundaries:     {default: policy, max_external: never, ttl: permanent}
```

### 3.3 记忆金字塔（进化版）

```
  W0: Working Memory               (当前 Mission/会话生命周期, turn 级草稿按需清理)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  │ 三类用途:                                        │
  │   task_state   — 当前 Mission 中间状态 (不进本体) │
  │   pending_obs  — 待批量写入本体的观察候选队列    │
  │   draft_facts  — 本轮对话中新发现但未验证的事实  │
  │                                                 │
  │ working_note tool 写入; turn_end / mission_end 时:│
  │   → turn_scratch 丢弃或压缩                     │
  │   → mission_state 写 checkpoint, 可跨轮恢复     │
  │   → pending_obs → learning packet candidates     │
  │   → draft_facts → L2 草稿 confidence=0.5        │
  └─────────────────────────────────────────────────┘

  L0: Profile Token Card          (~200-400 tokens, 任何 Agent 请求都注入)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  │ "张伟, Senior SWE @ TechCorp. Python/Rust 8y/2y. │
  │  AI/ML 聚焦. 直接沟通. 当前: Mnemo v2 构建中.   │
  │  核心价值: 隐私优先, 第一性原理. 时区: UTC+8."   │
  └─────────────────────────────────────────────────┘

  L1: Dimension Index              (~800-1200 tokens, 默认注入)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  (≤50行硬约束，场景触发词→维度指针映射)
  │ ## Pointers                                      │
  │ coding/debug → cognition#languages,prefs#tools   │
  │ health       → patterns#sleep,goals#health       │
  │ career       → goals#career,values#work          │
  │ ## Summaries (active items only)                 │
  │ [goals] Q3: Mnemo launch. [current]              │
  │ [cognition] Rust:growing, Python:fluent          │
  │ [context] Solo project, 3h/day available         │
  └─────────────────────────────────────────────────┘

  L2: Dimension Pages              (~500-2000 tokens each, 按需路由)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  wiki/cognition/programming-languages.md
  wiki/goals/mnemo-project.md
  wiki/preferences/tools.md
  wiki/relationships/team.md
  wiki/patterns/daily-routine.md
  ...

  L3: Detail & Historical          (仅搜索可达)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  wiki/_archive/, 对话摘要, 旧版本页面

  L4: Raw Sessions                 (FTS5 全文检索; 审计/深度召回)
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  state.db :: sessions + messages + messages_fts
  保留全量会话消息; 支持 FTS5 跨会话关键词搜索
  → "上次我在哪次对话里提到过 lifetime?" 可精确召回
  → 按 source/agent_type/date 过滤; 按相关性排序
  
```

### 3.4 记忆 Frontmatter Schema

```yaml
# wiki/goals/learn-rust.md
---
dimension: goals
status: active          # active | paused | completed | stale | archived | tombstoned
confidence: 0.92        # AI 对此事实的置信度
created: 2026-03-15
updated: 2026-04-18
expires: 2026-09-30     # 可选: 超过日期自动标 stale
decay_days: 90          # 若 90 天未更新, confidence 每天降 0.01
aliases: ["rust async", "tokio", "lifetime"] # QueryPlanner 使用的别名/代号

# 交叉引用 (wiki anchor links)
links:
  - cognition/programming-languages#rust
  - context/current-projects#mnemo
  - preferences/tools#editor

# 暴露控制
exposure:
  min_level: L2         # 至少 L2 才能读到此页
  agent_types: [coding, planning]  # 哪类 Agent 自动路由到此页

# 主动服务关联
watches: [rust-progress]  # 关联哪些 Watch 任务
---

# 学好 Rust

目标：2026 Q3 达到 Rust 生产力水平...
```

`dimension` 只接受九个内容维度：`identity|cognition|values|goals|preferences|relationships|context|history|patterns`。`boundaries` 不作为普通 wiki page 的 `dimension`，它存放在 `policy/boundaries.yaml` 和 `policy/exposure.yaml`，由 Memory Router、ApprovalGate、ContextCapsuleBuilder 执行。

### 3.5 Memory Search Pipeline：先规划 Query，再混合召回

记忆检索失败最常见的原因不是索引不够强，而是 query 构造错。Mnemo 把 query planning 作为检索第一步，而不是直接把用户原话丢给 BM25 或向量库。

```text
MemorySearchPipeline
  1. QueryPlanner       # 多语言、别名、项目代号、时间线索、澄清问题
  2. Lexical Recall     # FTS5/BM25，精确词、代号、文件名
  3. Semantic Recall    # vector embedding，语义近邻
  4. Temporal Recall    # recent/current/stale/window filters
  5. Wiki Expansion     # [[links]]、同维度邻居、十维指针扩展
  6. Fusion             # RRF 合并多路结果
  7. Dedup              # MMR 去重，避免同一事实多版本刷屏
  8. Rerank             # 预算允许时调用 reranker 或 llm_task
  9. Annotate           # 标记 confidence/stale/conflict/tombstone
  10. Return Capsule    # 返回最小可用片段，不直接倾倒整页
```

**MemoryQueryPlanner**:

```ts
type MemoryQueryPlan = {
  original: string;
  lexical: string[];      // 原词、代号、专有名词，保留用户语言
  semantic: string[];     // 改写后的语义 query
  aliases: string[];      // 项目别名、车型代号、人名简称等
  temporal?: string;      // "last week", "2026Q1", "recent"
  dimensions?: string[];  // goals/preferences/context/...
  shouldClarify: boolean;
  clarifyQuestion?: string;
};
```

QueryPlanner 的规则：

- 保留原语言 query，不默认把中文概念翻译成英文。
- 对数字、代号、缩写、品牌、项目名保留 lexical recall。
- 不确定实体含义时先多路召回；仍冲突时问一个澄清问题。
- 从 L1 指针、aliases frontmatter、recent runs 中补 query，不只依赖用户原话。

第一版可以只做 FTS5 + embedding + RRF + MMR；reranker、图遍历和多模态 embedding 是可插拔增强。

### 3.6 Memory Compiler（进化版）

```python
class MemoryCompiler:
    """
    将 L2/L3 页面蒸馏为 L0/L1 编译产物。
    
    触发条件:
      - L2 页面 frontmatter.updated 变化
      - DreamCycle 编排的定时/空闲编译
      - 显式 `mnemo compile`
      - 置信度衰减导致 stale 超出阈值
    """
    
    def compile_l0(self, dimension_summaries: list[str]) -> str:
        """生成 Profile Token Card: 3-5 句, 极高密度"""
        
    def compile_l1_index(self, wiki_pages: list[WikiPage]) -> str:
        """
        生成 L1 Dimension Index.
        硬约束: ≤50 行 / <1200 tokens.
        
        两层结构:
          Layer A: 场景触发词 → 维度指针 (高频场景直接映射)
          Layer B: 活跃事实摘要 (current/active items only)
        
        十维本体约束:
          - identity/cognition/values/goals/preferences/context 可进入 L1
          - relationships/history/patterns 默认只留指针或摘要, 不展开细节
          - boundaries 只参与 policy, 不作为普通内容编译进 L1
        
        剔除规则:
          - 通用常识 → 不写 (大模型已知)
          - 易变状态 → 不写 (当前 cwd, 临时 PID 等)
          - 低置信度事实 (< 0.5) → 标记 [?] 或移入 L3
          - 超过 expires 的事实 → 触发 stale 流程
        """
        
    def compile_dimension_summary(self, pages: list[WikiPage], dimension: str) -> str:
        """为单个维度生成 L1 段落摘要"""

COMPILER_PROMPT = """
You are a personal memory compiler. Distill wiki pages into a maximally dense index.

CONSTRAINTS:
- Every token must earn its place. Cut adjectives, filler, meta-commentary.
- Use compressed notation: "Python 8y, Rust 2y" not "experienced in Python and Rust"
- Active/current items take priority over historical ones
- Temporal markers required: [current] [recent-6mo] [historical]
- Flag contradictions: "[CONFLICT: goal X vs goal Y]"
- Flag stale facts: "[STALE: last updated 180d ago]"
- Confidence notation for uncertain facts: "possibly React [0.6]"

Layer A format:
  <trigger-scenario> → <dimension>#<section>[, <dim>#<sec>]
Example:
  writing/docs → prefs#writing-style, cognition#communication

Layer B format:
  [<dimension>] <compressed-fact>. [<temporal>]
Example:
  [goals] Q3 Mnemo launch, Q4 Rust prod-ready. [current]
"""
```

### 3.7 时间感知、选择性遗忘与 Tombstone

```python
class TemporalManager:
    """管理记忆的时效性和置信度衰减"""
    
    def decay_pass(self, page: WikiPage) -> WikiPage:
        """
        每日衰减计算:
          age_days = (today - page.updated).days
          if age_days > page.decay_days:
              daily_decay = 0.01
              page.confidence -= daily_decay * (age_days - page.decay_days)
          if page.confidence < 0.3:
              → 触发 "memory verification" 提示给用户
          if page.confidence < 0.1 and page.status == 'active':
              → 自动降级为 status='stale', 移出 L1 摘要
        """
    
    def stale_review_prompt(self, stale_pages: list[WikiPage]) -> str:
        """
        生成用户验证请求:
        "以下 3 条记忆可能已过时，请确认:
          1. [goals] 学好 Rust → 仍在进行? (最后更新 6 个月前)
          2. [context] 在 TechCorp 工作 → 仍然吗?
          3. [patterns] 每天 6:30 起床 → 还是这个时间?"
        """
```

选择性遗忘不是物理删除，而是把“不应再被用作事实”的信息从 active recall 中移出，并留下可审计的 tombstone，防止 DreamCycle 或 L4 session search 又把旧事实挖回来。

实现上不需要固定的“每日衰减流水线”。MemoryEngine 暴露一个有界维护能力：读取 active page 的 `metadata.expires` / `metadata.expires_at` / `metadata.decay_days` / `metadata.last_verified_at`，生成 `memory_decay_report`，并在模型决定调用时把过期页面标为 `stale:expired`、把置信度衰减到阈值以下的页面标为 `stale:decay`。Health report 只给出 `decay_due_active`、`expired_active` 和 review cards，不直接替模型做调度决策。

L4 session recall 默认也要尊重 tombstone：`memory_search(scope="sessions"|"all")` 会过滤命中 tombstone 摘要/标题信号的 session snippets，避免被否认的事实从历史聊天重新进入上下文。只有当用户或模型明确要做历史追溯时，才传 `include_tombstoned=true`，并且仍只返回 bounded snippet，不返回完整 transcript。

| Forget reason | 触发 | 处理 |
|---------------|------|------|
| `stale` | 过期且低置信 | 移出 L1，保留 L2 stale，等待验证 |
| `superseded` | 新事实替代旧事实 | 旧事实 archive，active 只保留新版 |
| `rejected` | 用户明确否认 | 写 tombstone，禁止自动复活 |
| `harmful` | 该记忆导致错误建议或错误行动 | 降权并进入 memory-core eval |
| `private_delete` | 用户要求删除 | 删除内容，保留最小 tombstone hash |
| `low_usefulness` | 长期未被引用或引用后无收益 | 降级到 L3/archive，不进 L1 |

```yaml
memory_tombstone:
  id: tomb_20260424_001
  target_path: context/old-startup-idea
  target_hash: sha256:...
  reason: rejected
  created_at: 2026-04-24
  evidence_run_id: run_...
  rule: "Do not re-create this fact from historical sessions unless user explicitly restates it."
```

Tombstone 只存最小必要信息，避免把用户要求删除的敏感内容再次写回系统。

实现接口：
- `MemoryEngine.private_delete_memory(id, reason, target_type)`：redact page/candidate 原文，写 `reason=private_delete` tombstone，只保留 `target_hash`、source run provenance 和非原文摘要。
- `mnemo memory forget <id>` / `memory_private_delete` tool：显式触发 private delete；这是模型可选择调用的写工具，不是后台固定流程。
- 对由 candidate promoted 出来的 page，private delete 会同步 redact source candidate；对 candidate，会同步 redact promoted pages。
- L4 session search 默认用 private-delete tombstone 的 `evidence_run_id` 抑制源 run snippets；不为了抑制召回而重新保存被删除文本。
- `MemoryEngine.tombstone_memory(id, reason, target_type, replacement_id?)`：统一承载非隐私选择性遗忘；`low_usefulness` 归档为 `archived:low_usefulness`，可选 `replacement_id` 写入 `superseded_by` link 和 compact tombstone metadata。
- `reason=harmful`：在已有 source run 或显式 `eval_run_id` 可用时，写入 compact `memory_harmful_regression` eval case，用于后续 memory-core 回归，不保存完整记忆正文或原始 transcript。

### 3.8 记忆信息决策树

```
"这条信息该如何处理?"

是关于「这个人」的持久性事实?
  ├─ YES → 值得长期存储?(质量过滤: 非常识/非可推理/有个性化价值)
  │         ├─ NO  → 丢弃
  │         └─ YES → 属于十维本体哪一维?
  │                   ├─ identity/cognition/values/goals/preferences
  │                   │    → L2 对应维度页面; 高价值摘要可进入 L1/L0
  │                   ├─ relationships/history/patterns
  │                   │    → L2/L3; 默认按需召回, 不自动暴露给外部 Agent
  │                   ├─ context
  │                   │    → L2 context 页面; 必须带 TTL/status/decay
  │                   └─ boundaries
  │                        → policy 层; 影响 Router/ApprovalGate, 不进普通 prompt
  │
  └─ NO  → 是当前对话焦点/Mission 的临时上下文或任务中间状态?
            ├─ YES → W0 Working Memory (working_note 工具)
            └─ NO  → 是用户提到但未验证的信息?
                      ├─ YES → W0 draft_facts 队列 + 等待验证
                      │        (mission_end 或 DreamCycle 时提升为 L2 草稿 confidence=0.5)
                      └─ NO  → 是可执行行为规则/重复工具序列?
                                ├─ YES → 作为 learning packet 证据，由模型选择 skill/tool/eval 候选工具
                                └─ NO  → 丢弃 (通用常识/可推理信息)
```

### 3.9 Working Memory (W0)——Mission 级草稿层

W0 是**当前 Mission/会话生命周期内**的临时存储层，不进入长期本体，但不能简单等同于聊天上下文窗口。一次用户委托可能跨很多轮：用户下一轮说“继续”“改成表格”“刚才那个发给 Alex”，系统必须能恢复目标、约束、产物、开放决定和中间状态，而不是只依赖上一轮 prompt。

W0 分成两层：

| 层 | 生命周期 | 用途 |
|----|----------|------|
| `turn_scratch` | 当前 run/turn | 工具临时输出、循环计数、短期 scratchpad；turn 结束后丢弃或摘要 |
| `mission_state` | 当前 Mission | 目标、计划、artifact 指针、open decisions、关键中间状态；跨轮 checkpoint |

只有 Mission 完成、取消、归档或 DreamCycle 压缩后，`mission_state` 才会被蒸馏为长期记忆、技能观察或归档摘要。这样 Mnemo 可以长期执行任务，同时避免把每个临时步骤都污染长期本体。

```python
class WorkingMemory:
    """
    Mission 级草稿缓冲。四种职责完全独立：
    
    turn_scratch:  当前 turn 的临时 scratchpad（工具片段、循环计数、临时假设）
                   → turn 结束时丢弃或压缩进 mission_state
    
    task_state:    当前 Mission 的中间进度（文件路径、计划、artifact 指针、上一步结果）
                   → 等价于 GenericAgent 的 working_checkpoint
                   → turn 结束时写入 mission checkpoint，Mission 结束后再蒸馏或归档
    
    pending_obs:   本轮已收集但尚未批量写入的行为观察
                   → turn 结束可批量归档，Mission 结束时进入 learning packet
                   → 可随时 flush（如 context 临近压缩触发前）
    
    draft_facts:   用户在本次对话中提及但尚未确认的新事实
                   → 示例: "顺便一提我换工作了" → draft: identity/job
                   → Mission 结束或 DreamCycle 时通过 stale_review_prompt 请求用户确认
                   → 确认后 → L2; 拒绝后 → 丢弃
    """
    
    def set_turn_scratch(self, key: str, value: Any) -> None:
        """记录当前 turn 内临时状态"""
    
    def set_task_state(self, key: str, value: Any) -> None:
        """记录 Mission 中间状态，类似 durable checkpoint"""
    
    def get_task_state(self, key: str, default: Any = None) -> Any:
        """读取 Mission 状态"""
    
    def append_observation(self, obs: Observation) -> None:
        """追加行为观察到待处理队列"""
    
    def add_draft_fact(self, dimension: str, content: str, confidence: float = 0.5) -> None:
        """追加待验证事实草稿"""
    
    def flush_to_learning_packet(self) -> WorkingMemoryDump:
        """Mission 结束或 DreamCycle 时将候选数据打包成 learning packet"""
    
    def checkpoint_mission(self, mission_id: str) -> MissionCheckpoint:
        """turn 结束时持久化 goal/plan/artifacts/open_decisions/task_state 摘要"""
    
    def on_pre_compress(self) -> None:
        """
        Context 压缩触发前的钩子:
        - 将 pending_obs 写入 patterns/ 归档（防止压缩时丢失观察信号）
        - task_state 序列化写入 mission checkpoint 作为跨轮断点
        """
```

> **与 L3 的区别**: L3 是已蒸馏的历史记录（wiki/_archive/）；W0 是当前 Mission 的临时暂存，正常情况对用户不可见，只在跨轮恢复和蒸馏流程里消费。

### 3.10 记忆矛盾与冲突解决

当新信息与已有记忆产生矛盾时，采用**显式矛盾协议**，而非静默覆盖：

```python
class ConflictResolver:
    """
    矛盾检测 + 分级解决策略。
    
    矛盾来源:
    1. Agent 观察到的事实与 L2 页面内容不一致
    2. 用户在本次对话中明确更正了某个记忆
    3. 两个 L2 页面之间相互矛盾 (e.g. goals 说"辞职创业" vs context 说"在 TechCorp")
    4. 联邦同步时两个 Mnemo 实例的同一字段有差异
    """
    
    ConflictSeverity = {
        "MINOR": 0,    # 细节不一致, 可信度差 < 0.2
        "MODERATE": 1, # 明确矛盾, 需要标记
        "CRITICAL": 2, # 核心事实矛盾 (身份/就业/就学等), 必须用户确认
    }    
    
    def detect_conflict(
        self,
        new_fact: str,
        existing_page: WikiPage,
    ) -> Conflict | None:
        """
        检测矛盾:
        - LLM 对比新事实与现有页面内容
        - 判断是否存在实质矛盾（不是补充，是替代）
        - 返回 Conflict(old_fact, new_fact, severity, page_path)
        """
    
    def resolve(self, conflict: Conflict) -> ConflictResolution:
        """
        按 severity 分级处理:
        
        MINOR:
          → 自动追加到页面（保留旧内容作为历史，降置信度至 0.6）
          → L1 编译时只反映最高置信度版本
        
        MODERATE:
          → 自动选择可信度高的一侧写入 L2
          → 旧版本标注为 [SUPERSEDED] 但保留在 audit trail
          → 写 Inbox 条目: "记忆已更新: <field>，旧值: '...'，新值: '...'"
          → 用户可在 Inbox 中查看详情或回滚；无需当场确认
        
        CRITICAL:
          → 当前会话不覆盖任何一侧（双侧并存，低置信度标注）
          → 写 Inbox 高优先级条目 (priority=HIGH):
            "需要你帮我确认: 你之前告诉我 '...'，
             但今天提到 '...'。两个哪个是对的？
             [选择旧版] [选择新版] [两个都对 - 是不同语境]"
          → 用户下次打开 Inbox 或发起对话时看到（不打断当前任务流）
          → Inbox 14 天无响应 → 自动保留高置信度侧，低置信侧 archive
        """
    
    CONFLICT_DETECTION_PROMPT = """
    Compare these two statements about the same person:
    
    Existing (confidence={existing_conf}): {existing_fact}
    New observation: {new_fact}
    
    Assessment:
    1. Is this a contradiction (new replaces old) or an update (new extends old)?
    2. If contradiction: severity? (MINOR/MODERATE/CRITICAL)
    3. What is the likely ground truth?
    
    Return: {"type": "contradiction|update", "severity": "MINOR|MODERATE|CRITICAL", 
             "ground_truth_hint": "..."}
    """
```

### 3.11 记忆溯源与审计轨迹

每条写入记忆的事实都携带**完整的溯源上下文**，支持回溯与纠错：

```sql
-- 记忆写入事件日志
CREATE TABLE memory_write_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    page_path   TEXT NOT NULL,           -- 写入的 wiki 页面路径
    session_id  TEXT NOT NULL,           -- 来源会话 ID
    agent_type  TEXT NOT NULL,           -- coding|planning|general|reflect
    operation   TEXT NOT NULL,           -- create|update|conflict_resolve|stale|archive
    old_content_hash TEXT,              -- 写入前内容 hash（用于回滚）
    new_content_hash TEXT NOT NULL,     -- 写入后内容 hash
    confidence_before REAL,
    confidence_after  REAL,
    trigger_type TEXT NOT NULL,         -- user_confirmed|agent_inferred|session_reflect|daily_compile
    evidence_quote TEXT,                -- 触发此写入的用户原话片段（如有）
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mwl_page     ON memory_write_log(page_path, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mwl_session  ON memory_write_log(session_id);
```

```python
class MemoryAuditTrail:
    """
    记忆历史查询接口。
    
    使用场景:
    - 用户问: "你什么时候开始觉得我喜欢 Rust?"
      → query_page_history("goals/learn-rust")
      → 返回首次写入时间、触发会话摘要、置信度变化曲线
    
    - 用户说: "你记错了，我从没说过那个"
      → rollback_to_before(page_path, session_id)
      → 恢复到该会话写入之前的状态
    
    - 管理员审计: 查看某时间段内所有记忆变动
      → query_writes_in_range(start, end)
    """
    
    def query_page_history(self, page_path: str, limit: int = 10) -> list[WriteEvent]:
        """返回某页面的写入历史，按时间倒序"""
    
    def rollback_to_before(self, page_path: str, session_id: str) -> bool:
        """回滚到某会话写入之前的状态"""
    
    def explain_fact(self, page_path: str, fact_snippet: str) -> str:
        """
        解释某条事实的来源:
        '你为什么知道我在学 Rust?'
        → '你在 2026-03-15 的对话中提到: \"我最近在学 Rust\"'
        → confirmation_session: abc123, confidence: 0.92
        """
```

### 3.12 记忆质量过滤器

在写入 L2 之前，所有候选事实必须通过质量评估，避免记忆库堆满低价值条目：

```python
class MemoryQualityFilter:
    """
    五维度质量评估。任一维度不达标则拒绝写入（进 W0 草稿队列或丢弃）。
    """
    
    DIMENSIONS = {
        "specificity":    "是否具体？(非'用户喜欢技术'，而是'用户偏好 Python 而非 Java')",
        "personalization": "是否个性化？(非常识，而是关于这个人的独特信息)",
        "persistence":    "是否持久？(非今日心情，而是稳定偏好/事实)",
        "actionability":  "是否可操作？(是否能让 Agent 下次表现更好)",
        "verifiability":  "是否可验证？(非纯猜测，有对话证据支撑)",
    }
    
    MIN_SCORE = 0.6      # 加权平均分低于此值拒绝写入
    AUTO_APPROVE = 0.85  # 高于此值免人工审核直接写入（仅 confidence ≥ 0.8 时）
    
    QUALITY_FILTER_PROMPT = """
    Evaluate this candidate memory fact for writing to long-term store.
    
    Candidate: {fact}
    Source: {evidence_quote}
    
    Score each dimension 0.0-1.0:
    - specificity: Is this specific to this person's unique situation?
    - personalization: Is this not just common knowledge?
    - persistence: Does this represent a stable trait, not a one-time state?
    - actionability: Would this meaningfully improve future agent behavior?
    - verifiability: Is this directly evidenced, not speculated?
    
    Return: {"scores": {...}, "weighted_avg": float, "recommendation": "write|draft|discard",
             "reason": "one sentence"}
    """
```

### 3.13 记忆养成系统：冷启动、卡片与健康度

一个关键洞察：记忆系统不是只靠后台抽取，也要让用户愿意长期“养”它。Mnemo 的记忆养成系统不应打断任务，而应在自然空档、晨报、Inbox 或 `mnemo stats` 中低压出现。

**冷启动五阶段**:

| 阶段 | 目标 | 机制 | 输出 |
|------|------|------|------|
| Quick Profile | 2 分钟内建立最小可用画像 | 模型生成 3-5 个低负担问题，用户可跳过 | L0 Profile + 骨架 L1 |
| Smart Import | 从已有数字足迹推断初始记忆 | GitHub、dotfiles、编辑器配置、项目 manifest；每条推断需确认 | cognition/preferences/context 草稿 |
| Guided Conversation | 首次会话补足关键维度 | 模型基于已有画像选择下一个最值得问的问题 | 高价值 L2 页面 |
| Ambient Learning | 日常使用中静默积累 | AgentRunHarness 收集 learning packet，模型按需提出候选 | pending_obs / draft_facts |
| Gamified Discovery | 长期补全薄弱维度 | 记忆卡片、健康度建议、周期性验证 | 更高 coverage/freshness |

**记忆卡片类型**:

| 类型 | 作用 | 模型决策依据 |
|------|------|--------------|
| 探索卡 | 补足低覆盖维度 | 哪个维度最影响后续服务质量 |
| 验证卡 | 确认可能过时的事实 | confidence、decay、recent contradiction |
| 深入卡 | 把表层事实变成可行动记忆 | “知道什么”还不足以改善行为时触发 |
| 连接卡 | 建立 wiki 交叉引用 | 两个页面相关但缺少显式链接 |
| 反思卡 | 捕捉历史、模式、价值观 | 周期性回顾、重大事件后 |

卡片不是固定规则轮播，而是由运行中的模型从 `MemoryHealthReport`、最近会话、Watch 状态和用户打扰成本中选择。用户可以回答、跳过、延后或永久关闭某类卡片。

**Memory Health Score**:

```yaml
memory_health:
  coverage:        # 十维覆盖率; boundaries 只看 policy 完整度
  freshness:       # stale 页面比例、active context 是否过期
  connectedness:   # wiki links、孤儿页面、联想热点
  evidence_quality:# source/evidence/confidence 完整度
  usefulness:      # 被 run 引用后是否提升 task_success / preference_adherence
  safety:          # wrong_memory / over_personalization / unsafe_disclosure
```

健康度的用途不是给用户制造负担，而是给模型一个“下一步该维护什么”的状态输入。`mnemo stats` 和晨报只展示高价值建议，例如：“`relationships` 维度覆盖低，但近期任务没有用到，暂不打扰”；“`context/current-projects` 影响多个 Watch，建议验证”。

`memory-health` harness 是这套机制的确定性回归门禁：它不调用模型、不跑后台流程，只验证 tombstone 是否压住 wrong-memory 复活、低置信偏好是否不会污染 L1/稳定页、冲突候选是否进入 review card、健康报告是否保持 compact 且不泄露原始证据或完整页面内容。

### 3.14 DreamCycle：空闲期记忆整理

DreamCycle 是 Mnemo 的低优先级后台记忆维护循环。daemon 负责触发条件、预算、锁、暂停和账本；具体整理什么、怎么合并、是否建 link、是否提出 skill/tool 候选，由模型在一次受限的 Dream maintenance run 中决定。

目标：每天把零散观察变成更短、更准、更有用的个人记忆，同时不打扰用户、不全量扫库、不把大量内容塞进 prompt。

**触发条件**:

| 触发 | 说明 |
|------|------|
| idle window | daemon 检测到无 active run、无高优先级队列、设备不在驾驶/会议等状态 |
| daily quiet time | 默认 02:00，本地可配置 |
| mission_idle delay | Mission 空闲或结束后延迟批处理 W0，避免任务中途写长期记忆 |
| backlog threshold | `pending_obs`、`draft_facts` 或 stale candidates 积累到阈值 |
| manual | `mnemo dream --now` |

当前实现用轻量 scheduler 承载 daily/idle 触发：`mnemo schedule add --kind dream` 默认创建 daily Dream maintenance item，也可显式传入 `--schedule daily`。SDK/HTTP 侧通过 `schedule_dream`，MCP 侧通过 `mnemo_dream_schedule` 暴露同一注册能力，仍然只写入 scheduled item 和预算元数据。到期 tick 会直接运行 bounded `MemoryEngine.dream_maintenance()`，写入 compact Dream report，刷新 L1 snapshot，并把最新 report card 存回 scheduled item metadata；watch/cron 仍然走普通 queue。

**输入只看增量**:

```yaml
dream_input:
  recent_runs: last_24h_or_since_last_dream
  w0_pending: draft_facts + pending_obs + task_state_summaries
  changed_pages: wiki pages changed since last compile
  stale_candidates: pages whose confidence/expiry changed
  tombstones: rejected/deleted facts that must not be resurrected
  hot_skills_tools: recently used skills/tools with failures or repetition
  inbox_context: unresolved memory/skill confirmations
```

**模型主导执行**:

Dream 的 less-is-more 分工：

| 层 | 负责什么 |
|----|----------|
| daemon | 何时运行、预算多少、是否暂停、只取增量、不阻塞用户 |
| Memory tools | 检索 delta、读取 wiki、写候选 patch、跑质量/冲突检查 |
| model | 规划本次维护重点，选择要处理的记忆/skill/tool 信号 |
| RunLedger | 记录 plan、tool calls、patch、跳过原因、成本和 eval |

系统不把每天维护写死成必须完整跑完的流水线。模型拿到 delta、预算和工具后，自主决定本轮优先级；预算不足时宁可少做，也不全量扫库。

当 health cards 显示存在过期或衰减候选时，Dream plan 可以把 `memory_decay_stale_pages` 作为可选工具暴露给模型。模型可以选择执行、先读取证据、请求用户确认，或跳过并记录原因。

Dream report 可以携带模型显式提出的 maintenance actions，形态兼容原生 tool call：

```json
[
  {"tool": "memory_tombstone", "arguments": {"memory_id": "mem_x", "reason": "low_usefulness"}},
  {"function": {"name": "memory_decay_stale_pages", "arguments": "{\"limit\": 20}"}},
  {"type": "tool_use", "name": "memory_tombstone", "input": {"memory_id": "mem_y", "reason": "harmful"}}
]
```

运行时只负责执行白名单内的记忆维护工具：`memory_tombstone` 和 `memory_decay_stale_pages`。无效、缺字段、找不到目标或不支持的 action 会进入 `execution.result.actions.skipped`，不会中断 Dream。这样模型可以同时提出多个候选动作，系统只提供能力边界和审计结果，不把 Dream 固化成固定流程。

```text
Dream maintenance run
  1. daemon.collect_delta          # 收集增量，不读全库
  2. model.plan                    # 选择本次维护重点和跳过项
  3. model uses memory tools       # 读页、查证据、提 patch、建 link 候选
  4. pipelines validate            # quality/conflict/privacy/schema/evidence
  5. compile changed anchors       # 只重编受影响 L0/L1/cache anchors
  6. optional mine skill/tool      # 只有高信号重复轨迹才处理
  7. optional replay smoke         # 只对关键 patch 跑轻量 eval
  8. inbox digest                  # 只把需要用户确认的少数事项写 Inbox
```

**预算与降级**:

| 预算项 | 默认 |
|--------|------|
| max wall time | 5-10 min |
| max model calls | 3 normal / 8 extended |
| max pages touched | 20 |
| max inbox items | 5 |
| max prompt per call | 8k tokens |

预算不足时，daemon 给出硬边界，模型选择本轮最值得处理的事项。默认优先级是：用户明确要求记住/删除 → correction/conflict → active project/profile compile → wiki link maintenance → skill/tool signals → replay smoke。Dream 永远不能阻塞用户同步请求。

**输出**:

- L0 Profile Card / L1 Index 更新。
- L2 页面 patch 或 stale 标记。
- memory health report。
- skill patch / `_generated` draft。
- Inbox digest。
- RunLedger dream trace：`dream.started`、`dream.delta_collected`、`dream.plan_recorded`、`dream.completed`。

**伪代码**:

```ts
interface DreamCycle {
  shouldRun(now: Date, state: DaemonState): boolean;
  collectDelta(since: Date): DreamInput;
  run(input: DreamInput, budget: DreamBudget): Promise<DreamReport>;
}

// 用户同步请求优先级永远高于 dream。
if (queue.hasPriorityLTE(1)) {
  dream.pause();
}
```

### 3.15 LLM Wiki 与联想召回

LLM Wiki 不是 Agent 通信扩展，而是 Memory Engine 的组织方式。它依赖 wiki 真相源、L1 编译、Memory Router、DreamCycle 和 MemoryWritePipeline，因此权威设计放在本章。

边界拆分：

| 能力 | 归属 | 默认路径 | 说明 |
|------|------|----------|------|
| `[[wiki-links]]` | MemoryEngine core | 是 | 页面之间的显式自然语言链接，可由用户、DreamCycle 或写入管线维护 |
| `associations` frontmatter | MemoryEngine core | 是 | 带 reason/strength/evidence 的联想边，是 wiki metadata，不是知识图谱真相 |
| Association Index | MemoryEngine derived index | 是 | 从 wiki links/frontmatter 编译，可重建，不是真相源 |
| L1 association hubs | MemoryCompiler | 是 | 高频联想节点可进入 L1，但只保留短指针 |
| Deterministic wiki expansion | MemorySearchPipeline | 是 | 从种子页面沿显式链接扩展 1-2 跳，预算内裁剪 |
| LLM spreading activation | Advanced Recall extension | 否 | 当 BM25/wiki links 不够时启用，成本高且需要更强审计 |

#### 3.15.1 问题与反直觉

传统记忆检索找“最相似”的片段；个人联想记忆更像从一个概念扩散到一串关联概念。

> 你想到“学习 Rust” → 触发“学 Python async 时的挫败感” → 触发“你用类比法学语言” → 触发“类比在编程中的局限” → 触发“上次项目里 Rust 和 Go 的对比思考”

这不是严格知识图谱遍历。知识图谱需要形式化实体和关系类型；Mnemo 的联想记忆需要自然语言、语义共鸣、证据溯源和 LLM 引导的涟漪扩散。

核心约束：
- 显式 wiki links 和 `associations` 是可审计 metadata。
- LLM 只能提出 association candidates，不能在 recall 过程中直接改 wiki。
- 所有关联写入必须经过 MemoryWritePipeline，携带 evidence、confidence、reason 和 source run。
- 联想召回输出是候选上下文，不是事实本身。

#### 3.15.2 LLM Wiki 页面格式

每个 wiki 页面可以包含 `[[wiki链接]]`，也可以在 frontmatter 中维护 `associations`：

```markdown
<!-- wiki/goals/learn-rust.md -->
---
dimension: goals
status: active
confidence: 0.92
links:
  - cognition/programming-languages#rust
  - context/current-projects#mnemo
associations:
  - path: "cognition/learning-style"
    strength: 0.8
    reason: "学习方式直接影响 Rust 学习效果"
    evidence: "run_2026_04_24_001"
  - path: "patterns/code-by-analogy"
    strength: 0.7
    reason: "用户倾向于类比学习，这在 Rust 里可能是陷阱"
    evidence: "wiki/history/2024-year-review"
---

# 学好 Rust

目标：2026 Q4 达到生产级别。当前困境主要是 lifetime，
和我学 [[python-async]] 时的困惑相似：都需要改变思维模型，
而不是增加新语法。

我用 [[mnemo-project]] 作为主要实战场景。
```

`links` 偏结构化指针，`associations` 偏叙事联想。两者都只是召回线索；页面正文和 evidence 仍然是事实判断依据。

#### 3.15.3 召回管线位置

联想召回应进入 MemorySearchPipeline，而不是单独作为 Agent extension 调用。

```text
MemorySearchPipeline
  1. QueryPlanner          # 生成 L1/L2/L4/artifact/session 查询
  2. Direct Retrieval      # BM25 / FTS5 / L1 pointer / aliases
  3. Wiki Expansion        # [[links]] + associations 1-2 跳
  4. Optional LLM Associate# Advanced Recall extension, 0-3 surprising pages
  5. Policy Filter         # exposure / stale / tombstone / task relevance
  6. Rank + Budget         # relevance × association_strength × freshness × token value
  7. Candidate handoff     # 交给运行中的模型决定是否展开/注入
```

默认只启用 Step 1-3。Step 4 只有在以下条件满足时启用：
- 当前任务明显需要创意联想、反思、长期模式或跨维度解释。
- 直接召回置信不足，但 L1/links 暗示可能有相关页面。
- token/cost budget 允许，且本轮不是低延迟路径。
- 运行中的模型或 MemoryQueryPlanner 明确选择 `associate=true`。

#### 3.15.4 AssociativeMemoryEngine 接口

```ts
interface AssociativeMemoryEngine {
  recall(input: {
    seed: string;
    missionContext?: string;
    explicitPages: RecalledPage[];
    pageIndex: PageIndexSummary;
    depth: 0 | 1 | 2;
    maxPages: number;
    budgetTokens: number;
    mode: "explicit_links" | "llm_spreading" | "hybrid";
  }): Promise<AssociativeCluster>;

  proposeLinks(input: {
    runId: string;
    changedPages: string[];
    observations: Observation[];
  }): Promise<AssociationCandidate[]>;
}
```

执行规则：
- `depth` 默认 1，硬上限 2；LLM 隐式联想只在第一跳发生。
- `maxPages` 默认 3，硬上限 5。
- 每个候选必须有 `why_relevant`、`source_path`、`evidence_ref` 或 `llm_association_reason`。
- `proposeLinks` 只产生候选，写入由 DreamCycle 的 `link_and_prune` 阶段处理。
- tombstone/stale 页面不能被 association 重新激活，除非用户明确要求回看历史。

#### 3.15.5 输出格式

```ts
interface AssociativeCluster {
  seed: string;
  directMatches: RecalledPage[];
  linkedMatches: RecalledPage[];
  llmAssociativeMatches: RecalledPage[];
  narrativeTrace: string;
  totalTokens: number;
  depthReached: number;
  dropped: Array<{path: string; reason: "budget" | "policy" | "stale" | "low_relevance"}>;
}
```

注入 prompt 时使用动态块，不进入 stable prefix：

```text
<associative-context>
[seed] 学习 Rust
[path] goals/learn-rust
[why] 直接目标页面

[path] cognition/learning-style
[why] 显式 association: 学习方式直接影响 Rust 学习效果

[path] patterns/code-by-analogy
[why] LLM association candidate: 类比学习可能是 lifetime 理解的陷阱

[association_path]
学 Rust → Mnemo 实战项目 → 代码优先学习风格 → 类比学习的局限
</associative-context>
```

#### 3.15.6 L1 索引中的联想热点

MemoryCompiler 会统计哪些页面频繁成为关联目标，将少数高价值“联想热点”提升到 L1 指针层：

```text
── Memory Index ──────────────────────────
POINTERS:
  coding/rust → goals#learn-rust *[assoc: learning-style, mnemo-project]*

ASSOCIATION HUBS:
  · learning-style: 7 pages link here; often relevant to learning tasks
  · mnemo-project: 5 pages link here; current core practice anchor
  · procrastination-pattern: 4 pages link here; use only when context suggests difficulty avoidance
```

L1 只保留热点名称和触发条件，不复述长事实。具体内容仍按需读取 L2。

#### 3.15.7 DreamCycle 中的维护

DreamCycle 的 `link_and_prune` 阶段负责维护 LLM Wiki：

```text
DreamCycle.link_and_prune
  → detect orphan pages
  → propose association candidates from recent runs
  → remove links to stale/tombstoned pages from active association index
  → update association strength by successful recall/usefulness
  → compile L1 association hubs
```

联想链接的收益也要评测：如果某个 association 被召回后经常被模型拒绝、导致偏题或增加 token 成本，DreamCycle 应降低 strength 或移出 L1 热点。

---
---

## 17. 记忆写入管线与事务安全

### 17.1 写入路径全景

所有对长期记忆（L2/L3）的写入，都必须经过**统一管线**，确保原子性、可回滚、可审计：

```
写入请求来源:
  Agent 推断 / 用户确认 / learning packet 候选 / 联邦同步

                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Step 1: Security Scan (prompt injection 过滤)        │
│  Step 2: Quality Filter (MemoryQualityFilter)         │
│  Step 3: Conflict Detection (ConflictResolver)        │
│  Step 4: Confidence Assignment                        │
│          (user_confirmed=0.9, agent_inferred=0.5,     │
│           cross_validated=0.95, stale_flag=0.3)       │
│  Step 5: Write to L2 Markdown + Frontmatter           │
│  Step 6: Atomic update SQLite wiki_pages record       │
│  Step 7: Append to memory_write_log (溯源记录)         │
│  Step 8: Invalidate affected L1 compiled segments     │
│  Step 9: Notify MessageBus: memory.page_updated       │
└───────────────────────────────────────────────────────┘
                    │
                    ▼
           (下一次 daily_compile 时生效于 L1)
```

### 17.2 事务安全模型

```python
class MemoryWriteTransaction:
    """
    保证：要么写入完整（文件 + SQLite + 日志），要么完全回滚。
    防止 Agent 崩溃或中断导致文件和 DB 之间状态不一致。
    """
    
    def execute(self, write_op: MemoryWriteOp) -> WriteResult:
        """
        原子性保证步骤:
        
        1. 计算 old_content_hash (用于回滚)
        2. 将 Markdown 写入临时文件 (.md.tmp)
        3. SQLite BEGIN IMMEDIATE 事务
        4. 在事务内:
           a. atomic_rename(.md.tmp → .md)
           b. UPDATE wiki_pages SET ... WHERE id=?
           c. INSERT INTO memory_write_log ...
        5. COMMIT
        
        Step 2 失败 → 清理 .tmp 文件
        Step 3-5 失败 → ROLLBACK (恢复 .md 文件)
        
        atomic_rename 是 POSIX 原子操作，确保文件写入不产生
        半写状态。Windows 上使用 ReplaceFile() 替代。
        """
    
    def batch_write(self, ops: list[MemoryWriteOp]) -> list[WriteResult]:
        """
        会话结束时批量写入，减少 SQLite 事务次数。
        单一 BEGIN IMMEDIATE → N 次文件写入 + N 次 INSERT → COMMIT
        
        优于 N 次单独事务: 减少 WAL checkpoint 频率，降低锁竞争。
        """
```

### 17.3 批量写入队列

```python
class MemoryWriteBatcher:
    """
    在会话生命周期内缓冲写入请求，会话结束时批量提交。
    
    设计原因:
    - 单次对话可能产生 10-30 条记忆更新请求
    - 每条单独事务 → WAL 锁竞争 + 文件 IO 碎片化
    - 批量 → 单次事务 + 顺序 IO + 减少 L1 重编译次数
    
    冲突合并:
    - 同一会话内对同一页面的多次写入 → 合并为最终状态
    - 避免 "先写甲再写乙相互矛盾" 的中间态
    """
    
    _pending: list[MemoryWriteOp] = []
    
    def queue(self, op: MemoryWriteOp) -> None:
        """将写入操作加入队列"""
        # 去重: 同一页面已有待写入 → 合并而非追加
        existing = next((o for o in self._pending if o.page_path == op.page_path), None)
        if existing:
            self._pending.remove(existing)
            op = self._merge_ops(existing, op)
        self._pending.append(op)
    
    def flush(self, reason: str = "mission_idle") -> BatchWriteResult:
        """批量提交所有待写入操作"""
        if not self._pending:
            return BatchWriteResult(written=0)
        results = MemoryWriteTransaction().batch_write(self._pending)
        self._pending.clear()
        return BatchWriteResult(written=len(results), reason=reason)
    
    def flush_on_compress(self) -> None:
        """上下文压缩前触发 flush，防止压缩丢失待写入观察"""
        self.flush(reason="pre_compress")
```

---
---

## 18. L4 跨会话检索——FTS5 引擎

### 18.1 设计动机

> **场景**: 用户问 "我上次说 Rust lifetimes 时什么情况？" 或 "有没有对话里提到过主动放弃某个项目？"

L2 wiki 只存储**已蒸馏**的事实，无法回答关于**具体对话**的问题。L4 保存全量原始消息，通过 FTS5 全文检索可精确定位。

### 18.2 FTS5 Schema

```sql
-- sessions 表 (来自 §9.1 的扩展)
ALTER TABLE sessions ADD COLUMN source TEXT DEFAULT 'cli';       -- cli|telegram|discord|mcp
ALTER TABLE sessions ADD COLUMN agent_type TEXT DEFAULT 'general';
ALTER TABLE sessions ADD COLUMN title TEXT;                      -- 摘要标题，可搜索

-- messages 表 (原 session_log 扩展)
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    role            TEXT NOT NULL,          -- user|assistant|tool_result
    content         TEXT,
    tool_name       TEXT,                   -- 若是工具调用，工具名称
    token_count     INTEGER,
    timestamp       REAL NOT NULL
);

CREATE INDEX idx_messages_session ON messages(session_id, timestamp);
CREATE INDEX idx_messages_timestamp ON messages(timestamp DESC);

-- FTS5 全文索引 (来自 Hermes SessionDB 设计)
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id,
    tokenize="unicode61 remove_diacritics 1"  -- 支持中文分词 (需扩展)
);

-- 自动触发器：消息写入/删除时同步 FTS 索引
CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;
CREATE TRIGGER messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
```

### 18.3 L4 搜索 API

```python
class SessionSearchEngine:
    """
    跨会话全文搜索，作为 L4 检索入口。
    
    Tool 暴露: memory_search(query=..., search_scope="sessions")
    """
    
    def search(
        self,
        query: str,
        limit: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[SessionSearchResult]:
        """
        FTS5 搜索步骤:
        1. messages_fts MATCH '{query}' — 全文匹配
        2. JOIN sessions — 获取会话元数据
        3. 过滤 filters (date_range / source / agent_type)
        4. 按相关性分数 + 时间新近度 加权排序
        5. 对每条结果，提取 ±3 条消息作为上下文窗口
        6. 返回 SessionSearchResult({session_id, timestamp, snippet, context_window})
        
        中文支持: 先 jieba 分词，再拼接为 FTS5 phrase query
                  "学习 Rust" → "FTS5: 学习 AND Rust"
        """
        sql = """
            SELECT m.id, m.session_id, m.role, m.content, m.timestamp,
                   s.title, s.agent_type, s.source,
                   snippet(messages_fts, 0, '<b>', '</b>', '...', 32) as snippet,
                   rank
            FROM messages_fts
            JOIN messages m ON messages_fts.rowid = m.id
            JOIN sessions s ON m.session_id = s.id
            WHERE messages_fts MATCH ?
              AND m.role = 'user'           -- 通常搜用户输入更精确
            ORDER BY rank, m.timestamp DESC
            LIMIT ?
        """
    
    def get_context_window(
        self, 
        message_id: int, 
        window: int = 3,
    ) -> list[Message]:
        """获取某条消息前后 N 轮的对话上下文"""
    
    def search_by_date(
        self,
        query: str,
        since: datetime,
        until: datetime | None = None,
    ) -> list[SessionSearchResult]:
        """在特定时间范围内搜索"""

@dataclass
class SessionSearchResult:
    session_id: str
    session_title: str
    message_id: int
    timestamp: datetime
    snippet: str              # FTS5 高亮摘要
    context_window: list[Message]  # ±N 轮上下文
    relevance_score: float
    
    def to_context_block(self) -> str:
        """格式化为可注入 prompt 的引用块"""
        return (
            f"[Session: {self.session_title} ({self.timestamp:%Y-%m-%d})]\n"
            + "\n".join(
                f"  [{m.role}]: {m.content[:200]}{'...' if len(m.content) > 200 else ''}"
                for m in self.context_window
            )
        )
```

### 18.4 L4 在 Memory Router 中的位置

```
memory_search(query, search_scope="sessions")
              │
              ▼
 SessionSearchEngine.search(query, filters)
              │
              ├─ FTS5 全文匹配 → 高精度关键词命中
              │
              └─ 结果: [SessionSearchResult...]
                        │
                        ├─ 单条摘要 → 注入 <session-recall> 块
                        └─ 多条 → 汇总摘要: "你在 3 次对话中提到过..."

注意: L4 检索的结果不自动注入 context (避免 token 爆炸)
     仅在 Agent 显式调用 memory_search(scope="sessions") 时使用
     或 用户明确提问关于"之前对话"时触发
```

---
---

## 19. 并发访问与数据库安全模型

### 19.1 典型并发场景

Mnemo 可能同时运行多个访问者：

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  CLI Session    │  │  MCP Server     │  │  ProactiveDaemon│
│ (用户对话)      │  │ (外部 Agent 调用)│  │ (后台 cron 任务)│
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                     │
         └────────────────────┴─────────────────────┘
                              │
                     ~/.mnemo/state.db
                     ~/.mnemo/wiki/**.md
```

### 19.2 SQLite WAL 模式 + 应用层重试

```python
class MnemoDatabase:
    """
    并发安全的 SQLite 访问层。
    来源: Hermes SessionDB 的 WAL + jitter retry 设计。
    
    SQLite WAL 模式特性:
    - 允许多个并发 Reader（无锁竞争）
    - 仅一个 Writer，但 Reader 不阻塞 Writer
    - 适合 Mnemo 的读多写少 pattern
    """
    
    _WRITE_MAX_RETRIES = 15
    _WRITE_RETRY_MIN_S = 0.020   # 20ms
    _WRITE_RETRY_MAX_S = 0.150   # 150ms
    _CHECKPOINT_EVERY_N = 50     # N 次写入后触发 passive WAL checkpoint
    
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=1.0,         # 短超时 → 配合应用层 jitter retry
            isolation_level=None, # 手动管理事务
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL") # WAL 模式下大幅提升写速度
    
    def _execute_write(self, fn: Callable) -> Any:
        """
        带 jitter 重试的写事务。
        
        使用 BEGIN IMMEDIATE 而非 BEGIN:
        → 在事务开始时立即获取写锁（而非 COMMIT 时）
        → 锁竞争暴露更早，避免大量工作后才失败
        
        Jitter 重试打破 convoy effect:
        → 若所有 Writer 都使用相同睡眠时间，会形成竞争护卫队
        → 随机 20-150ms 打散竞争窗口
        """
        for attempt in range(self._WRITE_MAX_RETRIES):
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    result = fn(self._conn)
                    self._conn.commit()
                except:
                    self._conn.rollback()
                    raise
                return result
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    jitter = random.uniform(self._WRITE_RETRY_MIN_S, self._WRITE_RETRY_MAX_S)
                    time.sleep(jitter)
                    continue
                raise
        raise RuntimeError(f"Write failed after {self._WRITE_MAX_RETRIES} retries")
```

### 19.3 Wiki 文件并发写保护

SQLite 提供原子性，但 wiki Markdown 文件写入需要**文件系统级别的保护**：

```python
class WikiFileManager:
    """
    Wiki Markdown 文件的并发安全写入。
    """
    
    _file_locks: dict[str, threading.Lock] = {}  # 按路径维护读写锁
    
    def write_page(self, page_path: str, content: str) -> None:
        """
        原子文件写入:
        1. 获取该路径的 threading.Lock（跨进程场景使用 filelock 库）
        2. 写入到 {path}.tmp 临时文件
        3. os.replace({path}.tmp, {path})  ← POSIX 原子重命名
        4. 释放锁
        
        os.replace 保证: 要么旧文件完整保留，要么新内容完整写入
        不会出现半写状态（断电/崩溃安全）
        """
    
    def read_page(self, page_path: str) -> str | None:
        """读取不需要锁（文件读操作原子性由 OS 保证）"""
```

### 19.4 会话隔离语义

```
读操作:
  - 任何会话可随时读取 L0/L1/L2 (无需锁)
  - 读到的是"最近 daily_compile 时的版本" (快照一致性)

写操作:
  - 写入通过 MemoryWriteBatcher 在会话结束时批量提交
  - 同一时刻只有一个写事务 (IMMEDIATE 锁)
  - ProactiveDaemon 的 daily_compile 也通过相同路径
    → 与普通写没有特殊冲突处理，排队等待即可

联邦同步 (Mnemo-to-Mnemo):
  - 视为外部写入，经过完整 pipeline (安全扫描 + 冲突检测)
  - 联邦写入优先级低于本地写入 (priority = LOW in MemoryWriteBatcher)
```

---
---

## 20. 记忆层完整数据流图

```
╔══════════════════════════════════════════════════════════════════════╗
║              Mnemo Memory Layer — Complete Data Flow                 ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ╔══════════════╗   一轮对话 / Mission turn 结束                      ║
║  ║  User Input  ║ ──────────────────────────────────────────────┐   ║
║  ╚══════════════╝                                              │   ║
║                                                                ▼   ║
║  ╔═══════════════════════════════════════════════════════════╗ │   ║
║  ║              W0: Working Memory (Mission 级暂存)            ║ │   ║
║  ║  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐ ║ │   ║
║  ║  │ task_state  │  │ pending_obs  │  │  draft_facts     │ ║ │   ║
║  ║  │ (Mission态) │  │ (行为观察队列)│  │ (未验证新事实)   │ ║ │   ║
║  ║  └──────x──────┘  └──────┬───────┘  └────────┬─────────┘ ║ │   ║
║  ║         │ turn 结束       │                   │            ║ │   ║
║  ║         │ checkpoint      │                   │            ║ │   ║
║  ╚═════════╪════════════════╪═══════════════════╪════════════╝ │   ║
║            │                │                   │              │   ║
║            │                ▼                   ▼              │   ║
║            │   ┌─────────────────────────────────────────┐     │   ║
║            │   │   Learning packet (Mission/Dream 触发)    │     │   ║
║            │   │  1. pending_obs / draft_facts 作证据      │     │   ║
║            │   │  2. 模型选择 0..N 个候选写入工具          │     │   ║
║            │   │  3. 冲突检测 + 质量过滤                   │     │   ║
║            │   │  4. memory 候选 → MemoryWriteBatcher     │     │   ║
║            │   └────────────────────┬────────────────────┘     │   ║
║            │                        │                           │   ║
║            │                        ▼                           │   ║
║            │   ┌─────────────────────────────────────────┐     │   ║
║            │   │       MemoryWritePipeline                │     │   ║
║            │   │  Scan → Quality → Conflict → Write       │     │   ║
║            │   │  → L2 Markdown + SQLite + AuditLog       │     │   ║
║            │   └────────────────────┬────────────────────┘     │   ║
║            │                        │                           │   ║
║            │            ┌───────────┴──────────┐               │   ║
║            │            ▼                      ▼               │   ║
║            │   ┌────────────────┐   ┌────────────────────┐     │   ║
║            │   │  L2 wiki/ 页面 │   │  L4 sessions + FTS │     │   ║
║            │   │  (持久化事实)   │   │  (原始消息归档)      │     │   ║
║            │   └────────┬───────┘   └──────────┬─────────┘     │   ║
║            │            │                      │                │   ║
║            │   每日00:00 ▼ daily_compile        │                │   ║
║            │   ┌────────────────┐              │                │   ║
║            │   │  Memory        │              │                │   ║
║            │   │  Compiler      │              │                │   ║
║            │   │  L2→L1→L0     │              │                │   ║
║            │   └────────┬───────┘              │                │   ║
║            │            │                      │                │   ║
║            │            ▼                      │                │   ║
║            │   ┌─────────────────────────────────────────┐     │   ║
║            │   │         Prompt Assembler                 │     │   ║
║            │   │  L0(cached) + L1(cached) + L2(dynamic)  │◄────┘   ║
║            │   │  + Skills Index + Watch Summary          │         ║
║            │   │  + Assoc Blocks + Session Recall         │         ║
║            │   └─────────────────────────────────────────┘         ║
╚══════════════════════════════════════════════════════════════════════╝
```

---
