# Core Architecture

> 产品定位、Lean Core、扩展面和整体架构。

## 1. 设计基础与核心原则

### 1.1 Mnemo 是什么

Mnemo 是一个**个人 AI 操作系统**——不是一个 Chatbot，不是一个工具集合，而是一个持续了解你、代表你思考、在你需要之前出现的 AI 实体。

三个核心命题：
- **记忆**：构建并维护关于你这个人的结构化知识（十个维度的个人本体论）
- **演进**：从每次交互中学习，自动生成个人技能和工具，无需手动配置
- **主动**：持续监测你关心的事物，在合适的时机以合适的方式出现

### 1.2 核心设计公理

```
╔══════════════════════════════════════════════════════════════════════╗
║                      Mnemo 设计公理                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  公理 1: 关于你的记忆 > 通用任务记忆                                  ║
║  公理 2: L1 是指针，不是内容（≤50行，指向 L2，不复述）                ║
║  公理 3: 验证原则——未验证的推断不写为事实，confidence < 0.5 标注        ║
║  公理 4: 过时记忆比没有记忆更有害（定期衰减+清理）                     ║
║  公理 5: 无感化原则——系统默认静默自动行动；只有不可逆/高风险操作        ║
║           才写入 Inbox 请求确认；绝不在任务执行中途打断用户             ║
║  公理 6: Watch = 你在乎的事 + 系统的关注承诺（推送失效自动退场）        ║
║  公理 7: Prompt 密度 = 每 token 的信息价值（零冗余原则）               ║
║  公理 8: 所有记忆写入路径都过注入安全扫描                              ║
║  公理 9: 暴露边界——外部 Agent 最多看到 L1                             ║
║  公理 10: 禁止易变状态进本体（PID/时间戳/会话 token 不进记忆）          ║
║  公理 11: 持续运行优先——Mnemo 是 daemon，不是一次性 prompt 拼接器      ║
║  公理 12: 个性化必须可评测——偏好遵循、误记忆率、打扰成本都要量化        ║
║  公理 13: 模型决策优先——规则负责候选生成和安全护栏，裁决交给模型        ║
╚══════════════════════════════════════════════════════════════════════╝
```

### 1.3 精简子系统边界

Mnemo 的架构必须克制：首发版本只保留一条能稳定闭环的 core path，其它能力做成 extension pack。判断标准是：如果没有它，用户还能不能在一个聊天框里派活、跨轮继续、得到产物、形成偏好学习。

这里的“精简”不是删掉记忆、prompt、harness 或 skills/tools 的细节，而是把它们从默认执行路径里解耦出来：

- 记忆模块仍然保留十维本体、W0、L1/L2/L4、DreamCycle、LLM Wiki、联想召回、写入事务、并发和评测细节。
- Prompt 系统仍然保留 OpenClaw/Hermes 借鉴、JSON/XML 边界、PromptBlock、缓存和模板细节。
- Runtime Harness 仍然保留 Mission、多轮恢复、RunLedger、RuntimeAdapter、回放和 eval 细节。
- Skills/Tools 仍然保留主流 Skills 操作兼容、自演进、SOP、tool candidate 和 generated tools 细节。
- 真正瘦身的是“哪些组件每轮必经、哪些内容每轮进 prompt、哪些能力首发必须实现”。

**Core path 只包含 5 个域**：

| 核心域 | 职责 | 首发必须有 |
|--------|------|------------|
| **Conversation Runtime** | 单一聊天入口、多轮恢复、执行状态机、流式事件 | `GatewayHarness`、`MissionStore`、`AgentRunHarness` |
| **Context Engine** | 记忆检索、上下文预算、prompt 组装、压缩 | `MemorySearchPipeline`、`PromptAssembler`、`ContextCompressor` |
| **Memory Engine** | 十维个人本体、W0、写入管线、DreamCycle | L1/L2/L4、`MemoryWritePipeline`、learning candidate tools |
| **Action Engine** | 工具注册、provider-native tool call 适配、轻量审批、结果压缩 | `ToolRegistry`、`ProviderToolAdapter`、`ToolHarness`、`ToolResultCompressor` |
| **Skill Engine** | 兼容主流 skills，并精炼模型提出的 SOP/skill 候选 | `SkillRegistry`、`SkillLoader`、skill candidate tools |

`RunLedger` 是横切基础设施，不作为第六个执行域；所有域都写事件，最小 eval/replay 直接消费这些事件。

**Extension pack 延后或插件化**：

| 扩展 | 进入条件 | 首发处理 |
|------|----------|----------|
| Watch / Proactive | 用户明确要求长期关注或定时任务 | 先作为简单 scheduled prompt，不做完整主动服务 OS |
| Sense / Android | 需要设备感知、位置、通知策略 | 延后；不进 core runtime |
| Sub-Agent / ACP / AgentCard | 任务复杂到需要多 agent 或对外能力描述 | 通过 `RuntimeAdapter` 插件接入 |
| Generated tools | 工具序列高度稳定，普通 skill/SOP 不够 | 延后；先只生成 SOP skill |

### 1.4 竞品调研与 Mnemo 定位

Mnemo 的目标不是复制 OpenClaw、Hermes Agent 或 GenericAgent，而是吸收三者的强项后，把重心推进到**持续运行的用户个性化 OS 层**。

**资料来源**:
- Agent Skills open standard: [Overview](https://agentskills.io/), [Specification](https://agentskills.io/specification), [Adding skills support](https://agentskills.io/client-implementation/adding-skills-support)
- Claude Code Skills: [Extend Claude with skills](https://code.claude.com/docs/en/skills)
- OpenClaw: [Agent runtime](https://docs.openclaw.ai/concepts/agent), [Agent workspace](https://docs.openclaw.ai/concepts/agent-workspace), [Skills](https://docs.openclaw.ai/tools/skills), [Sub-Agents](https://docs.openclaw.ai/tools/subagents), [Codex Harness](https://docs.openclaw.ai/plugins/codex-harness)
- Hermes Agent: [Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/), [Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/), [Context Compression](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching/), [Self-Evolution](https://github.com/NousResearch/hermes-agent-self-evolution)
- GenericAgent: [arXiv:2604.17091](https://arxiv.org/abs/2604.17091), [GitHub](https://github.com/lsdefine/GenericAgent)
- Agent Memory / Search: [2026 年做搜索就是做 Agent Memory](https://www.53ai.com/news/RAG/2026042381406.html)

| 系统 | 核心设计理念 | 强项 | 对 Mnemo 的启发 | Mnemo 的超越点 |
|------|-------------|------|----------------|----------------|
| Agent Skills / Claude Code | `SKILL.md` 开放格式 + progressive disclosure + slash/model 双触发 | 跨客户端可复用、目录式资源、`allowed-tools`、arguments、path scope、subagent context | Mnemo 必须兼容 `name/description/SKILL.md/scripts/references/assets` 标准操作 | Mnemo 在兼容格式上叠加个人记忆、本体、RunLedger、SkillHarness 和自演进治理 |
| OpenClaw | 本地 workspace + 多渠道 gateway + 工具/技能加载 | 能长期部署、接消息渠道、跑本地工具、调外部 harness | `SOUL.md`/`USER.md`/`AGENTS.md` 工作区文件、sub-agent、Codex/ACP harness、技能优先级 | OpenClaw 的个性化主要是文件注入和用户维护；Mnemo 要把个性化做成可验证、可回滚、可评测的运行时系统 |
| Hermes Agent | 持久运行 agent + bounded memory + agent-managed skills | 技能可由 agent 创建/修改，记忆有边界，压缩和缓存工程化 | Progressive disclosure、`skill_manage`、FTS5 session search、双层压缩、GEPA/DSPy 演进评测 | Hermes 的 `USER.md`/`MEMORY.md` 容量小，更多是“关键事实”；Mnemo 要维护完整个人本体、联想记忆和主动服务 |
| GenericAgent | Context information density maximization | 极简工具、分层记忆、轨迹晶化为 SOP/代码，低 token 长程执行 | L1 只放索引，任务前先搜 SOP，探索成功后晶化执行路径 | GenericAgent 强在任务自演进；Mnemo 还要衡量“这是不是更懂这个人” |

**战略判断**:
- OpenClaw 证明了本地持续运行 agent 的产品形态成立，但它更像可执行工作区和渠道网关。
- Hermes 和 GenericAgent 证明了 skills/SOP 自演进的工程价值，但用户个性化仍偏“记住少量偏好”或“任务轨迹复用”。
- Mnemo 的核心护城河应是 `Personalization Loop`: observe → infer → validate → write → compile → apply → measure。没有 measure 的个性化只是 prompt 风格；能回放和评测的个性化才是 OS 能力。

---
---

## 2. Mnemo AgenticOS 架构总览

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         Mnemo AgenticOS v2.2 Lean Core                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  User / App / CLI / MCP                                                      ║
║                  │                                                           ║
║  ┌───────────────▼──────────────────────────────────────────────────────┐   ║
║  │ Conversation Runtime                                                  │   ║
║  │ GatewayHarness → MissionStore → AgentRunHarness → ChatEvent stream   │   ║
║  └───────────────┬──────────────────────────────────────────────────────┘   ║
║                  │                                                           ║
║  ┌───────────────▼──────────────────────────────────────────────────────┐   ║
║  │ Agentic Loop Core                                                     │   ║
║  │ Model-led tool loop → ContextEngine → ActionEngine → Observe/Queue   │   ║
║  │                                                                       │   ║
║  │ ContextEngine = MemorySearch + PromptAssembler + ContextCompressor   │   ║
║  │ ActionEngine  = ToolRegistry + ProviderToolAdapter + ToolHarness     │   ║
║  └───────────────┬──────────────────────────────────────────────────────┘   ║
║                  │                                                           ║
║  ┌───────────────▼──────────────────────────────────────────────────────┐   ║
║  │ Personalization Substrate                                             │   ║
║  │ MemoryEngine(W0/L1/L2/L4/Dream) │ SkillEngine(SKILL.md/SOP)          │   ║
║  │ RunLedger(trace/eval)           │ Inbox/Decision(low-friction gate)  │   ║
║  └───────────────┬──────────────────────────────────────────────────────┘   ║
║                  │                                                           ║
║  ┌───────────────▼──────────────────────────────────────────────────────┐   ║
║  │ Storage                                                               │   ║
║  │ ~/.mnemo/state.db + wiki/ + skills/ + runs/ + artifacts/             │   ║
║  └──────────────────────────────────────────────────────────────────────┘   ║
║                                                                              ║
║  Extension Plane (plugins, not core path): Watch, Sense/Android, ACP,       ║
║  SubAgents, generated tools, full harness suites, enterprise sync.          ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

### 2.1 持续运行优先

Mnemo 的运行形态默认是一个轻量本地 daemon，而不是“每次请求拼一次上下文”的库函数。SDK、MCP、CLI、Android Companion、外部 Agent 都只是入口；真正的状态机在 Continuous Runtime Harness 中。

```
Inbound Event
  ├─ user message / MCP call / optional scheduled event / optional extension event
  ▼
GatewayHarness.normalize()
  ▼
AgentRunHarness.run_turn()
  ├─ hydrate minimal Mission state + short context indexes
  ├─ provider-native model/tool loop through ActionEngine
  ├─ persist response, tool results, artifacts, checkpoint
  └─ optionally queue learning packet / compression / Dream
  ▼
Delivery + RunLedger.append()
```

持续运行带来的设计约束：
- 每个 turn 必须有 `conversation_id`、`mission_id`、`run_id`；`trace_id` 可由 RunLedger 派生，只有外部 harness 或分布式追踪需要时显式生成。
- `session` 是入口通道和消息流，`run` 是一次执行尝试，`Mission` 才是跨多轮持续存在的用户委托。
- 每个工具结果必须进入 RunLedger，但进入 prompt 时可以被剪裁或摘要。
- 每次记忆/技能/Soul/工具变更必须能追溯到具体 run 和 evidence quote。
- daemon 重启后必须恢复 running Mission 和未完成 run；pending Inbox、观察队列和 session locks 只在对应能力启用时恢复。
- 外部 harness 只能收到 context capsule，不得绕过暴露边界读取完整 L2/L4。

### 2.2 Lean Core 原则

Mnemo 的扩展性来自“窄内核 + 稳定事件协议”，而不是把所有能力都做成一等子系统。核心路径只回答四个问题：

1. 这句话属于哪个对话焦点和 Mission？
2. 当前 turn 默认暴露哪些短上下文、skill 索引和工具 affordance？
3. 模型如何在运行中自由选择记忆、skill、工具和下一步？
4. 本轮哪些信号要变成 checkpoint、记忆候选或 skill 候选？

默认路径从一次模型调用开始。模型通过工具自己查询记忆、查看 skill、执行动作；工具调用优先沿用 OpenAI / Anthropic 等 provider 的原生 tool-call 语义。Mnemo 只把内部 `ToolRegistry` 编译成 provider schema，接收 provider 返回的 tool calls，执行后按 provider 要求回填 tool results；系统只在风险、预算、schema、缓存和账本边界上拦截。需要可审计对比时，把关键选择写成 RunLedger 的 `decision.recorded` 事件。

因此首发内核保留：

| Core module | 合并后的职责 |
|-------------|--------------|
| `ConversationRuntime` | `GatewayHarness` + `MissionStore` + `AgentRunHarness` |
| `ContextEngine` | Memory search、PromptAssembler、ContextCompressor、prompt cache |
| `ActionEngine` | ToolRegistry、ProviderToolAdapter、ToolHarness、ApprovalGate、ToolResultCompressor |
| `MemoryEngine` | W0、L1/L2/L4、MemoryWritePipeline、DreamCycle |
| `SkillEngine` | SkillRegistry、SkillLoader、skill/SOP candidate refinement |

横切基础设施：

| Infra | 职责 |
|-------|------|
| `RunLedger` | 每个 run 的 prompt、tool、memory、skill、artifact、decision、eval 事件 |
| `Eval cases` | 少量 smoke/golden replay；完整 harness suite 后置 |

降级为 extension 或 later 的组件：

| 原组件 | 精简决策 |
|--------|----------|
| `MessageBus` | 首发用 SQLite event/outbox 表即可，不单独做总线系统 |
| `SenseEngine` / `AndroidCompanion` | 设备感知延后；先支持用户显式 scheduled/Watch |
| `SubAgentSpawner` / `AgentCard` | 多 agent 和对外能力描述延后；通过 `RuntimeAdapter` 接入 |
| `Generated tools` | 先不生成新工具，只生成 SOP skill；确有稳定高频流程再晋升工具 |

扩展点统一走三类接口：
- `RuntimeAdapter`: 接 OpenClaw、Codex、ACP、外部 agent harness。
- `ToolProvider`: 接文件、浏览器、消息、日历、代码、企业系统。
- `EventPlugin`: 接 Watch、Sense、同步、通知和企业策略。

> **精简原则**：Watch、Sense、Sub-Agent、generated tools、外部 runtime 和同步/企业插件默认不进入 core path。真实场景反复触发后，再以 extension 方式接入或晋升为 core module。

> **细节保留原则**：extension 不进入 core path，不代表删除设计。详细规格继续保留在各自章节，用来指导后续实现、harness case 和 prompt/tool 预算。

---
