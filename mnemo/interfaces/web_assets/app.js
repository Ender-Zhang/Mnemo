const MEMORY_DIMENSIONS = [
  "identity",
  "cognition",
  "values",
  "goals",
  "preferences",
  "relationships",
  "context",
  "history",
  "patterns",
  "boundaries",
];

const DIMENSION_LABELS = {
  identity: "身份",
  cognition: "认知",
  values: "价值",
  goals: "目标",
  preferences: "偏好",
  relationships: "关系",
  context: "语境",
  history: "历史",
  patterns: "模式",
  boundaries: "边界",
};

const MEMORY_KIND_LABELS = {
  page: "稳定记忆",
  candidate: "候选信号",
  memory: "记忆",
};

const MEMORY_STATUS_LABELS = {
  active: "稳定",
  pending: "待确认",
  draft: "候选",
  promoted: "已沉淀",
  rejected: "已忽略",
  tombstoned: "已忘记",
};

const MEMORY_EVIDENCE_LABELS = {
  source_candidate: "来源信号",
  source_page: "来源记忆",
  evidence: "对话证据",
  memory_safety: "安全校验",
  tool_result: "工具结果",
  session: "会话证据",
};

const state = {
  conversationId: localStorage.getItem("mnemo.conversation_id") || "",
  missionId: localStorage.getItem("mnemo.mission_id") || "",
  lastRunId: localStorage.getItem("mnemo.last_run_id") || "",
  activeRunId: "",
  lastEventId: localStorage.getItem("mnemo.last_event_id") || "",
  lastUserIntent: localStorage.getItem("mnemo.last_user_intent") || "",
  renderedEventIds: new Set(),
  busy: false,
  cancelRequested: false,
  pendingAssistantNode: null,
  assistantNode: null,
  activityRows: new Map(),
  railActionRows: new Map(),
  artifacts: new Map(),
  artifactRelated: new Map(),
  settings: null,
  catalog: null,
  memoryOntology: null,
  memoryDimensions: new Map(),
  memoryItems: new Map(),
  compactTools: localStorage.getItem("mnemo.ui.compact_tools") !== "false",
  streamMarkdown: localStorage.getItem("mnemo.ui.stream_markdown") !== "false",
};

const views = {
  chat: document.querySelector("#chatView"),
  memory: document.querySelector("#memoryView"),
  skills: document.querySelector("#skillsView"),
  tools: document.querySelector("#toolsView"),
  settings: document.querySelector("#settingsView"),
};

const navItems = document.querySelectorAll("[data-view]");
const closeSheetButtons = document.querySelectorAll("[data-close-sheet]");
const mobileSheetQuery = window.matchMedia("(max-width: 640px)");
const timeline = document.querySelector("#timeline");
const emptyState = document.querySelector("#emptyState");
const form = document.querySelector("#composer");
const input = document.querySelector("#message");
const send = document.querySelector("#send");
const stop = document.querySelector("#stop");
const reset = document.querySelector("#reset");
const statusText = document.querySelector("#status");
const runBadge = document.querySelector("#runBadge");
const contextUserPrompt = document.querySelector("#contextUserPrompt");
const attachButton = document.querySelector("#attachButton");
const mentionButton = document.querySelector("#mentionButton");
const toolIntentButton = document.querySelector("#toolIntentButton");
const glanceActivity = document.querySelector("#glanceActivity");
const glanceMemory = document.querySelector("#glanceMemory");
const glanceMemoryHint = document.querySelector("#glanceMemoryHint");
const glanceRuntime = document.querySelector("#glanceRuntime");
const railStatus = document.querySelector("#railStatus");
const railActivity = document.querySelector("#railActivity");
const railActivityRow = document.querySelector("#railActivityRow");
const railActionList = document.querySelector("#railActionList");
const railRecentIntent = document.querySelector("#railRecentIntent");
const railMemory = document.querySelector("#railMemory");
const railMemoryHint = document.querySelector("#railMemoryHint");
const railRuntime = document.querySelector("#railRuntime");
const railRun = document.querySelector("#railRun");
const memoryRefresh = document.querySelector("#memoryRefresh");
const memoryCompass = document.querySelector("#memoryCompass");
const memoryLayerDetail = document.querySelector("#memoryLayerDetail");
const memoryStats = document.querySelector("#memoryStats");
const memoryCountBadge = document.querySelector("#memoryCountBadge");
const memoryCoverageLabel = document.querySelector("#memoryCoverageLabel");
const memoryCoverageFill = document.querySelector("#memoryCoverageFill");
const memoryActiveTitle = document.querySelector("#memoryActiveTitle");
const memoryActiveSummary = document.querySelector("#memoryActiveSummary");
const memoryActiveMeta = document.querySelector("#memoryActiveMeta");
const settingsProviderForm = document.querySelector("#settingsProviderForm");
const providerTiles = document.querySelector("#providerTiles");
const settingProvider = document.querySelector("#settingProvider");
const settingModel = document.querySelector("#settingModel");
const settingBaseUrl = document.querySelector("#settingBaseUrl");
const settingApiKeyEnv = document.querySelector("#settingApiKeyEnv");
const settingTimeout = document.querySelector("#settingTimeout");
const settingRetryCount = document.querySelector("#settingRetryCount");
const settingRetryBackoff = document.querySelector("#settingRetryBackoff");
const settingMaxToolRounds = document.querySelector("#settingMaxToolRounds");
const quietEnabled = document.querySelector("#quietEnabled");
const quietStart = document.querySelector("#quietStart");
const quietEnd = document.querySelector("#quietEnd");
const quietTimezone = document.querySelector("#quietTimezone");
const compactTools = document.querySelector("#compactTools");
const streamMarkdown = document.querySelector("#streamMarkdown");
const saveExperience = document.querySelector("#saveExperience");
const settingsStatus = document.querySelector("#settingsStatus");
const settingsSummary = document.querySelector("#settingsSummary");
const memoryMarkdownPanel = document.querySelector("#memoryMarkdownPanel");
const memoryMarkdownTitle = document.querySelector("#memoryMarkdownTitle");
const memoryMarkdownBody = document.querySelector("#memoryMarkdownBody");
const memorySelectedMeta = document.querySelector("#memorySelectedMeta");
const skillsStatus = document.querySelector("#skillsStatus");
const skillsRefresh = document.querySelector("#skillsRefresh");
const skillsSummary = document.querySelector("#skillsSummary");
const skillsSearch = document.querySelector("#skillsSearch");
const skillsStatusFilter = document.querySelector("#skillsStatusFilter");
const skillsList = document.querySelector("#skillsList");
const toolsStatus = document.querySelector("#toolsStatus");
const toolsRefresh = document.querySelector("#toolsRefresh");
const toolsSummary = document.querySelector("#toolsSummary");
const toolsSearch = document.querySelector("#toolsSearch");
const toolsRiskFilter = document.querySelector("#toolsRiskFilter");
const toolsList = document.querySelector("#toolsList");

document.body.classList.toggle("compact-tools", state.compactTools);

for (const item of navItems) {
  item.addEventListener("click", () => {
    switchView(item.dataset.view || "chat", { updateLocation: true });
  });
}

for (const button of closeSheetButtons) {
  button.addEventListener("click", () => {
    switchView("chat", { updateLocation: true });
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || state.busy) return;
  input.value = "";
  resizeInput();
  runTurn(message);
});

input.addEventListener("input", () => {
  resizeInput();
  updateComposerState();
});
input.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  if (!state.busy) form.requestSubmit();
});

stop.addEventListener("click", () => {
  requestCancel();
});

reset.addEventListener("click", () => {
  if (state.busy) return;
  state.conversationId = "";
  state.missionId = "";
  state.lastRunId = "";
  state.activeRunId = "";
  state.lastEventId = "";
  state.lastUserIntent = "";
  state.renderedEventIds.clear();
  state.activityRows.clear();
  state.railActionRows.clear();
  state.artifacts.clear();
  state.artifactRelated.clear();
  localStorage.removeItem("mnemo.conversation_id");
  localStorage.removeItem("mnemo.mission_id");
  localStorage.removeItem("mnemo.last_run_id");
  localStorage.removeItem("mnemo.last_event_id");
  localStorage.removeItem("mnemo.last_user_intent");
  timeline.replaceChildren(emptyState);
  emptyState.hidden = false;
  input.value = "";
  resizeInput();
  if (railActionList) railActionList.replaceChildren();
  setText(glanceActivity, "等待派活");
  setText(railActivity, "等待派活");
  setStatus("空闲");
  updateContextPanel();
  updateComposerState();
  input.focus();
});

attachButton.addEventListener("click", () => {
  prefillMessage("请使用这个文件：");
});

mentionButton.addEventListener("click", () => {
  insertComposerText("@");
});

toolIntentButton.addEventListener("click", () => {
  insertComposerText("/");
});

for (const suggestion of document.querySelectorAll("[data-prefill]")) {
  suggestion.addEventListener("click", () => {
    prefillMessage(suggestion.dataset.prefill || "");
  });
}

memoryRefresh.addEventListener("click", () => {
  state.memoryOntology = null;
  state.memoryDimensions.clear();
  state.memoryItems.clear();
  loadMemoryCompass();
});

if (skillsRefresh) {
  skillsRefresh.addEventListener("click", () => {
    loadCatalog({ force: true });
  });
}

if (toolsRefresh) {
  toolsRefresh.addEventListener("click", () => {
    loadCatalog({ force: true });
  });
}

if (skillsSearch) {
  skillsSearch.addEventListener("input", () => {
    renderSkillsCatalog(state.catalog);
  });
}

if (skillsStatusFilter) {
  skillsStatusFilter.addEventListener("change", () => {
    renderSkillsCatalog(state.catalog);
  });
}

if (toolsSearch) {
  toolsSearch.addEventListener("input", () => {
    renderToolsCatalog(state.catalog);
  });
}

if (toolsRiskFilter) {
  toolsRiskFilter.addEventListener("change", () => {
    renderToolsCatalog(state.catalog);
  });
}

settingsProviderForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveSettings();
});

settingProvider.addEventListener("change", () => {
  syncProviderTiles(settingProvider.value || "local");
});

saveExperience.addEventListener("click", () => {
  state.compactTools = Boolean(compactTools.checked);
  state.streamMarkdown = Boolean(streamMarkdown.checked);
  localStorage.setItem("mnemo.ui.compact_tools", String(state.compactTools));
  localStorage.setItem("mnemo.ui.stream_markdown", String(state.streamMarkdown));
  document.body.classList.toggle("compact-tools", state.compactTools);
  saveSettings({ quietOnly: true });
});

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (document.body.classList.contains("mobile-sheet-open") || document.body.classList.contains("drawer-open")) {
    switchView("chat", { updateLocation: true });
  }
});

window.addEventListener("online", () => {
  resumeLastRun();
});

window.addEventListener("hashchange", () => {
  switchView(viewFromLocation());
});

window.addEventListener("popstate", () => {
  switchView(viewFromLocation());
});

mobileSheetQuery.addEventListener("change", () => {
  switchView(viewFromLocation());
});

switchView(viewFromLocation());
updateContextPanel();
updateComposerState();
loadHomeContext();
resumeLastRun();

function switchView(name, options = {}) {
  const target = views[name] ? name : "chat";
  const useMobileSheet = isMobileSheetTarget(target);
  const useDesktopDrawer = isDesktopDrawerTarget(target);
  for (const [viewName, view] of Object.entries(views)) {
    const active = useMobileSheet || useDesktopDrawer ? viewName === "chat" || viewName === target : viewName === target;
    view.classList.toggle("active", active);
    view.classList.toggle("sheet-active", useMobileSheet && viewName === target);
    view.classList.toggle("drawer-active", useDesktopDrawer && viewName === target);
  }
  document.body.classList.toggle("mobile-sheet-open", useMobileSheet);
  document.body.classList.toggle("drawer-open", useDesktopDrawer);
  for (const item of navItems) {
    item.classList.toggle("active", item.dataset.view === target);
  }
  if (options.updateLocation) {
    const nextHash = `#${target}`;
    if (window.location.hash !== nextHash) {
      history.pushState(null, "", nextHash);
    }
  }
  if (target === "memory") {
    loadMemoryCompass();
  }
  if (target === "skills" || target === "tools") {
    loadCatalog();
  }
  if (target === "settings") {
    loadSettings();
  }
  if (target === "chat") {
    input.focus();
  }
}

function isMobileSheetTarget(target) {
  return target === "settings" && mobileSheetQuery.matches;
}

function isDesktopDrawerTarget(target) {
  return target === "settings" && !mobileSheetQuery.matches;
}

function viewFromLocation() {
  const hash = window.location.hash.replace("#", "");
  return views[hash] ? hash : "chat";
}

async function runTurn(message) {
  state.busy = true;
  state.cancelRequested = false;
  state.activeRunId = "";
  state.assistantNode = null;
  rememberUserIntent(message);
  addMessage("user", message);
  showPendingAssistant();
  setStatus("思考中");
  updateComposerState();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: state.conversationId || undefined,
        mission_id: state.missionId || undefined,
      }),
    });

    if (!response.ok || !response.body) {
      removePendingAssistant();
      addCard("error", "Error", `HTTP ${response.status}`);
      return;
    }

    await readNdjson(response.body, handleEvent);
  } catch (error) {
    removePendingAssistant();
    addCard("error", "Error", error.message || String(error));
  } finally {
    state.busy = false;
    state.cancelRequested = false;
    state.activeRunId = "";
    state.assistantNode = null;
    removePendingAssistant();
    updateComposerState();
    setStatus("空闲");
    input.focus();
    await resumeLastRun({ incremental: true });
  }
}

async function requestCancel() {
  if (!state.busy || state.cancelRequested || !state.activeRunId) return;
  state.cancelRequested = true;
  updateComposerState();
  setStatus("停止中");
  try {
    const response = await fetch("/api/runs/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: state.activeRunId, reason: "user requested" }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
  } catch (error) {
    state.cancelRequested = false;
    updateComposerState();
    addCard("error", "Error", error.message || String(error));
  }
}

async function resumeLastRun(options = {}) {
  if (!state.lastRunId || state.busy) return;
  const params = new URLSearchParams({ run_id: state.lastRunId, chat: "1" });
  if (options.incremental && state.lastEventId) {
    params.set("sinceEventId", state.lastEventId);
  }
  try {
    const response = await fetch(`/api/events?${params.toString()}`);
    if (!response.ok) return;
    const payload = await response.json();
    for (const event of payload.events || []) {
      handleEvent(event);
    }
  } catch (_error) {
    return;
  }
}

async function readNdjson(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line));
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}

function handleEvent(event) {
  if (!event || typeof event !== "object" || Array.isArray(event)) return;
  persistEventEnvelope(event);
  updateComposerState();
  if (event.event_id) {
    if (state.renderedEventIds.has(event.event_id)) return;
    state.renderedEventIds.add(event.event_id);
    state.lastEventId = event.event_id;
    localStorage.setItem("mnemo.last_event_id", state.lastEventId);
  }
  if (!isInternalLearningEvent(event)) {
    renderActivity(event);
  }

  switch (event.type) {
    case "turn.started":
      handleTurnStarted(event);
      break;
    case "conversation.hydrated":
    case "status.updated":
      if (event.data?.tone !== "learning") setStatus(event.data?.text || event.data?.summary || "执行中");
      break;
    case "assistant.delta":
      removePendingAssistant();
      appendAssistant(event.data?.text || "");
      break;
    case "assistant.message":
      removePendingAssistant();
      finalizeAssistantMarkdown(event.data?.text || "");
      break;
    case "action.queued":
    case "action.started":
    case "action.completed":
      if (!isInternalLearningEvent(event)) renderAction(event);
      break;
    case "source.attached":
      if (!isToolResultSource(event.data?.source)) renderSource(event.data?.source);
      break;
    case "artifact.card":
      renderArtifact(event.data?.artifact);
      break;
    case "recall.card":
      renderRecall(event.data?.recall);
      break;
    case "learning.chip":
      renderLearning(event.data?.item);
      break;
    case "decision.card":
      renderDecision(event.data?.decision);
      break;
    case "run.completed":
      persistRun(event);
      removePendingAssistant();
      state.cancelRequested = false;
      state.activeRunId = "";
      setStatus("空闲");
      updateComposerState();
      break;
    default:
      if (event.type && String(event.type).endsWith(".error")) {
        removePendingAssistant();
        addCard("error", "Error", event.data?.message || event.data?.error || event.type);
      }
  }
}

function persistEventEnvelope(event) {
  if (event.conversation_id) {
    state.conversationId = event.conversation_id;
    localStorage.setItem("mnemo.conversation_id", state.conversationId);
  }
  if (event.mission_id) {
    state.missionId = event.mission_id;
    localStorage.setItem("mnemo.mission_id", state.missionId);
  }
  if (event.run_id) {
    if (state.busy) state.activeRunId = event.run_id;
    state.lastRunId = event.run_id;
    localStorage.setItem("mnemo.last_run_id", state.lastRunId);
  }
  updateContextPanel();
}

function persistRun(event) {
  const result = event.data?.result || {};
  if (result.conversation_id) {
    state.conversationId = result.conversation_id;
    localStorage.setItem("mnemo.conversation_id", state.conversationId);
  }
  if (result.mission_id) {
    state.missionId = result.mission_id;
    localStorage.setItem("mnemo.mission_id", state.missionId);
  }
  if (event.run_id) {
    state.lastRunId = event.run_id;
    localStorage.setItem("mnemo.last_run_id", state.lastRunId);
  }
  updateContextPanel();
}

function renderActivity(event) {
  if (event.run_id) {
    runBadge.textContent = compactId(event.run_id);
  }
}

function isInternalLearningEvent(event) {
  const action = event.data?.action || {};
  const toolName = action.title || event.data?.tool_name || event.data?.result?.name || "";
  return (
    event.data?.internal === "learning" ||
    event.data?.stage === "after_turn_learning" ||
    event.data?.stage === "learning_debt_review" ||
    event.data?.tone === "learning" ||
    toolName === "learning_discard" ||
    String(event.data?.summary || "").includes("Learning evidence discarded")
  );
}

function actionState(eventOrType) {
  const type = typeof eventOrType === "string" ? eventOrType : eventOrType?.type;
  const outcome = typeof eventOrType === "string" ? "" : eventOrType?.data?.outcome;
  if (type === "action.queued") return "queued";
  if (type === "action.started") return "running";
  if (type === "action.completed") return outcome && outcome !== "success" ? "failed" : "done";
  return "queued";
}

function activityActionId(event) {
  return (
    event.data?.action_id ||
    event.data?.action?.action_id ||
    event.data?.provider_call_id ||
    event.event_id ||
    `action_${state.activityRows.size}`
  );
}

function renderAction(event) {
  emptyState.hidden = true;
  const action = event.data?.action || {};
  const id = activityActionId(event);
  const key = `action:${id}`;
  const name = event.data?.tool_name || action.title || "tool";
  const stateName = actionState(event);
  let row = state.activityRows.get(key);
  if (!row) {
    row = createToolCallCard(id, name);
    state.activityRows.set(key, row);
    timeline.appendChild(row.node);
  }
  row.node.dataset.state = stateName;
  row.title.textContent = name;
  row.status.textContent = toolStatusLabel(event);
  row.summary.textContent = action.summary || event.data?.summary || "工具调用";
  row.preview.textContent = row.summary.textContent;
  row.meta.textContent = [action.risk || "", action.provider || "", compactId(id)].filter(Boolean).join(" · ");
  if (state.busy) setStatus("执行中");
  updateGlanceActivity(name, row.status.textContent);
  upsertRailAction(key, name, row.status.textContent, row.summary.textContent, stateName);
  if (event.data?.action) {
    renderToolDetails(row.details, event.data.action, event.data);
  }
  if (event.type === "action.completed") {
    renderToolResult(row.result, event.data);
  }
  timelineScroll();
}

function updateGlanceActivity(name, status) {
  const label = [name || "工具调用", status || ""].filter(Boolean).join(" · ");
  setText(glanceActivity, label);
  setText(railActivity, label);
  setRailActivityActive(true);
}

function upsertRailAction(key, name, status, summary, stateName) {
  if (!railActionList) return;
  let row = state.railActionRows.get(key);
  if (!row) {
    row = createRailActionRow(key);
    state.railActionRows.set(key, row);
  }
  row.node.dataset.state = stateName;
  row.title.textContent = name || "工具调用";
  row.status.textContent = status || "排队";
  row.summary.textContent = compactText(summary || "正在处理", 72);
  railActionList.prepend(row.node);
  trimRailActions();
}

function createRailActionRow(key) {
  const node = document.createElement("div");
  node.className = "rail-row rail-action-row";
  node.dataset.railActionKey = key;
  const dot = document.createElement("span");
  dot.className = "rail-dot";
  dot.setAttribute("aria-hidden", "true");
  const body = document.createElement("div");
  const top = document.createElement("span");
  top.className = "rail-action-top";
  const title = document.createElement("strong");
  const status = document.createElement("em");
  const summary = document.createElement("small");
  top.append(title, status);
  body.append(top, summary);
  node.append(dot, body);
  return { node, title, status, summary };
}

function trimRailActions() {
  if (!railActionList) return;
  while (railActionList.children.length > 4) {
    const last = railActionList.lastElementChild;
    if (!last) return;
    state.railActionRows.delete(last.dataset.railActionKey || "");
    last.remove();
  }
}

function createToolCallCard(id, name) {
  const node = document.createElement("details");
  node.className = "event-card action tool-call-card";
  node.dataset.actionId = id;
  node.open = !state.compactTools;

  const summary = document.createElement("summary");
  summary.className = "tool-call-summary";

  const icon = document.createElement("span");
  icon.className = "tool-pulse";
  icon.setAttribute("aria-hidden", "true");

  const text = document.createElement("span");
  text.className = "tool-call-title";
  text.textContent = name;

  const copy = document.createElement("span");
  copy.className = "tool-call-copy";
  const preview = document.createElement("span");
  preview.className = "tool-call-preview";
  preview.textContent = "准备调用工具";
  copy.append(text, preview);

  const status = document.createElement("span");
  status.className = "tool-status";
  status.textContent = "排队";

  summary.append(icon, copy, status);

  const body = document.createElement("div");
  body.className = "tool-call-body";
  const meta = document.createElement("p");
  meta.className = "tool-meta";
  const description = document.createElement("p");
  description.className = "tool-summary";
  const details = document.createElement("div");
  details.className = "tool-details";
  const result = document.createElement("div");
  result.className = "tool-result";
  body.append(meta, description, details, result);
  node.append(summary, body);

  return { node, title: text, preview, status, meta, summary: description, details, result };
}

function toolStatusLabel(event) {
  if (event.type === "action.completed") {
    if (event.data?.outcome === "success") return "完成";
    if (event.data?.outcome === "skipped") return "跳过";
    return "失败";
  }
  if (event.type === "action.started") return "运行中";
  return "排队";
}

function renderToolDetails(target, action, data) {
  const blocks = [];
  if (action.arguments && Object.keys(action.arguments).length) {
    blocks.push(toolDetailBlock("调用参数", action.arguments));
  }
  if (data.provider_call_id) {
    blocks.push(toolDetailText("Provider Call", data.provider_call_id));
  }
  target.replaceChildren(...blocks);
}

function renderToolResult(target, data) {
  const blocks = [];
  if (data.summary) blocks.push(toolDetailText("结果摘要", data.summary));
  if (data.result) blocks.push(toolDetailBlock("返回结果", data.result));
  target.replaceChildren(...blocks);
}

function toolDetailText(label, value) {
  const block = document.createElement("section");
  block.className = "tool-detail";
  const title = document.createElement("strong");
  title.textContent = label;
  const text = document.createElement("p");
  text.textContent = String(value || "");
  block.append(title, text);
  return block;
}

function toolDetailBlock(label, value) {
  const block = document.createElement("section");
  block.className = "tool-detail";
  const title = document.createElement("strong");
  title.textContent = label;
  const pre = document.createElement("pre");
  pre.textContent = compactJson(value);
  block.append(title, pre);
  return block;
}

function isToolResultSource(source) {
  return source?.kind === "tool_result";
}

function handleTurnStarted(event) {
  const summary = event.data?.message || event.data?.user_message || event.data?.prompt || "";
  if (summary && !state.busy) {
    addMessage("user", summary);
  }
  if (summary) rememberUserIntent(summary);
}

function addMessage(role, text, options = {}) {
  emptyState.hidden = true;
  const message = document.createElement("article");
  message.className = `message ${role}`;
  if (options.pending) message.classList.add("pending");
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "我" : "M";
  const content = document.createElement("div");
  content.className = "message-content";
  if (role === "assistant") {
    content.classList.add("markdown");
    content.dataset.rawText = text || "";
    renderMarkdownInto(content, text || "");
  } else {
    content.textContent = text || "";
  }
  message.append(avatar, content);
  timeline.appendChild(message);
  timelineScroll();
  return content;
}

function showPendingAssistant() {
  removePendingAssistant();
  emptyState.hidden = true;
  const message = document.createElement("article");
  message.className = "message assistant pending";
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = "M";
  const content = document.createElement("div");
  content.className = "message-content pending-content";
  const label = document.createElement("span");
  label.textContent = "回复中";
  const dots = document.createElement("span");
  dots.className = "typing-dots";
  dots.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  content.append(label, dots);
  message.append(avatar, content);
  timeline.appendChild(message);
  state.pendingAssistantNode = message;
  timelineScroll();
}

function removePendingAssistant() {
  if (state.pendingAssistantNode) {
    state.pendingAssistantNode.remove();
    state.pendingAssistantNode = null;
  }
}

function appendAssistant(text) {
  if (!state.assistantNode) {
    state.assistantNode = addMessage("assistant", "");
  }
  const rawText = `${state.assistantNode.dataset.rawText || ""}${text || ""}`;
  state.assistantNode.dataset.rawText = rawText;
  if (state.streamMarkdown) {
    renderMarkdownInto(state.assistantNode, rawText);
  } else {
    state.assistantNode.textContent = rawText;
  }
  timelineScroll();
}

function finalizeAssistantMarkdown(text) {
  if (!state.assistantNode) {
    state.assistantNode = addMessage("assistant", text || "");
  }
  const rawText = text || state.assistantNode.dataset.rawText || "";
  state.assistantNode.dataset.rawText = rawText;
  renderMarkdownInto(state.assistantNode, rawText);
  state.assistantNode = null;
  timelineScroll();
}

function addCard(kind, titleText, bodyText) {
  emptyState.hidden = true;
  const card = document.createElement("section");
  card.className = `event-card ${kind}`;
  const title = document.createElement("strong");
  title.textContent = titleText;
  const body = document.createElement("p");
  body.textContent = bodyText || "";
  card.append(title, body);
  timeline.appendChild(card);
  timelineScroll();
  return card;
}

function renderSource(source) {
  if (!source) return;
  const card = addCard("source", source.title || source.kind || "Source", source.summary || "");
  if (source.source_id) card.dataset.sourceId = source.source_id;
}

function renderArtifact(artifact) {
  if (!artifact) return;
  const card = document.createElement("section");
  card.className = "event-card artifact";
  const header = document.createElement("div");
  header.className = "artifact-header";
  const icon = document.createElement("span");
  icon.className = "artifact-icon";
  icon.textContent = artifactIconLabel(artifact.kind);
  const copy = document.createElement("div");
  copy.className = "artifact-copy";
  const title = document.createElement("strong");
  title.textContent = artifact.title || "Artifact";
  const preview = document.createElement("p");
  preview.className = "artifact-preview";
  preview.textContent = artifact.summary || artifact.description || "产物已准备好，打开后查看正文。";
  const meta = document.createElement("span");
  meta.className = "artifact-kind";
  meta.textContent = artifact.kind || "artifact";
  copy.append(title, preview);
  header.append(icon, copy, meta);
  const actions = document.createElement("div");
  actions.className = "artifact-actions";
  const open = actionButton("打开", () => toggleArtifact(artifact.artifact_id || artifact.id, body));
  const exportButton = actionButton("导出", async () => {
    const loaded = await loadArtifact(artifact.artifact_id || artifact.id);
    if (loaded?.artifact) exportArtifact(loaded.artifact);
  });
  const continueButton = actionButton("继续编辑", () => prefillMessage(`Continue editing artifact ${artifact.artifact_id || artifact.id}: `));
  actions.append(open, exportButton, continueButton);
  const body = document.createElement("div");
  body.className = "artifact-body";
  body.hidden = true;
  card.append(header, actions, body);
  timeline.appendChild(card);
  timelineScroll();
}

function artifactIconLabel(kind) {
  const normalized = String(kind || "").toLowerCase();
  if (normalized.includes("markdown") || normalized.includes("doc")) return "文";
  if (normalized.includes("table") || normalized.includes("sheet") || normalized.includes("csv")) return "表";
  if (normalized.includes("code") || normalized.includes("diff")) return "码";
  if (normalized.includes("message") || normalized.includes("mail")) return "信";
  return "产";
}

async function toggleArtifact(artifactId, target) {
  if (!artifactId || !target) return;
  if (!target.hidden) {
    target.hidden = true;
    return;
  }
  target.hidden = false;
  target.replaceChildren(loadingRow("加载产物"));
  const payload = await loadArtifact(artifactId);
  if (!payload?.artifact) {
    target.replaceChildren(textRow("无法加载产物。"));
    return;
  }
  renderArtifactBody(target, payload);
}

async function loadArtifact(artifactId) {
  if (!artifactId) return null;
  if (state.artifacts.has(artifactId)) {
    return {
      artifact: state.artifacts.get(artifactId),
      related: state.artifactRelated.get(artifactId) || [],
    };
  }
  const response = await fetch(`/api/artifacts?artifact_id=${encodeURIComponent(artifactId)}`);
  if (!response.ok) return null;
  const payload = await response.json();
  if (payload.artifact) state.artifacts.set(artifactId, payload.artifact);
  state.artifactRelated.set(artifactId, payload.related || []);
  return payload;
}

function renderArtifactBody(target, payload) {
  const artifact = payload.artifact;
  const body = document.createElement("article");
  body.className = "artifact-markdown markdown-body";
  renderMarkdownInto(body, artifact.body || "");
  const related = document.createElement("div");
  related.className = "artifact-related";
  const title = document.createElement("strong");
  title.textContent = "相关产物";
  related.appendChild(title);
  for (const item of payload.related || []) {
    const row = document.createElement("button");
    row.className = "artifact-related-row";
    row.type = "button";
    row.textContent = item.title || item.id || "Artifact";
    row.addEventListener("click", () => prefillMessage(`Compare artifact ${artifact.id} with ${item.id}.`));
    related.appendChild(row);
  }
  target.replaceChildren(body, related);
}

function exportArtifact(artifact) {
  const blob = new Blob([artifact.body || ""], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${safeFileName(artifact.title || artifact.id || "artifact")}.${artifact.kind === "markdown" ? "md" : "txt"}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function renderRecall(recall) {
  if (!recall) return;
  const card = document.createElement("section");
  card.className = "event-card recall";
  const header = document.createElement("div");
  header.className = "event-title";
  const title = document.createElement("strong");
  title.textContent = `Recall · ${recall.count || 0} found`;
  const meta = document.createElement("span");
  meta.textContent = recall.scope || "all";
  header.append(title, meta);
  const query = document.createElement("p");
  query.className = "recall-query";
  query.textContent = recall.query || "";
  const list = document.createElement("div");
  list.className = "recall-list";
  for (const item of recall.items || []) {
    list.appendChild(recallItemRow(item));
  }
  card.append(header, query, list);
  timeline.appendChild(card);
  timelineScroll();
}

function recallItemRow(item) {
  const row = document.createElement("div");
  row.className = "recall-item";
  const body = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = compactRecallTitle(item);
  const summary = document.createElement("p");
  const summaryText = String(item.summary || item.snippet || "");
  if (summaryText && summaryText !== title.textContent) summary.textContent = summaryText;
  body.append(title, summary);
  const actions = document.createElement("div");
  actions.className = "recall-actions";
  if (item.kind === "artifact" && (item.artifact_id || item.id)) {
    actions.appendChild(actionButton("打开", () => prefillMessage(`Open artifact ${item.artifact_id || item.id}.`), "recall-button"));
  }
  if (item.kind === "decision" && item.item_id) {
    actions.appendChild(actionButton("处理", () => prefillMessage(`Resolve decision ${item.item_id}: `), "recall-button"));
  }
  actions.appendChild(actionButton("使用", () => prefillMessage(`Use this recalled context: ${title.textContent}`), "recall-button"));
  row.append(body, actions);
  return row;
}

function compactRecallTitle(item) {
  return item.title || item.summary || item.snippet || item.kind || "Recall";
}

function renderLearning(item) {
  if (!item) return;
  const card = document.createElement("section");
  card.className = "event-card learning";
  if (item.requires_confirmation) card.classList.add("confirmation");
  const head = document.createElement("div");
  head.className = "learning-chip-head";
  const icon = document.createElement("span");
  icon.className = "learning-icon";
  icon.textContent = item.requires_confirmation ? "!" : "+";
  const title = document.createElement("strong");
  title.textContent = item.requires_confirmation ? "记忆待复核" : "学习信号";
  const risk = document.createElement("span");
  risk.className = "learning-risk";
  risk.textContent = item.requires_confirmation ? "复核" : (item.risk || item.dimension || "候选");
  head.append(icon, title, risk);
  const summary = document.createElement("p");
  summary.className = "learning-summary";
  summary.textContent = item.summary || "";
  const actions = document.createElement("div");
  actions.className = "learning-actions";
  if (item.kind === "memory" && item.item_id) {
    actions.append(
      actionButton(item.requires_confirmation ? "记住" : "保留", () => resolveLearningMemory(item.item_id, "accept", card), "learning-button"),
      actionButton("仅本次", () => resolveLearningMemory(item.item_id, "this_time", card), "learning-button"),
      actionButton("忽略", () => resolveLearningMemory(item.item_id, "reject", card), "learning-button"),
    );
  }
  card.append(head, summary, actions);
  timeline.appendChild(card);
  timelineScroll();
}

async function resolveLearningMemory(itemId, action, card) {
  setCardBusy(card, true);
  try {
    const response = await fetch("/api/learning/memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_id: itemId, action }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    const status = document.createElement("p");
    status.className = "resolution";
    status.textContent = action === "undo" ? "已撤销。" : "已处理。";
    const undo = action === "accept" ? actionButton("撤销", () => resolveLearningMemory(itemId, "undo", card), "learning-button") : null;
    card.append(status);
    if (undo) card.append(undo);
  } catch (error) {
    addCard("error", "Learning error", error.message || String(error));
  } finally {
    setCardBusy(card, false);
  }
}

function renderDecision(decision) {
  if (!decision) return;
  const card = document.createElement("section");
  card.className = "event-card decision";
  const head = document.createElement("div");
  head.className = "decision-head";
  const icon = document.createElement("span");
  icon.className = "decision-icon";
  icon.textContent = "!";
  const title = document.createElement("strong");
  title.textContent = decision.title || "需要确认";
  const risk = document.createElement("span");
  risk.className = "decision-risk";
  risk.textContent = decision.risk || decision.priority || "确认";
  head.append(icon, title, risk);
  const question = document.createElement("p");
  question.className = "decision-question";
  question.textContent = decision.question || decision.summary || "";
  const actions = document.createElement("div");
  actions.className = "decision-actions";
  if (decision.item_id) {
    for (const option of decisionOptions(decision)) {
      actions.appendChild(actionButton(option.label, () => resolveDecision(decision.item_id, option.id, card), "decision-button"));
    }
  }
  card.append(head, question, actions);
  timeline.appendChild(card);
  timelineScroll();
}

function decisionOptions(decision) {
  const raw = Array.isArray(decision.options) && decision.options.length ? decision.options : [
    { id: "accepted", label: "继续" },
    { id: "rejected", label: "取消" },
    { id: "ignored", label: "稍后" },
  ];
  return raw
    .map((item) => {
      if (typeof item === "string") return defaultDecisionOption(item);
      return defaultDecisionOption(item?.id, item?.label);
    })
    .filter((item) => ["accepted", "rejected", "ignored"].includes(item.id));
}

function defaultDecisionOption(id, label) {
  const key = ["accepted", "rejected", "ignored"].includes(id) ? id : "ignored";
  const labels = { accepted: "继续", rejected: "取消", ignored: "稍后" };
  return { id: key, label: label || labels[key] };
}

async function resolveDecision(itemId, resolution, card) {
  setCardBusy(card, true);
  try {
    const response = await fetch("/api/inbox/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, resolution }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    const status = document.createElement("p");
    status.className = "resolution";
    status.textContent = `已${resolution === "accepted" ? "同意" : resolution === "rejected" ? "拒绝" : "忽略"}。`;
    card.append(status);
    if (payload.tool_result) {
      const resultCard = addCard(payload.tool_result.ok ? "action" : "error", payload.tool_result.tool || "tool", payload.tool_result.summary || "");
      card.after(resultCard);
    }
  } catch (error) {
    addCard("error", "Decision error", error.message || String(error));
  } finally {
    setCardBusy(card, false);
  }
}

async function loadMemoryCompass() {
  if (!memoryCompass) return;
  if (state.memoryOntology) {
    renderMemoryCompass(state.memoryOntology);
    return;
  }
  memoryCompass.replaceChildren(loadingRow("加载记忆 Wiki"));
  memoryLayerDetail.replaceChildren(textRow("选择一个维度查看长期记忆。"));
  setText(memoryActiveTitle, "维度详情");
  setText(memoryActiveSummary, "正在加载记忆。");
  setText(memoryActiveMeta, "未选择");
  hideMemoryMarkdown();
  try {
    const response = await fetch("/api/memory/ontology");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.memoryOntology = payload;
    renderMemoryCompass(payload);
  } catch (error) {
    memoryCompass.replaceChildren(textRow(error.message || String(error)));
  }
}

function renderMemoryCompass(payload) {
  const dimensions = payload.dimensions || [];
  const counts = payload.counts || {};
  memoryCountBadge.textContent = `${counts.pages || 0} 稳定 · ${counts.candidates || 0} 候选`;
  renderMemoryStats(counts);
  renderMemoryCoverage(counts, dimensions.length || MEMORY_DIMENSIONS.length);
  const cards = dimensions.map((dimension) => memoryDimensionCard(dimension));
  memoryCompass.replaceChildren(...cards);
  const first = dimensions.find((item) => Number(item.pages || 0) + Number(item.candidates || 0) > 0) || dimensions[0];
  if (first) loadMemoryDimension(first.dimension);
}

function renderMemoryStats(counts) {
  const rows = [
    ["稳定", counts.pages || 0, "可直接引用"],
    ["候选", counts.candidates || 0, "等待整理"],
    ["覆盖", counts.covered_dimensions || 0, "已触达维度"],
  ].map(([label, value, hint]) => {
    const row = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    const span = document.createElement("span");
    span.textContent = label;
    const small = document.createElement("small");
    small.textContent = hint;
    row.append(strong, span, small);
    return row;
  });
  memoryStats.replaceChildren(...rows);
}

function renderMemoryCoverage(counts, totalDimensions) {
  const total = Math.max(1, Number(totalDimensions || MEMORY_DIMENSIONS.length));
  const covered = Math.min(total, Number(counts.covered_dimensions || 0));
  setText(memoryCoverageLabel, `${covered}/${total}`);
  if (memoryCoverageFill) {
    memoryCoverageFill.style.setProperty("--coverage", `${Math.round((covered / total) * 100)}%`);
  }
}

function memoryDimensionCard(dimension) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "memory-dimension-card";
  button.dataset.dimension = dimension.dimension;
  const total = Number(dimension.pages || 0) + Number(dimension.candidates || 0);
  const head = document.createElement("span");
  head.className = "memory-dimension-head";
  const title = document.createElement("strong");
  title.textContent = dimensionLabel(dimension.dimension);
  const count = document.createElement("em");
  count.textContent = `${total} 条`;
  head.append(title, count);
  const counts = document.createElement("span");
  counts.className = "memory-dimension-counts";
  counts.textContent = `${dimension.pages || 0} 稳定 · ${dimension.candidates || 0} 候选`;
  const summary = document.createElement("p");
  summary.textContent = dimension.summary || "尚未沉淀稳定信号。";
  const meter = document.createElement("i");
  meter.className = "memory-meter";
  meter.style.setProperty("--level", `${Math.min(100, total * 18)}%`);
  button.append(head, counts, summary, meter);
  button.addEventListener("click", () => loadMemoryDimension(dimension.dimension));
  return button;
}

async function loadMemoryDimension(dimensionName) {
  const key = String(dimensionName || "context");
  for (const card of memoryCompass.querySelectorAll(".memory-dimension-card")) {
    card.classList.toggle("active", card.dataset.dimension === key);
  }
  if (state.memoryDimensions.has(key)) {
    renderMemoryDimensionDetail(state.memoryDimensions.get(key));
    return;
  }
  memoryLayerDetail.replaceChildren(loadingRow(`加载 ${dimensionLabel(key)}`));
  try {
    const response = await fetch(`/api/memory/dimension?dimension=${encodeURIComponent(key)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.memoryDimensions.set(key, payload);
    renderMemoryDimensionDetail(payload);
  } catch (error) {
    memoryLayerDetail.replaceChildren(textRow(error.message || String(error)));
  }
}

function renderMemoryDimensionDetail(payload) {
  hideMemoryMarkdown();
  setText(memoryActiveTitle, dimensionLabel(payload.dimension));
  setText(memoryActiveSummary, payload.summary || "暂无摘要。");
  setText(memoryActiveMeta, `${payload.counts?.pages || 0} 稳定 · ${payload.counts?.candidates || 0} 候选`);
  const stable = memoryDetailSection("稳定记忆", payload.pages || []);
  const candidates = memoryDetailSection("候选信号", payload.candidates || []);
  memoryLayerDetail.replaceChildren(stable, candidates);
}

function memoryDetailSection(titleText, entries) {
  const section = document.createElement("section");
  section.className = "memory-detail-section";
  const header = document.createElement("header");
  const title = document.createElement("h3");
  title.textContent = titleText;
  const count = document.createElement("span");
  count.textContent = `${entries.length} 条`;
  header.append(title, count);
  const list = document.createElement("div");
  list.className = "memory-detail-list";
  if (!entries.length) {
    list.appendChild(textRow("暂无内容。"));
  }
  for (const item of entries) {
    list.appendChild(memoryLayerItem(item));
  }
  section.append(header, list);
  return section;
}

function memoryLayerItem(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "memory-detail-card";
  button.title = "查看记忆详情";
  button.dataset.memoryItemId = item.id || "";
  button.dataset.memoryItemKind = item.kind || "memory";
  const type = document.createElement("span");
  type.className = "memory-detail-type";
  type.textContent = memoryKindLabel(item.kind || "memory");
  const title = document.createElement("strong");
  title.textContent = item.title || "Memory";
  const summary = document.createElement("p");
  summary.textContent = item.summary || "";
  const meta = document.createElement("span");
  meta.textContent = [
    memoryStatusLabel(item.status),
    confidenceLabel(item.confidence),
  ].filter(Boolean).join(" · ");
  button.append(type, title, summary, meta);
  button.addEventListener("click", () => loadMemoryItem(item.kind, item.id));
  return button;
}

async function loadMemoryItem(kind, id) {
  if (!kind || !id) return;
  const itemType = kind === "page" ? "page" : "candidate";
  const key = `${itemType}:${id}`;
  if (state.memoryItems.has(key)) {
    renderMemoryItemDetail(state.memoryItems.get(key));
    return;
  }
  const loading = loadingRow("加载记忆详情");
  loading.dataset.memoryItemLoading = "true";
  memoryLayerDetail.appendChild(loading);
  try {
    const response = await fetch(`/api/memory/item?type=${encodeURIComponent(itemType)}&id=${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.memoryItems.set(key, payload);
    renderMemoryItemDetail(payload);
  } catch (error) {
    loading.remove();
    memoryLayerDetail.appendChild(textRow(error.message || String(error)));
  }
}

function renderMemoryItemDetail(payload) {
  for (const row of memoryLayerDetail.querySelectorAll("[data-memory-item-loading]")) {
    row.remove();
  }
  const item = payload.item || {};
  for (const card of memoryLayerDetail.querySelectorAll(".memory-detail-card")) {
    card.classList.toggle("active", card.dataset.memoryItemId === item.id);
  }
  const panel = document.createElement("section");
  panel.className = "memory-selected-card";
  const summary = document.createElement("p");
  summary.textContent = item.summary || "";
  const meta = document.createElement("span");
  meta.textContent = [
    dimensionLabel(item.dimension),
    memoryStatusLabel(item.status || item.type || "memory"),
    confidenceLabel(item.confidence),
  ].filter(Boolean).join(" · ");
  const evidence = document.createElement("div");
  evidence.className = "memory-evidence-list";
  for (const row of payload.evidence || []) {
    evidence.appendChild(memoryDetailEvidence(row));
  }
  const actions = document.createElement("div");
  actions.className = "memory-item-actions";
  actions.append(
    actionButton("引用到当前任务", () => prefillMemoryAction("use", payload), "primary-button small"),
    actionButton("更新", () => prefillMemoryAction("update", payload), "secondary-button small"),
    actionButton("忘记", () => prefillMemoryAction("forget", payload), "secondary-button small danger-button"),
    actionButton("查看 Wiki", () => openMemoryMarkdown(payload), "secondary-button small"),
  );
  panel.append(summary, meta, evidence, actions);
  if (memorySelectedMeta) {
    memorySelectedMeta.hidden = false;
    memorySelectedMeta.replaceChildren(panel);
  }
  openMemoryMarkdown(payload, { scroll: false });
  revealMemoryItemPanel(memoryMarkdownPanel || panel);
}

function revealMemoryItemPanel(panel) {
  window.requestAnimationFrame(() => {
    panel.scrollIntoView({ block: "nearest" });
  });
}

function memoryDetailEvidence(item) {
  const row = document.createElement("div");
  row.className = "memory-detail-evidence";
  const title = document.createElement("strong");
  title.textContent = memoryEvidenceLabel(item.kind);
  const summary = document.createElement("p");
  summary.textContent = memoryEvidenceSummary(item);
  row.append(title, summary);
  return row;
}

function memoryKindLabel(value) {
  const key = String(value || "memory");
  return MEMORY_KIND_LABELS[key] || key;
}

function memoryStatusLabel(value) {
  const key = String(value || "").split(":")[0];
  if (!key) return "";
  return MEMORY_STATUS_LABELS[key] || (key === "unknown" ? "未知" : key);
}

function memoryEvidenceLabel(value) {
  const key = String(value || "evidence");
  return MEMORY_EVIDENCE_LABELS[key] || "证据";
}

function memoryEvidenceSummary(item) {
  const rawSummary = String(item.summary || "").trim();
  const summaryReason = memoryEvidenceReasonLabel(rawSummary);
  if (summaryReason) return summaryReason;
  if (rawSummary && !isTechnicalToken(rawSummary)) return compactText(rawSummary, 220);
  const reason = memoryEvidenceReasonLabel(item.reason);
  if (reason) return reason;
  const kind = String(item.kind || "");
  if (kind === "memory_safety") return "已通过基础记忆安全检查。";
  if (kind === "source_candidate") return "来自记忆整理过程中的候选信号。";
  if (kind === "source_page") return "来自已沉淀的长期记忆。";
  return "暂无更多摘要。";
}

function memoryEvidenceReasonLabel(value) {
  const reason = String(value || "").trim();
  if (!reason) return "";
  const labels = {
    user_message: "来自用户消息。",
    assistant_message: "来自助手回复。",
    tool_result: "来自工具执行结果。",
    duplicate: "与已有记忆存在重叠。",
  };
  if (labels[reason]) return labels[reason];
  if (isTechnicalToken(reason)) return "";
  return compactText(reason, 220);
}

function isTechnicalToken(value) {
  return /^[a-z0-9_.:-]+$/i.test(String(value || "").trim());
}

function openMemoryMarkdown(payload, options = {}) {
  if (!memoryMarkdownPanel || !memoryMarkdownTitle || !memoryMarkdownBody) return;
  const item = payload.item || {};
  const markdown = payload.markdown || memoryPayloadMarkdown(payload);
  memoryMarkdownTitle.textContent = markdownDocumentTitle(markdown) || item.title || "记忆详情";
  renderMarkdownInto(memoryMarkdownBody, markdown);
  memoryMarkdownPanel.hidden = false;
  if (options.scroll === false) return;
  window.requestAnimationFrame(() => {
    memoryMarkdownPanel.scrollIntoView({ block: "nearest" });
  });
}

function markdownDocumentTitle(text) {
  const lines = String(text || "").split(/\r?\n/);
  let index = 0;
  if (isMarkdownFrontmatterStart(lines, 0)) {
    const frontmatter = markdownFrontmatter(lines, 0);
    index = frontmatter.nextIndex;
  }
  while (index < lines.length) {
    const match = String(lines[index] || "").match(/^#\s+(.+)$/);
    if (match) return match[1].trim();
    index += 1;
  }
  return "";
}

function hideMemoryMarkdown() {
  if (!memoryMarkdownPanel || !memoryMarkdownTitle || !memoryMarkdownBody) return;
  memoryMarkdownPanel.hidden = false;
  memoryMarkdownTitle.textContent = "选择记忆";
  if (memorySelectedMeta) {
    memorySelectedMeta.hidden = true;
    memorySelectedMeta.replaceChildren();
  }
  const placeholder = document.createElement("section");
  placeholder.className = "memory-empty-detail";
  const title = document.createElement("strong");
  title.textContent = "尚未选择条目";
  const body = document.createElement("p");
  body.textContent = "从左侧列表选择一条稳定记忆或候选信号。";
  placeholder.append(title, body);
  memoryMarkdownBody.replaceChildren(placeholder);
}

function memoryPayloadMarkdown(payload) {
  const item = payload.item || {};
  const lines = [
    `# ${item.title || "Memory"}`,
    "",
    `- 维度: ${dimensionLabel(item.dimension || "context")}`,
    `- 类型: ${memoryKindLabel(item.type || "memory")}`,
    `- 状态: ${memoryStatusLabel(item.status || "unknown")}`,
    "",
    "## 摘要",
    "",
    item.summary || "",
  ];
  const evidence = payload.evidence || [];
  if (evidence.length) {
    lines.push("", "## 证据", "");
    for (const row of evidence) {
      lines.push(`- **${memoryEvidenceLabel(row.kind)}**: ${memoryEvidenceSummary(row)}`);
    }
  }
  return lines.join("\n");
}

function prefillMemoryAction(intent, payload) {
  const item = payload.item || {};
  const title = item.title || "这条记忆";
  const summary = compactText(item.summary || "", 180);
  const dimension = dimensionLabel(item.dimension || "context");
  if (intent === "forget") {
    prefillMessage(`请评估并忘记这条记忆：${title}。维度：${dimension}。摘要：${summary}`);
    return;
  }
  if (intent === "update") {
    prefillMessage(`请基于当前任务更新这条记忆：${title}。维度：${dimension}。现有摘要：${summary}`);
    return;
  }
  prefillMessage(`请把这条记忆引用到当前任务中：${title}。维度：${dimension}。摘要：${summary}`);
}

async function loadCatalog(options = {}) {
  if (!skillsList && !toolsList) return;
  if (state.catalog && !options.force) {
    renderCatalog(state.catalog);
    return;
  }
  setText(skillsStatus, "加载中");
  setText(toolsStatus, "加载中");
  if (skillsList) skillsList.replaceChildren(loadingRow("加载技能目录"));
  if (toolsList) toolsList.replaceChildren(loadingRow("加载工具目录"));
  try {
    const response = await fetch("/api/catalog");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.catalog = payload;
    renderCatalog(payload);
    setText(skillsStatus, "已加载");
    setText(toolsStatus, "已加载");
  } catch (error) {
    state.catalog = null;
    setText(skillsStatus, "加载失败");
    setText(toolsStatus, "加载失败");
    if (skillsSummary) skillsSummary.replaceChildren();
    if (toolsSummary) toolsSummary.replaceChildren();
    if (skillsList) skillsList.replaceChildren(textRow(error.message || String(error)));
    if (toolsList) toolsList.replaceChildren(textRow(error.message || String(error)));
  }
}

function renderCatalog(payload) {
  renderSkillsCatalog(payload);
  renderToolsCatalog(payload);
}

function renderSkillsCatalog(payload) {
  if (!skillsList || !skillsSummary) return;
  if (!payload) {
    skillsSummary.replaceChildren();
    skillsList.replaceChildren(textRow("技能目录未加载。"));
    return;
  }
  const skills = Array.isArray(payload.skills) ? payload.skills : [];
  const statusCounts = payload.counts?.skills?.status || {};
  skillsSummary.replaceChildren(
    catalogStatBlock("总数", String(payload.counts?.skills?.total ?? skills.length)),
    catalogStatBlock("active", String(statusCounts.active || 0)),
    catalogStatBlock("draft", String(statusCounts.draft || 0)),
    catalogStatBlock("ready", String(statusCounts.ready || 0)),
  );

  const query = String(skillsSearch?.value || "").trim().toLowerCase();
  const status = String(skillsStatusFilter?.value || "");
  const filtered = skills.filter((skill) => {
    if (status && skill.status !== status) return false;
    return catalogMatches(skill, query, ["name", "description", "source", "path", "allowed_tools"]);
  });
  if (!filtered.length) {
    skillsList.replaceChildren(textRow(skills.length ? "没有匹配的技能。" : "还没有已索引技能。"));
    return;
  }
  skillsList.replaceChildren(...filtered.map((skill) => skillCatalogCard(skill)));
}

function renderToolsCatalog(payload) {
  if (!toolsList || !toolsSummary) return;
  if (!payload) {
    toolsSummary.replaceChildren();
    toolsList.replaceChildren(textRow("工具目录未加载。"));
    return;
  }
  const tools = Array.isArray(payload.tools) ? payload.tools : [];
  const riskCounts = payload.counts?.tools?.risk || {};
  toolsSummary.replaceChildren(
    catalogStatBlock("总数", String(payload.counts?.tools?.total ?? tools.length)),
    catalogStatBlock("默认包", String(payload.counts?.tools?.in_bundle || 0)),
    catalogStatBlock("write", String(riskCounts.write || 0)),
    catalogStatBlock("external/admin", String((riskCounts.external || 0) + (riskCounts.admin || 0))),
  );

  const query = String(toolsSearch?.value || "").trim().toLowerCase();
  const risk = String(toolsRiskFilter?.value || "");
  const filtered = tools.filter((tool) => {
    if (risk && tool.risk !== risk) return false;
    return catalogMatches(tool, query, ["name", "description", "risk", "source"]);
  });
  if (!filtered.length) {
    toolsList.replaceChildren(textRow(tools.length ? "没有匹配的工具。" : "还没有注册工具。"));
    return;
  }
  toolsList.replaceChildren(...filtered.map((tool) => toolCatalogCard(tool, payload.tool_bundle || {})));
}

function catalogStatBlock(label, value) {
  const block = document.createElement("div");
  block.className = "catalog-stat";
  const strong = document.createElement("strong");
  strong.textContent = value;
  const span = document.createElement("span");
  span.textContent = label;
  block.append(strong, span);
  return block;
}

function skillCatalogCard(skill) {
  const card = document.createElement("article");
  card.className = "catalog-card skill-card";
  const head = catalogCardHead(skill.name || "Unnamed skill", skill.status || "unknown");
  const description = document.createElement("p");
  description.textContent = skill.description || "无描述";
  const meta = document.createElement("div");
  meta.className = "catalog-meta";
  meta.appendChild(catalogMetaItem("来源", skill.source || "unknown"));
  meta.appendChild(catalogMetaItem("路径", skill.path || "未记录", "catalog-path"));
  if (Array.isArray(skill.allowed_tools) && skill.allowed_tools.length) {
    meta.appendChild(catalogMetaItem("允许工具", skill.allowed_tools.join(", ")));
  }
  if (skill.usage) {
    meta.appendChild(catalogMetaItem("使用", `${skill.usage.uses || 0} 次 · 成功 ${skill.usage.successes || 0}`));
  }
  card.append(head, description, meta);
  return card;
}

function toolCatalogCard(tool, bundle) {
  const card = document.createElement("article");
  card.className = "catalog-card tool-card";
  card.dataset.risk = tool.risk || "read";
  const head = catalogCardHead(tool.name || "unnamed_tool", tool.risk || "read", `risk-${tool.risk || "read"}`);
  const description = document.createElement("p");
  description.textContent = tool.description || "无描述";
  const meta = document.createElement("div");
  meta.className = "catalog-meta";
  meta.appendChild(catalogMetaItem("来源", tool.source || "built-in"));
  meta.appendChild(catalogMetaItem("工具包", tool.in_bundle ? bundle.profile || "default" : "按需扩展"));
  if (bundle.bundle_id && tool.in_bundle) {
    meta.appendChild(catalogMetaItem("bundle", compactId(bundle.bundle_id)));
  }
  card.append(head, description, meta);
  return card;
}

function catalogCardHead(titleText, badgeText, badgeClass = "") {
  const head = document.createElement("header");
  head.className = "catalog-card-head";
  const title = document.createElement("strong");
  title.textContent = titleText;
  const badge = document.createElement("span");
  badge.className = `catalog-badge ${badgeClass}`.trim();
  badge.textContent = badgeText;
  head.append(title, badge);
  return head;
}

function catalogMetaItem(label, value, className = "") {
  const item = document.createElement("span");
  item.className = `catalog-meta-item ${className}`.trim();
  const name = document.createElement("em");
  name.textContent = label;
  const detail = document.createElement("strong");
  detail.textContent = value;
  item.append(name, detail);
  return item;
}

function catalogMatches(item, query, keys) {
  if (!query) return true;
  const text = keys
    .map((key) => {
      const value = item?.[key];
      if (Array.isArray(value)) return value.join(" ");
      return value === null || value === undefined ? "" : String(value);
    })
    .join(" ")
    .toLowerCase();
  return text.includes(query);
}

async function loadSettings() {
  settingsStatus.textContent = "加载中";
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.settings = payload;
    renderSettings(payload);
    settingsStatus.textContent = "已加载";
  } catch (error) {
    settingsStatus.textContent = "加载失败";
    settingsSummary.replaceChildren(textRow(error.message || String(error)));
  }
}

async function loadHomeContext() {
  if (!glanceMemory && !glanceRuntime && !railMemory && !railRuntime) return;
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.settings = payload;
    renderHomeContext(payload);
  } catch (_error) {
    setText(glanceMemory, "暂不可用");
    setText(railMemory, "暂不可用");
    setText(glanceRuntime, "未连接");
    setText(railRuntime, "未连接");
  }
}

function renderHomeContext(payload) {
  const runtime = payload.runtime || payload.settings?.runtime || {};
  const counts = payload.data_controls?.counts || {};
  const preference = (payload.learned_preferences?.items || [])[0];
  const memoryText = `${counts.memory_pages || 0} 稳定 / ${counts.memory_candidates || 0} 候选`;
  const hintText = preference?.summary || "只显示摘要，不暴露原文";
  const runtimeText = `${runtime.provider || "local"}${runtime.model ? ` · ${runtime.model}` : ""}`;
  setText(glanceMemory, memoryText);
  setText(railMemory, memoryText);
  setText(glanceMemoryHint, hintText);
  setText(railMemoryHint, hintText);
  setText(glanceRuntime, runtimeText);
  setText(railRuntime, runtimeText);
}

function renderSettings(payload) {
  const runtime = payload.runtime || payload.settings?.runtime || {};
  settingProvider.value = runtime.provider || "local";
  settingModel.value = runtime.model || "";
  settingBaseUrl.value = runtime.base_url || "";
  settingApiKeyEnv.value = runtime.api_key_env || "";
  settingTimeout.value = runtime.timeout_s || 30;
  settingRetryCount.value = runtime.retry_count || 0;
  settingRetryBackoff.value = runtime.retry_backoff_s || 0;
  settingMaxToolRounds.value = runtime.max_tool_rounds || 12;

  const quiet = payload.quiet_hours || payload.settings?.quiet_hours || {};
  quietEnabled.checked = Boolean(quiet.enabled);
  quietStart.value = quiet.start || "22:00";
  quietEnd.value = quiet.end || "07:00";
  quietTimezone.value = quiet.timezone || "local";
  compactTools.checked = state.compactTools;
  streamMarkdown.checked = state.streamMarkdown;
  renderProviderTiles(runtime);

  const blocks = [];
  blocks.push(settingsSummaryBlock("当前模型", `${runtime.provider || "local"}${runtime.model ? ` · ${runtime.model}` : ""}`));
  blocks.push(settingsSummaryBlock("权限待处理", String(payload.permissions?.open_decisions || 0)));
  blocks.push(settingsSummaryBlock("记忆", `${payload.data_controls?.counts?.memory_pages || 0} 稳定 / ${payload.data_controls?.counts?.memory_candidates || 0} 候选`));
  blocks.push(settingsSummaryBlock("工作区", connectedDetail(payload.connected_apps, "workspace")));
  settingsSummary.replaceChildren(...blocks);
}

function renderProviderTiles(runtime) {
  if (!providerTiles) return;
  const currentProvider = runtime.provider || "local";
  const providers = [
    { id: "openai-compatible", title: "OpenAI 兼容", detail: runtime.model || "任意 /v1 兼容模型" },
    { id: "anthropic", title: "Anthropic", detail: "Claude 系列模型" },
    { id: "local", title: "本地模式", detail: "离线确定性运行时" },
  ];
  const tiles = providers.map((provider) => providerTile(provider, currentProvider));
  providerTiles.replaceChildren(...tiles);
}

function providerTile(provider, currentProvider) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "provider-tile";
  button.dataset.provider = provider.id;
  button.classList.toggle("active", provider.id === currentProvider);
  const mark = document.createElement("span");
  mark.textContent = provider.id === "anthropic" ? "A" : provider.id === "local" ? "L" : "O";
  const copy = document.createElement("span");
  const title = document.createElement("strong");
  title.textContent = provider.title;
  const detail = document.createElement("small");
  detail.textContent = provider.detail;
  copy.append(title, detail);
  const status = document.createElement("em");
  status.textContent = provider.id === currentProvider ? "正在使用" : "选择";
  button.append(mark, copy, status);
  button.addEventListener("click", () => {
    settingProvider.value = provider.id;
    syncProviderTiles(provider.id);
  });
  return button;
}

function syncProviderTiles(currentProvider) {
  if (!providerTiles) return;
  for (const tile of providerTiles.querySelectorAll(".provider-tile")) {
    const active = tile.dataset.provider === currentProvider;
    tile.classList.toggle("active", active);
    const badge = tile.querySelector("em");
    if (badge) badge.textContent = active ? "正在使用" : "选择";
  }
}

function settingsSummaryBlock(label, value) {
  const block = document.createElement("div");
  block.className = "summary-block";
  const strong = document.createElement("strong");
  strong.textContent = value;
  const span = document.createElement("span");
  span.textContent = label;
  block.append(strong, span);
  return block;
}

function connectedDetail(apps, id) {
  const item = (apps || []).find((app) => app.id === id);
  return item?.detail || "未连接";
}

async function saveSettings(options = {}) {
  settingsStatus.textContent = "保存中";
  const payload = {
    quiet_hours: {
      enabled: Boolean(quietEnabled.checked),
      start: quietStart.value || "22:00",
      end: quietEnd.value || "07:00",
      timezone: quietTimezone.value || "local",
    },
  };
  if (!options.quietOnly) {
    payload.runtime = {
      provider: settingProvider.value,
      model: settingModel.value.trim(),
      base_url: settingBaseUrl.value.trim(),
      api_key_env: settingApiKeyEnv.value.trim(),
      timeout_s: Number(settingTimeout.value || 30),
      retry_count: Number(settingRetryCount.value || 0),
      retry_backoff_s: Number(settingRetryBackoff.value || 0),
      max_tool_rounds: Number(settingMaxToolRounds.value || 12),
    };
  }
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const saved = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(saved.error || `HTTP ${response.status}`);
    renderSettings(saved);
    settingsStatus.textContent = "已保存";
  } catch (error) {
    settingsStatus.textContent = "保存失败";
    settingsSummary.replaceChildren(textRow(error.message || String(error)));
  }
}

function renderMarkdownInto(node, text) {
  node.classList.add("markdown");
  node.replaceChildren();
  const blocks = markdownBlocks(text || "");
  if (!blocks.length) {
    node.appendChild(document.createTextNode(""));
    return;
  }
  for (const block of blocks) {
    node.appendChild(block);
  }
}

function markdownBlocks(text) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  const headingIds = new Map();
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const code = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1;
      const pre = document.createElement("pre");
      const codeNode = document.createElement("code");
      codeNode.textContent = code.join("\n");
      pre.appendChild(codeNode);
      blocks.push(pre);
      continue;
    }
    if (isMarkdownFrontmatterStart(lines, index)) {
      const frontmatter = markdownFrontmatter(lines, index);
      blocks.push(frontmatter.node);
      index = frontmatter.nextIndex;
      continue;
    }
    if (isMarkdownHorizontalRule(line)) {
      blocks.push(document.createElement("hr"));
      index += 1;
      continue;
    }
    if (isMarkdownBlockquoteStart(line)) {
      const quoteLines = [];
      while (index < lines.length && isMarkdownBlockquoteStart(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push(markdownBlockquote(quoteLines));
      continue;
    }
    if (isMarkdownTableStart(lines, index)) {
      const tableLines = [lines[index], lines[index + 1]];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        tableLines.push(lines[index]);
        index += 1;
      }
      blocks.push(markdownTable(tableLines));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(4, heading[1].length);
      const node = document.createElement(`h${level}`);
      node.id = markdownAnchorId(heading[2], headingIds);
      appendInlineMarkdown(node, heading[2]);
      blocks.push(node);
      index += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const list = document.createElement("ul");
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        const item = document.createElement("li");
        appendInlineMarkdown(item, lines[index].replace(/^\s*[-*]\s+/, ""));
        list.appendChild(item);
        index += 1;
      }
      blocks.push(list);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const list = document.createElement("ol");
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        const item = document.createElement("li");
        appendInlineMarkdown(item, lines[index].replace(/^\s*\d+\.\s+/, ""));
        list.appendChild(item);
        index += 1;
      }
      blocks.push(list);
      continue;
    }
    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].startsWith("```") &&
      !isMarkdownFrontmatterStart(lines, index) &&
      !isMarkdownHorizontalRule(lines[index]) &&
      !isMarkdownBlockquoteStart(lines[index]) &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !/^\s*[-*]\s+/.test(lines[index]) &&
      !/^\s*\d+\.\s+/.test(lines[index]) &&
      !isMarkdownTableStart(lines, index)
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    const p = document.createElement("p");
    appendInlineMarkdown(p, paragraph.join(" "));
    blocks.push(p);
  }
  return blocks;
}

function markdownAnchorId(text, headingIds) {
  const base =
    String(text || "")
      .normalize("NFKD")
      .toLowerCase()
      .replace(/[`*_()[\]]/g, "")
      .replace(/[^\w\u4e00-\u9fff\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-") || "section";
  const count = headingIds.get(base) || 0;
  headingIds.set(base, count + 1);
  return count ? `${base}-${count + 1}` : base;
}

function isMarkdownDocumentStart(lines, index) {
  return lines.slice(0, index).every((line) => !String(line || "").trim());
}

function isMarkdownFrontmatterStart(lines, index) {
  if (!isMarkdownDocumentStart(lines, index) || String(lines[index] || "").trim() !== "---") return false;
  return lines.slice(index + 1).some((line) => String(line || "").trim() === "---");
}

function isMarkdownHorizontalRule(line) {
  return /^\s*-{3,}\s*$/.test(String(line || ""));
}

function isMarkdownBlockquoteStart(line) {
  return /^\s*>\s?/.test(String(line || ""));
}

function markdownBlockquote(lines) {
  const quote = document.createElement("blockquote");
  const children = markdownBlocks(lines.join("\n"));
  if (!children.length) {
    quote.appendChild(document.createTextNode(""));
    return quote;
  }
  for (const child of children) {
    quote.appendChild(child);
  }
  return quote;
}

function markdownFrontmatter(lines, index) {
  let end = index + 1;
  while (end < lines.length && String(lines[end] || "").trim() !== "---") {
    end += 1;
  }
  const rawLines = lines.slice(index, Math.min(end + 1, lines.length));
  const section = document.createElement("section");
  section.className = "markdown-frontmatter";
  const title = document.createElement("strong");
  title.textContent = "原始信息";
  const pre = document.createElement("pre");
  const codeNode = document.createElement("code");
  codeNode.textContent = rawLines.join("\n");
  pre.appendChild(codeNode);
  section.append(title, pre);
  return {
    node: section,
    nextIndex: Math.min(end + 1, lines.length),
  };
}

function isMarkdownTableStart(lines, index) {
  return Boolean(
    lines[index] &&
      lines[index + 1] &&
      lines[index].includes("|") &&
      /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1]),
  );
}

function markdownTable(lines) {
  const wrapper = document.createElement("div");
  wrapper.className = "markdown-table-wrap";
  const table = document.createElement("table");
  const [headLine, _separator, ...bodyLines] = lines;
  const header = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const cell of splitTableRow(headLine)) {
    const th = document.createElement("th");
    appendInlineMarkdown(th, cell);
    headerRow.appendChild(th);
  }
  header.appendChild(headerRow);
  const body = document.createElement("tbody");
  for (const line of bodyLines) {
    const row = document.createElement("tr");
    for (const cell of splitTableRow(line)) {
      const td = document.createElement("td");
      appendInlineMarkdown(td, cell);
      row.appendChild(td);
    }
    body.appendChild(row);
  }
  table.append(header, body);
  wrapper.appendChild(table);
  return wrapper;
}

function splitTableRow(line) {
  return String(line || "")
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function appendInlineMarkdown(parent, text) {
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  const source = String(text || "");
  for (const match of source.matchAll(pattern)) {
    if (match.index > last) parent.appendChild(document.createTextNode(source.slice(last, match.index)));
    parent.appendChild(inlineMarkdownNode(match[0]));
    last = match.index + match[0].length;
  }
  if (last < source.length) parent.appendChild(document.createTextNode(source.slice(last)));
}

function inlineMarkdownNode(token) {
  if (token.startsWith("**") && token.endsWith("**")) {
    const strong = document.createElement("strong");
    strong.textContent = token.slice(2, -2);
    return strong;
  }
  if (token.startsWith("*") && token.endsWith("*")) {
    const em = document.createElement("em");
    em.textContent = token.slice(1, -1);
    return em;
  }
  if (token.startsWith("`") && token.endsWith("`")) {
    const code = document.createElement("code");
    code.textContent = token.slice(1, -1);
    return code;
  }
  const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
  if (link) {
    const anchor = document.createElement("a");
    anchor.textContent = link[1];
    anchor.href = safeHref(link[2]);
    if (!anchor.href.endsWith(link[2]) || !String(link[2]).startsWith("#")) {
      anchor.target = "_blank";
      anchor.rel = "noreferrer";
    }
    return anchor;
  }
  return document.createTextNode(token);
}

function safeHref(value) {
  const text = String(value || "").trim();
  if (text.startsWith("#")) return text;
  try {
    const url = new URL(text, window.location.href);
    if (["http:", "https:", "mailto:"].includes(url.protocol)) return url.href;
  } catch (_error) {
    return "#";
  }
  return "#";
}

function actionButton(label, onClick, className = "action-button") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function setCardBusy(card, busy) {
  for (const button of card.querySelectorAll("button")) {
    button.disabled = busy;
  }
}

function prefillMessage(text) {
  switchView("chat", { updateLocation: true });
  input.value = text || "";
  resizeInput();
  updateComposerState();
  input.focus();
}

function insertComposerText(text) {
  switchView("chat", { updateLocation: true });
  const value = input.value || "";
  const start = input.selectionStart ?? value.length;
  const end = input.selectionEnd ?? start;
  input.value = `${value.slice(0, start)}${text}${value.slice(end)}`;
  const caret = start + String(text || "").length;
  input.setSelectionRange(caret, caret);
  resizeInput();
  updateComposerState();
  input.focus();
}

function rememberUserIntent(message) {
  state.lastUserIntent = compactText(message, 120);
  localStorage.setItem("mnemo.last_user_intent", state.lastUserIntent);
  updateContextPanel();
}

function updateContextPanel() {
  const recentIntent = state.lastUserIntent || "暂无最近请求";
  const runLabel = state.activeRunId ? compactId(state.activeRunId) : state.lastRunId ? compactId(state.lastRunId) : "未执行";
  contextUserPrompt.textContent = recentIntent;
  runBadge.textContent = runLabel;
  setText(railRecentIntent, recentIntent);
  setText(railRun, runLabel);
}

function updateComposerState() {
  const hasDraft = Boolean(input.value.trim());
  form.classList.toggle("composer-busy", state.busy);
  form.classList.toggle("composer-has-draft", hasDraft);
  send.disabled = state.busy || !hasDraft;
  reset.disabled = state.busy;
  stop.hidden = !state.busy;
  stop.disabled = !state.activeRunId || state.cancelRequested;
  input.disabled = false;
  input.setAttribute("aria-busy", String(state.busy));
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

function setStatus(text) {
  statusText.textContent = text;
  setText(railStatus, text);
  setRailActivityActive(text !== "空闲");
}

function setText(node, text) {
  if (node) node.textContent = text;
}

function setRailActivityActive(active) {
  if (railActivityRow) railActivityRow.classList.toggle("active", active);
}

function timelineScroll() {
  timeline.scrollTop = timeline.scrollHeight;
}

function loadingRow(text) {
  const row = document.createElement("p");
  row.className = "loading-row";
  row.textContent = text;
  return row;
}

function textRow(text) {
  const row = document.createElement("p");
  row.className = "text-row";
  row.textContent = text;
  return row;
}

function dimensionLabel(value) {
  return DIMENSION_LABELS[value] || value || "语境";
}

function confidenceLabel(value) {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  if (Number.isNaN(number)) return "";
  return `${Math.round(number * 100)}%`;
}

function compactText(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 1)).trim()}…`;
}

function compactId(value) {
  const text = String(value || "");
  if (text.length <= 12) return text || "none";
  return `${text.slice(0, 6)}…${text.slice(-4)}`;
}

function compactJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return String(value);
  }
}

function safeFileName(value) {
  return String(value || "artifact").replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "") || "artifact";
}
