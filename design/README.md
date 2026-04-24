# Mnemo Design Package

> **版本**: v2.2 design package · **日期**: 2026-04-24
>
> Mnemo 的完整设计被拆成模块化设计包。根目录 `mnemo.md` 只作为入口；具体设计在本目录维护。

## 设计包原则

- **Lean Core**: 默认执行路径只依赖 ConversationRuntime、ContextEngine、ActionEngine、MemoryEngine、SkillEngine、TraceEngine。
- **Memory-Centered Recall**: LLM Wiki、wiki links、association hubs 属于 MemoryEngine；只有高成本 LLM spreading activation 作为 Advanced Recall extension。
- **Extension Plane**: Watch、Sense、Sub-Agent、ToolComposer、HookEngine、外部 runtime 是可选扩展，不进入默认执行路径。
- **Single User Surface**: 用户侧永远只有一个持续聊天框；Mission 是后端执行信封。
- **Model-Decided Agentic Loop**: 规则只做候选生成、安全护栏和资源边界；语义分流由模型裁决。
- **Token Budget First**: 默认 prompt 只暴露短索引、短工具卡和当前 turn 必要上下文。

## 文件结构

| 文件 | 内容 |
|------|------|
| [00-core-architecture.md](00-core-architecture.md) | 产品定位、Lean Core、扩展面和整体架构 |
| [01-memory-engine.md](01-memory-engine.md) | 十维本体、W0、LLM Wiki、联想召回、DreamCycle、写入事务、L4、并发和数据流 |
| [02-skills-tools.md](02-skills-tools.md) | Agent Skills 兼容、SkillComposer、SOP、工具分层和 ToolComposer |
| [03-agentic-loop-prompt-soul.md](03-agentic-loop-prompt-soul.md) | Agentic loop、模型裁决、prompt、缓存和 Soul.md |
| [04-proactive-sense-inbox.md](04-proactive-sense-inbox.md) | Watch、主动服务、Sense/Android 和 Inbox |
| [05-interfaces-data-security.md](05-interfaces-data-security.md) | SDK/MCP/CLI/Adapter、数据模型、安全和外部披露 |
| [06-agent-extensions-federation.md](06-agent-extensions-federation.md) | Sub-Agent、AgentCard、MessageBus、联邦和外部 Agent 协作 |
| [07-runtime-harness.md](07-runtime-harness.md) | 持续运行系统、Mission、多轮恢复、RunLedger、RuntimeAdapter 和 HookEngine |
| [08-frontend-chat.md](08-frontend-chat.md) | 单一聊天框前端、流式动作、Artifact、Decision、Learning cards |
| [09-roadmap-principles.md](09-roadmap-principles.md) | 开发路线图、Extension Packs、核心原则和组件速查 |
| [10-evolution-loops.md](10-evolution-loops.md) | Memory / Skills / Tools 三条自演进闭环和统一治理 |
| [11-prompt-system.md](11-prompt-system.md) | Prompt catalog、OpenClaw/Hermes 借鉴、PromptBlock、JSON/XML 边界策略、KV cache-first 组装、token/cache 预算和模板 |

## 推荐阅读路径

1. 先读 [00-core-architecture.md](00-core-architecture.md) 建立边界：core path 和 extension plane。
2. 再读 [07-runtime-harness.md](07-runtime-harness.md) 理解多轮执行与可回放状态机。
3. 读 [01-memory-engine.md](01-memory-engine.md) 和 [02-skills-tools.md](02-skills-tools.md) 理解差异化：个性化记忆 + skills/SOP 自演进。
4. 读 [08-frontend-chat.md](08-frontend-chat.md) 对齐用户体验：所有能力都落到一个聊天框。
5. 读 [10-evolution-loops.md](10-evolution-loops.md) 对齐 Memory / Skills / Tools 三条自演进闭环。
6. 读 [11-prompt-system.md](11-prompt-system.md) 对齐所有 prompt 和 PromptAssembler 细节。
7. 用 [09-roadmap-principles.md](09-roadmap-principles.md) 管控实现优先级。
