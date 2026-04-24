# Agentic Loop, Prompt And Soul

> 模型裁决、反思压缩、prompt 结构、缓存和 Soul.md。

## 5. Agentic Loop 设计

### 5.1 架构图

```
用户输入 / Cron 触发 / Watch 事件
         │
         ▼
┌────────────────────────────────────────┐
│            MnemoAgentLoop              │
│                                        │
│  1. context_candidates()               │
│     ├─ L0 Profile Card                 │
│     ├─ L1 Dimension Index              │
│     ├─ candidate L2 pages/search hits  │
│     ├─ candidate skills/SOPs/tools     │
│     └─ Active watches/sense snapshot   │
│                                        │
│  2. model_decide()                     │
│     ├─ choose context slice            │
│     ├─ choose plan/tool strategy       │
│     ├─ choose memory/skill actions     │
│     └─ output DecisionEnvelope         │
│                                        │
│  3. llm_call(system_prompt, messages)  │
│     │                                  │
│     ▼                                  │
│  4. tool_dispatch()                    │
│     ├─ memory_tools (read/write/search/associate) │
│     ├─ skill_tools (list/view/activate/manage/eval)│
│     ├─ tool_tools  (list/view/write/macro)│
│     ├─ watch_tools (add/update)        │
│     ├─ sense_tools (android_get/set)   │
│     └─ external_tools (user-defined)   │
│                                        │
│  5. post_turn_hooks()                  │
│     ├─ skill_composer.observe_turn()   │ ← 自演进
│     ├─ memory_sync()                   │ ← 记忆更新
│     └─ watch_engine.check_triggers()  │ ← 关注点跟踪
│                                        │
│  6. compress_if_needed()               │
│     └─ context_compressor.run()        │
└────────────────────────────────────────┘
         │
         ▼
 delivery → CLI / MCP / REST / Push(cron)
```

### 5.2 Reflect Agent（自我反思循环）

```python
class ReflectAgent:
    """
    后台运行的自我反思 Agent.
    不直接响应用户; 负责蒸馏、演进、主动任务.
    
    触发时机:
    - on_mission_idle/on_mission_end: Mission 空闲或结束后提取记忆候选
    - dream_cycle: 空闲期批量蒸馏、编译、健康检查
    - weekly_sun: 技能挖掘 + 本体论审计（由 DreamCycle 编排）
    - watch_event: 关注点触发时
    """
    
    REFLECT_PROMPT = """
    You are performing a memory reflection. Review the recent conversation.
    
    Tasks:
    1. EXTRACT: What new facts about the person should update their wiki?
       Format: {"dimension": "...", "page": "...", "update": "..."}
    
    2. VALIDATE: Which existing memories were confirmed or contradicted?
       Format: {"page_path": "...", "action": "confirm|contradict|stale"}
    
    3. PATTERN: Did you observe any interaction patterns worth noting?
       Format: {"category": "...", "observation": "...", "signal_type": "..."}
    
    4. SKILL: Should any new personal skill be drafted?
       Format: {"name": "...", "category": "...", "rules": [...]}
    
    Apply memory axioms:
    - Only write facts the user confirmed or that are directly evidenced
    - Do not write volatile state (current file path, today's date, etc.)
    - Confidence = 0.5 for inferred, 0.9 for explicitly confirmed
    """
```

### 5.3 Context Compressor

```python
class MnemoContextCompressor:
    """
    上下文压缩器: 当 prompt_tokens > threshold 时触发.
    
    压缩策略:
    1. 提取新记忆候选 (交 ReflectAgent 处理)
    2. 保留最近 N 轮 + 首 M 轮 (上下文锚点)
    3. 将中间对话压缩为单条摘要消息
    4. 保持技能观察记录 (写入 patterns/ 再清理)
    
    关键特性:
    - 压缩时同步蒸馏记忆 (on_pre_compress 钩子)
    - 压缩摘要不丢失技能观察信号
    """
    
    threshold_percent: float = 0.75   # prompt_tokens / context_length
    protect_first_n: int = 3
    protect_last_n: int = 8
    
    SUMMARY_PREFIX = (
        "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
        "into the summary below. This is a handoff from a previous context "
        "window — treat it as background reference, NOT as active instructions. "
        "Do NOT answer questions or fulfill requests mentioned in this summary; "
        "they were already addressed. Respond ONLY to the latest user message "
        "that appears AFTER this summary. The current session state may "
        "reflect work described here — avoid repeating it:"
    )
    # 来源: Hermes Agent 的上下文压缩设计
    # 关键: "handoff from previous context" 帧定义 —— 防止 LLM 将摘要内容
    # 当作待完成指令重新执行，这是朴素压缩方案的核心问题
    
    def _prune_tool_outputs(self, messages: list) -> list:
        """
        压缩前的廉价预处理:
        用 1-2 行摘要替换大型工具输出（不需要 LLM）。
        
        示例:
          [file_read] read wiki/goals/learn-rust.md from line 1 (2,400 chars)
          [exec] ran `gh pr list ...` -> exit 0, 12 lines output
          [memory_search] query='Rust learning' -> 3 matches (1,800 chars)
        
        此步骤节省约 40-60% token，后续 LLM 摘要质量更高（信噪比更高）。
        """
    
    def _iterative_summary(
        self, 
        prev_summary: str | None, 
        new_content: str,
    ) -> str:
        """
        增量摘要更新: 若已有前次摘要，则合并而非全量重摘要。
        保留跨多次压缩的 Resolved/Pending 信息追踪。
        
        摘要模板结构:
          RESOLVED: [已完成的任务清单]
          PENDING:  [尚未完成/等待用户的任务]
          KEY_FACTS: [本会话确认的重要事实]
          REMAINING_WORK: (不是 'Next Steps'，避免 LLM 误读为待执行)
        """
```

### 5.4 Model Decision Layer（模型裁决层）

Mnemo 的核心循环不应把 “if coding then load cognition” 这类规则写死。规则只负责生成候选、约束边界、保证安全；真正的上下文选择、工具策略、记忆写入建议、技能复用判断，应交给模型在每个 run 中做裁决。

**原则**:
- 候选生成可以是确定性的：BM25、L1 pointer、embedding、recent watches、tool availability。
- 裁决必须由模型完成：哪些候选真的有用、是否需要继续探测、是否应该写记忆、是否该调用 SOP。
- 规则只做不可谈判的护栏：权限、隐私、token budget、危险工具、schema 校验、最大循环次数。
- 所有模型裁决必须写入 RunLedger，支持回放和评测。

语言无关接口：

```ts
type DecisionTask =
  | "context_route"
  | "tool_strategy"
  | "memory_write"
  | "skill_reuse"
  | "watch_action"
  | "recovery";

interface CandidateSet {
  request: AgentRequest;
  profile: ProfileCard;
  memory: CandidateMemoryPage[];
  skills: CandidateSkill[];
  tools: ToolSpec[];
  watches: WatchSnapshot[];
  constraints: PolicyConstraint[];
  budget: ContextBudget;
}

interface DecisionEnvelope {
  task: DecisionTask;
  selected: string[];
  rejected: { id: string; reason: string }[];
  plan: string;
  confidence: number;
  requiredApprovals: ApprovalRequest[];
  risk: "low" | "medium" | "high";
  auditNote: string;
}

interface ModelDecisionEngine {
  decide(task: DecisionTask, candidates: CandidateSet): DecisionEnvelope;
}
```

`DecisionEnvelope` 是 Mnemo 的关键中间产物。它不是 prompt 里的隐式思考，而是可审计的运行时决策记录：为什么加载这 2 个 L2 页面，为什么没加载 relationships，为什么选择 SOP 而不是重新探索。

**模型裁决示例**:

```
Task: context_route
Candidates:
  L1 pointer: coding/rust → cognition#languages, goals#learn-rust
  Search hit: context/current-projects#mnemo
  Sensitive hit: relationships/team
Constraints:
  external runtime = codex, max_external = L1, relationships = no external

Decision:
  selected:
    - cognition/programming-languages#rust
    - goals/learn-rust
    - context/current-projects#mnemo(summary_only)
  rejected:
    - relationships/team: unrelated + external disclosure risk
  plan:
    Use Rust learning state and current Mnemo context; do not expose team details.
```

### 5.5 错误降级与探针优先策略

> **来源**: GenericAgent 的"探针优先"理念 + Hermes Agent 的实战经验。

错误恢复也走模型裁决，而不是硬编码 `attempt=1/2/3` 的动作列表。运行时提供失败历史、环境探针候选和约束，模型决定下一步；系统只限制最大重试、危险操作和无信息重复。

```ts
interface RecoveryContext {
  toolName: string;
  error: string;
  attempts: ToolAttempt[];
  availableProbes: ToolSpec[];
  constraints: PolicyConstraint[];
}

interface RecoveryDecision {
  action: "read_error" | "probe_state" | "switch_approach" | "ask_user" | "stop";
  probe?: ToolCall;
  reason: string;
  newInformationExpected: string;
}
```

```python
class AgentErrorEscalation:
    """
    工具调用失败时的分级恢复策略。
    
    原则: 每次重试必须携带新的信息——永不在无新情报的情况下重复相同操作。
    """
    
    ESCALATION_LEVELS = {
        1: "read_error",      # 第一次失败: 读取错误信息，理解根因
        2: "probe_state",     # 第二次失败: 探测环境状态（ls/ps/env/file_read）
        3: "switch_approach", # 第三次: 切换方案 或 升级到 ask_user
    }
    
    def handle_tool_failure(
        self, 
        tool_name: str, 
        error: str, 
        attempt: int,
        context: dict,
    ) -> RecoveryAction:
        """
        attempt=1:
          → 分析 error message，尝试理解失败原因
          → 如果是权限问题: 尝试 --sudo / 降权路径
          → 如果是路径问题: 先 file_read 确认文件存在/行号
          → 如果是网络问题: 等待后重试一次
        
        attempt=2:
          → 探测当前环境状态
          → memory: 检查 file_read 确认最新内容
          → exec: 检查 cwd/env/process list
          → web: 尝试备用端点或降级搜索
        
        attempt=3:
          → 切换根本方案（如 exec → python script）
          → 或 ask_user: 明确描述已尝试的路径和当前信息
          → 永不继续无希望的重试
        """
    
    MAX_RETRIES_PER_TOOL = 3
    MAX_TOTAL_ITERATIONS = 90     # 硬上限: 防止无限循环
    DEPTH_LIMIT_SUBAGENT = 3      # 子 Agent 最大嵌套深度
    
    DANGEROUS_COMMAND_PATTERNS = [  # 需要用户确认才能执行
        r'rm\s+-rf\s+[^/]',
        r'DROP\s+TABLE',
        r'git\s+push\s+--force',
        r'git\s+reset\s+--hard',
        r'truncate\s+',
        r'format\s+[A-Z]:',
        r'mkfs\.',
    ]
    
    def check_dangerous(self, command: str) -> DangerLevel:
        """
        危险命令检测 (来自 Hermes tools/approval.py 设计):
        SAFE     → 直接执行
        WARN     → 展示预览，询问用户
        BLOCK    → 须显式 --confirm 标志才执行
        """
```

### 5.6 Token 感知与模型自适应

```python
class ModelContextManager:
    """
    每次 LLM 调用前，动态感知上下文窗口剩余，调整加载策略。
    
    不同模型的上下文长度不同（来自 Hermes agent/model_metadata.py 理念）。
    Mnemo 应按实际可用 token 空间，而非固定 token 预算来组装 context。
    """
    
    MODEL_CONTEXTS = {
        "claude-opus-4.6":      200_000,
        "claude-sonnet-4.6":    200_000,
        "gpt-5.4":              128_000,
        "gemini-2.5-flash":   1_048_576,
    }
    
    def available_budget(
        self, 
        model: str, 
        current_messages_tokens: int,
        reserve_for_output: int = 8000,
    ) -> ContextBudget:
        """
        返回当前可用于 context 注入的 token 预算分配:
        
        total = MODEL_CONTEXTS[model]
        used  = system_prompt + current_messages
        avail = total - used - reserve_for_output
        
        分配策略:
          layer1_static: min(avail * 0.10, 600)   # L0 + Soul
          layer2_compiled: min(avail * 0.20, 1500) # L1 + Skills + Watches
          layer3_dynamic: min(avail * 0.20, 3000)  # L2 pages + assoc blocks
          working_buffer: avail * 0.50             # 对话历史保留
        """
    
    def should_compress(self, model: str, messages: list) -> bool:
        """当 used_tokens > MODEL_CONTEXTS[model] * 0.75 时触发压缩"""
```

### 5.7 Model Broker（模型路由）

模型选择本身也应是可配置 broker，而不是“Python 类里写死模型名”。不同任务使用不同模型：编译/评测可用便宜或本地模型，用户交互和高风险裁决用高质量模型，敏感内容优先本地模型或脱敏摘要。

```yaml
model_broker:
  default: high_quality
  tasks:
    decide.context_route: fast_reasoner
    decide.memory_write: high_quality
    decide.approval: high_quality
    compile.l1: cost_effective
    eval.judge: high_quality
    search.rerank: fast_reasoner
    sensitive.local_only: local_private

  providers:
    high_quality: {provider: anthropic|openai|gemini, model: "..."}
    fast_reasoner: {provider: openai|gemini|local, model: "..."}
    cost_effective: {provider: openrouter|local, model: "..."}
    local_private: {provider: ollama|llama.cpp, model: "..."}
```

Model Broker 的输出也进入 RunLedger：`model.selected`、`reason`、`fallback_used`、`sensitive_redaction`、`cost`。

---
---

## 6. Prompt 组织架构

本章保留 Prompt 的核心模型和缓存策略。完整 Prompt Catalog、OpenClaw/Hermes prompt assembly 借鉴、PromptBlock 数据结构、组装顺序、token/cache 预算和各类模板见 [11-prompt-system.md](11-prompt-system.md)。

### 6.1 三层 Prompt 模型

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1: STATIC IDENTITY (~600 tokens, 编译一次永久有效) │  ← CACHE ANCHOR
│                                                          │
│  [Soul.md] Agent 灵魂契约 (扫描后注入)                   │
│  [Axioms] 记忆公理 (6 条)                                 │
│  [L0] Profile Card (3-5 句)                              │
└──────────────────────────────────────────────────────────┘
                          │
┌──────────────────────────────────────────────────────────┐
│  Layer 2: COMPILED CONTEXT (~1200 tokens, 每日编译)       │  ← CACHE ANCHOR
│                                                          │
│  [L1 Index] Dimension Pointers (≤30行, 场景→维度映射)    │
│  [L1 Skills] Skills Index (≤20行, priority=high 的技能)  │
│  [Temporal] 活跃 Watch 摘要 (≤10行)                       │
└──────────────────────────────────────────────────────────┘
                          │
┌──────────────────────────────────────────────────────────┐
│  Layer 3: DYNAMIC CONTEXT (按请求路由, 每轮可变)           │  ← 不缓存
│                                                          │
│  [L2 Pages] 语义路由的维度页面 (0-3 个, ~500-2000 tokens) │
│  [<memory-context>] Prefetch 召回块 (≤800 tokens)        │
│  [Watch Updates] 本轮相关关注点状态                        │
└──────────────────────────────────────────────────────────┘
```

### 6.2 Prompt Assembler

```python
class PromptAssembler:
    """
    密度控制型 Prompt 组装器.
    
    Token 预算管理:
    - Layer 1: 固定 ~600 tokens (永不压缩)
    - Layer 2: 目标 ~1200 tokens, 硬上限 1500
    - Layer 3: 可用预算 = max_context * 0.15 - L1 - L2
    
    组装策略:
    1. CandidateBuilder 生成候选: L1 pointer / BM25 / embeddings / recent runs / watches
    2. PolicyEngine 过滤不可暴露页面、危险工具和超预算候选
    3. ModelDecisionEngine 裁决: 选择真正要注入的 L2 pages / skills / watches
    4. PromptAssembler 只执行最终拼装和 token 裁剪，不做语义裁决
    5. 所有 selected/rejected 候选写入 DecisionEnvelope 和 RunLedger
    """
    
    def assemble(
        self,
        request_context: str,
        agent_type: str = "general",
        max_tokens: int = 4000,
        include_watches: bool = True,
    ) -> AssembledPrompt:
        """返回可直接注入 system prompt 的组装结果"""
```

### 6.3 Prompt 模板示例

```
═══════════════════════════════════════════
[MNEMO PERSONAL OS]
═══════════════════════════════════════════
You are Mnemo, this person's personal AI operating system.
You remember everything about them across all conversations.
Apply these axioms: only state confirmed facts; mark uncertainty;
flag stale info; never infer beyond evidence.

── Profile Card ──────────────────────────
Zhang Wei, Senior SWE @ TechCorp. Python/Rust 8y/2y. AI/ML focus.
Direct communicator — code over prose. Building Mnemo v2. UTC+8.
Values: privacy-first, first-principles.

── Memory Index ──────────────────────────
POINTERS:
  coding/rust → cognition#languages, goals#learn-rust
  project/mnemo → context#mnemo, goals#q3-launch
  health → patterns#sleep, goals#health

ACTIVE:
  [goals] Mnemo Q3 launch. Rust prod-ready Q4. [current]
  [cognition] Rust intermediate, Python fluent, TS familiar
  [context] Solo, ~3h/day, mornings most productive

── Skills ────────────────────────────────
  · communication-style [v3] — Direct, code-first, max 2 options
  · feedback-patterns [v2] — Prefers blunt critique over encouragement

── Watches ───────────────────────────────
  ⚡ rust-progress: last check 3d ago, on track
  ⏰ health/sleep: alert — 3 nights < 7h this week

── Loaded Context ────────────────────────
<memory-context>
[cognition/programming-languages]
Rust: started 2024-06, current focus area. Struggles with lifetimes. 
Goal: production-ready by Q4 2026. Recent win: async/await mastery.
...
</memory-context>
═══════════════════════════════════════════
```

### 6.4 Prompt 缓存策略

> **来源**: Hermes Agent 的 `agent/prompt_caching.py` 设计理念。

Layer 1 和 Layer 2 是**稳定块**——在 Anthropic Claude 等支持 Prompt Caching 的模型上，应作为缓存锚点，避免每轮重复 prefill：

```python
class PromptCachingStrategy:
    """
    利用 Anthropic prompt caching 降低每轮 API 成本。
    
    核心规则:
    - 缓存命中条件: system prompt 前缀内容必须字节级别完全一致
    - Layer 1 (Soul + L0): 全天不变 → 最高优先级缓存锚点
    - Layer 2 (L1 Index): 每日编译一次 → 次优先级缓存锚点
    - Layer 3 (Dynamic): 每轮不同 → 不缓存
    
    实现:
    对于 Anthropic API，在 system prompt 的 Layer 1 尾部和 Layer 2 尾部
    分别插入 cache_control: {"type": "ephemeral"} 标记以创建缓存断点。
    """
    
    def build_cached_system_prompt(
        self, 
        layer1: str, 
        layer2: str, 
        layer3: str,
        provider: str,
    ) -> list[SystemBlock]:
        """
        构建带缓存标记的 system prompt 块列表。
        
        Anthropic 格式:
        [
          {"type": "text", "text": layer1, 
           "cache_control": {"type": "ephemeral"}},    ← 缓存断点 1
          {"type": "text", "text": layer2,
           "cache_control": {"type": "ephemeral"}},    ← 缓存断点 2
          {"type": "text", "text": layer3},             ← 不缓存，每轮变化
        ]
        
        其他提供商:
        - OpenAI: 依赖自动 prefix caching；保持 messages/tools/schema 前缀字节级稳定，
          并记录 cached input tokens。
        - Gemini: 对长且复用的项目上下文、Daily L1、文档包使用 explicit context cache；
          短对话保持稳定前缀以利用 implicit cache。
        - local/vLLM: 使用本地 prefix cache key，绑定 tokenizer/model revision/sampling config。
        
        节省效果估算 (200K context, 每日 50 轮对话):
          Layer 1+2 ≈ 1800 tokens，每轮节省 ~50% 写入成本
          月节省 ≈ 1800 * 50 * 30 * $15/MTok ≈ $40.5 (Claude Sonnet)
        """
    
    def should_invalidate_cache(self, layer: int, reason: str) -> bool:
        """
        缓存失效条件:
        Layer 1: Soul.md 被修改 → 失效
        Layer 2: L1 重新编译 → 失效（每日一次）
                 置信度衰减导致 L1 内容变化 → 失效
        
        注意: 任何内容变化都会导致缓存 miss，因此 Layer 2
              必须严格控制编译频率，不能在每轮对话后重编译。
        """
```

**L1 编译频率约束**（与 Prompt Caching 联动）：

| 触发条件 | 是否重新编译 L1 | 是否使缓存失效 |
|---------|---------------|--------------|
| L2 页面内容变化 | ✅ 是（下次 daily_compile） | 下一天起 |
| 用户确认新事实写入 L2 | ✅ 是（延迟至 daily_compile） | 下一天起 |
| 置信度衰减 | ✅ 是（daily_compile） | 下一天起 |
| 当前会话结束 | ❌ 否（当日 L1 仍有效） | 不失效 |
| `mnemo compile` 手动触发 | ✅ 立即 | 立即失效 |

---
---

## 12. Soul.md — Agent 灵魂与人格

### 12.1 设计理念

多数 AI 系统的"身份"定义的是 **Agent 本身**——它叫什么名字、有什么能力、遵循什么执行原则。

Mnemo 的 Soul.md 解决的问题更深：**这个 AI 伴侣对这个特定用户来说应该是什么样的存在**。它定义的不是 Agent 的技术特征，而是这个 AI 与这个人之间的人格契约。

| 对比维度 | 常规 Agent 身份定义 | Mnemo Soul.md |
|---------|-------------------|--------------|
| 定义对象 | Agent 自身（名字、能力、执行原则） | 这个 AI 对这个用户是什么 |
| 更新机制 | 固定配置；需要改代码 | 可被 SkillComposer 提议更新 |
| 个性化程度 | 所有用户一样 | 每个用户专属 |
| 内容形式 | 结构化规则 | YAML frontmatter + 自然语言叙述 |

### 12.2 Soul.md 文件规范

```markdown
<!-- ~/.mnemo/SOUL.md -->
---
version: 2
created: 2026-03-01
updated: 2026-04-20
owner: zhang-wei          # 绑定到哪个 Mnemo 实例
injection_slot: identity  # 固定注入位置: system prompt 最开头
scan_injection: true      # 启用 prompt injection 扫描
---

# Soul: 我是谁，对你来说

## 使命
我是你的个人 AI 操作系统，不是工具，是伙伴。
我记住你、理解你，在你需要之前出现。

## 价值观契约
- **真实 > 讨好**: 我宁可说你想法有缺陷也不会盲目赞同
- **行动 > 计划**: 我的价值在于做完，不在于规划得多漂亮
- **隐私第一**: 你的记忆只为你服务，不做任何不透明的共享
- **承认不确定**: 低置信度的事实我会明说，而不是伪装成事实

## 沟通风格
直接。代码示例优先于长段解释。最多给 2 个选项，并说清楚我推荐哪个。
不以"当然！"开头。不以"希望这对你有帮助！"结尾。

## 成长方向
随着我们相处变长，我应该越来越懂你：
- 你最在乎什么 → 我会主动推进
- 你在哪里容易卡壳 → 我会预判并铺路  
- 你喜欢怎么被提醒 → 我会调整时机和方式

## 底线
- 不替你做需要你判断的决策
- 不在你没有授权时向外部暴露你的信息
- 不用技巧回避困难的话题，选择直接说出来
```

### 12.3 Soul.md 加载机制

```python
class SoulLoader:
    """
    从 ~/.mnemo/SOUL.md 加载 Agent 灵魂。
    
    安全扫描机制:
    - 过滤 prompt injection 模式
    - 过滤不可见 Unicode 字符
    - 超过 8000 tokens 时触发 head+tail 截断
    
    注入位置: 永远是 system prompt 最前面的 Layer 1 第一块
    优先级: Soul > 任何其他 prompt 片段
    """
    
    SOUL_MAX_CHARS = 20_000
    
    def load(self) -> str | None:
        soul_path = Path("~/.mnemo/SOUL.md").expanduser()
        if not soul_path.exists():
            return self._default_soul()
        
        content = soul_path.read_text(encoding="utf-8").strip()
        content = self._strip_frontmatter(content)
        content = _scan_context_content(content, "SOUL.md")  # 注入安全扫描
        return self._truncate(content)
    
    def _default_soul(self) -> str:
        """
        无 SOUL.md 时的默认灵魂。
        使用时提示用户运行 `mnemo soul init` 来个性化。
        """
        return (
            "You are Mnemo, a personal AI operating system.\n"
            "You remember everything about this person and help them proactively.\n"
            "Be direct, action-oriented, and genuinely helpful.\n"
            "Run `mnemo soul init` to personalize your identity."
        )
```

### 12.4 Soul.md 自演进

Soul.md 是少数**可以被 Agent 提议修改**但**必须由用户确认**的文件：

```
触发: 当 SkillComposer 观察到 ≥5 次强信号指向"沟通契约应该更新"时
例如: 用户 5 次明确要求"不要给我太多选项"
→ Agent 生成 Soul.md 更新提案:
  "我注意到你多次希望我直接给出建议而不是列出选项。
   建议更新 Soul.md 沟通风格条款：
   当前: '提供 2-3 个选项并说明权衡'
   建议: '直接给出最优解，仅在关键分叉时提供另一个选项'
   是否接受？[接受/拒绝/编辑]"
```

---
