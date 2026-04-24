# Proactive, Sense And Inbox

> Watch、主动服务、设备感知、Android Companion 和无感化 Inbox。

## 7. 主动服务引擎

### 7.1 设计哲学

> 被动 AI: 你问它才说。
> 主动 AI OS: 它在你问之前已经想好了。

主动服务的三个层次：

| 层次 | 触发 | 示例 |
|------|------|------|
| **Temporal 提醒** | 时间触发 | "你说今天要回复 Alice 的邮件" |
| **Watch 监测** | 条件触发 | "你的 Rust 学习进度比预期慢了 2 周" |
| **Pattern 洞察** | 模式触发 | "你连续 3 周在周三下午生产力最低，这周你有个重要 deadline" |

### 7.2 Watch Engine（关注点引擎）

```yaml
# watches/rust-progress.yaml
---
id: rust-progress
name: Rust 学习进度追踪
dimension: goals
linked_page: wiki/goals/learn-rust.md

trigger:
  type: periodic
  schedule: "0 9 * * 1"    # 每周一 9:00
  also_on: [context_match]  # 用户提到 Rust 时也触发

context_match:
  keywords: [rust, lifetimes, async, cargo]

check_prompt: |
  Based on the user's Rust learning goal (target: Q4 2026 production-ready)
  and any recent mentions of Rust progress:
  1. Are they on track?
  2. Any blockers mentioned?
  3. Any wins to acknowledge?
  Respond with: status(on_track|behind|ahead), summary(1 sentence), action(optional)

delivery:
  silent_if: "status == on_track and no_new_info"
  format: brief   # brief | detailed
  channel: primary  # 通过主要渠道(CLI/Telegram等)推送

state:
  last_run: 2026-04-19
  last_status: on_track
  streak_on_track: 3
---
```

```python
class WatchEngine:
    """
    关注点监测引擎.
    
    Watch 类型:
    - goal_tracker: 追踪目标进展
    - pattern_monitor: 监测行为模式异常
    - temporal_reminder: 时间型提醒
    - context_trigger: 特定上下文触发
    - health_check: 与记忆一致性检查
    """
    
    def tick(self) -> list[WatchResult]:
        """每分钟被 CronDaemon 调用, 返回需要推送的结果"""
    
    def check_watch(self, watch: Watch) -> WatchResult:
        """执行单个 watch 的检查逻辑, 调用 LLM 评估"""
    
    def add_from_conversation(
        self, 
        user_msg: str, 
        extracted_watch: WatchDraft,
    ) -> Watch:
        """
        从对话中自动创建新 Watch.
        
        当用户说 "帮我追踪 X" / "提醒我 Y" / "关注 Z 的进展" 时,
        Agent 调用此方法自动注册关注点.
        """
```

### 7.3 Proactive Daemon（主动服务守护进程）

```python
class ProactiveDaemon:
    """
    后台守护进程, 驱动所有主动服务行为.
    
    职责:
    1. 每分钟: WatchEngine.tick() → 检查到期 watch
    2. 空闲窗口/每天 02:00: DreamCycle.run() → 记忆整理、编译、健康检查
    3. 每天 06:30: MorningBriefing → 生成晨报 (如果启用)
    4. 每周日: DreamCycle.extended() → 技能挖掘 + 本体论审计
    5. 实时: context_trigger 监测 (对话流中匹配关键词)
    """
    
    def morning_briefing(self) -> str:
        """
        晨报生成（仅在 Soul.md 启用早报且当前时段匹配时运行）:
        
        每日概况:
        - 今日目标: [goals 中 deadline 临近的]
        - 最近 Watch 更新: [有进展的 watch 结果]
        - Inbox 待办: [未处理的高优记忆矛盾]
        
        格式: <400 tokens，推送后等待 2 小时才发下一条
        不产生 Inbox 条目——晨报内容是建议，不是任务
        """
    
    def should_deliver(self, push: PushCandidate) -> bool:
        """
        推送静默判断:
        
        静默条件（任一满足 → 跳过本次推送，写入 push_queue 等下一个时机）:
        1. 当前在安静时段 (Soul.md quiet_hours: e.g. 23:00-07:00)
        2. 当前有活跃对话（last_interaction < 3 分钟前）
        3. 同一 watch 今天已推送两次
        4. 该 watch 连续 3 次推送均无反馈（→ 自动降为 periodic*7 缓存期）
        5. 设备状态为"驾驶"或"睡眠"（来自 SenseEngine）
        """
    
    def record_push_feedback(self, push_id: str, feedback: PushFeedback) -> None:
        """
        记录推送反馈（系统自动统计，不需要用户主动操作）:
        
        正反馈信号（自动检测）:
        - 用户在推送后 5 分钟内发起对话引用了推送内容 → positive
        - 用户点击"有用"（如有 UI）→ explicit_positive
        
        负反馈信号（自动检测）:
        - 用户 dismiss 了推送 → negative
        - 用户说"别再提这个" → explicit_negative → watch.snooze(days=30)
        - 连续 3 次推送没有任何反应 → implicit_ignore → 降低频率
        
        学习效果: Watch 自动调整 check_interval 和优先级
        """
```

### 7.4 主动推送流程

```
CronDaemon.tick()
    │
    ├─ WatchEngine.check_due_watches()
    │      │
    │      ├─ [periodic watch to run]
    │      │   ├─ load_watch_context()
    │      │   │   ├─ L0 Profile Card
    │      │   │   ├─ linked L2 page
    │      │   │   └─ recent session summary
    │      │   ├─ should_deliver() → False → skip + backoff
    │      │   ├─ llm_call(check_prompt, context)
    │      │   ├─ parse_result(status, summary, action)
    │      │   └─ if not silent → delivery_queue.push(result)
    │      │
    │      └─ [context_trigger keyword match in live conversation]
    │          └─ inject watch status into next turn context
    │
    └─ delivery_queue.flush()
           ├─ CLI: print formatted block
           ├─ MCP: push notification
           └─ REST: webhook callback

**推送自学习循环**:
每次推送记录 push_log; record_push_feedback() 收集正/负信号;
连续 3 次 implicit_ignore → check_interval *= 3 (自动稀疏化);
push_acceptance_rate < 10% for 2 weeks → watch 自动进入 hibernation
```

---
---

## 15. 感知架构——主动服务的触发层

### 15.1 感知总体设计

```
╔══════════════════════════════════════════════════════════════════╗
║                     Mnemo Sensing Stack                          ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Tier 1: Device Sensors (设备侧采集)                             ║
║  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐         ║
║  │ Android App  │   │  iOS/Watch   │   │  PC Daemon   │         ║
║  │  Companion   │   │  Companion   │   │              │         ║
║  │              │   │              │   │              │         ║
║  │ GPS/Cell/WiFi│   │ GPS/BLE/HK   │   │ App focus    │         ║
║  │ BLE beacons  │   │ Activity     │   │ Calendar     │         ║
║  │ Accelerometer│   │ Heart rate   │   │ Screen state │         ║
║  │ Screen state │   │              │   │              │         ║
║  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘         ║
║         │                  │                  │                  ║
║  Tier 2: Event Transport (事件传输)                              ║
║         └──────────────────┴──────────────────┘                 ║
║                            │                                     ║
║         WebSocket / HTTP POST → SenseEngine                      ║
║                            │                                     ║
║  Tier 3: SenseEngine (服务器侧处理)                              ║
║  ┌──────────────────────────────────────────────────────────┐    ║
║  │  EventNormalizer → ContextBuilder → OpportunityScorer   │    ║
║  │         ↓                                               │    ║
║  │  WatchMatcher → ActionDecider → MessageBus.publish()   │    ║
║  └──────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════╝
```

### 15.2 Android Companion App

Android 感知是最完整的移动端感知层，负责以下数据采集：

```kotlin
// Android Companion App 事件上报 (Kotlin)

data class SenseEvent(
    val device_id: String,
    val timestamp: Long,
    val event_type: SenseEventType,
    val payload: Map<String, Any>,
    val battery_ok: Boolean,   // 低电量时降频上报
)

enum class SenseEventType {
    // 位置类
    LOCATION_UPDATE,            // 定期位置更新 (100m 变化 or 5分钟)
    GEOFENCE_ENTER,             // 进入已注册地理围栏
    GEOFENCE_EXIT,              // 离开已注册地理围栏
    
    // 网络类  
    WIFI_CONNECTED,             // 连接新 WiFi (SSID + BSSID)
    WIFI_DISCONNECTED,          // 断开 WiFi
    BLE_BEACON_SEEN,            // 发现已注册 BLE beacon
    
    // 活动类
    ACTIVITY_CHANGED,           // 活动状态变化 (WALKING/DRIVING/STILL/RUNNING)
    SCREEN_ON,                  // 屏幕亮起
    SCREEN_OFF,                 // 屏幕熄灭
    APP_FOREGROUND,             // 特定 App 进入前台
    
    // 业务类 (需要额外权限)
    CALENDAR_EVENT_SOON,        // 日历事件 N 分钟后开始
    NOTIFICATION_CATEGORY,      // 通知类别（不含内容，只含 category/app）
    NFC_TAG_READ,               // NFC 标签读取
    PAYMENT_COMPLETE,           // 支付完成（来自 Accessibility Service）
}

// 事件上报频率策略
object ReportingPolicy {
    val LOCATION_MIN_INTERVAL_MS = 5 * 60 * 1000L     // 5 分钟
    val LOCATION_MIN_DISTANCE_M = 100f                  // 100 米
    val ACTIVITY_DEBOUNCE_MS = 30 * 1000L              // 30 秒防抖
    val BATTERY_REDUCED_THRESHOLD = 20                  // 电量 < 20% 时降频
    
    // 用户控制的隐私边界
    var location_permission: PermissionLevel = COARSE   // NONE/COARSE/FINE
    var call_log_permission: Boolean = false             // 默认不采集通话记录
    var notification_listener: Boolean = false           // 默认不读通知内容
}
```

### 15.3 SenseEngine（服务器端）

```python
class SenseEngine:
    """
    处理来自设备的感知事件，触发主动服务决策。
    """
    
    def process_event(self, event: SenseEvent) -> list[ProactiveAction]:
        """
        事件处理管线:
        1. 规范化事件 (统一格式)
        2. 丰富上下文 (从记忆中查找相关信息)
        3. 计算机会分数
        4. 匹配 Watch 触发条件
        5. 生成候选主动动作
        6. 按级别分类 (静默准备/轻提醒/确认卡/自动执行)
        """
    
    def _enrich_context(self, event: SenseEvent) -> EnrichedEvent:
        """
        给裸事件附加记忆上下文:
        
        WIFI_CONNECTED(ssid="Company-Corp") 
          → memory_search("Company-Corp") 
          → 找到: wiki/context/workplaces.md 中记录的"工作地点"
          → enriched: {"place_type": "work", "known_place": True, "place_name": "公司"}
        
        GEOFENCE_ENTER(lat=39.9, lng=116.4)
          → memory_search("餐厅 XX") 
          → 找到: wiki/relationships/favorite-places.md 
          → enriched: {"place_type": "restaurant", "visit_count": 12, "last_visit": "3d"}
        """
    
    def _calculate_opportunity_score(
        self, 
        event: EnrichedEvent,
        current_activity: ActivityState,
        current_time: datetime,
    ) -> float:
        """
        机会分数 = 
            expected_utility
            - interruption_cost(activity, time_of_day)
            - disclosure_cost(required_info, recipient_trust)
            + urgency(deadline_proximity)
            + confidence(context_match)
            - risk(reversibility, amount)
        
        interruption_cost 规则:
          DRIVING: +3.0 (高打扰成本，只允许 L1 静默准备)
          MEETING/CALL: +2.5
          SLEEPING (22:00-7:00): +4.0 (非紧急不触发)
          WALKING/TRANSIT: +0.5 (适合轻提醒)
          STILL/IDLE: 0.0
        """
    
    def _decide_action_level(self, score: float, risk: float) -> ActionLevel:
        """
        L1 静默准备:  score < 0.4
        L2 轻推送:    0.4 ≤ score < 0.6 and risk < 0.3
        L3 确认卡:    score ≥ 0.6 or risk ≥ 0.3
        L4 自动执行:  score ≥ 0.85 and risk < 0.1 and user_policy_allows
        """
```

### 15.4 感知触发 Watch 的具体示例

```python
# 示例: 进入餐厅 WiFi 触发主动服务

# 1. Android 上报: WIFI_CONNECTED(ssid="ZhangWei-Restaurant-Free")
# 2. SenseEngine.enrich: 
#    → memory_search("ZhangWei-Restaurant-Free") 
#    → 匹配 wiki/preferences/dining.md 中"美味小馆常去WiFi"
#    → enriched: {place="美味小馆", visit_count=8, last_visit="1w"}
# 3. OpportunityScorer:
#    → expected_utility=0.7 (省去当场选菜时间)
#    → interruption_cost=0 (step=WALKING, time=12:15=午餐时间窗口)
#    → disclosure_cost=0.2 (只需分享口味偏好，不涉及敏感信息)
#    → urgency=0.3 (用餐窗口)
#    → score = 0.7 - 0 - 0.2 + 0.3 = 0.8 → L3 确认卡
# 4. WatchMatcher:
#    → 匹配 watch: "dining-assist" (type=context_trigger, keywords=[餐厅,WiFi])
# 5. 生成主动动作:
#    → 载入 wiki/preferences/dining.md (忌口、偏好、预算)
#    → 生成最小披露胶囊
#    → 推送确认卡到手机

ACTION_DECISION = ProactiveAction(
    level=ActionLevel.L3_CONFIRMATION_CARD,
    trigger_reason="进入美味小馆（第 9 次）；午餐时间窗口",
    proposed_context="将向美味小馆分享：忌口(花生过敏)、口味偏好(低辣)、预算(50-80元)",
    proposed_action="推荐常点套餐并预留靠窗位置",
    disclosure_capsule=MinimalCapsule(
        fields=["spice_tolerance", "allergy_list", "budget_range", "seating_pref"],
        expires_in_minutes=45,
        purpose="本次用餐推荐",
    ),
)
```

### 15.5 感知工具（in-session）

```python
# Android Bridge 工具 (Integration toolset, 需要 Android Companion 已连接)

ANDROID_SENSE_TOOLS = {
    "android_get_location": {
        "desc": "获取当前位置（lat/lng + 附近地标）",
        "params": {"accuracy": "coarse|fine"},
        "requires": "android_companion_connected",
    },
    "android_get_activity": {
        "desc": "获取当前活动状态（驾驶/步行/静止）",
        "params": {},
    },
    "android_get_context": {
        "desc": "获取当前完整感知快照（位置+活动+WiFi+前台App+电量）",
        "params": {},
    },
    "android_set_geofence": {
        "desc": "注册地理围栏，进入/离开时触发 Watch",
        "params": {"name": "str", "lat": "float", "lng": "float", "radius_m": "int"},
    },
    "android_send_notification": {
        "desc": "向 Android 设备推送通知（证据卡或提醒）",
        "params": {"title": "str", "body": "str", "action_buttons": "list?", "priority": "high|normal|low"},
    },
}
```

---
---

## 21. 异步通知收件箱（Inbox）——无感化设计基础设施

### 21.1 设计动机

Mnemo 核心原则之一是**不在任务过程中打断用户**。但系统仍需一种机制：
- 通知用户"我做了 X"（已激活技能、已更新记忆）
- 请求确认"我遇到了 Y"（高优矛盾、危险操作）
- 聚合所有低优先级审核项（45 天内自行决定即可）

Inbox 是这个机制：**所有"可能需要你知道的事"都放进 Inbox；你什么时候打开都行，不打开也无妨。**

### 21.2 Inbox 数据模型

```sql
-- inbox 条目表
CREATE TABLE inbox (
    id          TEXT PRIMARY KEY,           -- ulid
    priority    INTEGER NOT NULL DEFAULT 1, -- 0=critical 1=high 2=normal 3=low
    category    TEXT NOT NULL,              -- skill|conflict|memory|tool|system|watch
    title       TEXT NOT NULL,              -- 单行摘要 (<80 chars)
    body        TEXT,                       -- 可选的详细说明（Markdown）
    action_type TEXT,                       -- approve|reject|choose|ack|none
    action_data TEXT,                       -- JSON, 操作元数据
    expires_at  TEXT,                       -- ISO 8601; NULL = 永不过期
    resolved_at TEXT,
    resolution  TEXT,                       -- accepted|rejected|ignored|auto_expired
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inbox_priority ON inbox(priority, created_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inbox_category ON inbox(category, created_at DESC);
```

```python
@dataclass
class InboxItem:
    id: str                      # ulid
    priority: int                # 0=critical 1=high 2=normal 3=low
    category: str
    title: str
    body: str | None
    action_type: str             # "approve" | "reject" | "choose" | "ack" | "none"
    action_data: dict | None
    expires_at: datetime | None  # 默认: 技能类 30d, 矛盾类 14d, 通知类 7d
    created_at: datetime
```

**优先级语义**:

| 级别 | 值 | 含义 | 初次展示时机 |
|------|----|------|------------|
| critical | 0 | 核心事实矛盾、危险操作待确认 | 下一次会话开始时主动提及 |
| high | 1 | 重要记忆更新、高风险技能激活 | 晨报集成 / 下次主动推送时顺带展示 |
| normal | 2 | 新技能激活通知、MODERATE 冲突 | `mnemo inbox` 命令查看 |
| low | 3 | SOP 晶化通知、技能使用统计 | `mnemo inbox --all` |

### 21.3 Inbox 管理器

```python
class AsyncNotificationInbox:
    """
    Mnemo 全系统的异步通知收件箱。
    
    所有原本会打断用户的行为都改为写入 Inbox:
    
    原设计                        →  Inbox 版本
    ─────────────────────────────────────────────────────────
    "要激活这个技能吗？"             → category=skill, action=approve
    "我发现记忆矛盾，哪个对？"       → category=conflict, priority=critical/high
    "宏工具候选，是否晋升？"         → category=tool, action=approve
    "记忆已更新，供查看"             → category=memory, action=ack
    "你有 3 个 watch 已静默"         → category=watch, action=none
    """
    
    def push(
        self,
        category: str,
        title: str,
        priority: int = 2,
        body: str | None = None,
        action_type: str = "none",
        action_data: dict | None = None,
        expires_days: int | None = 14,
    ) -> InboxItem:
        """写入新 Inbox 条目（线程安全，写 SQLite inbox 表）"""
    
    def get_pending(
        self,
        priority_lte: int = 3,
        category: str | None = None,
    ) -> list[InboxItem]:
        """拉取所有未解决的条目，按 priority + created_at 排序"""
    
    def resolve(self, item_id: str, resolution: str, notes: str | None = None) -> None:
        """
        解决一个条目。
        resolution: "accepted" | "rejected" | "ignored"
        
        副作用:
        - approved skill → SkillRegistry.activate(item.action_data["skill_id"])
        - rejected skill → SkillRegistry.reject(...)
        - conflict choose → ConflictResolver.apply_user_choice(...)
        """
    
    def expire_stale(self) -> int:
        """
        每日 02:00 由 ProactiveDaemon 调用。
        
        - 超过 expires_at 的 normal/low 条目 → resolution=auto_expired
        - critical 条目: 14 天无回应 → 记录日志 + resolution=auto_resolved_by_system
          → 自动保留高置信侧，低置信侧标为 [ARCHIVED]
        """
    
    def surface_critical_at_session_start(self) -> str | None:
        """
        会话开始时，如果有 priority=0 (critical) 的未解决条目，
        返回一段简短的会话开场注入文本。
        
        例: "在我们开始之前，有一件事需要你确认：
             你之前告诉我在 TechCorp 工作，今天提到了 StartupXYZ。
             点击查看详情或直接告诉我哪个对。"
        
        每个 critical 条目只在开场展示一次（避免重复打扰）。
        """
```

### 21.4 会话开场注入策略

```python
class SessionStartupManager:
    """
    会话开始时的无感化注入控制器。
    
    注入优先级（按顺序，找到第一个有内容的就停止）:
    
    1. Inbox critical 条目 (priority=0) → 开场第一句话
    2. Watch 有高分机会但今天未推送 → 在第一轮回复末尾追加
    3. Inbox high 条目 (priority=1) 且 > 3 条 → 在自然停顿时提一句
       "另外，你有 3 条消息待查看 (mnemo inbox)"
    4. 其他 → 完全静默
    
    注意: 步骤 2-4 永远不在步骤 1 的同一会话开场中出现（不堆积打扰）
    """
    
    def get_session_prefix(self, context: SessionContext) -> str | None:
        """如果有需要注入的内容返回文本；否则返回 None"""
```

### 21.5 CLI 接口

```bash
# 查看所有待处理 Inbox（按优先级排序）
mnemo inbox

# 只看 critical + high
mnemo inbox --priority high

# 查看特定分类
mnemo inbox --category skill
mnemo inbox --category conflict

# 处理条目（交互式）
mnemo inbox resolve <id> [--accept | --reject | --ignore]

# 批量清除 low 优先级通知
mnemo inbox clear --priority low --older 7d

# 以 JSON 输出（供 UI 集成）
mnemo inbox --json
```

**示例输出**:
```
┌─────────────────────────────────────────────────────────────┐
│  Mnemo Inbox  (2 critical, 1 high, 4 normal)                │
├─────────────────────────────────────────────────────────────┤
│ [!] #3a2f  记忆矛盾需确认: 就业 (TechCorp vs StartupXYZ)    │
│            → conflict  [CRITICAL]  2026-04-22  [resolve]    │
│ [!] #1e8b  记忆更新: goals/career 已修改，旧版可回滚         │
│            → memory   [HIGH]      2026-04-21  [view|undo]   │
│ [·] #77c1  新 SOP 技能已激活: git-pr-review                  │
│            → skill    [normal]    2026-04-21  [view]        │
│ [·] #5d0e  宏工具候选: deploy-check (被调用 11 次)           │
│            → tool     [normal]    2026-04-20  [approve|skip]│
└─────────────────────────────────────────────────────────────┘
```

### 21.6 无感化程度配置 (Soul.md 集成)

用户可以在 `~/.mnemo/soul.md` 里调整无感化级别：

```yaml
# soul.md frontmatter 片段
autonomy:
  # 技能自动激活阈值（更高 = 更自动）
  skill_auto_activate_confidence: 0.85   # 默认值
  
  # 是否允许 critical 矛盾在开场注入提示
  surface_critical_conflicts: true       # 默认 true
  
  # 是否允许晨报
  morning_briefing: false                # 默认 false，用户按需开启
  
  # 推送安静时间段
  quiet_hours: ["23:00", "07:30"]        # 格式: [开始, 结束]
  
  # 每日最大主动推送次数（-1 = 不限）
  max_daily_pushes: 3
  
  # 驾驶/睡眠时屏蔽推送（需要 SenseEngine）
  respect_activity_state: true
```

**全自动模式** (`autonomy.fully_autonomous: true`): 所有 action 类条目自动 accept（等待 1 小时后执行），Inbox 只作为日志。适合高级用户信任系统决策。

---
