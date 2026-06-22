# Mnemo Memory 改进建议

> 版本：2026-06-20 · 范围：`mnemo_memory` 后端 + `webui` 前端 · 关注点：易用性、闭环性、好用性、全自动化、配置便利性，重点在 WebUI

本文是一次外部代码走读后的改进清单。先给整体评估，再按维度展开，每条都尽量带「现状 → 问题 → 建议 → 涉及文件」，最后给一个按优先级排好的路线图。

> **2026-06-20 更新：全部 4 个 P0 项已实现并通过测试。** 见 [§8 P0 落地记录](#8-p0-落地记录)。其中 auth（5.1）按要求采用「删除误导 UI」方案，而非实现校验。下文对应小节已标注 ✅。

---

## 0. 整体评估

Mnemo 的**内核已经很扎实**：候选优先的写入管线、五维质量评分、安全扫描、重复/冲突检测、provenance 溯源、页面版本历史、DreamCycle 维护、十维本体、计划项（goal/todo）、可插拔向量检索——这些是真正有深度的设计，远超普通 KV 记忆库。

短板主要不在「能力」，而在「**把能力暴露给人和让它自己跑起来**」：

| 维度 | 评分 | 一句话结论 |
| --- | --- | --- |
| 闭环性 | ✅ 改善 | 「记忆预览 / Agent 视角」面板 + **语义检索（向量召回）已接通并可配**，召回质量可见可调 |
| 全自动化 | ✅ 改善 | 「本地确定性整理」开关：无 provider 也能自动 promote/去重/拒低质（仍有轮询/常驻等 P1 项待办） |
| 易用性 | ✅ 改善 | 首启引导 + 术语帮助 + forget/tombstone 确认 + **可堆叠 toast** + **计划↔记忆互链**；中英文案仍可统一 |
| 好用性（UI） | ✅ 改善 | 局部刷新 + 结构化视图 + 拆分 + 暗色模式 + **记忆地图（维度分布 + 关联图）** + **Dream 实时反馈** |
| 配置便利性 | ✅ 强 | 删误导 auth、独立 embeddings、**生效配置/来源视图、连通测试、阈值可配**（连同 eval 护栏）均已落地 |
| 可观测性 | ✅ 改善 | **全链路结构化日志**（write/promote/reject/dream/auto-dream/curation/http），此前为零 |
| 质量保障 | ✅ 改善 | **召回 + promote 门 eval 护栏**进 CI，外加可选模型驱动评测脚本 |
| 内核能力 | ✅ 强 | 写入/审核/检索/维护/溯源链路完整，设计有深度 |

下面按维度展开。

---

## 1. 闭环性（Closed-loop）

### 1.1 【P0 · ✅ 已修复】UI 看不到 agent 实际会拿到的记忆

> **已修复**：新增「记忆预览 · Agent 视角」Tab（`PreviewPanel`），调用 `/api/memory/context` 与 `/api/memory/recall`，按 L0 画像（每轮）/ L1 快照路标（默认）/ L2 上下文卡片（按需）/ 联想召回分层展示，并给出粗略 token 估算。

- **现状**：整个系统的产出是喂给 agent 的 `context(intent)` / `recall(seed)`（L0 profile + L1 snapshot + context cards）。但 `webui/src/main.tsx` 里 `callMemory` **从未调用 `context` 或 `recall`**（已 grep 确认）。UI 只展示了 `profile` 的 L0 摘要，没有任何「给定一个查询，看看 agent 会被注入什么」的入口。
- **问题**：这是最关键的闭环断点。用户写入/promote/维护了一堆记忆，却**无法验证「当 agent 问 X 时，到底会召回什么、注入多少 token」**。调优记忆时看不到最终产品，等于盲调。
- **建议**：新增「**记忆预览 / Agent 视角**」面板：
  - 输入一个 intent/query，调用 `/api/memory/context` 和 `/api/memory/recall`，原样展示将被注入的文本块、命中的 pages/candidates、`match_signals`、`retrieval_score`，以及**预估 token 数**。
  - 标注每条命中来自 L0 / L1 / L2 哪一层，让记忆金字塔变得可见。
  - 与搜索 Tab 并列一个「预览」开关即可，后端 API 已经齐全，只差前端接线。
- **涉及**：`webui/src/main.tsx`（新增面板）、`mnemo_memory/interfaces/web.py`（`context`/`recall` 已分发，无需改）。

### 1.2 【P1 · ✅ 已修复】向量/语义检索是否生效不可见、不可配

> **已修复**：接通了此前从未连上的向量检索——新增独立 embeddings 端点配置（`providers/embeddings.py` + `core/config.py` 的 `embeddings_enabled`/`embedding_*`），promote 时增量建索引，召回融合向量路由。设置页有「语义检索 / Embeddings」区（启用 / 端点 / 索引状态 / 重建索引），预览里语义命中标「语义」徽标。默认关，保持离线零依赖。见 §9。

- **现状**：架构文档说 embedding 可插拔并参与 RRF 融合，但 UI 没有任何地方显示「当前是否启用了向量检索」，搜索范围下拉只有「记忆/会话/全部」，没有语义开关；也没有 provider/embedding 的接线入口。
- **问题**：用户分不清自己拿到的是纯 SQLite 关键词召回还是语义召回，召回质量差时无从判断原因。
- **建议**：在搜索面板和维护页显示 embedding 状态（已索引页数 / 未索引页数 / provider 是否配置），提供「重建向量索引」按钮；搜索结果里标出哪些命中来自 `vector` 路由。

### 1.3 【P2 · ✅ 已修复】计划与记忆相互割裂

> **已修复**：记忆详情显示同 scope 的「相关计划」并可跳转到计划页；计划卡片的 scope 变成链接，跳到该 scope 的记忆列表。见 §10。

- **现状**：plans（goal/todo）和 memories 是两个独立 Tab，虽然共享 scope/provenance，但 UI 上没有互相跳转或关联展示。
- **建议**：在记忆详情里展示「相关计划」，在计划详情里展示「相关记忆/来源事件」，让 `source_event_id` 这条已有的链路在 UI 上闭合。

### 1.4 【P2 · ✅ 部分修复】冲突解决与不可逆删除缺少防呆/可回溯

> **已修复（删除防呆部分）**：详情面板的 `forget`（不可逆擦除）和 `tombstone` 现在都要 `window.confirm`，与 hard-delete 对齐。冲突解决的一键回滚仍待办。

- **现状**：`resolveConflict` 的 `keep_new` 会替换旧记忆；页面有版本历史（好），但冲突误判后要去 versions 里手动找。`forget`（私密擦除，不可逆）在详情面板里**直接执行、无任何二次确认**，而 `hard-delete` 反而有 `window.confirm`。
- **问题**：最危险的操作（forget 内容擦除）防护最弱，确认逻辑不一致。
- **建议**：`forget` 和详情面板里的 `tombstone` 也加二次确认（带「输入 reason / 勾选确认」）；冲突解决后给一条「已替换，可在版本历史回滚」的提示并提供一键回滚。
- **涉及**：`webui/src/main.tsx:824 curateSelected`、`855/882 window.confirm`。

---

## 2. 全自动化（Full automation）

### 2.1 【P0 · ✅ 已修复】没有 provider 时永远不会自动 promote

> **已修复**：新增配置 `auto_dream_local_fallback`（默认关，保留原 `provider_required` 安全行为）。开启后，未配置 provider 时自动 Dreaming 会以 `use_provider=False` 跑确定性 fallback（高置信 promote、去重、拒低质、W0 ingest、自动建链）；冲突等高风险动作仍留给人工/模型。设置页新增「本地确定性整理（无需模型）」开关，状态里增加 `last_run_mode`（model/local）。

- **现状**：`AutoDreamScheduler.tick_once` 在 provider 未配置时直接 `_skip(..., "provider_required")`，README 明确「不会退回到本地确定性 promote」。而 `dream.py` 里其实**存在 `deterministic_fallback`**（高置信 promote、重复/低质 reject、解决高置信差冲突、W0 ingest、自动建链），只是手动 Run Dream 才走得到。
- **问题**：开箱即用（没填 API key）时，**每条候选都会永远停在 draft**，除非人工逐条 promote。对「全自动化」诉求这是最大障碍——系统默认是「人工审核台」，不是「自动记忆体」。
- **建议**：增加一个**显式开关**「本地自动整理（无需模型）」，让 auto-dream 在无 provider 时也能跑确定性 fallback（仅做高置信 promote / 去重 / 低质拒绝这类安全动作，冲突和高风险整理仍留给人或模型）。让用户在「安全但停滞」和「自动但确定性」之间自己选。
- **涉及**：`mnemo_memory/interfaces/auto_dream.py:171-173`、`mnemo_memory/memory/dream.py`（fallback 已实现）。

### 2.2 【P1】只有轮询，没有事件/阈值触发

- **现状**：调度器每 60s 轮询、每 180min 才跑一次（`DEFAULT_AUTO_DREAM_POLL_S=60`、间隔默认 180 分钟）。
- **问题**：新写入的候选最坏要等 3 小时才被处理，「自动」感很弱；空跑时又在反复轮询。
- **建议**：加 backlog 阈值触发（如「draft 候选 ≥ N 条立即排一次」）和静默期合并（debounce）。事件驱动比定时更贴近「自动」。

### 2.3 【P1】调度器随 serve 进程存亡，无常驻方案

- **现状**：`AutoDreamScheduler` 是 `serve_http` 里起的 in-process daemon 线程，`serve` 一停，维护全停。没有独立 `auto-dream` 守护进程，也没有 systemd/launchd/cron 指引。
- **建议**：提供独立子命令（如 `mnemo-memory auto-dream --state-dir ...`）或在 README 给 launchd/systemd 配置范例，让「always-on」成立。

### 2.4 【P2】多用户自动维护无方案

- **现状**：auto-dream 按 state-dir 单例、单进程内全局锁。推荐的多用户隔离是「每人一个 state-dir」，但这样需要 N 个 serve/调度器。
- **建议**：要么支持单进程内多 state-dir 轮转维护，要么在文档里明确多租户部署形态。

### 2.5 【P2】缺少「可信来源直通」预设

- **现状**：`ingest_event` 有 `auto_promote` 但默认 false 且仍过门禁；没有按 source 配置信任级别的能力。
- **建议**：允许给某些 `source`/`agent_id` 配置「高置信自动 promote」策略，减少可信链路上的人工审核。

---

## 3. 易用性（Usability）

### 3.1 【P1 · ✅ 已修复】首次启动无引导

> **已修复**：记忆库为空时显示 `OnboardingChecklist`（配置 → 写第一条 → 跑 Dream → 在预览看 agent 拿到什么），可一键跳转、可 dismiss（localStorage 记住）。

- **现状**：全新启动后没有记忆、没有配 provider，UI 直接是 6 个 Tab 的稠密三栏控制台，空状态只有「暂无记忆」。
- **建议**：加一个首启 checklist / 空状态引导：「① 配置 provider（可跳过）→ ② 写入第一条记忆 → ③ 运行一次 Dream → ④ 在预览里看看 agent 会拿到什么」。把现有的 `EmptyState` 升级成带 CTA 的引导卡。

### 3.2 【P1 · ✅ 部分修复】术语门槛高 + 中英混排

> **已修复（术语帮助部分）**：顶栏「术语 / 帮助」按钮打开 `GlossaryDrawer`，一句话解释 candidate/promote/tombstone/forget/dream/snapshot/L0-L1/scope/dimension/provenance/embeddings。中英文案统一仍可继续。

- **现状**：candidate / promote / tombstone / forget / dream / snapshot / L0-L1 / working note / scope / dimension / provenance 等术语无内联解释；按钮中英混排（「保存记忆」与「Add Memory」「Operations Queue」「Run Now」并存）。
- **建议**：① 加一个「术语 / 帮助」抽屉或 hover tooltip，一句话解释每个概念；② 统一文案策略（建议中文为主，首次出现括注英文术语），消除 `Operations Queue`、`Run Now/Run Model` 这类残留英文。

### 3.3 【P1】UID 同时充当「搜索过滤」和「写入 scope」

- **现状**：`uidFilter` 既过滤检索，又决定新写入 fact 的 scope（`scopeFromUidFilter`）。耦合很隐蔽，容易误写到错误 scope。
- **建议**：在写入抽屉里用醒目 banner 明示「本次写入 scope：`user:xxx` / global」，或把「检索 UID」和「写入 scope」拆成两个独立输入。
- **涉及**：`webui/src/main.tsx:654 submitMemory`、`2707 scopeFromUidFilter`。

### 3.4 【P2 · ✅ 已修复】反馈只有单条瞬时 notice

> **已修复**：改为右下角可堆叠 toast（最多 5 条、自动消失、可手动关闭、错误停留更久），连续/批量操作不再互相覆盖。

- **现状**：`notice` 同时只存在一条，连续操作会互相覆盖。
- **建议**：换成可堆叠的 toast，保留最近几条；长耗时操作（Dream）显示进度而不仅是计时。

---

## 4. UI 界面（重点）

### 4.1 【P0 · ✅ 已修复】每次操作触发 13 个请求的全量刷新

> **已修复**：`refresh()` 改为接收 `parts` 切片集合（service/inventory/candidates/maintenance/tombstones/config/plans/profile/health），每个 mutation 只刷新自己影响的切片。例如拒绝候选由 13 个请求降到 2 个（candidates + tombstones），计划操作降到 1 类。初始加载、手动 Refresh 和 Run Dream 仍走全量刷新。

- **现状**：`refresh()` 在一个 `Promise.all` 里并发 12 个接口（health、list×2、dream-status、snapshot、tombstones、provider-config、auto-dream-status、dream-proposals、profile、plan-list、plan-proposals），随后再补 1 个 `health` 共 **13 个请求**；而**几乎每个写操作**（promote/reject/plan-create/tombstone…）成功后都调用 `refresh()`。
- **问题**：单次点按就打 13 个请求，列表整体重渲染、选中态丢失、闪烁，数据量大时明显卡顿；也放大了后端压力。
- **建议**：引入查询缓存（React Query / SWR）做按需失效，或改成**局部刷新 + 乐观更新**（promote 后只更新该条和候选列表，而不是全量）。这是 UI 体验最划算的一处优化。
- **涉及**：`webui/src/main.tsx:478 refresh`，以及所有 `await refresh({ clearNotice: false })` 调用点。

### 4.2 【P1 · ✅ 已修复】2900 行单文件 + 几乎无组件测试

> **已修复（首轮拆分）**：从 `main.tsx`（~3171 行）抽出 `types.ts`（全部类型）、`format.ts`（纯工具/格式化/审核派生/快照/计划 helpers）、`components/shared.tsx`（JsonBlock/StatusBadge/StatusDot/EmptyState）、`components/structured.tsx`（结构化视图）。`main.tsx` 降至 ~2610 行，App 与有状态面板仍在其中。后续可继续抽 `hooks/`（如 `useMemoryApi`）和把更多展示型组件移入 `components/`。

- **现状（原）**：`webui/src/main.tsx` 单文件 2923 行，约 25 个组件 + 工具函数全在里面；测试只有 `candidateFilters`/`providerSettings`/`promotionMessages` 三个纯函数文件。
- **建议**：拆分为 `components/`、`hooks/`（如 `useMemoryApi`）、`api/`、`types.ts`；为关键交互组件补测试。利于维护与后续协作。

### 4.3 【P1 · ✅ 已修复】大量 raw JSON 直接当成品界面

> **已修复**：新增 `components/structured.tsx`——`HealthView`（健康卡片结构化）、`SnapshotView`（pointers/hubs + 元信息）、`LinksView`（关联边）、`KeyValueGrid`（metadata/概要键值表），以及可折叠的 `DeveloperJson`。MaintenancePanel、MemoryDetail、TombstonePanel、OperationsQueue 的 Health/Snapshot/Links/Metadata 已改为结构化展示；原始 JSON 收进 `DeveloperJson`「开发者详情」作为兜底。Dream Status、Tombstones 列表、提案 Before/After 这类任意 diff 仍保留为可折叠 JSON。

- **现状（原）**：高级模式下 Health、Dream Status、Snapshot、Tombstones、Metadata、Links 全是 `JsonBlock`（`JSON.stringify` + `<pre>`）。
- **问题**：这是调试视图不是产品视图，信息密度高但可读性差。
- **建议**：把 health cards、snapshot 的 pointers/hubs、links 渲染成结构化卡片/列表；raw JSON 折叠到「开发者详情」里作为兜底。

### 4.4 【P1 · ✅ 已修复】无暗色模式，颜色未做 token 化

> **已修复**：把手写样式里的硬编码 hex 抽成 CSS 变量（bg/surface/border/text/muted/accent + tint/on-color 令牌），新增 `[data-theme="dark"]` 覆盖与顶栏切换，默认跟随系统、持久化到 localStorage。浏览器内验证过两套主题：浅色保持原样，深色面板/导航/按钮/输入/徽标对比度可读。

- **现状**：`:root { color-scheme: light }`，颜色全是硬编码十六进制（`#f6f8fb`、`#172033`、`#dce3ec`…），没有 CSS 变量主题层，也没有 `prefers-color-scheme`。
- **问题**：开发者工具常开一整天，缺暗色模式体验差；硬编码色值导致后续做主题成本高。
- **建议**：先把颜色抽成 CSS 变量（design tokens），再加暗色主题 + 跟随系统。先 tokens 后主题，顺序很重要。
- **涉及**：`webui/src/styles.css:1`。

### 4.5 【P2 · ✅ 已修复】十维本体 / 关联网络没有可视化

> **已修复**：维护页新增「记忆地图」——十维分布条形图 + 基于 memory_links 的环形关系图（节点大小按度数、颜色按维度、孤岛页虚线高亮）。后端 `memory_graph()` 聚合。见 §10。

- **现状**：dimension 只作为筛选下拉出现；`memory_links` 只在高级模式以 raw JSON 展示。
- **建议**：加「记忆地图」——十维分布热力/计数，以及基于 links/associations 的关系图（孤岛页面高亮）。这能把系统最有特色的结构化知识变得直观，也呼应 health 里的「孤岛发现」。

### 4.6 【P2】可访问性与响应式

- **现状**：抽屉有 `role="dialog"`/`aria-modal`（好），但状态仅靠颜色区分、抽屉无 focus trap、部分 icon-only 按钮缺 `aria-label`、表格无键盘导航；响应式只有 1280/900 两个断点，稠密三栏本质上仍是桌面布局。
- **建议**：状态加图标/文字双编码、补 focus trap 与 aria-label；移动端可作为后续目标（本地工具优先级可低）。

### 4.7 【P2 · ✅ 已修复】运行中无实时反馈

> **已修复**：Dream 运行期间每 2.5s 轮询 dream-status / auto-dream-status，显示「处理中」backlog 条带（候选/笔记/变更页/复核/墓碑）+ 计时。

- **现状**：auto-dream 在后台跑，但 UI 只在手动 Refresh 或操作后更新；手动 Dream 只显示计时，结果跑完才出。
- **建议**：Dream 运行期间轮询 `dream-status`（或 SSE）流式展示进度与中间动作。

---

## 5. 配置便利性（Configuration）

### 5.1 【P0/安全 · ✅ 已修复（删 UI 方案）】auth 配置形同虚设且有误导

> **已修复（采用方案 ②）**：移除前端全部 Bearer token UI——顶栏 token 状态丸、设置页 token 输入框与「清除 Token」按钮、`Authorization` 请求头、`mnemo.authToken` 本地存储；顶栏「Needs token / offline」改为「服务离线」。设置页新增一行明确提示：HTTP API 默认绑定 127.0.0.1 且不鉴权，仅限可信本地网络。后端 `MemoryWebConfig.auth_token` 字段与 CLI `--auth-token` 兼容标记保留（测试仍引用），但行为不变（API 仍开放）。如未来要对外暴露，仍建议改为真正实现校验。

- **现状**：前端有完整的 Bearer token UI（保存、`Authorization` 头、「Token 已设置/未设置」状态丸、设置页输入框），但后端 `web.py` **完全不校验** token（`auth_token` 注释为 "kept for compatibility; HTTP API access is currently open"），CLI `--auth-token` 标注为 "Deprecated... access is open"；顶栏还显示「Needs token / offline」。
- **问题**：UI 暗示了一个并不存在的安全特性，给用户**虚假的安全感**；一旦有人据此把端口暴露到非 localhost，风险很大。
- **建议**：二选一——① 真正实现 Bearer 校验（在 `MemoryHandler` 入口校验 `Authorization`，这是对外暴露的前提）；或 ② 移除前端 token UI 和误导文案，并在文档显著位置写明「仅限可信本地网络」。当前「半实现」状态最糟。
- **涉及**：`mnemo_memory/interfaces/web.py:42/334`、`webui/src/main.tsx:364/1147/2548`、`cli.py:301`。

### 5.2 【P1 · ✅ 已修复】没有「生效配置 / 来源」视图

> **已修复**：`describe_effective_config()` 报告每个字段的生效值与来源（config.json > env/.env > 默认），设置页有可折叠「生效配置 / 来源」表，秘钥只显示是否已配置。见 §10。

- **现状**：配置来源有 CLI 参数 > `config.json` > `.env` > 默认，外加一堆 `MNEMO_MEMORY_*` 环境变量；优先级文档有写，但 UI 无法看出「此刻到底用的是哪个值、来自哪里」。
- **建议**：设置页加「生效配置」只读区，显示每个关键项的当前值与来源（CLI/config.json/.env/default），排查「为什么没生效」会快很多。

### 5.3 【P1 · ✅ 已修复】provider 无连通测试

> **已修复**：provider/embeddings 各加 `ping()` + `test-provider`/`test-embedding` 端点，设置页「测试连接」按钮显示延迟或错误（未配置时直接报告，不发网络）。见 §10。

- **现状**：保存 base_url/model/key 后没有「测试连接」，只有真正跑 Dream 失败时才暴露问题。
- **建议**：加「测试」按钮，发一个最小请求验证 model 可达，并把结果回显在设置页。

### 5.4 【P2 · ✅ 已修复】质量/置信度阈值写死，不可调

> **已修复**：质量写入/草稿阈值 + promote 默认置信度纳入 config（env / config.json / 设置页「调参」块），写入时按配置评分；与 §3 eval 护栏配套调参。见 §10。

- **现状**：`QUALITY_WRITE_THRESHOLD=0.68`、`QUALITY_DRAFT_THRESHOLD=0.5`、五维权重（0.22/0.18/.../0.15）、`min_confidence=0.7` 都硬编码在 `quality.py`/`learning.py`。
- **建议**：把这些纳入 `config.json` 并在设置页暴露（高级），让不同领域可以调松/调严 promote 门槛，而不必改代码。
- **涉及**：`mnemo_memory/memory/quality.py:9-29`。

### 5.5 【P2】provider 仅一个写死选项，无预设

- **现状**：provider 下拉只有 `openai-compatible`。
- **建议**：给常见后端（OpenAI / Azure / 本地 Ollama / vLLM 等）预设，一键填好 base_url/model 模板，降低填错率。

---

## 6. 优先级路线图

按「影响 ÷ 成本」排序，建议如下推进。

### P0 — ✅ 已全部完成（2026-06-20）
| # | 项 | 价值 | 状态 |
| --- | --- | --- | --- |
| 1.1 | 「记忆预览 / Agent 视角」面板（接 `context`/`recall`） | 补上最关键的闭环：看见 agent 实际拿到什么 | ✅ 已实现 |
| 2.1 | 无 provider 时可选「本地确定性自动整理」 | 让「全自动化」开箱即真的能自动 | ✅ 已实现（默认关，可在设置开启） |
| 4.1 | 局部刷新替代 13 请求全量 `refresh()` | UI 流畅度最划算的一处 | ✅ 已实现（parts 切片） |
| 5.1 | 修复 auth「半实现」 | 消除虚假安全感 | ✅ 已删除误导 UI + 加可信网络提示 |

### P1 — 紧接着做
| # | 项 |
| --- | --- |
| 1.2 | 向量检索状态可见 + 重建索引入口 |
| 2.2 / 2.3 | backlog 阈值触发；独立常驻 auto-dream 方案 |
| 3.1 / 3.2 / 3.3 | 首启引导；术语帮助 + 统一中英文案；UID/scope 解耦提示 |
| 4.2 ✅ / 4.3 ✅ / 4.4 | 拆分 `main.tsx`（已完成首轮）；结构化展示替代 raw JSON（已完成）；颜色 token 化 + 暗色模式（待办） |
| 5.2 / 5.3 | 「生效配置/来源」视图；provider 连通测试 |

### P2 — 体验打磨
| # | 项 |
| --- | --- |
| 1.3 / 1.4 | 计划↔记忆互链；forget/tombstone 二次确认 + 冲突回滚 |
| 2.4 / 2.5 | 多租户自动维护；可信来源直通预设 |
| 3.4 | 可堆叠 toast |
| 4.5 / 4.6 / 4.7 | 十维/关联网络可视化；a11y & 响应式；Dream 运行时实时反馈 |
| 5.4 / 5.5 | 阈值可配；provider 预设 |

---

## 7. 附录：低成本快赢（Quick wins）

这些改动小、见效快，可以穿插着做：

- ~~顶栏「Needs token / offline」改为准确文案~~ ✅ 已随 5.1 改为「服务离线」。
- `forget` 和详情面板 `tombstone` 补 `window.confirm`，与 hard-delete 对齐。（`main.tsx`，见 1.4）
- 空状态文案加一个 CTA 按钮（「写入第一条记忆」直接打开抽屉）。
- 写入抽屉顶部明示当前写入 scope。
- 设置页 provider 区加一行「最后一次 Dream 是否成功 / 最近错误」（`auto_dream_status` 已有 `last_error`，接出来即可）。
- README/导览补一句：默认无 provider 时系统是「人工审核台」，需要模型或开启本地自动整理才会自动 promote——澄清开箱即用的预期。

---

## 8. P0 落地记录

> 2026-06-20 实现。全部改动随 `npm --prefix webui run build` 重新构建并提交了 `web_assets`。验证：`python3 -m unittest discover -s tests` 共 63 项通过（含新增 `test_auto_dream_scheduler_runs_local_fallback_without_provider`）；`node --test webui/tests/*.test.ts` 共 7 项通过；`tsc --noEmit` 类型检查通过；`context`/`recall`/`local_fallback` 经 HTTP dispatch 端到端冒烟通过。

| P0 | 改动摘要 | 主要涉及文件 |
| --- | --- | --- |
| 1.1 记忆预览 | 新增「记忆预览 · Agent 视角」Tab，分层展示 L0/L1/L2 + 联想召回 + token 估算 | `webui/src/main.tsx`（`PreviewPanel`、`runPreview`、新类型）、`webui/src/styles.css` |
| 2.1 本地自动整理 | 新增 `auto_dream_local_fallback` 配置；无 provider + 开关开启时跑确定性 Dream；状态加 `last_run_mode` | `core/config.py`、`sdk/client.py`、`interfaces/auto_dream.py`、`interfaces/web.py`、`webui/src/providerSettings.ts`、`webui/src/main.tsx`、`tests/test_web_service.py` |
| 4.1 局部刷新 | `refresh({ parts })` 切片刷新，21 处 mutation 改为按需刷新 | `webui/src/main.tsx` |
| 5.1 删除误导 auth UI | 移除前端 token 状态丸/输入框/请求头/本地存储，加可信网络提示；后端兼容字段保留 | `webui/src/main.tsx` |

**2026-06-20 续：P1 中的 4.2（拆分 `main.tsx` 首轮）与 4.3（结构化替代 raw JSON）已完成**，新增 `webui/src/types.ts`、`format.ts`、`components/shared.tsx`、`components/structured.tsx`；source-contract 测试改为读整棵 webui src 树。

剩余 P1/P2 项（向量检索状态、首启引导、术语帮助、暗色模式 + 颜色 token 化、生效配置视图、provider 连通测试、阈值可配、事件触发/常驻调度、`hooks/` 进一步拆分等）仍按 §6 路线图推进。

---

## 9. 第三轮落地记录（语义检索 / 评估 / 可观测性 / 易用性）

> 2026-06-20 实现，四项各一个独立 commit。验证：`python3 -m unittest discover -s tests` 共 72 项通过（含新增 embeddings / eval / logging 测试）；`node --test webui/tests/*.test.ts` 7 项通过；`tsc --noEmit` 通过；embeddings/日志经 HTTP 冒烟；暗色与浅色主题在浏览器内核对。

| 项 | 改动摘要 | 主要涉及 |
| --- | --- | --- |
| 语义检索（接通向量召回） | 独立 embeddings 端点配置 + `embed_texts` provider；promote 增量建索引；召回融合向量路由；设置页配置 + 重建索引 + 预览「语义」徽标 | `core/config.py`、`providers/embeddings.py`、`sdk/client.py`、`memory/learning.py`、`interfaces/web.py`、`webui/src/*`、`tests/test_embeddings.py` |
| 质量评估 eval | 召回 recall@k + promote 门决策的确定性 golden 集（进 CI）+ 可选模型驱动脚本 | `mnemo_memory/eval/`、`tests/test_eval.py`、`scripts/eval_model.py` |
| 可观测性 | `core/log.py` 结构化日志 + 全链路埋点（candidate/promote/reject/dream/auto-dream/curation/http） | `core/log.py`、`memory/learning.py`、`memory/dream.py`、`interfaces/auto_dream.py`、`memory/curation.py`、`interfaces/web.py`、`tests/test_logging.py` |
| 易用性 | forget/tombstone 二次确认、首启引导、术语帮助抽屉、暗色模式（颜色 token 化 + 跟随系统 + 切换） | `webui/src/main.tsx`、`webui/src/styles.css`、`webui/src/components/Glossary.tsx`、`webui/src/components/Onboarding.tsx` |

**多用户隔离：单租户 + 软多租户（A 定调 + B 落地）。**
- **硬隔离（A）**：Mnemo 仍是“每个 `state-dir` 单租户”，互不信任的用户各用一个 `state-dir`（真隔离）。护栏：绑定非回环地址时 `serve` 打印 `WARNING`（`insecure_bind_warning`，含测试）。
- **软多租户（B，已落地）**：共享一个库时用 `scope=user:<uid>` 区分；`search`/`recall`/`context`（含 MCP）新增可选 `uid`，**传了就把召回限定到该用户**（`scope_matches_uid`，post-filter 覆盖 pages/candidates/alias/vector/plan/associated 全部来源，不含 global）。agent 带 `uid` 即可只召回自己用户的记忆。WebUI 顶部「当前用户 (UID)」统一控制写入/搜索/预览/召回归属。仍非权限边界（无鉴权、admin 可见全部、可不传 uid）——互不信任用户仍走 A。已加 `tests/test_recall_scope.py`，README「安全与多用户隔离」专节已更新。

## 10. 第四轮落地记录（配置 / 反馈 / 互链 / 可视化）

> 2026-06-20 实现，7 项各一个独立 commit。验证：`python3 -m unittest discover -s tests` 共 82 项通过（新增 tuning / connectivity / effective-config / memory-graph 测试）；`node --test webui/tests/*.test.ts` 7 项通过；`tsc --noEmit` 通过；记忆地图与暗色主题在浏览器内核对（7 页→6 维度条 + 7 节点 + 5 边 + 孤岛虚线）。

| 项 | 改动摘要 | 主要涉及 |
| --- | --- | --- |
| 5.4 阈值可配 | 质量写入/草稿阈值 + promote 默认置信度纳入 config，写入时按配置评分 | `core/config.py`、`memory/quality.py`、`memory/engine.py`、`memory/learning.py`、`sdk/client.py`、`interfaces/web.py`、`tests/test_tuning.py` |
| 5.3 连通测试 | provider/embeddings `ping()` + test 端点 + 设置页「测试连接」 | `providers/openai.py`、`providers/embeddings.py`、`sdk/client.py`、`interfaces/web.py`、`tests/test_connectivity.py` |
| 5.2 生效配置视图 | `describe_effective_config()` 报告值+来源 + 设置页表 | `core/config.py`、`sdk/client.py`、`interfaces/web.py`、`tests/test_effective_config.py` |
| 3.4 可堆叠 toast | 单 notice → 右下角 toast 栈（自动消失/可关闭） | `webui/src/main.tsx`、`webui/src/styles.css`、`webui/src/types.ts` |
| 4.7 Dream 实时反馈 | 运行期轮询 dream-status + 「处理中」backlog 条带 | `webui/src/main.tsx`、`webui/src/format.ts` |
| 1.3 计划↔记忆互链 | 记忆详情「相关计划」+ 计划卡 scope 跳记忆 | `webui/src/main.tsx`、`webui/src/styles.css` |
| 4.5 维度/关联可视化 | `memory_graph()` 聚合 + 「记忆地图」分布条 + 关系图 | `sdk/client.py`、`interfaces/web.py`、`webui/src/components/MemoryMap.tsx`、`tests/test_memory_graph.py` |

剩余建议里仍待办：事件触发 + 常驻调度（2.2/2.3）、可信来源直通（2.5）、中英文案统一（3.2 文案部分）、a11y & 响应式（4.6）、provider 预设（5.5）、冲突解决一键回滚（1.4 剩余部分）。

---

*P0 全部，P1/P2 中的语义检索 / 评估 / 可观测性 / 易用性 / 配置（生效视图·连通测试·阈值）/ 反馈（toast·Dream 实时）/ 计划↔记忆互链 / 维度可视化均已落地并通过测试；多用户隔离已定为单租户并加护栏。其余仍为建议；告诉我接着推进哪项即可。*
