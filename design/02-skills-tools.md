# Skills And Tools

> Agent Skills 兼容、自演进技能、SOP 晶化、工具分层和 generated tools。

## 4. 技能自演进子系统

### 4.1 设计哲学：Skill 是程序性记忆，不是偏好规则

Mnemo 的 Skill 定义要向主流 agent 系统收敛：Skill 是 **按需加载的程序性能力包**，不是单纯的用户偏好，也不是固定脚本。它告诉模型：

1. 什么时候应该使用这项能力。
2. 执行任务时应加载哪些上下文、记忆和工具。
3. 如何分解步骤、处理分支、检查中间结果。
4. 失败时如何恢复，完成后如何验证。
5. 哪些个人化约束必须遵守，哪些观察可以反哺技能演进。

参考边界：

- OpenClaw: tool 是可调用能力，skill 是写给模型看的 `SKILL.md` 指南，plugin 是更完整的运行时扩展；skill 可以附带脚本和资源，但核心仍是上下文和 procedure。
- Hermes Agent: skill 采用 progressive disclosure，运行时只加载必要说明；agent 可通过 `skill_manage` 创建和修改技能，但修改必须可追溯。
- GenericAgent: 解题轨迹会被晶化成 SOP/Skill，下次相似任务先复用经验，再按现场反馈调整。

Mnemo 的差异化不在于“也有 skills”，而在于 **skills 被用户记忆、本体、RunLedger 和评测 harness 共同约束**：同一个 code review skill 对不同用户会有不同检查重点、沟通方式、风险边界和交付格式。

| 概念 | 回答的问题 | 存什么 | 运行时如何使用 |
|------|------------|--------|----------------|
| Memory | “这个用户/世界是什么样？” | 事实、偏好、关系、历史、边界 | 作为候选上下文，由模型在 loop 中决定是否加载 |
| Skill | “这类任务该怎么做？” | 触发条件、程序步骤、工具计划、验证点、失败恢复、例子 | 进入 prompt 指导模型执行 |
| Tool | “系统能实际调用什么？” | API、CLI、函数、浏览器、文件系统能力 | 由模型或 harness 调用，结果写 RunLedger |
| SOP | “重复任务的成熟路径是什么？” | 从成功 run 抽象出的参数化 procedure | 作为 skill 子类型被模型实例化和监控 |
| Plugin / Adapter | “如何接入外部运行时？” | 协议、权限、生命周期、资源边界 | 给 RuntimeHarness 暴露能力 |

一句话边界：**Skill 指导执行，Tool 负责执行，Memory 提供个性化事实，模型在 agentic loop 中做语义选择。**

### 4.2 技能目录与加载粒度

每个 skill 是一个目录，主文件固定为 `SKILL.md`。目录内可以包含脚本、模板、示例、测试和历史 trace，但运行时不默认全部加载。

Mnemo 原生目录是 `~/.mnemo/skills/`，但必须兼容主流 Agent Skills 操作，因此扫描器同时支持 `.agents/skills/` 约定和常见客户端目录。外部目录默认只读，除非用户显式授权写入。

| Scope | 路径 | 默认权限 | 说明 |
|-------|------|----------|------|
| native user | `~/.mnemo/skills/` | read-write | Mnemo 自演进主目录 |
| native project | `<workspace>/.mnemo/skills/` | read-write if trusted | 项目级 Mnemo skill |
| cross-client user | `~/.agents/skills/` | read-only | Agent Skills 开放约定，便于 Codex/Claude/OpenClaw/VS Code 共享 |
| cross-client project | `<workspace>/.agents/skills/` | read-only if trusted | repo 内共享 skill |
| Claude | `~/.claude/skills/`, `<workspace>/.claude/skills/` | read-only | 支持 slash skill、arguments、allowed-tools 等字段 |
| Hermes | `~/.hermes/skills/` | read-only by default | 支持 `skills_list` / `skill_view` / `skill_manage` 语义映射 |
| OpenClaw | `~/.openclaw/skills/`, `<workspace>/skills/` | read-only by default | 支持 workspace precedence、allowlist、plugin-bundled skills |

同名冲突按安全优先处理：trusted workspace native > trusted workspace `.agents` > user native > user `.agents` > imported client dirs > bundled。被遮蔽的 skill 仍写入 diagnostics，用户可用 `mnemo skills why <name>` 查看来源和冲突。

```
~/.mnemo/skills/
├── always_on/
│   └── direct-communication/
│       └── SKILL.md
│
├── interaction/
│   ├── feedback-style/
│   │   └── SKILL.md
│   └── task-handoff/
│       └── SKILL.md
│
├── task/
│   ├── code-review/
│   │   ├── SKILL.md
│   │   ├── examples/
│   │   └── evals/
│   └── technical-research/
│       ├── SKILL.md
│       └── templates/
│
├── tool_use/
│   ├── github-cli/
│   │   └── SKILL.md
│   └── browser-research/
│       └── SKILL.md
│
├── domain/
│   ├── ai-agent-architecture/
│   │   └── SKILL.md
│   └── product-strategy/
│       └── SKILL.md
│
├── sop/
│   ├── github-pr-review/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   ├── templates/
│   │   └── traces/
│   └── weekly-project-review/
│       └── SKILL.md
│
└── _generated/
    └── <skill-id>/
        ├── SKILL.md
        └── evidence.jsonl
```

**Progressive disclosure**:

| 层级 | 进入上下文的内容 | 触发方式 |
|------|------------------|----------|
| L1 Skill Index | skill 名称、描述、类型、置信度、最近使用 | 常驻，几十行以内 |
| L2 Skill Summary | frontmatter + “When to use / Procedure” 摘要 | skill_search / runtime 候选检索命中 |
| L3 Full Skill | 完整 `SKILL.md`、关键例子、模板片段 | 模型明确调用 `skill_view` 或高风险/harness 场景需要 |
| Asset Load | scripts、examples、long traces、eval fixtures | 执行步骤真正需要时加载 |

这个设计避免把全部 skill 常驻塞进 prompt，同时保留模型按任务自主发现能力的空间。

### 4.3 Skill Contract：`SKILL.md`

`SKILL.md` 是模型可读的契约，不绑定某一种编程语言。脚本可以是 Python、TypeScript、Shell、Wasm、SQL 或运行时插件；Skill 本身描述的是 procedure 和决策点。

```yaml
# skills/sop/github-pr-review/SKILL.md
---
name: github-pr-review
description: Review and summarize GitHub PRs using the user's review standards. Use when the user asks to inspect, review, unblock, or merge pull requests.
license: Proprietary
compatibility: Requires git, gh CLI, network access to GitHub, and a trusted workspace.
allowed-tools: Bash(gh:*) Bash(git:*) Read Grep

# Claude / AgentSkills-compatible extensions. Unknown clients may ignore them.
when_to_use:
  - User asks to inspect, review, unblock, or merge pull requests.
  - A Watch reports PR activity in a repo the user cares about.
disable-model-invocation: false
user-invocable: true
argument-hint: "[repo-or-pr]"
arguments: [target]

metadata:
  mnemo:
    version: 2
    type: sop                  # always_on | interaction | task | tool_use | domain | sop
    status: active             # draft | shadow | active | promoted | deprecated | rejected
    activation:
      mode: model_selected     # always_on | model_selected | explicit_only
      priority: medium
      evidence_min: 0.70
      max_context_tokens: 1800
    do_not_use_when:
      - The request is about reviewing a local diff without GitHub context.
      - The repo or PR identity is ambiguous and cannot be inferred safely.
    required_tools:
      - name: shell
        purpose: call gh/git commands when available
        approval: per_runtime_policy
      - name: browser
        purpose: inspect remote docs or CI pages when shell is insufficient
    inputs:
      repo: optional string
      pr_number: optional integer
      branch: optional string
    outputs:
      - concise status report
      - blockers and recommended next action
      - memory or skill observations, if any
    personalization:
      reads_memory:
        - preferences/code-review
        - cognition/engineering-standards
        - boundaries/security-and-secrets
      writes_observations:
        - skill_usage
        - preference_reinforcement
        - failure_recovery
    safety:
      destructive_actions: require_explicit_approval
      secret_handling: redact_before_prompt
      external_posts: require_user_confirmation
    verification:
      success_signals:
        - CI and review status were inspected or limitation was stated.
        - Final answer separates blockers from recommendations.
      failure_modes:
        - missing gh auth
        - ambiguous repo
        - stale branch data
    provenance:
      source: crystallized_run
      observation_count: 6
      run_ids: ["run_20260412_01", "run_20260418_03"]
      confidence: 0.88
---
```

正文推荐结构：

```markdown
# GitHub PR Review

## When To Use
Describe task signals that should make the model consider this skill.

## Procedure
1. Identify repo and PR scope.
2. Inspect status checks, review state, changed files, and discussion.
3. Compare findings against the user's review standards.
4. Produce a decision-oriented report.

## Decision Points
- If repo is ambiguous, infer from cwd and recent context; otherwise ask one focused question.
- If checks are still running, report current state and avoid declaring merge readiness.

## Tool Plan
- Prefer `gh pr view` and `gh pr checks`.
- Fall back to browser only when CLI is unavailable or remote details matter.

## Verification
- Confirm source freshness.
- Ensure final answer includes blockers, risks, and next action.

## Failure Recovery
- Missing auth: explain the blocked command and continue with available local context.
- Tool error: record error class and retry only if the failure is transient.

## Examples
Include compact positive and negative examples.

## Related Memory
List memory pages that personalize this skill.
```

### 4.4 任务执行中的 Skill 使用

Skill 不是“先规则匹配再执行”的分流表，而是 agentic loop 的候选上下文。模型必须在运行时根据任务、记忆、工具状态和风险做裁决。

```
request.received
  → PromptAssembler:
      user request + Mission + compact skill index + short tool affordances
  → AgentRunHarness:
      model step → skill_view/memory_search/tool call → observation → model step → verification
  → SkillLoader:
      progressive load only when the model asks for SKILL.md or assets
  → RunLedger:
      skill candidates, viewed skills, rejected/unused candidates, tool results, verification, observations
  → Learning candidate tools:
      model may write memory/skill/tool/eval candidates or discard
```

语言无关接口：

```ts
type SkillCandidate = {
  id: string;
  type: "always_on" | "interaction" | "task" | "tool_use" | "domain" | "sop";
  summary: string;
  evidence: Evidence[];
  retrievalScore: number;
  lastUsedAt?: Date;
  confidence: number;
  risk: "low" | "medium" | "high";
};

type SkillUseDecision = {
  selected: string[];
  rejected: { id: string; reason: string }[];
  loadLevel: Record<string, "summary" | "full" | "assets">;
  toolPlan: ToolPlan;
  verificationPlan: VerificationPlan;
  rationale: string;
};

interface SkillRuntime {
  buildCandidates(input: RunInput, context: ContextSnapshot): Promise<SkillCandidate[]>;
  load(decision: SkillUseDecision): Promise<LoadedSkill[]>;
  recordUse(runId: string, skillId: string, outcome: SkillOutcome): Promise<void>;
  proposePatch(runId: string, evidence: Evidence[]): Promise<SkillPatch[]>;
}
```

关键原则：

- Registry 只生成候选，不做最终路由。
- SkillLoader 只加载模型明确选择的内容，不偷偷改变任务目标。
- Tool 调用仍由 AgentRunHarness 管理权限、超时、重试和审计。
- 每次 skill 被查看、加载、用于输出、被模型拒绝或未使用，都尽量写入 RunLedger，支持 replay 和 ablation eval。

### 4.5 Skill Candidate Refinement：从 learning candidate 中自演进

Skill 候选精炼不单独重扫完整轨迹，也不定义“先抽 skill”的工作流。AgentRunHarness 把用户纠正、工具结果、artifact diff、失败恢复和已接受输出打成 learning packet；模型可以从同一个 packet 提出 0..N 个候选，其中 skill candidate 才进入精炼工具。

| 信号 | 来源 | 可演进成什么 |
|------|------|--------------|
| explicit_correction | 用户直接纠正 | interaction / task skill patch |
| explicit_approval | 用户确认“这样做对” | 置信度提升、例子追加 |
| repeated_task_trace | 多次相似任务成功 | SOP draft |
| repeated_tool_sequence | 稳定工具链 | tool_use skill 或宏工具候选 |
| failure_recovery | 某类错误被成功恢复 | Failure Recovery section patch |
| verification_gap | 任务完成后发现漏验 | Verification section patch |
| preference_conflict | skill 与 memory 冲突 | 降级、拆分或请求异步确认 |

```ts
interface SkillCandidateTools {
  refineCandidate(candidate: SkillCandidateProposal, evidence: Evidence[]): Promise<SkillDraft | SkillPatch>;
  evaluateDraft(draftId: string, harness: SkillHarness): Promise<SkillEvalReport>;
  recordOutcome(runId: string, skillId: string, outcome: SkillOutcome): Promise<void>;
}
```

Skill candidate tools 由模型负责语义判断，规则只做证据校验、权限边界、schema 校验和回滚要求。例如“同类任务出现多次”只是 evidence，不等于自动生成；模型需要判断这些 run 是否真是同一 procedure、是否有足够验证、是否适合泛化。

Skill patch 必须包含：

- evidence quotes 或 run trace 引用。
- 变更前后的行为差异。
- 影响的 memory/tool/boundary。
- 至少一个 replay case 或 synthetic case。
- rollback 条件。

### 4.6 Skill Registry 与模型裁决

`SkillRegistry` 是检索索引，不是路由系统。它负责把可能相关的 skills 找出来，把选择权交给运行中的模型。

```ts
interface SkillRegistry {
  listIndex(scope?: SkillScope): Promise<SkillIndexEntry[]>;
  search(query: string, filters?: SkillFilters): Promise<SkillCandidate[]>;
  getMetadata(skillId: string): Promise<SkillMetadata>;
  getSummary(skillId: string): Promise<SkillSummary>;
  getFull(skillId: string): Promise<SkillDocument>;
}
```

L1 Skill Index 示例：

```markdown
## Skills Index
- always_on/direct-communication [v3, high] - concise direct handoff style
- task/technical-research [v2, medium] - compare sources, cite assumptions
- tool_use/github-cli [v1, medium] - use gh safely with auth checks
- sop/github-pr-review [v2, medium] - inspect PR status and blockers
- _generated: 4 draft, 2 shadow, 1 needs eval
```

普通执行中，模型通过 `skill_view` 和工具循环自然选择 skill；需要审计、harness 对比或高风险动作时，运行时可把选择写成 `decision.recorded` 事件：

```json
{
  "selected_skills": ["task/technical-research", "sop/github-pr-review"],
  "rejected_skills": [
    {"id": "interaction/teaching-style", "reason": "task is execution-heavy, not explanation-heavy"}
  ],
  "load_level": {
    "task/technical-research": "full",
    "sop/github-pr-review": "summary"
  },
  "reason": "The user asks for an executable research-backed update; both research procedure and PR-like verification are relevant.",
  "verification_plan": ["source freshness check", "doc consistency scan", "run ledger event check"]
}
```

### 4.7 SOP Skills：任务路径晶化，而不是绕过模型

SOP Skill 是“成熟任务路径”的可复用表达。它不是默认直接执行的脚本，也不是为了跳过模型推理；它让模型少走弯路，但仍由模型实例化参数、处理分支、判断何时偏离原 SOP。

| 维度 | Interaction Skill | Task Skill | Tool-use Skill | SOP Skill |
|------|-------------------|------------|----------------|-----------|
| 描述什么 | 如何与用户协作 | 一类任务的方法 | 如何安全高效使用工具 | 重复任务的参数化路径 |
| 主要来源 | 反馈和偏好 | 成功任务总结 | 工具调用经验 | 多条成功 run trace |
| 是否个性化 | 强 | 中到强 | 中 | 强 |
| 是否可执行 | 指导模型 | 指导模型 | 指导工具使用 | 指导模型执行步骤 |
| 何时晋升工具 | 不适合 | 少数稳定片段 | 高频机械片段 | 固定、安全、无需语义判断的子序列 |

SOP 晶化循环：

```
explore
  → solve
  → record trace
  → abstract procedure
  → replay on old cases
  → shadow use on new cases
  → activate
  → monitor drift
```

SOP 示例：

```markdown
# Technical Research Update

## When To Use
Use when the user asks to update a design document based on external agent systems,
frameworks, or papers.

## Inputs
- topic
- target document
- required comparison axes

## Procedure
1. Gather primary or official sources first.
2. Extract execution model, skill model, memory model, and harness model.
3. Compare with Mnemo's current architecture.
4. Patch the target document.
5. Run consistency checks: headings, stale terminology, contradictory claims.
6. Report changed sections and source list.

## Decision Points
- If sources conflict, prefer official docs over commentary.
- If a product is not open-source, mark inference boundaries.
- If a rule-like router appears, convert it to candidate generation plus model decision.

## Verification
- Every external claim links to a source.
- The document no longer claims SOPs bypass model reasoning.
- RunLedger events include skill selection and verification.
```

稳定机械片段可以从 SOP 中拆出成宏工具，例如“收集 `gh pr view` 的 JSON 并规范化字段”；但“PR 是否可合并”“该如何向用户解释风险”仍应由模型裁决。

### 4.8 Skill Harness：让技能可评测、可回放、可回滚

Skill 自演进必须配 harness，否则会变成不可控的 prompt 漂移。

| Harness | 目的 | 例子 |
|---------|------|------|
| selection eval | 判断候选 skill 是否被正确选择/拒绝 | “调研并改文档”应选 `task/technical-research` |
| execution replay | 用历史 run 重放 skill 行为 | 新版 SOP 不应漏掉 source check |
| ablation eval | 比较加载/不加载 skill 的差异 | task_success、token、tool_error |
| conflict eval | 检查 skill 与 memory/boundary 冲突 | 直接风格不能覆盖安全确认 |
| red-team eval | 测试 prompt injection 和越权调用 | 外部网页诱导修改 skill |
| drift eval | 检查过期或误泛化 | 旧 repo 流程不适用于新 monorepo |
| lint eval | 结构检查 | frontmatter、when_to_use、verification 是否齐全 |

```yaml
# skills/task/technical-research/evals/research-doc-update.yaml
case_id: research_doc_update_openclaw_hermes_generic
input:
  user_request: "参考 openclaw、Hermes agent 和 generic agent 的执行方式，修改技能定义"
expected:
  selected_skills:
    - task/technical-research
  rejected_patterns:
    - "directly execute SOP without model reasoning"
  required_checks:
    - official_or_primary_sources_used
    - skill_tool_memory_boundary_explained
    - runledger_skill_events_present
metrics:
  task_success: model_judge
  source_grounding: exact_match_or_citation_check
  personalization_adherence: model_judge
  regression_risk: replay_diff
```

核心指标：

- `activation_precision`: 被选中的 skill 是否真的有用。
- `activation_recall`: 应该使用 skill 时是否漏选。
- `task_success_lift`: 加载 skill 后任务成功率提升。
- `preference_adherence`: 是否更贴合用户偏好。
- `tool_error_rate`: 是否减少工具错误和无效调用。
- `rollback_rate`: 新 skill/patch 是否频繁回滚。
- `context_cost`: 额外 token 是否值得。

### 4.9 技能生命周期与权限边界

所有自动生成的 skill 走统一状态机：

```
generated/draft
  → shadow             # 后台评测；不影响用户可见行为
  → available          # 通过 lint/smoke，可进入候选集；低优先级、可回滚
  → active             # 通过 selection/replay eval，模型可正常选择加载
  → promoted           # 高频高价值，进入 L1 index 或 always_on；需要更强 eval
  → deprecated         # 长期不用、过期或被替代
  → rejected           # 用户或 harness 明确拒绝，不再自动提议
  → rolled_back        # 新版本造成回归，恢复上一稳定版
```

自动化边界：

- Agent 可以自动写 `_generated/*` draft；lint、安全扫描通过后可自动进入 `shadow`。
- 低风险 interaction/task skill 在 replay smoke 通过后可进入 `available`，作为低优先级候选被模型考虑，但不能进入 always_on。
- 升 `active` 必须通过 SkillHarness 的 selection/replay/conflict eval，并记录 `skill.activated`。
- 升 `promoted` 必须有多次正收益、低 rollback rate 和无安全回归；进入 L1 index / always_on 需要更强 eval gate。
- 涉及权限、外部发布、删除数据、支付、部署、账号操作的 skill patch 必须异步确认。
- Agent 可以修改 `_generated/*` 和自己创建的 skill draft；修改 `always_on/*`、`policy/*`、高风险 `tool_use/*` 需要更高审批。
- 技能首次影响用户可见行为时，在任务末尾简短披露，例如：“这次使用了 `task/technical-research` 和 `sop/research-doc-update`。”
- 不在任务中途打断用户询问“要不要激活这个技能”；确认和回滚进入 Inbox。

RunLedger 需要记录 skill 全生命周期事件：候选、选择、加载、验证、patch、available、激活、回滚。这样 Skill 自演进不会成为黑箱。

### 4.10 主流 Skills 操作兼容层

Mnemo 的 skill 系统必须能被当作一个 Agent Skills-compatible client 使用，而不是自造一套孤立格式。兼容目标分三层：

| 层级 | 必须兼容 | Mnemo 行为 |
|------|----------|------------|
| 文件格式 | `skill-name/SKILL.md`、YAML frontmatter、Markdown body、`scripts/`、`references/`、`assets/` | 原样读取；Mnemo 扩展只放 `metadata.mnemo`，导出时可剥离 |
| 运行操作 | list/search/view/activate、slash invocation、model invocation、supporting file load | 暴露 CLI、MCP、slash command 和模型工具四种入口 |
| 生命周期 | install/import/export/update/patch/enable/disable/eval/rollback | Native skills 可写；外部 skills 默认 shadow copy 后再 patch |

**字段兼容矩阵**:

| 字段 | Agent Skills 标准 | Claude Code | Hermes | OpenClaw | Mnemo |
|------|-------------------|-------------|--------|----------|-------|
| `name` | required | supported | supported | supported | required |
| `description` | required | model activation 关键字段 | `skills_list` 摘要 | prompt list / slash discovery | required |
| `license` | optional | tolerated | tolerated | tolerated | preserved |
| `compatibility` | optional | tolerated | used as guidance | load-time gating hint | parsed into env requirements |
| `allowed-tools` | experimental | pre-approve tools | mapped to toolsets | mapped to tool allowlist | mapped to ApprovalGate policy |
| `when_to_use` | extension | supported | folded into description if needed | folded into summary | supported |
| `disable-model-invocation` | extension | user-only slash skill | maps to explicit_only | maps to slash-only | `activation.mode=explicit_only` |
| `user-invocable` | extension | controls slash visibility | maps to slash command | maps to slash command | supported |
| `arguments` / `argument-hint` | extension | slash args | slash args | slash args | supported |
| `paths` | extension | path-scoped activation | external metadata | workspace gating | boundary filter |
| `metadata.mnemo` | client metadata | ignored | ignored unless imported | ignored unless imported | native extension |

**操作面**:

```bash
mnemo skills list                         # catalog: name, description, source, status
mnemo skills search "github pr"           # semantic + lexical candidate search
mnemo skills show github-pr-review        # show SKILL.md metadata and body
mnemo skills activate github-pr-review -- target=123
mnemo skills install <git-or-dir>          # install into ~/.mnemo/skills or vendor cache
mnemo skills import ~/.claude/skills/foo   # copy or shadow external skill
mnemo skills export foo --target agentskills
mnemo skills enable foo
mnemo skills disable foo
mnemo skills patch foo --from-run <run_id>
mnemo skills eval foo
mnemo skills rollback foo --to v2
mnemo skills doctor                       # parse, permissions, missing deps, collisions
mnemo skills why foo                      # source, precedence, activation history
```

MCP / tool surface mirrors mainstream clients:

```ts
interface SkillTools {
  skills_list(scope?: string): Promise<SkillIndexEntry[]>;
  skill_view(name: string, path?: string): Promise<SkillContent>;
  skill_activate(name: string, args?: Record<string, unknown>): Promise<SkillActivation>;
  skill_manage(action: "create" | "patch" | "edit" | "delete" | "write_file" | "remove_file", payload: SkillManagePayload): Promise<SkillManageResult>;
  skill_eval(name: string, caseId?: string): Promise<SkillEvalReport>;
}
```

Slash / mention 语义：

| 输入 | 语义 |
|------|------|
| `/skill-name args` | 用户显式激活；可绕过模型自动选择，但仍进入 ApprovalGate |
| `$skill-name` | 对话内 mention，等价于要求模型考虑该 skill |
| 自然语言请求 | runtime 暴露短 catalog，由模型决定是否加载 |
| Watch / daemon trigger | 只能生成候选；高风险 skill/action 必须由模型在 loop 中确认并通过 ActionEngine |

**导入策略**:

1. Parse: 宽松解析 frontmatter，保留未知字段。
2. Normalize: 生成内部 `SkillManifest`，把客户端扩展映射到 `metadata.mnemo`。
3. Trust: 项目级外部 skill 需要 workspace trust；第三方 skill 先进入 `shadow`。
4. Dependencies: 解析 `compatibility`、`allowed-tools`、脚本 shebang、package hints。
5. Eval: 至少跑 lint + selection eval；有 side effects 的 skill 必须 dry-run。
6. Activate: 通过后进入 catalog；原文件只读，patch 写入 Mnemo shadow copy。

**导出策略**:

- `--target agentskills`: 只保留标准字段和正文，Mnemo 扩展压缩到 `metadata.mnemo`。
- `--target claude`: 保留 `when_to_use`、`arguments`、`allowed-tools`、`paths`、`context`。
- `--target hermes`: 生成 Hermes 友好的目录，支持 slash command 和 `${HERMES_SKILL_DIR}` 替换提示。
- `--target openclaw`: 输出 `.agents/skills/` 或 workspace `skills/` 目录，并生成 allowlist/gating 建议。

**兼容但不退化**:

Mnemo 可以读取主流 skills，但不会把外部 skill 的 instructions 当作绝对系统命令。所有外部内容都只是候选上下文，由模型按需查看；外部 skill 不能绕过 `ActionEngine`、`RunLedger` 和必要的确认卡。这保证了兼容性，同时保留 Mnemo 的核心优势：个性化记忆、可回放执行、技能自演进和 harness 评测。

---
---

## 13. 工具架构与自演进

### 13.1 轻量工具模型：Registry 不是权限层

```
╔══════════════════════════════════════════════════════════════╗
║                   Mnemo Tool Registry                        ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Built-in: 默认安装，但仍受 profile / risk / deny 控制        ║
║  ─────────────────────────────────────────────               ║
║  file_read  file_patch  exec  web_search  web_fetch          ║
║  memory_search  memory_read  working_note                    ║
║  skills_list  skill_view  skill_manage                       ║
║  artifact_update  ask_user                                    ║
║                                                              ║
║  Extension Toolsets: 连接或启用后才出现，按需注入              ║
║  ─────────────────────────────────────────────               ║
║  browser_*  messaging_*  calendar_*  mail_*  mcp:<server>    ║
║  watch_*  cronjob  hooks_*  delegate_task  android_sense     ║
║  provider_status(admin)  gateway_status(admin)               ║
║                                                              ║
║  Generated: 后置能力，只有 SOP 不够时才晋升                  ║
║  ─────────────────────────────────────────────               ║
║  ~/.mnemo/tools/_generated/*.tool.yaml   (候选)              ║
║  ~/.mnemo/tools/*.tool.yaml              (已激活)            ║
╚══════════════════════════════════════════════════════════════╝
```

核心原则：

- Registry 只说明“系统有哪些工具”，不代表模型一定能看到或调用。
- 每个 run 只暴露一个小 profile 对应的工具卡，避免 token 膨胀。
- 暴露给 provider 的 tool name 必须使用 `snake_case` / `kebab-case` 安全集合，不使用 dotted namespace。
- 权限只分四级风险：`read | write | external | admin`。
- `deny` 永远优先；危险动作走 ActionEngine 内置确认；普通读操作不打扰用户。

### 13.2 Core Tools 最小集合

首发工具要少，避免工具卡膨胀。Core tools 只覆盖“读写、执行、检索、记忆读取、技能、产物、确认”七类。长期记忆写入不作为普通 core tool 暴露，统一走候选写入工具。

```python
CORE_TOOLS = {
    "file_read": "读取文件片段；先读后改",
    "file_patch": "精确替换唯一文本块；失败时重新读取",
    "exec": "执行命令；探针优先，带超时和工作目录",
    "web_search": "搜索网络，返回结构化结果",
    "web_fetch": "获取 URL 正文或链接摘要",
    "memory_search": "检索 L1/L2/L4，返回 bounded snippets",
    "memory_read": "读取允许暴露的记忆页面或 L1 指针",
    "skills_list": "列出 skill 索引和短摘要",
    "skill_view": "按需加载 SKILL.md 或 supporting file",
    "skill_manage": "创建/补丁 skill shadow copy，晋升需治理",
    "artifact_update": "创建或更新聊天内 artifact",
    "ask_user": "生成内联 Decision/clarification card",
    "working_note": "写 W0 turn_scratch/mission_state",
}
```

Learning / Dream 阶段按需暴露的候选写入工具使用 provider-safe snake_case 名称：

```python
LEARNING_CANDIDATE_TOOLS = {
    "memory_write_candidate": "提交 MemoryFactCandidate，经写入管线处理",
    "skill_propose_candidate": "提交 SKILL.md 草稿或 patch 候选",
    "tool_propose_candidate": "提交 generated tool spec 候选",
    "eval_propose_case": "提交 replay/eval case 候选",
    "learning_discard": "记录本轮不学习的依据",
}
```

Standard / Extension tools 不进默认 prompt，只在连接、授权或模型明确需要时通过 toolset 注入。它们是保留能力，不是被删除的能力：

| Extension toolset | 例子 | 进入条件 |
|-------------------|------|----------|
| `browser` | `browser_navigate`、`browser_snapshot` | 需要交互式网页操作 |
| `messaging` | `send_message`、`slack_*`、`mail_*` | 连接账号且涉及外发/收件 |
| `calendar` | `calendar_read/write` | 用户要求日程操作 |
| `automation` | `watch_*`、`cronjob` | 用户明确要求长期关注/定时 |
| `runtime_ext` | `process`、`code_run`、`terminal_backend`、`docker` | 长任务、代码片段或隔离执行需要 |
| `research_ext` | `web_extract`、`llm_task` | 结构化抽取、评审、分类、批处理推理 |
| `memory_ext` | `memory_associate`、高级 vector/rerank search | 联想召回或基础 FTS 不够 |
| `skills_ext` | `skill_activate`、`skill_eval`、skill red-team | 显式技能治理或评测 |
| `media` | `vision_analyze`、`image_generate`、`tts` | 输入/输出是媒体 |
| `mcp` | `mcp:<server>` | 用户连接具体服务 |
| `sessions` | `session_status`、`session_history`、`spawn/cancel` | 调试、恢复、子任务控制 |
| `admin` | `provider_status`、`gateway_status`、`hooks_*`、`reflect` | 设置/调试/企业策略/手动维护 |

生成工具也保留，但晋升顺序必须轻量：

```text
repeated trajectory
  → SOP skill candidate
  → shadow skill eval
  → available/active skill
  → only if still too costly: generated tool candidate
  → tool shadow run
  → active generated tool
```

这样不会丢掉 GenericAgent 的“轨迹晶化”思想，也不会一开始就让系统背负一套重型 tool generation 平台。

### 13.3 轻量权限与省 Token 策略

OpenClaw / Hermes 的启发要吸收，但不能把配置矩阵搬进 Mnemo。Mnemo 采用 **小 profile + 四级风险 + 短工具卡**：

| 概念 | 用途 | 是否进 prompt |
|------|------|---------------|
| `Tool` | 可调用 typed function | 只进当前 profile 的短工具卡 |
| `Toolset` | 一组可启停工具，如 `web`、`runtime`、`skills`、`mcp:github` | 只进名称和 1 行摘要 |
| `ToolProfile` | 本轮默认暴露哪些 toolsets | 只进 profile 名和工具卡 |
| `RiskLevel` | 调用前是否需要确认 | 只在工具卡上用 1 个词标注 |
| `ToolHarness` | 执行、审计、压缩、回放、loop 防护 | 不进 prompt，运行时内部执行 |

**Tool groups**:

```ts
type ToolGroup =
  | "fs"           // file_read/edit/apply_patch
  | "runtime"     // exec/process/code_run
  | "web"          // search/fetch/extract
  | "browser"      // interactive browser
  | "sessions"     // status/history/spawn/cancel
  | "memory"       // memory read/search/write
  | "skills"       // skills list/view/manage/eval
  | "automation"   // watch/cron; tasks/flows are optional extensions
  | "messaging"    // send_message/platform delivery
  | "media"        // vision/image/tts/pdf/video
  | "integrations" // android/homeassistant/calendar/mail/mcp
  | "admin";       // gateway/config/provider management
```

**Profiles 只保留四个基础款**：

| Profile | 默认 toolsets | 说明 |
|---------|---------------|------|
| `minimal` | `sessions:status`, `ask_user` | 高风险环境、只读状态 |
| `coding` | `fs`, `runtime`, `web`, `sessions`, `memory:read`, `skills:read` | 本地开发任务 |
| `messaging` | `messaging`, `sessions`, `memory:read`, `skills:read` | IM/移动端渠道 |
| `full` | 除 `admin` 外的可用工具 | 本地可信 CLI |

`research` 和 `automation` 不做独立 profile，改成 task hints：模型可以从 `coding` 或 `full` 中选择更少工具；长期任务先由 `cronjob` 表达，`tasks/flows` 作为后续扩展。

**四级风险足够**：

| Risk | 例子 | 默认处理 |
|------|------|----------|
| `read` | `file_read`、`web_search`、`memory_search`、`skills_list` | profile 允许即执行 |
| `write` | `file_patch`、`memory_write_candidate`、`skill_manage patch` | 可信 workspace 内执行，写 RunLedger，可回滚 |
| `external` | 发消息、发邮件、公开发布、付款、删除远端资源 | 执行前确认，或要求 standing authority |
| `admin` | gateway config、provider key、全局安全策略、安装第三方 tool/plugin | 不暴露给普通 run，只能 owner 显式调用 |

四级风险是用户侧和 prompt 侧的压缩表示；ActionEngine 内部还必须计算副作用标记，避免把 `exec`、浏览器、MCP 等复杂工具简化成一个 `write`。

```ts
type SideEffectFlag =
  | "filesystem_write"
  | "destructive"
  | "network"
  | "secret_read"
  | "process_spawn"
  | "install"
  | "inline_eval"
  | "credential"
  | "external_delivery"
  | "permission_change";

interface ToolRiskEnvelope {
  risk: "read" | "write" | "external" | "admin";
  sideEffects: SideEffectFlag[];
  requiresProbe: boolean;
  requiresDecisionCard: boolean;
  sandbox: "none" | "workspace" | "docker" | "remote";
}
```

`exec` 默认是 `write + process_spawn`，只有静态 allowlist 命中时才降级为普通 write。出现 `destructive`、`secret_read`、`install`、`credential`、`permission_change`、`external_delivery` 或非 allowlist 的 `network` 时，ActionEngine 必须升级为 Decision Card、sandbox 或拒绝。

`deny` 永远优先。复杂的 provider/platform/backend 策略留在配置和 harness 内部，不进入 prompt：

```yaml
tools:
  profile: coding
  deny: [gateway_config_patch, provider_key_write]
  backend:
    exec: local          # local|docker|ssh|modal|daytona
    untrusted_input: docker
```

**短工具卡格式**:

```text
file_read(path, range?) - read workspace files [read]
apply_patch(patch) - edit files by patch [write]
exec(cmd, cwd?) - run shell command; probe first [write]
web_search(query) - current web search [read]
skills_list(query?) - list matching skills [read]
skill_manage(action,name,patch?) - create/patch local skills [write]
send_message(target,text) - deliver message externally [external]
gateway_config_patch(path,value) - gateway/admin config [admin]
```

Prompt 预算规则：

- 默认只展示当前 profile 的工具卡，目标控制在 20 行以内。
- 不展示完整 JSON schema；模型选中工具后由 runtime 注入严格 schema。
- runtime 注入 schema 时优先使用版本化 `ToolBundle`，同一 Mission 内尽量冻结，避免每轮 schema 变化打掉 KV cache。
- prompt 只展示四级风险；side-effect flags 留在 ActionEngine / ToolHarness，不进 prompt。
- 不展示不可用工具、被 deny 工具、admin 工具。
- MCP 工具按 `mcp:<server>` 汇总为 1 行，只有被模型选中时展开具体工具。
- 工具结果默认先摘要，原始输出只进 RunLedger；需要时再由模型请求展开。

运行时格式原则：

- prompt 里的工具卡只是给模型阅读的 affordance，不是可执行契约。
- canonical tool call 统一为 `{name, arguments, call_id, risk, source}`，只在 provider 边界层规范化；模型侧优先使用 OpenAI / Anthropic / Gemini 的原生 tool call。
- `ToolRegistry` 是内部事实源；`ProviderToolAdapter` 把同一个 ToolBundle 编译成 OpenAI `tools`、Anthropic `tools` 或其他 provider 的原生 schema。
- OpenAI 路径：发送稳定 `tools` + `tool_choice:auto` 或受限选择，接收 function tool call，执行后用对应 call id 回填 function tool output。
- Anthropic 路径：发送稳定 `tools` + `tool_choice:auto`，接收 `tool_use` blocks，执行后在下一条 user message 中回填对应 `tool_result` blocks。
- 同一轮可以有多个 tool calls；ToolHarness 可以并行执行互不冲突的 read-only calls，但 write/external/admin 默认串行并保留确认点。
- XML-wrapped JSON 只作为 raw text 模型 fallback、训练轨迹和 replay 格式；不能作为默认执行通道。
- 用户消息、网页、文件、assistant 普通文本中出现 `<tool_call>` 或类似标签时，默认当作内容展示，不执行。
- ToolHarness 执行前必须重新做 allowlist、schema parse、risk guard 和 ApprovalGate 检查。

**调用链保持短**:

```
模型产生 provider-native tool call
  → ProviderToolAdapter 规范化 call id/name/arguments/source
  → ActionEngine 检查 profile + deny + risk + schema
  → 内置确认只处理 external/admin/高风险 write
  → ToolHarness 执行 + 压缩结果 + 写 RunLedger
  → ProviderToolAdapter 回填 provider-native tool result
  → ToolLoopGuard 阻止重复无效调用
```

这样保留主流系统的兼容边界，同时避免把权限管控做成重型策略系统。

### 13.4 Tool 自演进机制（Tool Candidate）

> **核心理念**: 稳定、机械、低语义判断的工具序列可以成为工具；其余重复做法先沉淀成 SOP skill。

Tool 自演进不需要单独的规则引擎。执行结束后，同一份 learning packet 暴露 `tool_propose_candidate` 能力；模型只有在看到“稳定输入输出、固定副作用、低语义判断、可回滚、可评测”的证据时，才把某段工具链提议成 generated tool。

```ts
interface ToolCandidateTool {
  proposeCandidate(input: {
    runId: string;
    name: string;
    description: string;
    inputSchema: JsonSchema;
    outputSchema: JsonSchema;
    risk: "read" | "write" | "external" | "admin";
    evidenceRefs: EvidenceRef[];
    rollbackPlan: string;
    evalCases: string[];
  }): Promise<ToolDraft>;
}
```

示例：模型可能把“读取 PR 列表并规范化 JSON 字段”提议成工具；但“PR 是否该合并”“如何向用户解释风险”仍留给模型。系统只检查 schema、权限、risk、eval 和 rollback，不按固定次数阈值自动晋升。

Rollback 是 generated tool 的一等生命周期动作：触发后 generated tool 和来源 candidate 都进入 `rolled_back`，不删除历史；若模型之后仍认为它值得恢复，必须重新通过 review/eval gate。

### 13.5 Tool 文件格式（Generated Tools）

```yaml
# ~/.mnemo/tools/morning-context-load.tool.yaml
---
name: morning-context-load
version: 1
category: workflow
source: generated          # generated | user-defined
promoted_from: pattern     # pattern | manual
observation_count: 4
confidence: 0.91
created: 2026-04-10
activated: 2026-04-11      # 用户确认激活的日期
last_used: 2026-04-22
use_count: 8

# 触发条件 (何时建议使用这个工具)
suggest_on:
  - "早上第一条消息"
  - "新会话开始时"
  - "keywords: [早上, 今天, 开始]"

# 执行步骤
steps:
  - tool: memory_read
    args: {level: L1}
    label: "加载记忆索引"
  - tool: watch_list
    args: {}
    label: "检查关注点状态"
  - tool: web_search
    args: {query: "today important AI news", num_results: 3}
    label: "获取今日 AI 动态"
  - tool: memory_read
    args: {path: "context/current-projects"}
    label: "加载当前项目上下文"

# 产出格式
output_template: |
  ## 晨间上下文
  {{ memory_index }}
  
  ## 关注点 ({{ watch_count }} 个)
  {{ watch_summary }}
  
  ## 今日 AI 动态
  {{ ai_news }}
  
  ## 当前项目
  {{ projects }}
---
```

### 13.6 Agent 自写工具

Agent 不只能"提议宏工具"，还能在任务中**直接编写新工具**。这些动作仍通过 provider-native tool call 调用 Mnemo 暴露的 `skill_manage`、`file_write`、`tool_propose_candidate` 等工具；模型不手写 Mnemo 私有 XML 指令：

```python
# 在 agentic loop 中，Agent 遇到重复且可自动化的模式时，可以：

# 1. 调用 skill_manage 写一个 SOP 型 SKILL.md
skill_manage(action="create", name="check-github-prs", content="""
---
name: check-github-prs
description: Check open GitHub PRs and summarize blockers. Use when the user asks for PR status or a scheduled PR watch fires.
compatibility: Requires git, gh CLI, and GitHub network access.
metadata:
  mnemo:
    type: sop
    status: draft
---

# Check GitHub PRs

## 何时使用
用户询问 PR 状态时，或每日早晨上下文加载时。

## 步骤
1. Use `gh pr list --author @me --state open --json number,title,url,isDraft`.
2. For each relevant PR, inspect reviews, status checks, and changed files.
3. Summarize open count, blockers, required review, failing checks, and next action.

## Verification
- State if CLI auth or repo inference blocked full inspection.
- Do not merge or comment without explicit approval.
""")

# 2. 对于需要代码执行的工具，写 .tool.yaml + tool_code
file_write(
    path="~/.mnemo/tools/github-pr-check.tool.yaml",
    content="""
name: github-pr-check
type: executable
runtime: python
code: |
    import subprocess, json
    result = subprocess.run(["gh", "pr", "list", "--author", "@me", "--json", "number,title,url"], 
                           capture_output=True, text=True)
    prs = json.loads(result.stdout)
    return {"open_prs": len(prs), "items": prs}
"""
)
```

---
