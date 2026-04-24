# Agent Extensions And Federation

> Sub-Agent、MessageBus、AgentCard、联邦和外部 Agent 协作。

## 14. Agent 间通信协议

### 14.1 通信模型总览

Mnemo 的 Agent 间通信分三个维度：

```text
1. Mnemo ↔ Sub-Agents
   主 Mnemo 将复杂任务拆分为临时子任务。
   子 Agent 只接收任务所需 context capsule，不继承完整记忆。

2. Mnemo ↔ External Agents
   Mnemo 向外部 runtime / agent harness 发送 task capsule。
   外部 runtime 只返回 structured result，不直接写 memory、skill 或 tool。

3. Mnemo ↔ Mnemo
   同一用户的工作/个人/沙箱实例可以选择性共享 wiki 页面。
   不做完整记忆同步。
```

### 14.2 Sub-Agent 生命周期

```python
class SubAgentSpawner:
    """
    设计原则:
    - 子 Agent 是临时执行体，不是长期身份。
    - 子 Agent 不继承完整 L0/L1，只接收任务所需 context capsule。
    - 子 Agent 不与用户直接对话。
    - 子 Agent 不创建 cron、memory、skill、tool 或持久状态。
    - 深度限制: 最大 spawn 深度 = 3。
    """

    def spawn(
        self,
        task: str,
        context_slice: ContextSlice,
        tools: list[str],
        depth: int = 1,
    ) -> SubAgentSession:
        """创建临时子 Agent。"""

    def announce_completion(
        self,
        session_key: str,
        result: str,
        metadata: dict,
    ) -> None:
        """结果 push 给父 Agent，父 Agent 负责合并和用户回复。"""
```

子 Agent system prompt 核心原则：

```text
You are a temporary bounded worker for Mnemo.
Complete only the assigned task.
Use only the provided context and tools.
Return structured evidence, changed artifacts, open questions, and confidence.
Do not contact the user.
Do not write memory, skills, tools, schedules, or persistent state.
```

### 14.3 MessageBus

首发实现不需要独立消息中间件，使用 SQLite `events/outbox` 表即可。未来需要多进程或多设备时再替换为真正的 MessageBus。

```python
class MnemoMessageBus:
    EVENT_TYPES = {
        "subagent.spawned": "子 Agent 已启动",
        "subagent.completed": "子 Agent 任务完成",
        "subagent.failed": "子 Agent 执行失败",

        "run.queued": "一次 Agent run 已入队",
        "run.started": "一次 Agent run 已开始",
        "run.completed": "一次 Agent run 已完成",
        "run.failed": "一次 Agent run 失败或超时",
        "run.recovered": "daemon 重启后恢复或标记历史 run",

        "approval.required": "高风险动作需要 Decision Card",
        "memory.compile_completed": "L0/L1 编译完成",
        "watch.check_due": "关注点到期需要检查",
        "watch.alert": "关注点产生提醒",
        "tool.pattern_detected": "发现重复工具调用模式",
    }

    def publish(self, event_type: str, payload: dict, priority: int = 5) -> None:
        """发布事件。priority: 1=最高, 10=最低。"""

    def get_pending_for_session(self, session_id: str) -> list[Event]:
        """获取当前会话需要处理的 pending 事件。"""
```

### 14.4 Agent Card

Agent Card 是对外能力描述，不是权限授予。外部 Agent 即使拿到 Agent Card，也必须通过 `RuntimeAdapter` 和 `ContextCapsule` 工作。

```json
{
  "agent_id": "mnemo-local",
  "agent_type": "personal-os",
  "version": "2.0",
  "capabilities": [
    {
      "id": "context-capsule",
      "description": "Receive a bounded task capsule with scoped personal context.",
      "input_schema": {"task": "string", "capsule": "object"},
      "output_schema": {"result": "object", "evidence": "array"}
    },
    {
      "id": "structured-return",
      "description": "Return task result, evidence, artifacts, and open questions.",
      "input_schema": {"task_id": "string", "result": "object"},
      "output_schema": {"ack": "boolean"}
    }
  ],
  "disclosure_policy": {
    "requires_task_capsule": true,
    "capsule_fields_only": true,
    "no_direct_memory_write": true,
    "no_direct_skill_write": true,
    "no_direct_tool_write": true
  }
}
```

### 14.5 Mnemo-to-Mnemo 联邦

当用户有多个 Mnemo 实例时，可以选择性共享 wiki 页面。共享的单位是页面或目录，不是完整数据库。

```yaml
instances:
  - id: mnemo-work
    endpoint: "http://localhost:7432"
    trust_level: high
    shared_pages:
      - "cognition/"
      - "values/"

  - id: mnemo-personal
    endpoint: "http://localhost:7433"
    trust_level: high
    shared_pages:
      - "cognition/"
      - "values/"
      - "patterns/health"

conflict_resolution: manual  # manual | newer_wins | higher_confidence
sync_schedule: "0 */6 * * *"
```

联邦规则：
- 默认不共享完整 L4 transcript。
- 默认不共享 relationships 和当前工作 context。
- 冲突不静默覆盖；低置信变更进入 Inbox。
- 同步只写候选 patch，仍经过 MemoryWritePipeline。
