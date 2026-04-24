# Evolution Loops

> Mnemo 的三条自演进闭环：Memory、Skills、Tools。它们共享同一套原则：模型做语义判断，RunLedger 保留证据，Harness 验证收益，低风险自动推进，高风险进入用户确认。

## 1. 总览

Mnemo 的自演进不是“越用越多地写规则”，而是把用户派活过程中的信号转成可验证、可回滚、可复用的系统能力。

```text
User delegates work in one chat
  → AgentRunHarness executes
  → RunLedger records prompt/tool/artifact/result events
  → W0 captures temporary state + observations
  → model receives a learning packet when useful
  → model may propose 0..N mixed candidates
  → candidate tools validate evidence/risk/schema
  → low-risk candidates enter draft/shadow; high-risk items enter Inbox
  → future runs may recall/use candidates
  → replay/eval measures whether they actually helped
```

Mnemo 不定义“先抽 memory、再抽 skill、再抽 tool”的 workflow。同一段执行轨迹可能同时产生多个候选，也可能一个都没有。系统提供统一 learning packet 和候选写入工具；模型自己判断要不要学、学成什么类型、是否需要后续校验。

三条闭环：

| Loop | 学到什么 | 产物 | 主要文件 |
|------|----------|------|----------|
| Memory Evolution | 用户事实、偏好、边界、长期上下文 | L2 wiki page、L1 index、tombstone、health card | [01-memory-engine.md](01-memory-engine.md) |
| Skills Evolution | 这类任务该怎么做 | `SKILL.md`、SOP skill、skill patch | [02-skills-tools.md](02-skills-tools.md) |
| Tools Evolution | 稳定机械工具链如何固化 | generated `.tool.yaml`、tool profile candidate | [02-skills-tools.md](02-skills-tools.md#134-tool-自演进机制tool-candidate) |

## 2. Memory Evolution

目标：让 Mnemo 越来越懂这个用户，但不把临时状态、错误推断、过时事实污染长期记忆。

```text
learning packet
  → model proposes memory candidates when durable user facts/preferences/boundaries exist
  → memory_write_candidate validates evidence, scope, confidence and taint
  → conflict/tombstone checks run only for memory candidates
  → accepted candidates update L2 draft or write batch
  → later compile updates L1/L0
```

关键设计：
- W0 是 Mission/turn 暂存，不是长期记忆。
- DreamCycle 只看增量，不全量扫库。
- 写入必须带 evidence、confidence、provenance 和 exposure。
- 过时记忆通过 decay/tombstone 退出 active recall。
- 用户纠正优先级高于模型推断。

成功标准：
- 明确事实能被召回。
- 过时事实不会复活。
- 偏好能改变后续行为。
- 不在无关任务里过度个性化。

## 3. Skills Evolution

目标：把重复任务的做法沉淀成模型可读的程序性记忆，同时保持主流 Agent Skills 兼容。

```text
learning packet
  → model proposes skill candidates when a reusable procedure appears
  → skill_propose_candidate writes draft SKILL.md or patch with evidence refs
  → shadow/eval applies only to skill candidates
  → future model-led loop may view/select/reject it per task
  → RunLedger records outcome and rollback evidence
```

关键设计：
- Skill 是 procedure，不是偏好规则。
- Skill 进入 prompt 采用 progressive disclosure。
- 规则只触发候选挖掘，不能直接决定使用哪个 skill。
- SOP 是 skill 子类型，不绕过模型。
- 外部 skills 默认只读或 shadow copy，避免供应链污染。

成功标准：
- 应该使用时能被选中，不该使用时能被拒绝。
- 加载 skill 后任务成功率、工具效率或偏好遵循提升。
- skill patch 有证据、可回放、可回滚。
- 与 memory/boundary 冲突时降级或请求确认。

## 4. Tools Evolution

目标：把稳定、机械、高频的工具序列晋升为更低成本的工具，但避免过早生成工具平台。

Tools Evolution 的正确顺序是：

```text
learning packet
  → model proposes tool candidates only for stable mechanical sequences
  → tool_propose_candidate writes spec draft with input/output/risk/evidence
  → shadow dry-run/eval applies only to tool candidates
  → activation requires risk review and rollback path
```

关键设计：
- 先 SOP，后工具。不要一看到重复序列就生成工具。
- generated tool 只处理机械步骤；判断、取舍、风险解释仍由模型做。
- 工具必须声明 input schema、risk、required capabilities、rollback 和 eval cases。
- external/admin 风险工具不能静默晋升。
- 工具输出必须压缩后进入模型，原始输出只进 RunLedger。

成功标准：
- 降低 token、工具调用次数或失败率。
- 不降低任务质量和个性化遵循。
- 失败可回放，可禁用，可回滚。
- 不扩大权限面。

## 5. 统一治理

三条自演进闭环共用同一套治理：

统一 learning packet：

```yaml
run_id: string
mission_summary: string
user_messages: []
assistant_summary: string
tool_calls: []
tool_results_summary: []
artifact_changes: []
user_corrections: []
accepted_outputs: []
failures_or_retries: []
candidate_context:
  memory_hits: []
  skills_viewed: []
  tools_used: []
budget:
  max_candidates: 8
```

候选工具：

| Tool | 用途 |
|------|------|
| `memory_write_candidate` | 写入事实、偏好、目标、边界、冲突或 tombstone 候选 |
| `skill_propose_candidate` | 写入 SKILL.md 草稿或 patch 候选 |
| `tool_propose_candidate` | 写入 generated tool spec 候选 |
| `eval_propose_case` | 从失败、纠正或关键成功轨迹生成 replay/eval case |
| `learning_discard` | 记录为什么不学习，避免下次重复分析 |

模型可以一次调用多个候选工具，也可以完全不调用。系统只负责校验证据、风险、schema、权限和回滚条件。

| 机制 | Memory | Skills | Tools |
|------|--------|--------|-------|
| Evidence | evidence quote / source / run_id | run traces / user corrections | tool_calls / outputs / timings |
| Candidate Store | W0 / write batch | `skills/_generated/` | `tools/_generated/` |
| Shadow Mode | draft facts / low confidence | shadow skill | shadow tool |
| Evaluation | memory-safety / personalization | selection/replay/conflict eval | replay/dry-run/side-effect eval |
| Activation | write pipeline + compile | available → active/promoted skill | active generated tool |
| Rollback | audit log / tombstone | skill version rollback | disable tool / revert tool yaml |
| User Confirmation | conflict/private/high confidence | high-risk skill patch | external/admin/high-risk tool |

全局约束：
- 自演进不能只看频次，必须看是否提升用户结果。
- 所有候选、选择、激活和回滚都写 RunLedger。
- 模型负责语义判断；规则只做候选生成、安全护栏和资源边界。
- 默认低打扰：低风险进入 shadow/available；active/promoted 必须过 eval gate，高风险进入 Inbox/Decision。

## 6. 在设计包中的位置

- 记忆自演进：见 [01-memory-engine.md](01-memory-engine.md) 的 W0、MemoryWritePipeline、DreamCycle、MemoryCompiler、tombstone。
- Skills 自演进：见 [02-skills-tools.md](02-skills-tools.md) 的 skill candidate tools、SkillHarness、SOP Skills、兼容层。
- Tools 自演进：见 [02-skills-tools.md](02-skills-tools.md#134-tool-自演进机制tool-candidate) 的 Tool Candidate、Generated Tools、Agent 自写工具。
- 运行与审计：见 [07-runtime-harness.md](07-runtime-harness.md) 的 RunLedger、Mission checkpoint、Personalization Eval。
- 路线图与原则：见 [09-roadmap-principles.md](09-roadmap-principles.md) 的 Phase 2、Extension Packs、核心原则。
