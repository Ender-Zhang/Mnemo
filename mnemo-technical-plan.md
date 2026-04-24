# Mnemo — 个人记忆操作系统 · 技术方案

> **Mnemo** /ˈniːmoʊ/，源自希腊语 Μνημοσύνη（Mnemosyne），记忆女神。
> 
> 一个 AI Agent 可插拔的、隐私优先的个人记忆系统。它不是另一个 RAG 管道，而是关于「你」的一部活的百科全书——由 AI 撰写和维护，由你策展和引导。

---

## 目录

1. [核心理念](#1-核心理念)
2. [需求分析与设计哲学](#2-需求分析与设计哲学)
3. [系统架构总览](#3-系统架构总览)
4. [记忆本体论——关于一个人的十个维度](#4-记忆本体论关于一个人的十个维度)
5. [多级暴露机制——分层编译模型](#5-多级暴露机制分层编译模型)
6. [模块详细设计](#6-模块详细设计)
7. [数据模型与存储](#7-数据模型与存储)
8. [接口规范](#8-接口规范)
9. [交互心理学设计](#9-交互心理学设计)
10. [自我对话模块](#10-自我对话模块)
11. [安全与隐私](#11-安全与隐私)
12. [技术选型](#12-技术选型)
13. [项目结构](#13-项目结构)
14. [开发路线图](#14-开发路线图)
15. [附录：与现有系统的定位对比](#15-附录与现有系统的定位对比)

---

## 1. 核心理念

### 问题

当下 AI Agent 生态的痛点：**每一个 Agent 都是失忆的**。

你用 Claude Code 做了一周的项目，它终于了解了你的代码风格、调试习惯、技术栈偏好。然后你打开 Codex、Pi、ChatGPT——一切归零。你得再介绍一遍自己。再纠正一遍同样的误解。再说一遍"我喜欢用 Rust 不用 Go"。

AI Agent 的智力在指数增长，但关于「你」的记忆是零。

### 解法

Mnemo 不是一个 AI Agent，而是一个**记忆层**——一个独立于任何 Agent 的、关于「你」的结构化知识库。它通过标准协议（MCP / CLI / REST）暴露给任意 Agent，让每一个 Agent 在第一次对话时就已经认识你。

**类比：**
- ChatGPT Memory = 粗粒度的便利贴（扁平 key-value，无结构）
- RAG = 每次问问题都翻一遍所有文件（无编译，无积累）
- Mnemo = 一部关于你的维基百科（结构化、交叉引用、持续演化、分层暴露）

### 核心原则

| 原则 | 含义 |
|------|------|
| **AI 写，人策展** | 所有记忆的创建、更新、交叉引用由 AI 自动完成；人负责策展和验证 |
| **编译，不检索** | 记忆不是 RAG 式的检索，而是预编译成多级摘要，随时可注入 |
| **隐私优先** | 所有数据存本地，不上云。你的记忆只属于你 |
| **Agent 无关** | 通过标准协议暴露，任意 Agent 都能接入，不绑定任何平台 |
| **渐进积累** | 不需要一次性填完。每次交互自然沉淀，记忆越用越丰富 |
| **时间感知** | 记忆不是静态的。有时效性的信息会自然衰减、被更新或归档 |

---

## 2. 需求分析与设计哲学

### 2.1 传统个人信息管理的失败

人类历史上的个人知识管理（PKM）工具——Notion、Obsidian、Roam、Evernote——有一个共同的失败模式：**维护成本超过使用价值**。你花 3 小时整理笔记，下次搜的时候还是靠全文搜索。交叉引用是手动的。过时信息永远不会被清理。最终，工具变成了数字垃圾场。

Karpathy 的 LLM Wiki 洞察到了关键：**让 LLM 做维护者**。人只负责投喂原料和提问。

但 LLM Wiki 面向的是通用知识（研究课题、读书笔记）。我们的场景更聚焦也更敏感——**那个「原料」就是你自己**。

### 2.2 为什么「关于人的记忆」比通用 Wiki 更难

| 挑战 | 通用 Wiki | 关于人的记忆 |
|------|----------|------------|
| 信息来源 | 客观文档 | 主观对话、行为推断 |
| 正确性验证 | 可溯源 | 需要人确认（"你还在用 React 吗？"） |
| 时效性 | 论文发表后固定 | 持续变化（目标、项目、偏好） |
| 隐私等级 | 通常公开 | 分级敏感（名字 vs 健康状况） |
| 信任建立 | 不需要 | 必须让用户愿意交付信息（核心挑战） |
| 暴露策略 | 全量或按章节 | 必须分级（Agent 不需要知道你的体重） |

### 2.3 设计哲学总结

```
              ┌──────────────────────────────────────────────────────┐
              │                 MNEMO 设计公理                        │
              ├──────────────────────────────────────────────────────┤
              │ 1. 记忆的价值 = 减少用户未来的重复解释次数              │
              │ 2. 最好的交互是用户感觉不到在「填表」                   │
              │ 3. 暴露给 Agent 的记忆量 ∝ 任务相关性，不是记忆总量     │
              │ 4. 过时的记忆比没有记忆更有害                          │
              │ 5. 信任是挣来的，不是要来的                            │
              └──────────────────────────────────────────────────────┘
```

---

## 3. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Interface Layer                                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐  │
│  │   CLI    │  │ MCP Server│  │ REST API │  │ Python SDK│  │ Agent Hook│  │
│  └────┬─────┘  └─────┬─────┘  └────┬─────┘  └─────┬─────┘  └─────┬─────┘  │
└───────┼──────────────┼─────────────┼──────────────┼──────────────┼──────────┘
        │              │             │              │              │
        └──────────────┴─────────────┴──────────────┴──────────────┘
                                     │
                 ┌───────────────────┼───────────────────┐
                 │          Orchestration Layer           │
                 │  ┌─────────────────────────────────┐  │
                 │  │       Memory Router              │  │ ← 根据 Agent 类型/上下文
                 │  │  (决定暴露什么、多少、怎么暴露)    │  │   选择性暴露记忆
                 │  └──────────────┬──────────────────┘  │
                 │                 │                      │
                 │  ┌──────────────┼──────────────────┐  │
                 │  │       Memory Compiler            │  │ ← 将 L2/L3 原始页面
                 │  │  (多级摘要编译：L3→L2→L1→L0)     │  │   编译为高密度摘要
                 │  └──────────────┬──────────────────┘  │
                 │                 │                      │
                 │  ┌──────────────┼──────────────────┐  │
                 │  │       Hook Engine                │  │ ← 插件系统
                 │  │  (pre/post lifecycle hooks)      │  │   生命周期钩子
                 │  └──────────────┬──────────────────┘  │
                 └─────────────────┼─────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │              Core Engine Layer                       │
        │                                                      │
        │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
        │  │ Memory   │  │ Search   │  │   Interaction    │  │
        │  │ Store    │  │ Engine   │  │   Engine         │  │
        │  │ (CRUD)   │  │ (BM25+  │  │   (心理学驱动    │  │
        │  │          │  │  Vector) │  │    的信息获取)   │  │
        │  └────┬─────┘  └────┬─────┘  └───────┬──────────┘  │
        │       │             │                 │              │
        │  ┌────┴─────┐  ┌───┴──────┐  ┌──────┴───────────┐  │
        │  │ Provider │  │ Temporal │  │  Self-Dialogue   │  │
        │  │ Manager  │  │ Engine   │  │  Module          │  │
        │  │ (多LLM)  │  │ (时间    │  │  (与自己对话)    │  │
        │  │          │  │  感知)   │  │                  │  │
        │  └──────────┘  └──────────┘  └──────────────────┘  │
        └──────────────────────────┬──────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │              Storage Layer                           │
        │                                                      │
        │  ┌───────────────────┐  ┌──────────────────────┐    │
        │  │ Wiki Filesystem   │  │ Metadata Store       │    │
        │  │ (Markdown files   │  │ (SQLite)             │    │
        │  │  with frontmatter │  │ - search index       │    │
        │  │  + anchor links)  │  │ - temporal metadata  │    │
        │  │                   │  │ - event log          │    │
        │  │ ~/.mnemo/wiki/    │  │ - compile cache      │    │
        │  └───────────────────┘  └──────────────────────┘    │
        └─────────────────────────────────────────────────────┘
```

---

## 4. 记忆本体论——关于一个人的十个维度

从发展心理学（Erikson）、人格心理学（Big Five）、认知科学和实际 Agent 交互需求出发，定义一个人的十个核心维度：

| # | 维度 | 英文 | 内容示例 | 默认暴露级别 |
|---|------|------|---------|------------|
| 1 | **身份** | identity | 姓名、年龄、所在地、职业、角色 | L0 (始终) |
| 2 | **认知** | cognition | 技能、知识领域、学习风格、思维模式 | L1 (默认) |
| 3 | **价值观** | values | 信念、原则、优先级排序、世界观 | L1 (默认) |
| 4 | **目标** | goals | 短期/长期目标、当前聚焦、计划 | L1 (默认) |
| 5 | **偏好** | preferences | 工具、工作流、沟通风格、审美 | L1 (默认) |
| 6 | **关系** | relationships | 重要的人、团队、组织、社群 | L2 (按需) |
| 7 | **语境** | context | 当前项目、生活状况、挑战 | L1 (默认) |
| 8 | **历史** | history | 过去的决策、教训、成就 | L2 (按需) |
| 9 | **模式** | patterns | 行为习惯、日常惯例、反复出现的倾向 | L2 (按需) |
| 10 | **边界** | boundaries | 隐私等级、不同 Agent 可见范围 | 系统内部 |

### 为什么是这十个维度？

**身份**是 Agent 认识你的入口——"我在跟谁说话"。
**认知+偏好**是 Agent 调整响应方式的依据——"该用什么语言/深度/风格跟你沟通"。
**目标+语境**是 Agent 做正确事情的前提——"你现在在做什么、想要什么"。
**价值观**是 Agent 做出符合你价值取向的决策——"你在乎什么"。
**关系+历史+模式**是深度个性化的来源——"为什么你是你"。
**边界**是安全阀——"哪些信息不该暴露给哪些 Agent"。

### 维度之间的交叉引用

维度不是孤岛。一个目标（"学好 Rust"）可以链接到认知（"当前 Rust 水平：中级"）、偏好（"喜欢系统编程"）、语境（"正在做的项目需要 Rust"）。这些交叉引用通过 wiki anchor 链接实现：

```markdown
<!-- wiki/goals/learn-rust.md -->
---
dimension: goals
temporal: current
created: 2026-03-15
updated: 2026-04-18
links:
  - cognition/programming-languages
  - context/current-projects
  - preferences/tools
---

# 学好 Rust

目标：在 2026 年 Q3 前达到 Rust 生产力水平。

当前水平见 [[cognition/programming-languages#rust|编程语言 - Rust 章节]]。
动机来自 [[context/current-projects#mnemo|Mnemo 项目]]对性能的要求。
```

---

## 5. 多级暴露机制——分层编译模型

这是 Mnemo 最核心的创新：**像编译器一样，把原始记忆编译成多级优化产物**。

```
   ┌─────────────────────────────────────────────────────────────┐
   │                    Memory Pyramid                            │
   │                                                              │
   │     L0: Profile Card     (~200-400 tokens, 始终注入)         │
   │     ┌─────────────────────────────────────────┐              │
   │     │ "Zhang Wei, Senior SWE @ TechCorp.      │              │
   │     │  Python/Rust, AI/ML focus. Direct        │              │
   │     │  communication. Currently building       │              │
   │     │  personal memory system. Values           │              │
   │     │  privacy and first-principles."          │              │
   │     └─────────────────────────────────────────┘              │
   │                          │                                    │
   │     L1: Topic Summaries  (~1000-2000 tokens, 默认加载)       │
   │     ┌─────────────────────────────────────────┐              │
   │     │ ## Technical                             │              │
   │     │ Primary: Python, Rust. Infra: Docker,   │              │
   │     │ K8s. Current: Mnemo memory system.      │              │
   │     │ ## Goals                                 │              │
   │     │ Q3: launch Mnemo. Health: daily walks.  │              │
   │     │ ## Preferences                           │              │
   │     │ Editor: VS Code + Vim. Dark mode.       │              │
   │     │ Communication: direct, no fluff.        │              │
   │     │ ## Context                               │              │
   │     │ Active project: Mnemo. Team: solo.      │              │
   │     └─────────────────────────────────────────┘              │
   │                          │                                    │
   │     L2: Detail Pages     (~500-2000 tokens each, 按需加载)   │
   │     ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐                 │
   │     │Python │ │Rust   │ │Health │ │Mnemo  │ ...              │
   │     │Patterns│ │Journey│ │Goals  │ │Design │                  │
   │     └───────┘ └───────┘ └───────┘ └───────┘                 │
   │                          │                                    │
   │     L3: Archive/Raw      (仅搜索可达)                         │
   │     ┌───────────────────────────────────────────────┐        │
   │     │ 对话日志 | 旧版本 | 历史事件 | 已归档信息       │        │
   │     └───────────────────────────────────────────────┘        │
   └─────────────────────────────────────────────────────────────┘
```

### 编译流程

```
┌────────────┐     ┌────────────────┐     ┌──────────────┐     ┌──────────┐
│ L2/L3 页面 │────▶│ Memory Compiler│────▶│ L1 摘要合集  │────▶│ L0 名片  │
│ (原始记忆)  │     │ (LLM 驱动)     │     │ (每类一段)   │     │ (极简)   │
└────────────┘     └────────────────┘     └──────────────┘     └──────────┘
                          │
                   触发条件：
                   - L2 页面被修改/创建
                   - 定时编译（每日/每周）
                   - 显式 `mnemo compile` 命令
                   - 编译结果缓存，hash 比对避免重复
```

### 编译器 Prompt（核心）

```
You are a memory compiler. Given a collection of detailed personal wiki pages,
generate an ultra-compact summary at the requested level.

Rules:
1. Maximum information density — every word must earn its place
2. Use specific facts, not vague descriptions ("Python 8y, Rust 2y" not "experienced programmer")
3. Prioritize what reduces future AI-user friction
4. Current/active items take precedence over historical ones
5. Flag known contradictions or staleness instead of hiding them
6. Maintain temporal markers: [current], [recent], [historical]

Level 0 (Profile Card): 3-5 sentences that let any AI agent instantly understand
who this person is, what they do, how they communicate, and what they're focused on.

Level 1 (Topic Summary): One paragraph per dimension. Include the most actionable
facts. An AI agent reading this should be able to have a productive conversation
without loading any detail pages.
```

### Agent 消费流程

```
Agent 请求记忆
    ↓
Memory Router 接收请求：
    agent_type = "coding"
    context = "user is asking about database optimization"
    ↓
加载 L0 (始终)                                     ~300 tokens
加载 L1 (始终)                                     ~1500 tokens
    ↓
上下文路由：
    "database optimization" → 搜索 L2 页面 → 匹配：
    - cognition/databases.md                       ~800 tokens
    - context/current-projects.md (含 DB 相关部分)  ~500 tokens
    ↓
Agent 类型路由：
    agent_type="coding" → 加权 Technical 维度
    → 追加 preferences/tools.md 中编码相关部分       ~300 tokens
    ↓
组装输出：
    L0 + L1 + 筛选的 L2 页面                       ~3400 tokens
    ↓
返回给 Agent（注入其 system prompt 或提供为 context）
```

### 为什么不需要重型搜索架构（v1）

| 规模 | 预估页面数 | 推荐方案 |
|------|-----------|---------|
| < 100 页 | 个人用半年 | Index 文件 + 全文 grep 足够 |
| 100-500 页 | 个人用 1-3 年 | BM25（SQLite FTS5）+ Index |
| 500-2000 页 | 深度用户多年 | BM25 + 向量检索 |
| 2000+ 页 | 极端场景 | 接入外部搜索引擎（如 qmd） |

**v1 策略：内置轻量 BM25（SQLite FTS5），预留向量检索接口。** 多级暴露机制本身就大幅减少了搜索需求——Agent 大部分时候只需要 L0+L1，偶尔按维度加载 L2 页面。真正需要全文搜索的场景（"我半年前说过关于 Redis 的什么？"）才触发搜索引擎。

---

## 6. 模块详细设计

### 6.1 Memory Store（记忆仓库）

核心 CRUD 引擎，所有记忆操作的入口。

```python
class MemoryStore:
    """
    Wiki-based memory storage with frontmatter metadata.
    
    Directory structure:
        ~/.mnemo/
        ├── wiki/                      # 记忆 wiki 根目录
        │   ├── _compiled/             # 编译产物（L0, L1）
        │   │   ├── profile-card.md    # L0
        │   │   └── topic-summary.md   # L1
        │   ├── identity/              # 维度目录
        │   │   └── basics.md
        │   ├── cognition/
        │   │   ├── programming.md
        │   │   └── domains.md
        │   ├── goals/
        │   │   ├── career.md
        │   │   └── health.md
        │   ├── preferences/
        │   │   └── tools.md
        │   ├── context/
        │   │   └── current-projects.md
        │   ├── values/
        │   │   └── principles.md
        │   ├── relationships/
        │   │   └── team.md
        │   ├── history/
        │   │   └── career-timeline.md
        │   ├── patterns/
        │   │   └── work-habits.md
        │   └── _archive/              # L3 归档
        │       └── ...
        ├── index.md                   # 全局索引（页面列表+摘要）
        ├── log.md                     # 操作日志（追加写入）
        ├── config.yaml                # 配置文件
        └── mnemo.db                   # SQLite（搜索索引+元数据）
    """
    
    async def create(self, path: str, content: str, metadata: dict) -> Page
    async def read(self, path: str) -> Page
    async def update(self, path: str, content: str, metadata: dict) -> Page
    async def delete(self, path: str, archive: bool = True) -> None
    async def list(self, dimension: str = None, temporal: str = None) -> list[Page]
    async def search(self, query: str, limit: int = 10) -> list[SearchResult]
    async def get_index(self) -> str
    async def get_log(self, n: int = 20) -> list[LogEntry]
```

**原子写入**：所有文件操作使用 `write_tmp → fsync → rename` 模式（与 hermes-agent 的 `_atomic_write_text` 一致），防止进程崩溃导致数据损坏。

**Frontmatter 规范**：

```yaml
---
dimension: cognition          # 所属维度
title: "编程语言"              # 页面标题
temporal: current             # permanent | current | recent | historical
privacy: standard             # public | standard | sensitive | private
created: 2026-03-15T10:30:00
updated: 2026-04-18T14:22:00
sources:                      # 信息来源溯源
  - type: conversation
    date: 2026-03-15
    agent: claude-code
  - type: user_input
    date: 2026-04-01
links:                        # 交叉引用
  - goals/learn-rust
  - context/current-projects
tags: [python, rust, typescript, programming]
confidence: high              # high | medium | low | unverified
---
```

### 6.2 Memory Compiler（记忆编译器）

将 L2/L3 原始页面编译为 L0/L1 高密度摘要。

```python
class MemoryCompiler:
    """
    Compiles raw wiki pages into multi-level summaries.
    
    编译策略：
    1. 收集所有 L2 页面（按维度分组）
    2. 为每个维度生成 L1 段落摘要
    3. 将所有 L1 段落合并，再编译为 L0 Profile Card
    4. 缓存编译结果，content hash 比对避免无变化重编译
    """
    
    async def compile_all(self) -> CompileResult:
        """Full recompile: L2 → L1 → L0"""
    
    async def compile_dimension(self, dimension: str) -> str:
        """Recompile a single dimension's L1 summary"""
    
    async def compile_incremental(self, changed_paths: list[str]) -> CompileResult:
        """Only recompile dimensions affected by recent changes"""
    
    def should_recompile(self) -> bool:
        """Check if any source pages changed since last compile"""
```

**增量编译**：跟踪每个 L2 页面的 content hash。只有当页面内容变化时，才重新编译其所属维度的 L1 摘要。只有当 L1 变化时，才重新编译 L0。

**编译系统 Prompt 详细设计**：

```
SYSTEM: You are Mnemo's memory compiler. Your job is to distill detailed
personal wiki pages into ultra-compact summaries at two levels.

INPUT: A collection of markdown pages about one person, organized by dimension.

LEVEL 1 COMPILATION (per dimension):
- Read all pages in this dimension
- Generate ONE paragraph (80-150 words) capturing the most important facts
- Prioritize: (1) what's current/active, (2) what's unique to this person,
  (3) what would prevent an AI from making mistakes
- Use specific data points, not vague descriptions
- Mark temporal state: use [current] for active items, [recent] for last 30 days
- If a fact is low-confidence, mark it as [unverified]

LEVEL 0 COMPILATION (from all L1 summaries):
- Distill ALL L1 summaries into 3-5 sentences (50-80 words total)
- This must be enough for ANY AI agent to have a productive first interaction
- Structure: Who → What they do → How they communicate → Current focus → Key value
- Example: "Zhang Wei, senior software engineer at TechCorp, specializing in
  AI/ML and distributed systems (Python, Rust). Communicates directly, prefers
  depth over breadth. Currently building Mnemo, a personal memory system.
  Values privacy and first-principles thinking."
```

### 6.3 Memory Router（记忆路由器）

根据请求上下文决定暴露什么记忆、多少记忆。

```python
class MemoryRouter:
    """
    Smart memory exposure based on agent type, context, and privacy rules.
    
    路由算法：
    1. 始终返回 L0 + L1
    2. 解析请求上下文（agent_type, query, platform）
    3. 维度权重加权：coding agent → 加权 cognition, preferences
    4. 上下文搜索：query 关键词 → 匹配 L2 页面
    5. 隐私过滤：根据 platform/agent_type 过滤 sensitive/private 页面
    6. Token 预算控制：确保总输出不超过配置的 max_tokens
    """
    
    async def expose(
        self,
        agent_type: str = "general",     # coding | chat | research | planning | ...
        context: str = "",               # 当前对话上下文/查询
        platform: str = "default",       # 平台标识（用于隐私过滤）
        max_tokens: int = 4000,          # Token 预算
        include_dimensions: list = None, # 强制包含的维度
        exclude_dimensions: list = None, # 强制排除的维度
    ) -> ExposureResult:
        """
        Returns structured memory ready for agent injection.
        
        ExposureResult:
          - profile_card: str      (L0, always)
          - topic_summary: str     (L1, always)  
          - detail_pages: list     (selected L2 pages)
          - total_tokens: int      (estimated token count)
          - metadata: dict         (routing decisions for debugging)
        """
```

**Agent 类型路由权重矩阵**：

```yaml
agent_type_weights:
  coding:
    cognition: 1.5        # 技术能力
    preferences: 1.3      # 工具偏好
    context: 1.2          # 当前项目
    goals: 0.8
    values: 0.5
    relationships: 0.3
    
  chat:
    preferences: 1.3      # 沟通风格
    values: 1.2           # 价值观
    context: 1.0
    goals: 1.0
    cognition: 0.8
    relationships: 0.8
    
  research:
    cognition: 1.5        # 专业知识
    goals: 1.3            # 研究方向
    context: 1.2
    history: 1.0
    preferences: 0.7
    
  planning:
    goals: 1.5            # 目标优先
    context: 1.3          # 当前状况
    values: 1.2           # 决策依据
    patterns: 1.0         # 行为模式
    relationships: 0.8
```

### 6.4 Search Engine（搜索引擎）

轻量级搜索，内置 BM25，可选向量检索。

```python
class SearchEngine:
    """
    Multi-backend search over wiki pages.
    
    v1: SQLite FTS5 (BM25) — 零外部依赖，毫秒级响应
    v2: + 可选向量检索（sentence-transformers + faiss-cpu）
    v3: + 可选外部搜索引擎集成（qmd, Elasticsearch）
    
    搜索范围可配置：
    - 全库搜索
    - 按维度过滤
    - 按时间范围过滤
    - 按隐私等级过滤
    """
    
    async def search(
        self,
        query: str,
        method: str = "bm25",           # bm25 | vector | hybrid
        dimensions: list = None,
        temporal: str = None,            # current | recent | all
        privacy_max: str = "standard",
        limit: int = 10,
    ) -> list[SearchResult]
    
    async def reindex(self) -> None:
        """Rebuild FTS index from wiki files"""
    
    async def embed(self, force: bool = False) -> None:
        """Generate/update vector embeddings (optional)"""
```

**为什么用 SQLite FTS5 而不是自建 BM25：**
- 零外部依赖（Python 自带 sqlite3）
- 经过十几年生产验证的实现
- 支持中文分词（通过 ICU tokenizer 或 jieba + 自定义 tokenizer）
- 查询性能：数千文档搜索 < 5ms
- 与元数据存储共享同一个 SQLite 实例

### 6.5 Provider Manager（提供者管理器）

支持多种 LLM 提供者，Memory Compiler 和 Interaction Engine 依赖此模块。

```yaml
# ~/.mnemo/config.yaml
providers:
  default:
    type: openai_compatible
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: anthropic/claude-sonnet-4
    
  compiler:                        # 编译任务可用更便宜的模型
    type: openai_compatible
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: google/gemini-2.5-flash
    
  local:                           # 可选：本地模型（完全离线）
    type: ollama
    base_url: http://localhost:11434
    model: qwen3:8b
    
  interaction:                     # 交互/对话用高质量模型
    type: openai_compatible
    base_url: https://api.anthropic.com/v1
    api_key: ${ANTHROPIC_API_KEY}
    model: claude-sonnet-4-20250514

# 任务到提供者的映射
task_routing:
  compile: compiler                # 编译用便宜模型
  interact: interaction            # 交互用高质量模型
  self_dialogue: interaction       # 自我对话用高质量模型
  ingest: default                  # 信息摄入用默认模型
  search_rerank: compiler          # 搜索重排用便宜模型
```

```python
class ProviderManager:
    """
    Unified interface to multiple LLM providers.
    Uses litellm under the hood for provider abstraction.
    
    Features:
    - Task-based routing (different tasks → different models)
    - Automatic fallback chain (primary → secondary → local)
    - Token usage tracking per provider
    - Rate limit handling with exponential backoff
    """
    
    async def chat(
        self,
        messages: list[dict],
        task: str = "default",       # compile | interact | ingest | ...
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str
    
    async def structured(
        self,
        messages: list[dict],
        schema: type[BaseModel],     # Pydantic model for structured output
        task: str = "default",
    ) -> BaseModel
```

### 6.6 Temporal Engine（时间引擎）

管理记忆的时间维度——时效性、衰减、事件追踪。

```python
class TemporalEngine:
    """
    Time-aware memory management.
    
    时效等级：
    - permanent: 不衰减（姓名、核心价值观）
    - current:   当前活跃（进行中的项目、本季度目标）
    - recent:    近期（过去 30 天的事件、刚完成的项目）
    - historical: 历史（已完成的项目、旧的目标）
    
    自动衰减规则：
    - current → recent: 如果 30 天未更新且无活跃引用
    - recent → historical: 90 天后自动降级
    - historical 页面移至 _archive/ 目录
    
    事件模型：
    - 事件是跨维度的time-stamped记录
    - 自动关联到相关 wiki 页面
    - 用于编译时的时间上下文注入
    """
    
    @dataclass
    class Event:
        date: datetime
        type: str           # decision | achievement | lesson | change | milestone
        summary: str
        dimensions: list[str]
        entities: list[str]  # 关联的 wiki 页面
        impact: str          # high | medium | low
    
    async def record_event(self, event: Event) -> None
    async def decay_check(self) -> list[DecayProposal]
    async def get_timeline(self, start: date, end: date) -> list[Event]
    async def get_current_context(self) -> str
        """Return temporal overlay for L1: what's active right now"""
```

### 6.7 Hook Engine（钩子引擎）

插件化扩展系统，所有生命周期事件都可挂载自定义逻辑。

```python
class HookEngine:
    """
    Plugin system for extending Mnemo's behavior.
    
    钩子类型：
    - Sync hooks: 同步执行，可修改数据流
    - Async hooks: 异步执行，不阻塞主流程
    - Filter hooks: 接收数据，返回修改后的数据
    - Action hooks: 只执行副作用，无返回
    """

# Hook 定义 — 通过 Python entry_points 注册
HOOK_POINTS = {
    # 记忆生命周期
    "pre_create":     "Filter[Page]",         # 创建前可修改/拦截
    "post_create":    "Action[Page]",         # 创建后通知
    "pre_update":     "Filter[Page, Page]",   # 更新前（old, new）
    "post_update":    "Action[Page]",         # 更新后通知
    "pre_delete":     "Filter[Page]",         # 删除前可拦截
    "post_delete":    "Action[str]",          # 删除后通知
    
    # 编译生命周期
    "pre_compile":    "Filter[list[Page]]",   # 编译前可修改输入
    "post_compile":   "Action[CompileResult]",# 编译后（可用于通知/同步）
    
    # 暴露生命周期
    "on_expose":      "Filter[ExposureResult]",# 暴露前可过滤/修改
    "post_expose":    "Action[ExposureResult]",# 暴露后（可用于审计日志）
    
    # 搜索
    "on_search":      "Filter[str, list[SearchResult]]",  # 搜索结果过滤
    
    # 交互
    "on_interaction":    "Action[InteractionEvent]",  # 交互事件
    "post_interaction":  "Action[InteractionResult]", # 交互结果
    
    # 时间
    "on_decay":       "Filter[list[DecayProposal]]",  # 衰减提议可修改
}
```

**插件示例：自动同步到 Obsidian**

```python
# plugins/obsidian_sync.py
from mnemo.hooks import hook

@hook("post_update", "post_create")
async def sync_to_obsidian(page):
    """Mirror wiki changes to Obsidian vault"""
    obsidian_path = Path("~/Documents/ObsidianVault/Mnemo")
    target = obsidian_path / page.relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page.render_obsidian())  # 转换 anchor → [[wikilink]]
```

**插件示例：暴露审计日志**

```python
@hook("post_expose")
async def audit_log(result):
    """Log what was exposed to which agent"""
    logger.info(
        "Exposed %d tokens to %s (%s): L2 pages=%s",
        result.total_tokens,
        result.agent_type,
        result.platform,
        [p.path for p in result.detail_pages],
    )
```

### 6.8 Interaction Engine（交互引擎）

这是 Mnemo 的「人性化」核心——通过心理学驱动的交互获取、验证和丰富记忆。详见[第 9 节](#9-交互心理学设计)。

### 6.9 Self-Dialogue Module（自我对话模块）

详见[第 10 节](#10-自我对话模块)。

---

## 7. 数据模型与存储

### 7.1 文件系统层（Markdown Wiki）

**选择理由：**
- 人类可读（打开任何编辑器就能看）
- Git 友好（版本历史、diff、分支全免费）
- Agent 友好（LLM 天然理解 Markdown）
- 与 Obsidian 等工具兼容
- 无锁定（纯文本，永远可迁移）

**页面结构**：

```markdown
---
# YAML Frontmatter (机器可读的元数据)
dimension: cognition
title: "编程语言"
temporal: current
privacy: standard
created: 2026-03-15T10:30:00+08:00
updated: 2026-04-18T14:22:00+08:00
content_hash: sha256:a1b2c3d4...
compile_hash: sha256:e5f6g7h8...    # 上次编译时的 hash
sources:
  - {type: conversation, date: 2026-03-15, agent: claude-code}
  - {type: user_input, date: 2026-04-01}
links:
  - goals/learn-rust
  - context/current-projects
tags: [python, rust, typescript]
confidence: high
---

# 编程语言

## Python [primary, 8y]
主力语言。偏好 asyncio + type hints。常用框架：FastAPI, Typer, Pydantic。
不喜欢 Django 的「magic」。
详见 [[cognition/python-patterns|Python 模式和习惯]]。

## Rust [learning, 2y]
正在深入学习，已到中级水平。用于性能敏感场景。 
当前学习路径见 [[goals/learn-rust]]。

## TypeScript [secondary, 5y]
前端和 Node.js 工具链。偏好 strict mode + Zod。
```

### 7.2 SQLite 元数据层

```sql
-- 页面元数据（从 frontmatter 同步）
CREATE TABLE pages (
    path          TEXT PRIMARY KEY,     -- 'cognition/programming.md'
    dimension     TEXT NOT NULL,
    title         TEXT,
    temporal      TEXT DEFAULT 'current',
    privacy       TEXT DEFAULT 'standard',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    confidence    TEXT DEFAULT 'high',
    tags          TEXT                   -- JSON array
);

-- BM25 全文索引
CREATE VIRTUAL TABLE pages_fts USING fts5(
    path,
    title,
    content,
    tags,
    tokenize='unicode61'               -- 支持多语言
);

-- 交叉引用（从 links 字段和 [[]] 语法提取）
CREATE TABLE links (
    source_path   TEXT NOT NULL,
    target_path   TEXT NOT NULL,
    anchor        TEXT,                 -- 可选的锚点
    PRIMARY KEY (source_path, target_path)
);

-- 事件日志
CREATE TABLE events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    type          TEXT NOT NULL,        -- decision | achievement | lesson | ...
    summary       TEXT NOT NULL,
    dimensions    TEXT,                 -- JSON array
    entities      TEXT,                 -- JSON array of wiki paths
    impact        TEXT DEFAULT 'medium'
);

-- 编译缓存
CREATE TABLE compile_cache (
    level         TEXT NOT NULL,        -- 'L0' | 'L1' | 'L1:cognition' | ...
    content       TEXT NOT NULL,
    source_hashes TEXT NOT NULL,        -- JSON: {path: content_hash}
    compiled_at   TEXT NOT NULL,
    PRIMARY KEY (level)
);

-- 向量嵌入（v2+, 可选）
CREATE TABLE embeddings (
    path          TEXT NOT NULL,
    chunk_idx     INTEGER NOT NULL,
    embedding     BLOB NOT NULL,        -- float32 array
    chunk_text    TEXT NOT NULL,
    PRIMARY KEY (path, chunk_idx)
);

-- 操作日志（审计）
CREATE TABLE audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    operation     TEXT NOT NULL,        -- create | update | delete | expose | compile
    path          TEXT,
    agent_type    TEXT,
    platform      TEXT,
    details       TEXT                  -- JSON
);
```

### 7.3 Index 文件（人机共读）

```markdown
<!-- ~/.mnemo/index.md — 自动生成，不要手动编辑 -->
# Mnemo Memory Index

Last compiled: 2026-04-18T14:22:00
Total pages: 23 | Dimensions: 8/10

## identity (2 pages)
- [basics](wiki/identity/basics.md) — 基础身份信息：姓名、年龄、位置、职业
- [roles](wiki/identity/roles.md) — 社会角色：工程师、开源贡献者、创业者

## cognition (4 pages)
- [programming](wiki/cognition/programming.md) — 编程语言：Python(主力), Rust(学习中), TS
- [domains](wiki/cognition/domains.md) — 专业领域：AI/ML, 分布式系统, 开发者工具
- [python-patterns](wiki/cognition/python-patterns.md) — Python 特定模式和偏好
- [learning-style](wiki/cognition/learning-style.md) — 学习方式：先原理后实践，通过构建学习

## goals (3 pages)
- [career](wiki/goals/career.md) — 职业目标：[current] 构建 Mnemo 项目
- [health](wiki/goals/health.md) — 健康目标：[current] 每日步行、改善睡眠
- [learn-rust](wiki/goals/learn-rust.md) — [current] Q3前达到 Rust 生产力水平

## preferences (2 pages)
...

## context (2 pages)
...

## values (1 page)
...

## relationships (1 page)
...

## history (2 pages)
...
```

---

## 8. 接口规范

### 8.1 CLI 接口

```bash
# ============================
# 初始化
# ============================
mnemo init                              # 创建 ~/.mnemo/ 目录结构，启动冷启动向导
mnemo init --import-github              # 从 GitHub profile 导入初始信息
mnemo init --import-config              # 从 dotfiles 推断工具偏好

# ============================
# 记忆 CRUD
# ============================
mnemo create cognition/databases        # 创建新页面（打开编辑器 或 AI 辅助）
mnemo read cognition/programming        # 读取页面内容
mnemo edit cognition/programming        # 编辑页面（编辑器 或 AI 辅助）
mnemo delete history/old-project        # 删除（实际移至 _archive/）
mnemo list                              # 列出所有页面
mnemo list --dimension=goals            # 按维度过滤
mnemo list --temporal=current           # 按时效过滤

# ============================
# 暴露（给 Agent 使用的核心接口）
# ============================
mnemo expose                            # 返回 L0+L1（默认）
mnemo expose --agent-type=coding        # 针对编码 Agent 优化暴露
mnemo expose --context="database opt"   # 基于上下文加载相关 L2 页面
mnemo expose --max-tokens=2000          # Token 预算控制
mnemo expose --format=json              # JSON 格式输出（给 Agent 解析）
mnemo expose --format=system-prompt     # 直接生成 system prompt 片段

# ============================
# 编译
# ============================
mnemo compile                           # 全量编译 L0+L1
mnemo compile --incremental             # 增量编译（只编译变化的维度）
mnemo compile --dimension=cognition     # 只编译指定维度
mnemo compile --dry-run                 # 预览编译结果，不写入

# ============================
# 搜索
# ============================
mnemo search "Rust async patterns"      # BM25 全文搜索
mnemo search "Rust" --dimension=cognition
mnemo search "database" --method=hybrid # BM25 + 向量 (v2+)

# ============================
# 摄入（从外部信息更新 wiki）
# ============================
mnemo ingest --text "今天学了 Tokio runtime 的工作原理"
mnemo ingest --file ./article.md        # 从文件摄入
mnemo ingest --conversation ./chat.json # 从对话记录摄入

# ============================
# 交互
# ============================
mnemo chat                              # 开始对话式记忆收集
mnemo chat --mode=discovery             # 发现模式（随机提问）
mnemo chat --mode=review                # 审查模式（验证旧记忆）
mnemo card                              # 抽一张随机记忆卡片

# ============================
# 自我对话
# ============================
mnemo dialogue                          # 与自己的记忆对话
mnemo dialogue --mode=socratic          # 苏格拉底模式
mnemo dialogue --mode=journal           # 日记模式
mnemo dialogue --mode=mirror            # 镜像模式（AI 扮演你）
mnemo dialogue --mode=timecapsule       # 时间胶囊

# ============================
# 维护
# ============================
mnemo lint                              # 检查 wiki 健康度
mnemo lint --fix                        # 自动修复（补交叉引用、标记过时内容）
mnemo decay                             # 执行时间衰减检查
mnemo stats                             # 统计信息（页面数、维度覆盖率、新鲜度）
mnemo export --format=obsidian          # 导出为 Obsidian vault
mnemo export --format=json              # 导出为 JSON（可读）

# ============================
# 服务模式
# ============================
mnemo serve --mcp                       # 启动 MCP Server
mnemo serve --rest                      # 启动 REST API Server
mnemo serve --mcp --rest                # 同时启动
```

### 8.2 MCP Server 接口

```json
{
  "tools": [
    {
      "name": "memory_profile",
      "description": "Get the user's L0+L1 memory profile. Always call this first.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "agent_type": {"type": "string", "enum": ["coding","chat","research","planning","general"]},
          "context": {"type": "string", "description": "Current conversation context"}
        }
      }
    },
    {
      "name": "memory_search",
      "description": "Search the user's memory wiki for specific information.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "dimension": {"type": "string"},
          "limit": {"type": "integer", "default": 5}
        },
        "required": ["query"]
      }
    },
    {
      "name": "memory_read",
      "description": "Read a specific wiki page by path.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "e.g. cognition/programming"}
        },
        "required": ["path"]
      }
    },
    {
      "name": "memory_update",
      "description": "Update a wiki page with new information learned about the user.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "operation": {"type": "string", "enum": ["append","replace","merge"]},
          "content": {"type": "string"},
          "source": {"type": "string", "description": "Where this info came from"}
        },
        "required": ["path", "operation", "content"]
      }
    },
    {
      "name": "memory_ingest",
      "description": "Process new information about the user and integrate it into the wiki.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "information": {"type": "string"},
          "context": {"type": "string", "description": "Context of how this info was obtained"}
        },
        "required": ["information"]
      }
    },
    {
      "name": "memory_interact",
      "description": "Start an interactive session to learn more about the user.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "mode": {"type": "string", "enum": ["guided","discovery","review"]}
        }
      }
    }
  ]
}
```

### 8.3 Python SDK

```python
from mnemo import Mnemo

# 初始化
m = Mnemo()  # 自动加载 ~/.mnemo/config.yaml

# 暴露记忆（给 Agent 用）
profile = await m.expose(agent_type="coding", context="database optimization")
print(profile.profile_card)       # L0
print(profile.topic_summary)      # L1
print(profile.detail_pages)       # 选中的 L2 页面
print(profile.total_tokens)       # 预估 token 数

# CRUD 操作
page = await m.read("cognition/programming")
await m.update("cognition/programming", content="...", source="user_input")
await m.create("goals/new-project", content="...", dimension="goals")

# 搜索
results = await m.search("Rust async", dimension="cognition")

# 编译
result = await m.compile(incremental=True)

# 摄入
await m.ingest("用户说他最近开始学 Go 了", source="conversation")

# 事件记录
await m.record_event(
    type="decision",
    summary="决定用 Rust 重写搜索引擎核心",
    dimensions=["cognition", "goals"],
)

# 钩子注册
@m.hook("post_update")
async def on_update(page):
    print(f"Updated: {page.path}")
```

### 8.4 与各类 Agent 的对接示例

**Claude Code (.claude/settings.json)**：

```json
{
  "mcpServers": {
    "mnemo": {
      "command": "mnemo",
      "args": ["serve", "--mcp"]
    }
  }
}
```

**OpenAI Codex (AGENTS.md)**：

```markdown
## Personal Memory

This user has a personal memory system (Mnemo). To access it:

1. Run `mnemo expose --agent-type=coding --format=system-prompt` to get user context
2. Use `mnemo search "<query>"` to find specific information
3. Use `mnemo ingest --text "<info>"` to save important discoveries about the user
```

**Hermes Agent (system prompt injection)**：

```python
# 在 prompt_builder.py 中增加一个 provider
def build_mnemo_context(agent_type: str, context: str) -> str:
    result = subprocess.run(
        ["mnemo", "expose", f"--agent-type={agent_type}",
         f"--context={context}", "--format=text"],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout if result.returncode == 0 else ""
```

**通用 Shell 集成（.bashrc / .zshrc）**：

```bash
# 任何 Agent 都可以读取的环境变量方式
export MNEMO_PROFILE=$(mnemo expose --format=compact --max-tokens=500)
```

---

## 9. 交互心理学设计

### 9.1 核心原则

从心理学和行为设计的角度，让用户**愿意**把自己交给 Mnemo：

| 原则 | 心理学基础 | 设计体现 |
|------|-----------|---------|
| **互惠性** | 社会交换理论 | 先给予价值，再请求信息 |
| **渐进披露** | 认知负荷理论 | 不要一次问太多，从简单开始 |
| **自主感** | 自我决定理论 | 用户随时可以跳过、删除、修改 |
| **即时反馈** | 操作性条件作用 | 每次输入后立即展示 wiki 变化 |
| **有趣 > 有用** | 游戏化理论 | 如果只是有用，用户会拖延；有趣才会主动用 |
| **镜像效应** | 自我知觉理论 | 看到自己的结构化画像，本身就有吸引力 |
| **损失厌恶** | Kahneman 前景理论 | "你的记忆健康度只有 47%"比"填更多信息"有效 |

### 9.2 冷启动：五阶段信任建立

```
Phase 1: Quick Profile (2 min)
────────────────────────────────
5 个核心问题，每个有智能默认值。
不是填表，而是简短对话：

  "嗨！我是 Mnemo，你的个人记忆助手。
   我只需要知道几件事就能开始帮你——

   1. 你希望 AI 怎么称呼你？
   2. 你主要做什么工作/研究？
   3. 你目前最关注的事情是什么？
   4. 你喜欢怎样的沟通风格？(直接/详细/轻松)
   5. 有没有什么 AI 经常误解你的地方？

   随时可以跳过任何问题 😉"

→ 输出：L0 Profile Card + 骨架 L1 Index
→ 立即可用。Agent 已经能比从零开始好 10 倍了。

Phase 2: Smart Import (5 min, optional)
────────────────────────────────────────
从已有数字足迹自动推断：

- GitHub README/profile → 技术身份
- dotfiles (.gitconfig, .vimrc, .zshrc) → 工具偏好
- VS Code settings.json → 开发环境偏好
- package.json / pyproject.toml → 常用技术栈
- 浏览器书签导出 → 兴趣领域

每条推断都需要用户确认：
  "从你的 GitHub 看到你主要用 Python 和 Rust，
   最活跃的仓库是 mnemo 和 hermes-agent-fork。
   这准确吗？需要补充什么？"

Phase 3: Guided Conversation (15-30 min, first session)
─────────────────────────────────────────────────────────
自然对话，逐步填充：

  "你提到在做 AI 相关的工作。能多说说吗？
   你的团队是什么样的？你在团队里主要负责什么？"

关键技巧：
- 每问一个问题，先展示已有信息，让用户感到被理解
- 绝不连续问两个以上的问题
- 每收到一条信息，立即展示它在 wiki 中的位置
- 使用「我注意到...」而不是「请告诉我...」

Phase 4: Ambient Learning (continuous)
──────────────────────────────────────
当 AI Agent 通过 MCP 使用 Mnemo 时，Agent 可以反馈：
  
  mnemo ingest --text "用户偏好在终端中用 ripgrep 而不是 grep" \
               --source "observation:coding-session"

这些观察会被审查合并到 wiki 中（可配置自动或需要确认）。

Phase 5: Gamified Discovery (ongoing)
─────────────────────────────────────
让持续的信息收集变得有趣：

- 每日记忆卡片：随机抽一张卡，问一个趣味问题
- 记忆健康度分数：覆盖率、新鲜度、深度的综合打分
- 维度雷达图：哪些维度丰富，哪些还空
- "是否仍然正确？" 周期性验证旧信息
- 连续更新天数 streak
```

### 9.3 记忆卡片机制（Random Card）

```
┌─────────────────────────────────────────────────┐
│  🎴 Daily Memory Card                           │
│                                                  │
│  Category: 💡 Cognition                         │
│                                                  │
│  "如果你要教一个完全不懂编程的人                    │
│   一个你觉得最优雅的编程概念，                      │
│   你会选哪个？为什么？"                            │
│                                                  │
│  [回答] [跳过] [换一张]                           │
└─────────────────────────────────────────────────┘
```

卡片类型池：

| 类型 | 示例 | 触发条件 |
|------|------|---------|
| **探索卡** | "描述一个改变了你工作方式的工具" | 某个维度深度不足 |
| **验证卡** | "你还在用 React 做前端吗？" | 信息超过 90 天未更新 |
| **深入卡** | "你说过喜欢 Rust，最吸引你的是什么？" | 有表层信息但缺深度 |
| **连接卡** | "你的 Rust 学习和 Mnemo 项目有什么关系？" | 两个相关页面无交叉引用 |
| **反思卡** | "回顾上个月，最满意的一个决策是什么？" | 月度反思触发 |
| **想象卡** | "如果你有一整周没有工作，你会做什么？" | 丰富 values/patterns 维度 |

### 9.4 记忆健康度仪表板

```
$ mnemo stats

📊 Memory Health Score: 72/100

  Dimensions Coverage:
    identity     ████████████████████  100%  ✓
    cognition    ████████████████░░░░   80%
    values       ████████████░░░░░░░░   60%  ← needs attention
    goals        ██████████████████░░   90%
    preferences  ████████████████░░░░   80%
    relationships████████░░░░░░░░░░░░   40%  ← low coverage
    context      ████████████████████  100%  ✓
    history      ██████░░░░░░░░░░░░░░   30%  ← low coverage
    patterns     ████████░░░░░░░░░░░░   40%  ← low coverage
    
  Freshness:
    Pages updated <7d:    12/23 (52%)
    Pages updated <30d:   18/23 (78%)
    Stale pages (>90d):    2/23 (9%)
    
  Connections:
    Cross-references:      34 links
    Orphan pages:          1 (history/old-job.md)
    Dense hubs:            cognition/programming (8 inbound links)
    
  Suggestions:
    💡 "relationships" 维度只有 1 个页面。想聊聊你的团队吗？
    💡 "history/old-job.md" 没有被任何页面引用，要归档吗？
    💡 "values/principles.md" 超过 90 天没更新了。还准确吗？
```

---

## 10. 自我对话模块

### 核心理念

Mnemo 知道足够多关于你的信息之后，它可以成为一个**了解你的对话伙伴**——不是通用 AI，而是一个读过你所有记忆的 AI。这开启了几种独特的交互模式：

### 10.1 镜像模式（Mirror Mode）

AI 扮演你。你可以问它任何关于自己的问题，测试它对你的了解程度。

```
用户: 如果有人问我"你为什么选择 Rust？"我会怎么回答？

Mnemo (as you): "主要三个原因：一是我在做的 Mnemo 项目对性能有实际需求，
不是为学而学；二是所有权模型让我觉得很优雅，它把内存安全从运行时检查变成
了编译时保证，这和我一贯重视的'尽早发现问题'原则一致；三是说实话，
写系统级代码本身就让我兴奋。"

用户: 差不多，但我还会提到 Rust 的社区氛围。

Mnemo: 好的，我把这一点加入了 [[cognition/programming#rust]] 的动机部分。
下次我会更完整！
```

**系统 Prompt**：

```
你现在要扮演这个人。基于以下记忆 wiki 内容，用他/她的视角、
语气和思维方式回答问题。不要用第三人称谈论他们——你就是他们。
回答中展示你对他们价值观、偏好和知识的理解。
如果你不确定他们会怎么回答，明确说出你的推测和依据。

[wiki content injected here]
```

### 10.2 苏格拉底模式（Socratic Mode）

用你自己的价值观和目标来挑战你的决策。

```
Mnemo: 你说过健康目标是"每日步行"，但我看到你最近的 context 更新里
连续 5 天都是凌晨 2 点在写代码。你怎么看这两者之间的张力？

用户: ...你说得对。我确实在说一套做一套。

Mnemo: 这不是批评——你的 patterns 里记录了你在项目兴奋期会进入
"地狱周"模式。这次是一样的模式，还是有什么不同？
```

### 10.3 日记模式（Journal Mode）

基于你的当前语境和最近事件，生成反思性问题。

```
Mnemo: 上周你记录了一个事件："决定用 Rust 重写搜索引擎核心"。
现在过了一周了——这个决定执行得怎么样？有没有遇到意外？

用户: 比预想的难。Rust 的异步生态和 Python 很不一样，
特别是 Pin/Unpin 那一套让我头疼。

Mnemo: 记录了。我更新了 [[cognition/programming#rust]] 的难点列表，
也在 [[goals/learn-rust]] 里补充了"异步编程是当前卡点"。
要不要也调整一下 Q3 的时间线预期？
```

### 10.4 时间胶囊模式（Time Capsule Mode）

```
Mnemo: 📦 一个月前的你...

> "正在犹豫 Mnemo 该用 Python 还是 Rust。倾向 Python 快速迭代，
>  但担心性能。" — 2026-03-18

一个月后的现在，你做了怎样的选择？回头看这个纠结有什么感想？
```

### 10.5 发现模式（Discovery Mode）

挖掘你可能没意识到的跨维度连接。

```
Mnemo: 我注意到一个有趣的模式——你的三个看似独立的兴趣之间
可能有深层联系：
  1. 你在学 Rust 的所有权模型
  2. 你关注 AI 安全和对齐
  3. 你的 values 里强调"尽早发现问题"

这三者有一个共同的底层结构：都是关于"在设计阶段就消除一类错误"
而不是在运行时补救。你觉得这个观察准确吗？
```

---

## 11. 安全与隐私

### 11.1 威胁模型

| 威胁 | 风险 | 缓解措施 |
|------|------|---------|
| 本地文件被恶意程序读取 | 高 | 文件系统权限 0700；可选加密静态存储 |
| Agent 过度暴露 | 高 | 隐私分级 + Agent 类型权限矩阵 |
| LLM provider 数据泄漏 | 中 | 可选本地模型替代；敏感字段不发送给 LLM |
| 恶意 MCP Client | 中 | MCP 认证 token；审计日志；操作频率限制 |
| 供应链攻击（恶意插件） | 中 | Hook 沙箱；默认只允许本地插件 |
| Prompt 注入 via 记忆内容 | 中 | 记忆内容注入前扫描（类似 hermes prompt_builder.py 的 `_scan_context_content`） |

### 11.2 隐私分级

```yaml
# 每个页面的 privacy 字段
privacy_levels:
  public:     # 可暴露给任何 Agent/平台（姓名、职业）
  standard:   # 默认级别，可暴露给已配置的 Agent
  sensitive:  # 仅暴露给高信任 Agent（健康、财务、关系细节）
  private:    # 永不暴露给 Agent，仅本地查看（密码提示、极私密日记）

# Agent/平台信任等级
platform_trust:
  local_cli:    sensitive    # 本地 CLI 可访问 sensitive
  claude_code:  standard     # 远程 Agent 默认 standard
  chatgpt:      standard
  web_api:      public       # Web API 只暴露 public
```

### 11.3 静态加密（可选）

```
~/.mnemo/
├── wiki/          # 明文 Markdown（默认）
│   └── ...
└── wiki.enc/      # 加密版本（可选，使用 age 或 GPG）
    └── ...

# 启用加密
mnemo config set encryption.enabled true
mnemo config set encryption.method age
mnemo config set encryption.key_file ~/.mnemo/key.txt
```

---

## 12. 技术选型

### 12.1 核心决策

| 组件 | 选型 | 理由 |
|------|------|------|
| **主语言** | Python 3.12+ | 最丰富的 AI/LLM 生态；LLM 调用是瓶颈而非本地计算；asyncio 已足够快 |
| **CLI 框架** | Typer + Rich | 类型安全、自动帮助文档、美观输出；启动 <200ms |
| **LLM 抽象** | LiteLLM | 100+ provider 统一接口；自动 fallback；无需为每个 provider 写适配器 |
| **结构化输出** | Pydantic v2 | 与 LiteLLM/FastAPI 无缝协作；JSON Schema 自动生成 |
| **数据库** | SQLite（via aiosqlite） | 零依赖；单文件；FTS5 内置 BM25；够快 |
| **MCP Server** | mcp Python SDK | 官方 SDK；stdio + HTTP transport |
| **REST API** | FastAPI (可选) | 仅当需要 REST 时；与 Pydantic 原生集成 |
| **配置管理** | YAML + python-dotenv | 人类可读配置 + 环境变量敏感信息 |
| **测试** | pytest + pytest-asyncio | Python 生态标准 |
| **向量检索(v2+)** | sentence-transformers + faiss-cpu | 可选安装；不是 v1 必需 |
| **包管理** | uv | 极快的依赖解析和安装；替代 pip + poetry |
| **Markdown 解析** | python-frontmatter + markdown-it-py | frontmatter 提取 + Markdown AST 操作 |

### 12.2 性能预算

| 操作 | 目标延迟 | 策略 |
|------|---------|------|
| `mnemo expose` (L0+L1 cached) | < 50ms | 编译缓存 + 文件读取 |
| `mnemo expose` (with L2 routing) | < 200ms | Index 匹配 + 文件读取 |
| `mnemo search` (BM25) | < 30ms | SQLite FTS5 |
| `mnemo compile` (incremental) | 2-5s | LLM 调用（一次） |
| `mnemo compile` (full) | 10-30s | 多次 LLM 调用 |
| `mnemo chat` (per turn) | 1-5s | LLM 调用 + wiki 更新 |
| CLI 冷启动 | < 300ms | 延迟导入；最小化 import chain |

### 12.3 为什么不选 Rust/Go/TypeScript

| 语言 | 不选理由 |
|------|---------|
| Rust | 开发速度慢 3-5x；LLM 生态弱；性能瓶颈在 LLM API 而非本地计算 |
| Go | LLM 库少且不成熟；CLI 框架不如 Typer 好用；缺少 Pydantic 级别的数据验证 |
| TypeScript | qmd 证明了 TS 可行，但 Python 的 LiteLLM/Pydantic/FastAPI 生态链更成熟 |

**预留升级路径**：如果 BM25/向量搜索成为瓶颈（>1000 页），可通过 PyO3 将搜索热路径替换为 Rust 实现，对外接口不变。

---

## 13. 项目结构

```
mnemo/
├── pyproject.toml                    # uv / pip 包定义
├── README.md
├── LICENSE                           # MIT
├── config.example.yaml               # 配置示例
│
├── src/
│   └── mnemo/
│       ├── __init__.py               # 版本 + 顶层导出
│       ├── __main__.py               # python -m mnemo 入口
│       │
│       ├── cli/                      # CLI 层
│       │   ├── __init__.py
│       │   ├── app.py                # Typer app 定义
│       │   ├── commands/
│       │   │   ├── init.py           # mnemo init
│       │   │   ├── crud.py           # create/read/edit/delete/list
│       │   │   ├── expose.py         # mnemo expose
│       │   │   ├── compile.py        # mnemo compile
│       │   │   ├── search.py         # mnemo search
│       │   │   ├── ingest.py         # mnemo ingest
│       │   │   ├── interact.py       # mnemo chat / card
│       │   │   ├── dialogue.py       # mnemo dialogue
│       │   │   ├── lint.py           # mnemo lint / decay / stats
│       │   │   ├── serve.py          # mnemo serve --mcp / --rest
│       │   │   └── export.py         # mnemo export
│       │   └── display.py            # Rich 格式化输出
│       │
│       ├── core/                     # 核心引擎
│       │   ├── __init__.py
│       │   ├── store.py              # MemoryStore (CRUD)
│       │   ├── compiler.py           # MemoryCompiler (L2→L1→L0)
│       │   ├── router.py             # MemoryRouter (暴露路由)
│       │   ├── search.py             # SearchEngine (BM25 + optional vector)
│       │   ├── temporal.py           # TemporalEngine (时间衰减+事件)
│       │   ├── ingestor.py           # Ingestor (外部信息→wiki)
│       │   └── linter.py             # WikiLinter (健康检查)
│       │
│       ├── interaction/              # 交互引擎
│       │   ├── __init__.py
│       │   ├── engine.py             # InteractionEngine
│       │   ├── cold_start.py         # 冷启动向导
│       │   ├── cards.py              # 记忆卡片生成器
│       │   ├── guided_chat.py        # 引导式对话
│       │   └── prompts.py            # 交互 Prompt 模板
│       │
│       ├── dialogue/                 # 自我对话模块
│       │   ├── __init__.py
│       │   ├── mirror.py             # 镜像模式
│       │   ├── socratic.py           # 苏格拉底模式
│       │   ├── journal.py            # 日记模式
│       │   ├── timecapsule.py        # 时间胶囊模式
│       │   ├── discovery.py          # 发现模式
│       │   └── prompts.py            # 对话 Prompt 模板
│       │
│       ├── providers/                # LLM 提供者
│       │   ├── __init__.py
│       │   ├── manager.py            # ProviderManager
│       │   └── config.py             # 提供者配置解析
│       │
│       ├── hooks/                    # 插件系统
│       │   ├── __init__.py
│       │   ├── engine.py             # HookEngine
│       │   ├── decorators.py         # @hook 装饰器
│       │   └── builtin.py            # 内置钩子（日志、index 更新等）
│       │
│       ├── server/                   # 服务层
│       │   ├── __init__.py
│       │   ├── mcp.py                # MCP Server
│       │   └── rest.py               # REST API (FastAPI)
│       │
│       ├── models/                   # 数据模型
│       │   ├── __init__.py
│       │   ├── page.py               # Page, Frontmatter
│       │   ├── events.py             # Event, LogEntry
│       │   ├── exposure.py           # ExposureResult, ExposureRequest
│       │   ├── search.py             # SearchResult
│       │   └── config.py             # MnemoConfig (全局配置)
│       │
│       ├── storage/                  # 存储层
│       │   ├── __init__.py
│       │   ├── filesystem.py         # Markdown 文件读写（原子操作）
│       │   ├── database.py           # SQLite 元数据 + FTS
│       │   ├── index.py              # index.md 生成器
│       │   └── migrations.py         # Schema 迁移
│       │
│       └── utils/                    # 工具函数
│           ├── __init__.py
│           ├── markdown.py           # Frontmatter 解析、anchor 提取
│           ├── tokens.py             # Token 估算
│           ├── hashing.py            # Content hash
│           └── prompts.py            # Prompt 模板管理
│
├── plugins/                          # 示例插件
│   ├── obsidian_sync/
│   │   └── __init__.py
│   └── git_auto_commit/
│       └── __init__.py
│
├── tests/
│   ├── conftest.py
│   ├── test_store.py
│   ├── test_compiler.py
│   ├── test_router.py
│   ├── test_search.py
│   ├── test_temporal.py
│   ├── test_interaction.py
│   ├── test_dialogue.py
│   ├── test_hooks.py
│   ├── test_mcp.py
│   └── test_cli.py
│
└── docs/
    ├── getting-started.md
    ├── configuration.md
    ├── ontology.md                   # 十维度本体论详解
    ├── plugin-guide.md               # 插件开发指南
    └── architecture.md               # 架构细节
```

---

## 14. 开发路线图

### Phase 0: Foundation（1-2 周）

```
[ ] 项目骨架搭建（pyproject.toml, src 目录, CLI 入口）
[ ] 配置系统（YAML + 环境变量）
[ ] ProviderManager（LiteLLM 集成）
[ ] MemoryStore（Markdown CRUD + frontmatter + 原子写入）
[ ] SQLite 元数据层（pages 表 + FTS5 索引）
[ ] 基础 CLI（init, create, read, edit, delete, list, search）
```

### Phase 1: Core Intelligence（2-3 周）

```
[ ] MemoryCompiler（L2→L1→L0 编译，增量编译）
[ ] MemoryRouter（agent_type 路由 + 上下文搜索 + token 预算）
[ ] expose 命令（CLI + 多种输出格式）
[ ] Ingestor（文本/文件/对话 → wiki 页面）
[ ] Index.md 自动生成
[ ] Log.md 追加写入
[ ] TemporalEngine（时效等级 + 自动衰减）
```

### Phase 2: Interaction（2-3 周）

```
[ ] 冷启动向导（五阶段信任建立）
[ ] InteractionEngine（引导式对话收集记忆）
[ ] 记忆卡片机制（每日/随机 card）
[ ] 记忆健康度仪表板（mnemo stats）
[ ] WikiLinter（矛盾检测、孤岛页面、过时内容）
```

### Phase 3: Integration（1-2 周）

```
[ ] MCP Server（stdio + HTTP transport）
[ ] Python SDK（pip install mnemo）
[ ] 与 Claude Code / Codex / Hermes Agent 的集成示例
[ ] Shell 集成（环境变量 / .bashrc 注入）
```

### Phase 4: Self-Dialogue（2 周）

```
[ ] 镜像模式
[ ] 苏格拉底模式
[ ] 日记模式
[ ] 时间胶囊模式
[ ] 发现模式
```

### Phase 5: Polish & Extend（持续）

```
[ ] Hook Engine + 插件系统
[ ] 可选向量检索（sentence-transformers + faiss-cpu）
[ ] Obsidian 同步插件
[ ] Git 自动提交插件
[ ] Smart Import（GitHub, dotfiles, VS Code settings）
[ ] REST API（FastAPI）
[ ] Web UI（可选，未来方向）
[ ] 静态加密（age / GPG）
[ ] 多用户支持（家庭模式）
```

---

## 15. 附录：与现有系统的定位对比

| 系统 | 类型 | 关于「你」？ | 结构化？ | Agent 可用？ | 持续演化？ |
|------|------|------------|---------|------------|----------|
| ChatGPT Memory | Key-Value | 部分 | ❌ 扁平 | ❌ 仅 ChatGPT | 有限 |
| Claude Projects | 上下文窗口 | ❌ | ❌ | ❌ 仅 Claude | ❌ |
| NotebookLM | RAG | ❌ 面向文档 | ❌ | ❌ | ❌ |
| Obsidian + AI | 笔记工具 | 可以 | 手动 | ❌ | 手动 |
| Mem.ai | 笔记 + AI | 部分 | 部分 | ❌ | 部分 |
| Karpathy LLM Wiki | Wiki | ❌ 面向知识 | ✅ | 单 Agent | ✅ |
| Hermes Memory | Agent 记忆 | 部分 | 有限 | ❌ 仅 Hermes | ✅ |
| **Mnemo** | **个人记忆 OS** | **✅ 核心设计** | **✅ 十维度** | **✅ MCP/CLI** | **✅ 编译式** |

### Mnemo 的独特定位

```
                        面向知识 ──────────────────── 面向个人
                           │                            │
                           │    LLM Wiki                │
                           │    NotebookLM              │
                           │              Obsidian+AI   │
                           │                        ┌───────┐
                 被动检索   │                        │ MNEMO │
                     │      │    Mem.ai              └───┬───┘
                     │      │                            │     主动编译
                     │      │         ChatGPT Memory     │
                     │      │              Hermes Memory  │
                     │      │                            │
                     │      └────────────────────────────┘
```

---

## 结语

Mnemo 的本质不是一个更好的笔记工具，也不是一个更好的 RAG 管道。它是一个**关于你的操作系统**——把散落在各个 Agent、各次对话、各种平台中的关于你的碎片信息，编译成一部活的、结构化的、随时可查的百科全书。

每一个 AI Agent 都应该在第一秒就认识你。Mnemo 让这成为可能。
