# Roadmap And Principles

> Lean roadmap、extension packs、核心原则速查和组件速查。

## 11. 开发路线图

路线图按 Lean Core 重排。目标是先验证一个问题：用户只通过一个聊天框派活时，Mnemo 是否能跨轮执行、自然学习偏好、可回放地改进行为。

Lean Core 只约束实现顺序和默认启用路径，不裁剪详细设计。尤其是 MemoryEngine 的十维本体、LLM Wiki、DreamCycle、写入事务和 L4 检索，是 Mnemo 的核心竞争力，必须作为详细规格保留。

三条自演进闭环必须贯穿路线图：

| Loop | 首次落地 | 完整增强 |
|------|----------|----------|
| Memory Evolution | Phase 0: W0 + MemoryWritePipeline + L1/L2/L4 | DreamCycle、tombstone、health cards、memory-safety eval |
| Skills Evolution | Phase 2: learning candidate tools + skill/SOP draft refinement | SkillHarness、red-team、cross-client import/export、rollback |
| Tools Evolution | Phase 4: Generated tool extension | generated tool shadow run、tool eval、standard toolset promotion |

### Phase 0: Storage + Memory Baseline (2-3 周)

```
✓ 继承 Mnemo v1 的 MemoryStore + Wiki 文件系统
+ SQLite core schema: sessions/messages/missions/turns/artifacts/decisions/runs
+ W0: turn_scratch + mission_state + pending_obs + draft_facts
+ L1/L2/L4 baseline: Markdown wiki + FTS5/BM25 session search
+ MemoryWritePipeline: scan → quality → conflict → write → audit
+ RunLedger JSONL trace mirror
+ Minimal Inbox/Decision table
```

**里程碑**: 能保存连续对话、恢复 Mission checkpoint、检索历史消息、写入带溯源的记忆候选；L1 ≤50 行。

### Phase 1: Conversation Runtime MVP (3 周)

```
+ MnemoDaemon + single-instance lock + crash recovery
+ GatewayHarness: CLI/MCP/REST → AgentRequest
+ MissionStore: resolve/create/continue/fork/checkpoint
+ AgentRunHarness(provider-native tool-call runtime only)
+ ContextEngine: search + prompt assembly + compression
+ ActionEngine: tool registry + ProviderToolAdapter + risk(read/write/external/admin) + result compression
+ Model-led tool loop: 模型通过 memory_search / skill_view / provider-native tool call 自主选择；关键选择只在高风险、外部 runtime、fork/压缩或 harness 场景写 `decision.recorded`
+ mnemo run / replay / daemon status CLI
```

**里程碑**: 用户连续输入“继续”“改成表格”“把刚才那份发给 Alex”时，系统能恢复目标、artifact 和 open decision，不依赖完整聊天窗口。

### Phase 2: Personalization Loop + Skills (3-4 周)

```
+ SkillRegistry/SkillLoader: 兼容 Agent Skills / Claude Code SKILL.md
+ Learning packet MVP: 用户纠正、失败恢复、已接受输出、artifact diff 统一打包
+ Candidate tools: memory_write_candidate / skill_propose_candidate / tool_propose_candidate / eval_propose_case / learning_discard
+ Skill/SOP draft: 只处理模型已提出的候选，不按次数阈值自动挖掘
+ DreamCycle: idle/daily delta-only 记忆整理
+ Prompt cache: L1 + stable skill summaries
+ Minimal eval: runtime-smoke + 3-5 个 personalization golden cases
```

**里程碑**: 系统能从同一 learning packet 中产生 0..N 个混合候选；带记忆/skill 候选版本比 no_memory 版本更符合用户偏好。频次只作为 evidence，不能替代模型判断。

### Phase 3: Primary Chat Frontend MVP (3 周)

```
+ 单一持续聊天框 + 底部 Composer
+ Streaming ChatEvent protocol
+ Inline action/artifact/decision/learning cards
+ Artifact preview drawer
+ Recall in chat
+ Minimal settings drawer: 连接应用、权限、安静时间、数据控制
```

**里程碑**: 用户只通过一个聊天框派活和追问；系统展示流式动作、确认高风险动作、交付 artifact，并允许用户直接说“继续改/发出去/以后按这个来”。

### Phase 4: Extension Packs (按需求启用)

这些不是首发内核，但都是保留能力。区别只是默认不开启、不压进第一版 prompt 和 daemon 主路径。真实使用场景出现后，按 extension pack 逐个启用：

| Extension | 触发条件 | 最小实现方式 |
|-----------|----------|--------------|
| Watch / Proactive | 用户明确要求长期关注 | `WatchEngine` + scheduled event + chat summary；不默认主动打扰 |
| External Runtime | 代码/浏览器/第三方 harness 明显更强 | `RuntimeAdapter` + context capsule + external-harness eval |
| Advanced Recall | FTS5/BM25/wiki links 召回质量不足 | vector recall + RRF/MMR + optional LLM spreading activation |
| Generated tools | SOP skill 仍无法降低成本 | 从稳定 SOP 晋升为 generated tool，带 shadow/eval/rollback |
| Sub-Agent / AgentCard | 单 agent 明显无法并行完成 | `SubAgentSpawner` + `AgentCard` + ACP/OpenClaw 插件 |
| Sense / Android | 用户需要设备感知入口 | Android Companion + SenseEngine + explicit permission |
| Sync / Enterprise Policy | 需要企业策略或同步系统 | 读取 SQLite outbox，以 adapter 方式接入，不进入主路径 |
| Messaging / Calendar / Mail | 用户要 Mnemo 代发/排期/处理收件 | ToolProvider + Decision Card + standing authority |
| Full Harness Suites | 多用户/多画像/发布前回归 | memory-safety、skill-evolution、external-harness、proactive-watch suites |

**里程碑**: 每个 extension 都能独立安装、禁用、回滚；不改变 core path 的 `AgentRequest → ChatEvent → RunLedger` 协议。

保留的详细设计位置：
- Watch / Proactive：§7、§21、§15.4。
- Generated tools：§13.4-§13.6。
- Sub-Agent / AgentCard：§14。
- Sense / Android：§15。
- Extension Events：§22.11。
- External RuntimeAdapter：§22.4。

---
---

## 附录: 核心设计原则速查

```
记忆层原则:
 1. 关于你的记忆 > 通用任务记忆
 2. L1 是指针，不是内容（≤50行，指向 L2，不复述）
 3. 置信度 < 0.5 的事实必须标注 [?]
 4. 过时记忆比没有记忆更有害（定期衰减+清理）
 5. W0 是暂存，不是记忆——Mission 空闲/结束或 DreamCycle 时蒸馏、checkpoint 或丢弃
 6. 所有记忆写入都过质量过滤器（五维评分 ≥ 0.6 才写）
 7. 矛盾不静默覆盖——CRITICAL 级必须用户确认
 8. 每条记忆都有溯源——可查询"你从哪得知这个？"

运行层原则:
 9. Mnemo 默认是持续运行 daemon，不是一次性 prompt 拼接器
10. 每个 turn/scheduled task 都必须有 run_id/session_id/mission_id/trace_id
11. 工具结果完整写 RunLedger，进入 prompt 的版本可裁剪
12. daemon 重启必须恢复 running Mission、Inbox、pending observations 和 running run 状态
13. 模型在 agentic loop 中做语义选择，规则只做候选生成、安全护栏、schema 校验和资源边界

自演进原则:
14. Agent 生成候选，低风险可自动进入 shadow/available；active/promoted 必须过 eval gate，高风险写 Inbox 待用户异步确认
15. SOP 晶化 = 探索→解决→结晶→复用（GenericAgent 核心循环）
16. 第一次重试必须携带新信息，否则不重试
17. 自演进不能只看任务成功，还要看个性化收益和误记忆率

主动服务原则:
18. Watch 是 extension，不是默认打扰机制；只有用户明确要求才持续关注
19. 主动推送的机会分数必须考虑打扰成本（推送落空自动稀疏化）
20. 一次会话不超过 1 次主动打断（critical Inbox 优先，其余推后）

无感化原则:
21. 所有"可能需要你知的事"放 Inbox，用户什么时候打开都行，不打开也运作正常
22. 技能/工具变更都有 audit trail，随时可撤销——所以不需要事先确认
23. Soul.md autonomy 字段支持调整无感化粒度（默认为 fully_autonomous=false）

技术原则:
24. Prompt 密度 = 每 token 的信息价值（零冗余原则）
25. KV cache 是一等目标：stable prefix 字节级稳定，动态状态只放 tail，工具 schema 用版本化 ToolBundle
26. 所有记忆写入路径都过注入安全扫描
27. 外部 runtime fresh-context：只收 context capsule，只回 final summary/structured result，不直接写 memory/skill/tool
28. 禁止易变状态进本体（PID/时间戳/会话 token 不进记忆）
29. SQLite WAL + jitter retry 保证并发写安全
30. 文件写入使用原子重命名（os.replace），不产生半写状态
31. 个性化必须可评测：preference adherence、wrong-memory、over-personalization 都是发布门禁
```

---
---

## 附录: 完整系统组件速查

### Core Components

| 组件 | 职责 | 关键设计 |
|------|------|---------|
| **ConversationRuntime** | 单一聊天入口和多轮执行 | GatewayHarness + MissionStore + AgentRunHarness；用户只见一个聊天框 |
| **ContextEngine** | 检索、组装、压缩上下文 | MemorySearch + PromptAssembler + ContextCompressor + prompt cache |
| **ActionEngine** | 执行工具并控制风险 | ToolRegistry + ProviderToolAdapter + dispatch + read/write/external/admin 四级审批 + result compression |
| **MemoryEngine** | 个性化长期记忆与草稿层 | W0、L1/L2/L4、MemoryWritePipeline、DreamCycle、ConflictResolver |
| **SkillEngine** | 主流 skill 兼容和自演进 | SkillRegistry/Loader/Composer；SOP candidate 先作为 skill，不直接造工具 |
| **MnemoDatabase** | 本地真相源和并发层 | SQLite WAL + wiki Markdown + runs JSONL + atomic file write |
| **Soul.md** | 用户关系契约 | 稳定人格/边界/沟通偏好；热重载但走注入扫描 |

### Extension Components

| 扩展组件 | 状态 | 原因 |
|----------|------|------|
| **RuntimeAdapter(OpenClaw/Codex/ACP)** | 插件 | 强能力但非首发必要；通过 context capsule 最小披露 |
| **WatchEngine / ProactiveDaemon** | 插件 | 只有用户明确要求长期关注时启用 |
| **SenseEngine / AndroidCompanion** | 延后 | 设备感知成本高，且容易增加打扰和隐私面 |
| **SubAgentSpawner / AgentCard** | 延后 | 单 agent core 先跑通；多 agent 通过 RuntimeAdapter 接入 |
| **Generated tools** | 延后 | 先用 SOP skill 降低复杂度；稳定高频后再晋升 generated tool |
| **Advanced Recall** | 可选增强 | 基础 wiki links 在 MemoryEngine；LLM spreading activation 后置 |
