# Frontend Visual System

> 依据 `design/assets/frontend-redesign/` 中的生成参考图沉淀。目标不是做一个运维控制台，而是把 Mnemo 做成用户每天进入世界的单一聊天界面。

## 1. Reference Set

| Image | Role | Adopted Ideas |
|------|------|---------------|
| `assets/frontend-redesign/chat-desktop.png` | 桌面聊天主界面 | 白色产品壳、左侧极窄导航、主聊天流、右侧实时活动和长期记忆摘要 |
| `assets/frontend-redesign/memory-drawer.png` | 长期记忆抽屉 | 十维记忆列表、覆盖度、选中记忆详情、证据链、引用/更新/忘记操作 |
| `assets/frontend-redesign/settings-drawer.png` | 设置抽屉 | 聊天背景轻遮罩、右侧配置抽屉、模型/工具权限/记忆/Dream/工作区/外观/数据 |
| `assets/frontend-redesign/mobile-sheets.png` | 移动端 | 仍然只有一个聊天入口；记忆和设置变成 bottom sheet |
| `assets/frontend-redesign/chat-annotated.png` | 信息层级 | streaming answer、action in progress、memory candidate、decision needed、artifact preview、composer 的层级 |

## 2. Design Direction

Mnemo 的界面要像一个安静但能行动的个人工作台：

- **单入口**：屏幕的重心永远是聊天流和底部 composer。用户不会被 Mission、Run、Trace 等内部概念打断。
- **浅色高端感**：使用 warm off-white 作为画布，白色卡片、细线边框、低透明阴影；避免大面积深色后台感。
- **紧凑动作可见**：工具调用以内联 action strip/card 展示，默认只显示工具名、状态、摘要；参数和结果折叠。
- **记忆像上下文，不像数据库**：右侧显示“偏好与长期记忆”的少量摘要；完整维度化记忆以「记忆罗盘」呈现。
- **配置像用户设置，不像控制面板**：设置抽屉只处理模型连接、工具权限、记忆学习、Dream 整理、工作区、外观密度和数据控制。
- **移动端同一心智**：聊天不变；活动、记忆、设置从侧栏降级为 bottom sheet。

## 3. Layout

### Desktop

```text
┌────────┬────────────────────────────────────────┬──────────────────────┐
│ Rail   │ Chat Shell                             │ Context Rail          │
│        │ ┌ topbar: title / status / reset ┐     │ Real-time Activity    │
│ 对话    │ │ timeline                         │     │ Preference Memory     │
│ 记忆    │ │ assistant markdown / action cards │     │ Recent Context        │
│ 设置    │ │ artifacts / decisions / recall    │     │                      │
│        │ └ composer: tools / input / send ┘    │                      │
└────────┴────────────────────────────────────────┴──────────────────────┘
```

Grid:
- Outer shell: 76px rail, flexible chat, 360-390px context rail.
- Gap: 12px.
- Radius: 8px maximum for cards, drawers and buttons.
- Chat timeline width: max 880px, centered inside the chat column but aligned to the left enough for scanability.
- Composer: fixed at bottom of chat shell, white floating input with subtle shadow.

### Mobile

```text
┌──────────────────────┐
│ Mnemo header          │
│ chat timeline         │
│ inline compact tools  │
│ composer              │
│ bottom nav: tools/mem │
└──────────────────────┘
```

- Rail becomes a compact horizontal top strip.
- Context rail is hidden.
- Memory/settings use the same overlay element but render as a full-width sheet.
- Tables and long artifacts scroll horizontally inside message/card boundaries.

## 4. Visual Language

### Color Tokens

| Token | Use |
|------|-----|
| `--bg` | app canvas, warm white |
| `--surface` | chat shell and drawer background |
| `--surface-raised` | messages/cards |
| `--surface-soft` | subtle chips, table headers, input controls |
| `--ink` | primary text |
| `--muted` | secondary text |
| `--teal` | primary action, running status, send |
| `--violet` | memory dimension and recall |
| `--gold` | queued/planning/artifact accent |
| `--red` | risk, error, decision |

The palette must not collapse into a single hue. Teal is primary, violet is reserved for memory, gold for artifact/queued state, red for risk.

### Typography

- Topbar title: 18px, 800.
- Message body: 15px, 1.62 line height.
- Card title: 13px, 780.
- Details/meta: 12-13px.
- No viewport-scaled font sizes.
- Letter spacing is `0`.

### Shape and Density

- Radius: 8px or less.
- No nested cards inside cards. A drawer can contain rows; rows can contain compact chips.
- Cards use 1px lines and tiny shadows, not thick borders.
- Tool cards should fit in a scan line first; details open only on demand.

## 5. Main Chat Screen

### Topbar

Topbar should read as user context, not internal runtime:

- Title: `Mnemo`
- Subtitle: `一个聊天框，完成所有事`
- Status pill: `空闲` / `执行中` / `停止中` / concise runtime status.
- Reset button: `新对话`

No visible Mission id. Technical ids can remain in DOM for continuity tests but labels must be user-facing: `当前上下文`、`最近请求`、`最近运行`.

### Timeline

The empty state is a quiet prompt: `今天想完成什么？`

Message rules:
- User message is right-aligned with a soft teal tint, not a full dark bubble.
- Assistant message is left-aligned, white, markdown-rendered during streaming.
- Markdown tables render as bordered tables with horizontal overflow.
- Pending response shows `回复中` with three animated dots.

### Action Cards

Action card hierarchy:

```text
[icon] tool_name                 [queued/running/success]
summary of what is happening
Call details  ▾
Result        ▾
```

States:
- queued: gold dot/chip.
- running: teal dot/chip with subtle pulse.
- success: teal check tone.
- failed/error: red.

Action cards must stay compact:
- max width about 680px.
- 8-10px vertical padding.
- details max height around 160px.
- no duplicate visible result cards for the same tool result.

## 6. Context Rail

The right rail has two sections:

### Real-time Activity

Purpose: show current action state without becoming a log viewer.

Rows:
- status dot
- concise title
- one-line detail
- latest first

Internal learning housekeeping is hidden. The rail shows no raw provider payload, prompt, chain-of-thought or full tool output.

### Preference And Long-Term Memory

Purpose: reassure the user that Mnemo carries continuity.

Rows:
- recent ask
- conversation context
- long-term memory summary
- latest run

Use user language. Avoid `Mission` and raw ids as visible concepts.

## 7. Memory Drawer

用户可见名称是 **记忆罗盘**。它比“十维记忆”更像产品能力：Mnemo 用十个维度理解用户的偏好、目标、边界和工作方式，并用这些信号为后续行动定向。`十维记忆` 只作为内部解释或设计文档中的结构说明，不出现在主要 UI 标题里。

Opened by the `记忆` rail button. It uses the same overlay as settings but renders memory-first content.

Structure:

```text
记忆罗盘
  罗盘总览 | 全部记忆
  search/filter row
  left/list: dimensions with coverage bars and counts
  right/detail: selected memory summaries and evidence rows
  footer actions: 忘记 / 更新 / 引用到当前任务
```

Implementation scope for current lightweight frontend:
- Fetch `/api/memory/ontology` on open.
- Show coverage summary.
- Show every dimension row with a progress bar and count.
- Expand each dimension with clipped memory summaries already returned by the API.
- Footer actions prefill the single composer; browser does not directly mutate memory except existing learning-chip APIs.

## 8. Settings Drawer

Opened by the `设置` rail button.

Sections:
- **模型**：provider/model connection summary, never API keys.
- **工具权限**：default policy and open decisions. Keep simple: default open / needs confirmation.
- **记忆**：learned preferences summary, memory learning review action, link to memory drawer.
- **Dream 整理**：quiet-hour style controls and schedule summary when available.
- **工作区**：workspace/app connection summary.
- **外观**：density/theme placeholders can prefill composer until backed by API.
- **数据**：counts and export/delete prompts.

Settings are a drawer, not a second app. Any complex action becomes composer prefill so the agentic loop decides.

## 9. Implementation Checklist

The executable checklist lives in `design/frontend-redesign-checklist.md`.
