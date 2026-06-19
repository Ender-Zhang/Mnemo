# Mnemo Memory Module 架构文档

> 版本：2026-06-19 · 对应 `mnemo_memory` 包实现

---

## 概览

Mnemo 的记忆模块是一个**以候选管线为核心的个人记忆系统**。它不是简单的 KV 存储，而是一个有写入验证、质量评估、冲突检测、版本追踪、向量检索和自动维护的完整记忆生命周期引擎。

核心设计原则：
- **模型决策，规则守护**：候选写入和晋升由规则提供质量/安全/冲突护栏，但最终决策权在模型
- **永不直接写入稳定记忆**：所有写入先经过候选管线（candidate pipeline），由 DreamCycle 或显式操作晋升
- **十维本体**：记忆不是无结构文本池，而是 identity / cognition / values / goals / preferences / relationships / context / history / patterns / boundaries 十个维度的结构化知识
- **零外部运行时依赖**：纯 Python + SQLite，embedding 等能力可选插入

---

## 模块拆分

```
mnemo_memory/memory/
├── engine.py        # MemoryEngine 门面，Mixin 组合，不承载业务逻辑
├── base.py          # MemoryStoreAccessMixin，store 读取基础能力
├── learning.py      # 写入管线：candidate → quality → safety → promote/reject
├── recall.py        # 检索管线：QueryPlan → 多路搜索 → RRF 融合 → 联想扩展
├── curation.py      # 内容治理：tombstone、private delete、级联 redaction
├── health.py        # 健康报告：覆盖度、新鲜度、连通性、衰减检查
├── dream.py         # DreamCycle：增量收集 → 维护计划 → 动作执行 → 报告
├── query.py         # QueryPlanner：十维本体路由、RRF 融合、匹配标注
├── quality.py       # 五维质量评分：specificity/personalization/persistence/actionability/verifiability
├── safety.py        # 安全扫描：prompt injection 检测、来源污染分析
├── embedding.py     # 向量检索：可插拔 EmbeddingProvider、cosine similarity、brute-force top-k
├── profile.py       # L0 Profile Card：从 active pages 蒸馏 ~200-400 token 极致浓缩人格卡片
├── snapshot.py      # L1 Snapshot：pointer/hub 编译，KV-cache-friendly 的维度索引
├── associations.py  # 联想网络：wiki links/associations 解析、alias 匹配、孤岛发现
├── cards.py         # 返回形态：page/candidate/session/snapshot/context 的紧凑 card 格式
├── wiki.py          # Wiki materialization：active page → wiki/<dimension>/<slug>.md
├── constants.py     # 共享常量：本体维度、marker 列表、阈值
└── utils.py         # 纯函数工具：normalize、fingerprint、polarity、keywords
```

---

## 事件写入 → 记忆形成 全流程

下图展示一个外部事件（如用户对话、SDK 调用）如何通过候选管线最终成为稳定记忆。

```
                         外部事件
                            │
                   SDK ingest_event() / update()
                            │
                ┌───────────▼────────────┐
                │    事件提取 (Extraction)  │
                │  ┌────────────────────┐ │
                │  │ 启发式规则提取      │ │  偏好/目标 marker 匹配
                │  │ + 可选 Provider 提取 │ │  LLM 辅助结构化抽取
                │  └────────┬───────────┘ │
                │           │             │
                │    facts[] + observations[]
                └───────────┬────────────┘
                            │
              ┌─────────────┴──────────────┐
              │                            │
              ▼                            ▼
    ┌──────────────────┐       ┌───────────────────────┐
    │  observations     │       │  facts                 │
    │  → Working Note   │       │  → write_candidate()   │
    │  (W0 暂存)        │       │                        │
    │  retention:        │       │  ┌──────────────────┐  │
    │   ephemeral → 丢弃 │       │  │ 1. Safety Scan   │  │
    │   memory_candidate │       │  │    prompt injection│  │
    │    → 后续 ingest   │       │  │    来源污染分析    │  │
    └──────────────────┘       │  ├──────────────────┤  │
                                │  │ 2. Quality Score  │  │
                                │  │    五维评分        │  │
                                │  │    specificity     │  │
                                │  │    personalization │  │
                                │  │    persistence     │  │
                                │  │    actionability   │  │
                                │  │    verifiability   │  │
                                │  ├──────────────────┤  │
                                │  │ 3. Dimension归一  │  │
                                │  │    → 十维本体之一  │  │
                                │  ├──────────────────┤  │
                                │  │ 4. 写入 Candidate │  │
                                │  │    status: draft  │  │
                                │  │    或 needs_review │  │
                                │  └──────────────────┘  │
                                └───────────┬───────────┘
                                            │
                                            ▼
                            ┌──────────────────────────┐
                            │   Candidate 候选池         │
                            │   status: draft            │
                            │   status: needs_review:*   │
                            │   (等待 DreamCycle 或      │
                            │    显式 promote 处理)      │
                            └──────────────┬───────────┘
                                           │
                              DreamCycle / promote_candidate()
                                           │
                            ┌──────────────▼───────────┐
                            │  晋升审查 (Promotion Review) │
                            │                            │
                            │  1. 空内容? → reject:empty │
                            │  2. 质量过低? → reject/skip│
                            │  3. 重复检测 → reject +    │
                            │     reinforce existing page │
                            │  4. 冲突检测 → 极性分析    │
                            │     conflict? → mark +     │
                            │     conflict decision card │
                            │  5. 置信度 < 阈值? → skip  │
                            │  6. 全部通过 → promote!     │
                            └──────────────┬───────────┘
                                           │
                            ┌──────────────▼───────────┐
                            │  Page 路由 & 写入          │
                            │                           │
                            │  找同维度+同主题已有 page?  │
                            │  ├─ YES → 版本快照(v)      │
                            │  │        合并内容到已有 page│
                            │  │        page_action:merged│
                            │  └─ NO  → 创建新 page      │
                            │           page_action:created│
                            │                           │
                            │  → 写 promoted_to link    │
                            │  → materialize wiki .md   │
                            │  → 重编译 L1 snapshot      │
                            └──────────────┬───────────┘
                                           │
                                           ▼
                            ┌──────────────────────────┐
                            │   Stable Memory Page       │
                            │   status: active           │
                            │   wiki/<dim>/<slug>.md     │
                            │   ┌────────────────────┐   │
                            │   │  L0 Profile Card   │   │ ~200-400 tokens
                            │   │  (每轮注入)         │   │ 极致浓缩人格卡
                            │   ├────────────────────┤   │
                            │   │  L1 Snapshot        │   │ ~800-1200 tokens
                            │   │  pointers + hubs   │   │ 维度索引+联想热点
                            │   ├────────────────────┤   │
                            │   │  L2 Dimension Pages │   │ 按需路由
                            │   │  (完整主题页)       │   │
                            │   └────────────────────┘   │
                            └──────────────────────────┘
```

---

## 记忆检索 → 召回 全流程

```
                      用户查询 / Agent 意图
                            │
                            ▼
                ┌───────────────────────┐
                │  1. QueryPlanner       │
                │  ┌───────────────────┐ │
                │  │ 原始 query         │ │
                │  │ → lexical routes   │ │  原词/代号/关键词
                │  │ → semantic routes  │ │  语义改写
                │  │ → dimension routes │ │  十维本体匹配
                │  │ → temporal cues    │ │  时间线索
                │  │ → alias expansion  │ │  从 L1 补充
                │  └───────────────────┘ │
                │  输出: MemoryQueryPlan  │
                │  routes: [{route, query}]│
                └───────────┬───────────┘
                            │
                ┌───────────▼───────────┐
                │  2. 多路并行检索        │
                │                        │
                │  每条 route 分别执行:   │
                │  ┌────────────────────┐│
                │  │ FTS5 文本搜索       ││  store.search_memory_pages()
                │  │ (LIKE + 全文匹配)   ││
                │  ├────────────────────┤│
                │  │ Alias 匹配          ││  metadata aliases 反查
                │  ├────────────────────┤│
                │  │ Candidate 搜索      ││  未晋升的草稿也参与
                │  ├────────────────────┤│
                │  │ Vector 近邻搜索     ││  可选，需 EmbeddingProvider
                │  │ (cosine similarity) ││  brute-force top-k
                │  └────────────────────┘│
                └───────────┬───────────┘
                            │
                ┌───────────▼───────────┐
                │  3. RRF 融合 + 去重     │
                │                        │
                │  fuse_ranked_batches() │
                │  k=60, 跨路由合并分数  │
                │  fingerprint 内容去重   │
                │  按 score → confidence  │
                │     → recency 排序     │
                └───────────┬───────────┘
                            │
                ┌───────────▼───────────┐
                │  4. 联想扩展 (Wiki)     │
                │                        │
                │  从种子 page 出发:      │
                │  → memory_links 正向边  │
                │  → memory_backlinks 反向│
                │  → metadata links/assoc │
                │  1 跳扩展，budget 内裁剪│
                └───────────┬───────────┘
                            │
                ┌───────────▼───────────┐
                │  5. 匹配标注           │
                │                        │
                │  annotate_memory_match()│
                │  → dimension_match?    │
                │  → keyword_overlap     │
                │  → staleness warning   │
                │  → tombstone check     │
                └───────────┬───────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │  返回结果               │
                │  matches: [            │
                │    { type, id, title,  │
                │      content, scope,   │
                │      confidence,       │
                │      match_signals,    │
                │      vector_score? }   │
                │  ]                     │
                │  + query_plan metadata │
                │  + recall_policy       │
                └───────────────────────┘
```

---

## 核心子系统详解

### 1. 候选管线 (Candidate Pipeline)

所有记忆写入的唯一入口是 `write_candidate()`，它执行三步防护：

**安全扫描** (`safety.py`)：检测 prompt injection 模式和外部来源污染。扫描结果标注 taint 级别（trusted / external / untrusted）和 risk 级别（low / medium / high）。检测到注入时，候选状态变为 `needs_review:prompt_injection`，不会被自动晋升。

**质量评分** (`quality.py`)：五维加权评分（满分 1.0）：

| 维度 | 权重 | 评估内容 |
|------|------|----------|
| specificity | 0.22 | 是否具体而非泛泛（"Python 8年" vs "会编程"） |
| personalization | 0.18 | 是否个人化而非常识 |
| persistence | 0.20 | 是否稳定持久而非临时状态 |
| actionability | 0.25 | 是否能改善后续服务质量 |
| verifiability | 0.15 | 是否有证据支撑而非猜测 |

加权均分 < 0.5 → `rejected:low_quality`；0.5~0.68 → `needs_review:low_quality`；≥ 0.68 → 正常 `draft`。

**维度归一** (`query.py`)：将维度标签归一到十维本体。`profile` → `identity`，`habit` → `patterns`，`finance` → `preferences` 等。

### 2. 晋升审查 (Promotion Review)

候选从 `draft` 晋升为稳定 page 需经过：

1. **重复检测**：fingerprint 比对 + 搜索已有 page，重复则 `rejected:duplicate` 并 reinforce 已有 page 的置信度
2. **冲突检测**：极性分析（positive/negative marker 匹配），同主题+反向极性 → `needs_review:conflict`，生成 conflict decision card
3. **置信度门槛**：默认 min_confidence=0.7，低于则跳过等待更多证据
4. **主题路由**：找同维度已有主题 page（标题/内容/关键词匹配打分 ≥ 50），有则合并，无则创建新 page

### 3. 冲突解决 (Conflict Resolution)

冲突候选生成结构化 **conflict decision card**：

```json
{
  "kind": "conflict_decision_card",
  "candidate_claim": "用户现在大量使用 Python",
  "page_content": "用户不喜欢 Python",
  "options": [
    {"resolution": "keep_new",  "description": "替换旧记忆"},
    {"resolution": "keep_old",  "description": "拒绝新候选"},
    {"resolution": "keep_both", "description": "两者并存，非矛盾"}
  ]
}
```

确定性降级路径：当候选置信度 ≥ min_confidence 且比冲突页面高 ≥ 0.2 时，自动 `keep_new`。

### 4. DreamCycle 维护循环

DreamCycle 是空闲期记忆整理，三阶段流程：

**收集增量** (`collect_dream_delta`)：
- 未处理的 W0 working notes
- 未解决的候选（draft / needs_review:*）
- 近期变更的 pages
- tombstones
- 健康报告 + 孤岛页面发现
- **新增**：自动关联建议（orphan pages 的关键词重叠分析）

**构建计划** (`build_dream_plan`)：
- 生成 focus_candidates 优先级列表（W0 ingest → draft review → conflict resolve → orphan connect → health → decay）
- 指定 allowed_tools 和预算

**执行** (三种模式)：
- `model_actions`：模型提出的显式工具调用
- `deterministic_fallback`：无模型可用时，自动执行确定性逻辑——晋升高置信候选、拒绝重复/低质量、解决高置信差冲突、W0 ingest、自动链接发现的关联
- `model_required`：仅收集报告，不执行动作

### 5. 记忆金字塔

| 层 | Token 预算 | 生命周期 | 注入时机 |
|----|-----------|----------|----------|
| **L0 Profile** | ~200-400 | 随 active pages 重编译 | 每轮注入 |
| **L1 Snapshot** | ~800-1200 | 随晋升/dream 重编译 | 默认注入 |
| **L2 Pages** | ~500-2000 each | 稳定存储 | 按需路由 |
| **L3 Archive** | 不限 | 历史归档 | 仅搜索可达 |

**L0 Profile Card** (`profile.py`)：从 active pages 按 identity → preferences → goals → context → patterns 优先级蒸馏，每个维度最多 3 条，每条 ≤ 120 chars。输出格式：`[身份] ...\n[偏好] ...\n[目标] ...`

**L1 Snapshot** (`snapshot.py`)：两层结构——
- `pointers`：trigger 词 → `dimension#slug` 路标，帮助模型定位记忆
- `association_hubs`：被多个 page 指向的高价值联想节点

### 6. 向量检索 (Embedding Search)

可选能力，通过 `EmbeddingProvider` Protocol 插入：

```python
class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
```

- `ensure_page_embeddings()`：增量更新——只对 content_hash 变化的 page 重新嵌入
- `vector_search_pages()`：brute-force cosine similarity，纯 Python 实现（无 numpy 依赖）
- 嵌入存储为 `struct.pack` 的 little-endian float32 BLOB
- 在 recall 管线中作为额外 `"vector"` 路由参与 RRF 融合

### 7. 版本历史 (Page Versions)

每次 page 被修改前（promote merge / dream rewrite / dream merge），自动 snapshot 旧版本到 `memory_page_versions` 表。支持 `list_page_versions()` 和 `get_page_version()` 进行历史追溯。

### 8. 联想发现 (Association Discovery)

对健康报告识别的孤岛页面（无 link / backlink / metadata association），执行关键词重叠分析：

- 提取每个 page 的 title + content 关键词
- 孤岛 page vs 非孤岛 page 做 pairwise 交集
- 显著关键词（≥3 chars）重叠 ≥ 2 个 → 建议关联
- DreamCycle 确定性降级时，weight ≥ 0.5 的建议自动建立 link

---

## 存储层

SQLite 单文件 (`storage/sqlite.py`)，schema v4：

| 表 | 用途 |
|----|------|
| `memory_candidates` | 候选记忆池 |
| `memory_pages` | 稳定记忆页 |
| `memory_links` | 页面间关系边 |
| `memory_tombstones` | 选择性遗忘墓碑 |
| `memory_events` | 写入事件溯源 |
| `memory_embeddings` | 向量嵌入存储 |
| `memory_page_versions` | 页面版本历史 |
| `working_notes` | W0 工作笔记 |
| `dream_proposals` | Dream 高风险提案 |

所有表通过 `StateStore` 类的方法访问，WAL 模式 + jitter retry 保证并发安全。

---

## SDK 入口

`MemoryClient` (`sdk/client.py`) 提供完整的高层 API：

| 方法 | 作用 |
|------|------|
| `context(intent)` | 返回 L0 profile + L1 snapshot + 相关 context cards |
| `recall(seed)` | 带 QueryPlan 的语义召回 |
| `search(query)` | 通用搜索（memory / sessions / all） |
| `update(facts, observations)` | 批量写入事实+观察 |
| `ingest_event(text)` | 单事件摄入，自动提取 fact/observation |
| `profile()` | 编译 L0 Profile Card |
| `snapshot(compile)` | 编译/加载 L1 Snapshot |
| `promote_candidate(id)` | 显式晋升候选 |
| `resolve_conflict(id, resolution)` | 解决冲突（keep_new/keep_old/keep_both） |
| `dream_run()` | 执行 DreamCycle |
| `versions(id)` | 查看页面版本历史 |
| `tombstone(id, reason)` | 选择性遗忘 |
| `forget(id)` | 隐私删除（redact 内容，保留最小 hash） |
