# Mnemo AgenticOS — Design Package Entry

> **Mnemo** /ˈniːmoʊ/，源自希腊语 Μνημοσύνη（Mnemosyne），记忆女神。
> **版本**: v2.2 design package · **日期**: 2026-04-24
>
> 这份设计已从单一长文档拆成模块化设计包。完整内容见 [design/README.md](design/README.md)。

## 快速入口

| 主题 | 文件 |
|------|------|
| 架构总览与 Lean Core | [design/00-core-architecture.md](design/00-core-architecture.md) |
| 记忆系统 | [design/01-memory-engine.md](design/01-memory-engine.md) |
| Skills 与 Tools | [design/02-skills-tools.md](design/02-skills-tools.md) |
| Agentic Loop / Prompt / Soul | [design/03-agentic-loop-prompt-soul.md](design/03-agentic-loop-prompt-soul.md) |
| 主动服务 / Sense / Inbox | [design/04-proactive-sense-inbox.md](design/04-proactive-sense-inbox.md) |
| 接口 / 数据 / 安全 | [design/05-interfaces-data-security.md](design/05-interfaces-data-security.md) |
| Agent 扩展与联邦 | [design/06-agent-extensions-federation.md](design/06-agent-extensions-federation.md) |
| Runtime Harness | [design/07-runtime-harness.md](design/07-runtime-harness.md) |
| 前端聊天体验 | [design/08-frontend-chat.md](design/08-frontend-chat.md) |
| 路线图与原则 | [design/09-roadmap-principles.md](design/09-roadmap-principles.md) |
| 三大自演进闭环 | [design/10-evolution-loops.md](design/10-evolution-loops.md) |
| Prompt 系统与组装 | [design/11-prompt-system.md](design/11-prompt-system.md) |

## 当前设计原则

- 用户侧只有一个持续聊天框。
- Mission 是后端执行信封，不是用户管理对象。
- Core path 保持轻量；重要能力通过 extension pack 保留。
- LLM Wiki、wiki links、association hubs 属于 MemoryEngine；高成本 LLM spreading activation 才是 Advanced Recall extension。
- Memory、Skills、Tools 三条自演进闭环都有候选、shadow/eval、激活和回滚机制。
- Prompt 不是单一 system prompt，而是一套可缓存、可裁剪、可审计的 Prompt Assembly System；KV cache 复用是组装器的一等目标。
- Tools 使用版本化 ToolBundle；用户侧保持轻量风险词，运行时内部计算副作用标记。
- 外部 runtime 只接收 context capsule，只返回结构化结果，不直接写 memory、skill 或 tool。
- 模型负责语义裁决，规则只负责候选、安全和资源边界。
- RunLedger 和最小 eval 保证个性化、技能和工具演进可回放、可验证、可回滚。
