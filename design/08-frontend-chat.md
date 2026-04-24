# Frontend Chat Experience

> 单一持续聊天框、流式动作、Artifact/Decision/Learning cards 和前端 API。

## 23. 用户世界入口前端设计

用户侧不要暴露 Mission、任务管理器、记忆管理器或运维面板。对用户而言，Mnemo 永远只有一个入口：**一个持续存在的聊天框**。用户在这里派活、追问、改方向、确认外发、接收产物、搜索过去、设置偏好；系统在背后用 Mission、Artifact、Decision、Watch 和 Memory 维持状态。

一句话：**用户只和 Mnemo 说话，Mnemo 负责把话变成行动。**

### 23.1 第一性原则

1. **单入口**：所有交互从同一个聊天框开始，也回到同一个聊天框。
2. **连续性优先**：用户说“继续”“刚才那个”“换成表格”时，系统必须恢复上下文，而不是要求用户重新解释。
3. **行动可见但不暴露内部**：用户看到“正在搜索/读取/修改/等待确认”，不看到 prompt、规则、trace 或内部状态机。
4. **产物内嵌在对话里**：文档、diff、表格、消息草稿是聊天里的可操作卡片，不是另一个应用。
5. **确认以内联卡片发生**：外发、删除、付款、发布、权限变更等高风险动作，直接在对话里给出确认卡。
6. **学习自然发生**：用户的补充、修改、拒绝、确认和格式偏好会沉淀为记忆/技能，但不要求用户管理记忆。
7. **低频设置隐藏**：授权、连接应用、数据控制可以从聊天进入，但不占据主体验。

### 23.2 用户可见模型：一条对话流

```text
Mnemo Chat
  ├─ Message Stream        # 用户和 Mnemo 的持续对话
  ├─ Universal Composer    # 唯一输入框：文本/语音/文件/链接/app mention
  ├─ Inline Action Cards   # 正在做什么、做到哪、卡在哪
  ├─ Inline Artifacts      # 文档、表格、diff、消息草稿、计划
  ├─ Inline Decisions      # 需要用户确认的动作
  ├─ Inline Recall         # 从过去找回上下文并继续
  └─ Inline Learning Chips # “以后按这个来”的可撤销学习
```

Mission 是内部执行信封，不是用户导航对象。用户不需要知道“当前是哪一个 Mission”，也不需要手动切换任务。前端只维护一个当前对话焦点；后台的 `MissionStore` 负责判断这句话是继续当前任务、新开任务、分叉任务，还是只是普通问答。

### 23.3 第一屏：只有聊天

第一屏就是一条持续对话和底部输入框，不做 dashboard。

```text
┌─────────────────────────────────────────────────────┐
│ Mnemo                                               │
│                                                     │
│ Mnemo  我在继续整理 Mnemo 技术方案。                 │
│        当前正在把前端收敛成单一聊天入口。             │
│        [查看动作] [暂停]                             │
│                                                     │
│ You    不是在记忆上啊，用户派活时偏好就记录下来了。   │
│                                                     │
│ Mnemo  明白。我会把学习点放回派活过程，而不是做成     │
│        记忆管理 UI。                                │
│        [文档草稿 · 已更新] [查看 diff]               │
│                                                     │
│ ─────────────────────────────────────────────────── │
│ [ 继续改 / 发链接 / 上传文件 / @github ...       ▷ ] │
└─────────────────────────────────────────────────────┘
```

系统主动事项也进入同一条对话，但必须克制：
- **需要决定**：以内联 Decision Card 出现。
- **正在执行**：用一行状态卡，不刷屏。
- **值得知道**：用低频摘要消息，用户可忽略。
- **已静默处理**：默认不打扰，只在用户问“最近做了什么”时展示。

### 23.4 Universal Composer：唯一交互控件

Composer 支持文本、语音、文件、截图、链接、app mention、选中内容转交给 Mnemo。用户不选择 intent，也不选择工具；模型裁决这句话意味着什么。

| 用户说法 | 内部解释 | 用户看到 |
|----------|----------|----------|
| “这是什么意思？” | Ask | 直接回答 |
| “帮我改完并验证” | 创建或继续 Mission | 流式动作 + 结果 |
| “换成表格” | redirect current focus | 当前产物更新 |
| “刚才那个发给 Alex” | resolve artifact + external action | 发送确认卡 |
| “以后都按这个格式” | learning candidate | 可撤销学习 chip |
| “上次那份继续改” | recall + continue/fork | 找回上下文后继续 |
| “以后每天早上看一下” | Watch/Cron | 关注项确认 |

前端可以展示轻量理解 chip，例如 `正在继续当前草稿 · 生成表格 · 外发前确认`。这些 chip 是可点开的纠错入口，不是必填流程。

### 23.5 内部 Mission：隐藏的执行信封

Mission 只服务三个后台需求：
- **持久化**：任务可以跨轮、跨天、跨设备继续。
- **可恢复**：崩溃、刷新、断网后能恢复到上一步。
- **可审计**：每次工具调用、确认、产物变化都能回放。

用户侧不展示 Mission 列表。一个 Mission 的状态会被投影成聊天里的简短状态：

| 内部状态 | 聊天里的表达 |
|----------|--------------|
| `queued` | “已接下，马上开始。” |
| `understanding` | “我需要确认一个约束。” |
| `working` | “正在处理...” |
| `waiting` | “等你确认后继续。” |
| `blocked` | “缺少权限/信息，卡在这里。” |
| `ready` | “草稿好了。” |
| `done` | “已完成。” |
| `cancelled` | “已取消，状态已保留。” |

用户仍然可以用自然语言控制内部 Mission：`暂停这个`、`继续`、`别做了`、`另起一版`、`明天再提醒我`。这些不是导航动作，而是普通聊天指令。

### 23.6 Action Stream：对话里的动作展示

参考 OpenClaw 的 durable task flow 和 Hermes 的 streaming/TUI，Mnemo 要让行动可见，但不能把日志倾倒给用户。动作展示应是聊天消息的一部分。

```ts
type ChatEvent =
  | {type: "conversation.hydrated"; summary: string}
  | {type: "turn.started"; turnId: string; inputSummary?: string}
  | {type: "assistant.delta"; text: string}
  | {type: "assistant.message"; text: string; final?: boolean}
  | {type: "status.updated"; text: string; tone?: "working" | "waiting" | "blocked" | "done"}
  | {type: "plan.updated"; steps: PlanStep[]; currentStepId?: string}
  | {type: "action.started"; action: ActionCard}
  | {type: "action.progress"; actionId: string; text: string; percent?: number}
  | {type: "action.completed"; actionId: string; outcome: "success" | "failed" | "skipped"; summary: string}
  | {type: "artifact.delta"; artifactId: string; patch: ArtifactPatch}
  | {type: "artifact.card"; artifact: ArtifactCard}
  | {type: "decision.card"; decision: DecisionCard}
  | {type: "learning.chip"; item: LearnedChip}
  | {type: "source.attached"; source: SourceCard};
```

默认展示层级：

| 层级 | 默认行为 | 例子 |
|------|----------|------|
| Status line | 总是显示，单行 | `正在比较 4 个来源` |
| Action cards | 可折叠 | `搜索 web`、`读取 PR`、`更新文档` |
| Artifact cards | 总是可见 | `技术方案草稿 · v3` |
| Evidence drawer | 用户点开 | 来源链接、文件片段、命令摘要 |
| Debug trace | 不在普通前端 | RunLedger 原始事件只给 CLI/harness |

流式规则：
- `assistant.delta` 只用于用户可读内容，不展示 chain-of-thought。
- 前端重连时用 `sinceEventId` 补齐事件；对话流必须可断线续传。
- 新一轮输入先产生 `turn.started`，后台恢复当前对话焦点后再输出动作。
- 工具原始输出不进前端，只显示摘要；完整内容进 RunLedger。
- 长产物用 `artifact.delta` 更新，用户可以边生成边说“这里改一下”。
- 后台任务不刷屏，默认只在状态变化、需要确认、完成时发消息。

### 23.7 Artifact：聊天里的可操作产物

Mnemo 的重要输出不能埋在长气泡里，而应成为对话里的 Artifact Card。桌面端可以点开右侧预览，移动端进入全屏预览，但入口仍来自当前聊天。

| 类型 | 例子 | 卡片操作 |
|------|------|----------|
| Doc | 方案、报告、总结、PR review | 查看、继续改、导出、比较版本 |
| Message | 邮件、Slack、评论、短信 | 预览、改语气、发送 |
| Plan | 行程、学习计划、项目计划 | 调整、排期、转关注 |
| Code Change | diff、patch、测试结果 | 查看 diff、应用、回滚、验证 |
| Table | 对比表、预算、候选清单 | 排序、筛选、导出 |
| Decision Brief | “该不该买/发/做” | 看证据、选择方案 |

用户对产物的操作也通过聊天表达：`第三段再严谨点`、`导出 PDF`、`把这个发给 Alex`、`基于这个建个模板`。前端把选中的 artifact/span 作为隐式上下文传给 Composer。

### 23.8 Decision：确认卡也是聊天消息

确认不是弹窗，也不是设置页。它是对话中的一张合约卡，必须说清楚：

1. 要做什么。
2. 为什么现在做。
3. 会暴露什么信息或修改哪里。
4. 错了能否撤销。

```text
要发送这条 GitHub 评论吗？

动作：把这段 review comment 发到 PR #184。
原因：CI 已通过，但还有一个边界条件需要提醒。
会暴露：你的 GitHub 身份和评论正文。

[编辑] [发送] [不发送]
```

权限策略保持轻量：

| Risk | 对话行为 |
|------|----------|
| `read` | 默认执行，只显示必要来源 |
| `write` | 本地可信 workspace 默认执行，保留可撤销记录 |
| `external` | 必须 Decision Card 或 standing authority |
| `admin` | 需要显式授权入口，不在普通对话中静默执行 |

### 23.9 Recall：用聊天找回过去

Recall 不是单独的记忆浏览器。用户直接在聊天里问：

```text
“上次我们怎么决定 agent skills 的？”
“把上次那份前端方案继续改成更产品化”
“找一下我之前让你追踪的 OpenClaw 变化”
```

系统返回的是可继续行动的结果卡：

| 结果类型 | 用户动作 |
|----------|----------|
| Past Work | 继续、另起一版、比较 |
| Artifact | 打开、复用、改写、发送 |
| Decision | 查看当时理由、撤销、复用 |
| Knowledge | 引用、更新、忘记 |

默认不展示原始长会话，只展示摘要、来源和可操作入口；用户要求证据时再展开。

### 23.10 学习偏好：发生在派活过程中

用户不是在“管理记忆”，而是在派活过程中自然表达偏好。前端只在对话里给出轻量反馈。

| 用户行为 | 系统观察 | 可能沉淀 |
|----------|----------|----------|
| “别列这么多选项，直接推荐” | explicit correction | 沟通偏好 |
| 用户让报告改成表格 | artifact edit pattern | 交付格式偏好 |
| 用户总要求先看风险 | repeated instruction | planning/review skill |
| 用户拒绝主动推送 | negative push feedback | 打扰成本模型 |
| 用户选择 Slack 而非邮件 | channel choice | 外发渠道偏好 |
| 用户每次 PR review 都看测试和边界条件 | repeated workflow | SOP skill |

展示方式：

```text
我学到一个偏好：研究类文档要把来源放在结论旁边。
[以后这样] [这次而已]
```

低风险学习可默认 shadow/active，并允许撤销；高风险和隐私相关学习必须确认。

### 23.11 低频控制：从聊天进入，不做主界面

设置不是主体验。用户可以在聊天里说：
- “接上我的 GitHub。”
- “以后发 Slack 前都问我。”
- “别记住这件事。”
- “把你知道的我的工作偏好列出来。”
- “这周别主动提醒我。”

前端可以打开轻量设置抽屉，但入口仍是聊天。抽屉只处理连接应用、权限、已学偏好、安静时间和数据控制。

### 23.12 API 与事件投影

前端 API 应以 conversation 为中心，`mission_id` 可以作为 opaque metadata 存在，但不成为用户可见概念。

```ts
interface MnemoChatAPI {
  sendMessage(input: ChatInput, presentation?: Presentation): Promise<ChatTurnAck>;
  subscribeConversation(conversationId: "primary", sinceEventId?: string): AsyncIterable<ChatEvent>;
  respondToCard(cardId: string, action: CardAction): Promise<void>;
  updateArtifact(artifactId: string, instruction: string): Promise<void>;
  openArtifact(artifactId: string): Promise<ArtifactView>;
  undoLearning(itemId: string): Promise<void>;
  updateStandingAuthority(patch: AuthorityPatch): Promise<void>;
}
```

RunLedger/runtime event 到前端事件的投影：

| Backend event | UI event | 用户看到 |
|---------------|----------|----------|
| `request.received` | `turn.started` | 已收到 |
| `mission.hydrated` | `conversation.hydrated` | 恢复上下文摘要 |
| `mission.state.updated` | `status.updated` | 当前进展 |
| `decision.made` | `plan.updated` | 做法摘要 |
| `model.delta` | `assistant.delta` | 可读输出流 |
| `tool.called` | `action.started` | 正在行动 |
| `tool.result` | `action.completed` / `source.attached` | 动作完成或证据就绪 |
| `artifact.created` | `artifact.card` | 产物出现 |
| `artifact.updated` | `artifact.delta` | 产物更新 |
| `decision.required` | `decision.card` | 需要确认 |
| `memory.queued` | `learning.chip` | 可能学到一个偏好 |
| `run.completed` | `assistant.message(final)` | 本轮完成 |

前端永远不展示完整 prompt、chain-of-thought、敏感 memory、原始工具长输出或 Mission 调试字段。

### 23.13 视觉与体验语言

- 第一屏只有对话流和底部 Composer，不做 Mission 列表、Now dashboard 或运维仪表盘。
- 导航最多保留搜索、设置和 artifact 抽屉入口，不把 `Missions / Watches / Memory` 做成主标签。
- 动作卡片要紧凑，默认折叠细节；用户点开才看证据和步骤。
- 常用操作用短动词：`继续`、`暂停`、`发送`、`撤销`、`记住`、`忘记`。
- 卡片只作为聊天消息中的单层对象，不嵌套卡片。
- 记忆语言必须是用户语言：`我学到一个偏好`、`以后按这个格式来`、`撤销这条学习`。
- 移动端和桌面端心智一致：都是一条对话；桌面端只是多一个 artifact 预览区域。

### 23.14 MVP 范围

第一版只做“一个聊天框能完成事情”的闭环：

1. Primary conversation：持久对话、断线续传、跨轮上下文恢复。
2. Universal Composer：文本、文件、链接、app mention。
3. Streaming action cards：状态、工具摘要、可折叠证据。
4. Artifact cards：文档/消息/表格/diff 的查看、版本和继续修改。
5. Decision cards：外发和高风险确认。
6. Recall in chat：用自然语言找回过去并继续。
7. Learning chips：派活过程中的可撤销偏好学习。

暂不做 Mission 管理页、完整记忆图谱、复杂设置中心、调试 trace UI。高级调试保留给 CLI / harness report。

---
