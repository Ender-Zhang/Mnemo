# Mnemo Design Package

> **版本**: v2.2 design package · **日期**: 2026-04-24
>
> Mnemo 的完整设计被拆成模块化设计包。`design/README.md` 是唯一入口；具体设计在本目录维护。

## 设计包原则

- **Lean Core**: 默认执行路径只依赖 ConversationRuntime、ContextEngine、ActionEngine、MemoryEngine、SkillEngine；RunLedger 是横切基础设施。
- **Memory-Centered Recall**: LLM Wiki、wiki links、association hubs 属于 MemoryEngine；只有高成本 LLM spreading activation 作为 Advanced Recall extension。
- **Extension Plane**: Watch、Sense、Sub-Agent、generated tools、外部 runtime 和高级插件都是可选扩展，不进入默认执行路径。
- **Single User Surface**: 用户侧永远只有一个持续聊天框；Mission 是后端执行信封。
- **Model-Decided Agentic Loop**: 规则只做候选生成、安全护栏和资源边界；语义分流由模型裁决。
- **Token Budget First**: 默认 prompt 只暴露短索引、短工具卡和当前 turn 必要上下文。
- **Slim Core, Rich Specs**: 瘦身发生在默认执行路径、实现优先级和 prompt 暴露面；记忆、skills、tools、prompt、harness 的详细设计是系统资产，不能为了“少”而删除。

## 瘦身边界

本设计包采用“窄内核 + 详细规格”的结构：

- **Core path** 只描述每个 turn 必经的最小闭环，避免把 Watch、Sense、Sub-Agent、generated tools 等扩展做成默认路径。
- **Subsystem specs** 保留细节，尤其是 MemoryEngine、PromptAssembler、RuntimeHarness、Skill/Tool 自演进和数据安全。它们是未来实现和评测的依据。
- **Extension specs** 保留但标注进入条件。不是首发默认启用，不等于删除。
- **Prompt/token slimming** 只影响运行时注入策略：短索引、按需加载、KV cache-first；不影响设计文档保留必要细节。
- **真正应删除的内容** 只有旧版入口、重复章节、与当前方向冲突的兼容包袱和过期参考。

## Less Is More 执行原则

Mnemo 的 less is more 不是少能力，而是少固定路径：

- 默认不定义业务 workflow。系统只提供 Mission 状态、记忆检索、skill 索引、工具卡、权限边界和回放账本。
- 模型在每轮 agentic loop 中自己决定是否查记忆、加载 skill、调用工具、继续探索、交付结果或在高影响场景请求用户复核。
- 工具调用优先使用 OpenAI / Anthropic 等 provider 的原生 tool-call 机制；Mnemo 只定义工具 schema、处理调用、压缩结果和写账本。
- 关键选择只在需要审计时写成 RunLedger 的 `decision.recorded` 事件；普通任务从 prompt blocks、tool calls、skill views 和 memory searches 还原。
- Registry、Search、boundary filters 只生成候选和边界，不替模型做语义选择。
- 执行细节保留在文档里，运行时按需暴露给模型，避免把复杂度压进每次 prompt。

## 文件结构

| 文件 | 内容 |
|------|------|
| [00-core-architecture.md](00-core-architecture.md) | 产品定位、Lean Core、扩展面和整体架构 |
| [01-memory-engine.md](01-memory-engine.md) | 十维本体、W0、LLM Wiki、联想召回、DreamCycle、写入事务、L4、并发和数据流 |
| [02-skills-tools.md](02-skills-tools.md) | Agent Skills 兼容、skill/SOP 候选、工具分层和 generated tools |
| [03-agentic-loop-prompt-soul.md](03-agentic-loop-prompt-soul.md) | Agentic loop、模型裁决、prompt、缓存和 Soul.md |
| [04-proactive-sense-inbox.md](04-proactive-sense-inbox.md) | Watch、主动服务、Sense/Android 和 Inbox |
| [05-interfaces-data-security.md](05-interfaces-data-security.md) | SDK/MCP/CLI/Adapter、数据模型、安全和外部披露 |
| [06-agent-extensions-federation.md](06-agent-extensions-federation.md) | Sub-Agent、AgentCard、MessageBus、联邦和外部 Agent 协作 |
| [07-runtime-harness.md](07-runtime-harness.md) | 持续运行系统、Mission、多轮恢复、RunLedger、RuntimeAdapter 和扩展事件 |
| [08-frontend-chat.md](08-frontend-chat.md) | 单一聊天框前端、流式动作、Artifact、Decision、Learning cards |
| [09-roadmap-principles.md](09-roadmap-principles.md) | 开发路线图、Extension Packs、核心原则和组件速查 |
| [10-evolution-loops.md](10-evolution-loops.md) | Memory / Skills / Tools 三条自演进闭环和统一治理 |
| [11-prompt-system.md](11-prompt-system.md) | Prompt catalog、OpenClaw/Hermes 借鉴、PromptBlock、JSON/XML 边界策略、KV cache-first 组装、token/cache 预算和模板 |
| [12-frontend-visual-system.md](12-frontend-visual-system.md) | 生成 UI 参考图沉淀后的前端视觉系统、桌面/移动布局、记忆罗盘页面和设置抽屉设计 |
| [frontend-redesign-checklist.md](frontend-redesign-checklist.md) | 前端视觉重构执行 checklist |

## 推荐阅读路径

1. 先读 [00-core-architecture.md](00-core-architecture.md) 建立边界：core path 和 extension plane。
2. 再读 [07-runtime-harness.md](07-runtime-harness.md) 理解多轮执行与可回放状态机。
3. 读 [01-memory-engine.md](01-memory-engine.md) 和 [02-skills-tools.md](02-skills-tools.md) 理解差异化：个性化记忆 + skills/SOP 自演进。
4. 读 [08-frontend-chat.md](08-frontend-chat.md) 对齐用户体验：所有能力都落到一个聊天框。
5. 读 [10-evolution-loops.md](10-evolution-loops.md) 对齐 Memory / Skills / Tools 三条自演进闭环。
6. 读 [11-prompt-system.md](11-prompt-system.md) 对齐所有 prompt 和 PromptAssembler 细节。
7. 读 [12-frontend-visual-system.md](12-frontend-visual-system.md) 对齐用户可体验前端。
8. 用 [09-roadmap-principles.md](09-roadmap-principles.md) 管控实现优先级。
