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
  artifacts: new Map(),
  artifactRelated: new Map(),
  settings: null,
  memoryOntology: null,
  memoryDimensions: new Map(),
  memoryItems: new Map(),
  avatarStarted: false,
  avatarRendered: false,
  compactTools: localStorage.getItem("mnemo.ui.compact_tools") !== "false",
  streamMarkdown: localStorage.getItem("mnemo.ui.stream_markdown") !== "false",
};

const views = {
  chat: document.querySelector("#chatView"),
  memory: document.querySelector("#memoryView"),
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
const glanceActivity = document.querySelector("#glanceActivity");
const glanceMemory = document.querySelector("#glanceMemory");
const glanceMemoryHint = document.querySelector("#glanceMemoryHint");
const glanceRuntime = document.querySelector("#glanceRuntime");
const railStatus = document.querySelector("#railStatus");
const railActivity = document.querySelector("#railActivity");
const railActivityRow = document.querySelector("#railActivityRow");
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
const memoryAvatar3d = document.querySelector("#memoryAvatar3d");
const memoryOrbit = document.querySelector("#memoryOrbit");
const settingsProviderForm = document.querySelector("#settingsProviderForm");
const providerTiles = document.querySelector("#providerTiles");
const settingProvider = document.querySelector("#settingProvider");
const settingModel = document.querySelector("#settingModel");
const settingBaseUrl = document.querySelector("#settingBaseUrl");
const settingApiKeyEnv = document.querySelector("#settingApiKeyEnv");
const settingTimeout = document.querySelector("#settingTimeout");
const settingRetryCount = document.querySelector("#settingRetryCount");
const settingRetryBackoff = document.querySelector("#settingRetryBackoff");
const quietEnabled = document.querySelector("#quietEnabled");
const quietStart = document.querySelector("#quietStart");
const quietEnd = document.querySelector("#quietEnd");
const quietTimezone = document.querySelector("#quietTimezone");
const compactTools = document.querySelector("#compactTools");
const streamMarkdown = document.querySelector("#streamMarkdown");
const saveExperience = document.querySelector("#saveExperience");
const settingsStatus = document.querySelector("#settingsStatus");
const settingsSummary = document.querySelector("#settingsSummary");
const memoryMarkdownModal = document.querySelector("#memoryMarkdownModal");
const memoryMarkdownClose = document.querySelector("#memoryMarkdownClose");
const memoryMarkdownTitle = document.querySelector("#memoryMarkdownTitle");
const memoryMarkdownBody = document.querySelector("#memoryMarkdownBody");

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

input.addEventListener("input", resizeInput);
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
  state.artifacts.clear();
  state.artifactRelated.clear();
  localStorage.removeItem("mnemo.conversation_id");
  localStorage.removeItem("mnemo.mission_id");
  localStorage.removeItem("mnemo.last_run_id");
  localStorage.removeItem("mnemo.last_event_id");
  localStorage.removeItem("mnemo.last_user_intent");
  timeline.replaceChildren(emptyState);
  emptyState.hidden = false;
  setStatus("空闲");
  updateContextPanel();
  updateComposerState();
});

attachButton.addEventListener("click", () => {
  prefillMessage("请使用这个文件：");
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

memoryMarkdownClose.addEventListener("click", closeMemoryMarkdown);
memoryMarkdownModal.addEventListener("click", (event) => {
  if (event.target === memoryMarkdownModal) closeMemoryMarkdown();
});

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!memoryMarkdownModal.hidden) {
    closeMemoryMarkdown();
    return;
  }
  if (document.body.classList.contains("mobile-sheet-open")) {
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
  for (const [viewName, view] of Object.entries(views)) {
    const active = useMobileSheet ? viewName === "chat" || viewName === target : viewName === target;
    view.classList.toggle("active", active);
    view.classList.toggle("sheet-active", useMobileSheet && viewName === target);
  }
  document.body.classList.toggle("mobile-sheet-open", useMobileSheet);
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
    initMemoryAvatar();
    loadMemoryCompass();
  }
  if (target === "settings") {
    loadSettings();
  }
  if (target === "chat") {
    input.focus();
  }
}

function isMobileSheetTarget(target) {
  return target !== "chat" && mobileSheetQuery.matches;
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
    event.data?.tone === "learning" ||
    toolName === "learning_discard" ||
    String(event.data?.summary || "").includes("Learning evidence discarded")
  );
}

function actionState(type) {
  if (type === "action.queued") return "queued";
  if (type === "action.started") return "running";
  if (type === "action.completed") return "done";
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
  const action = event.data?.action || {};
  const id = activityActionId(event);
  const key = `action:${id}`;
  const name = event.data?.tool_name || action.title || "tool";
  const stateName = actionState(event.type);
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
  row.meta.textContent = [action.risk || "", action.provider || "", compactId(id)].filter(Boolean).join(" · ");
  updateGlanceActivity(name, row.status.textContent);
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

  const status = document.createElement("span");
  status.className = "tool-status";
  status.textContent = "排队";

  summary.append(icon, text, status);

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

  return { node, title: text, status, meta, summary: description, details, result };
}

function toolStatusLabel(event) {
  if (event.type === "action.completed") {
    return event.data?.outcome === "success" ? "完成" : "失败";
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
  avatar.textContent = role === "user" ? "你" : "M";
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
  const title = document.createElement("strong");
  title.textContent = artifact.title || "Artifact";
  const meta = document.createElement("span");
  meta.textContent = artifact.kind || "artifact";
  header.append(title, meta);
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
  const title = document.createElement("strong");
  title.textContent = item.requires_confirmation ? "确认是否记住" : "学习信号";
  const summary = document.createElement("p");
  summary.textContent = item.summary || "";
  const actions = document.createElement("div");
  actions.className = "learning-actions";
  if (item.kind === "memory" && item.item_id) {
    actions.append(
      actionButton(item.requires_confirmation ? "确认记住" : "以后这样", () => resolveLearningMemory(item.item_id, "accept", card), "learning-button"),
      actionButton("这次而已", () => resolveLearningMemory(item.item_id, "this_time", card), "learning-button"),
      actionButton("不要记", () => resolveLearningMemory(item.item_id, "reject", card), "learning-button"),
    );
  }
  card.append(title, summary, actions);
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
  const title = document.createElement("strong");
  title.textContent = decision.title || "需要确认";
  const question = document.createElement("p");
  question.textContent = decision.question || decision.summary || "";
  const actions = document.createElement("div");
  actions.className = "decision-actions";
  if (decision.item_id) {
    actions.append(
      actionButton("同意", () => resolveDecision(decision.item_id, "accepted", card), "decision-button"),
      actionButton("拒绝", () => resolveDecision(decision.item_id, "rejected", card), "decision-button"),
      actionButton("忽略", () => resolveDecision(decision.item_id, "ignored", card), "decision-button"),
    );
  }
  card.append(title, question, actions);
  timeline.appendChild(card);
  timelineScroll();
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
  memoryCompass.replaceChildren(loadingRow("加载记忆罗盘"));
  memoryLayerDetail.replaceChildren(textRow("选择一个维度继续查看摘要与证据。"));
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
  renderMemoryOrbit(dimensions);
  const cards = dimensions.map((dimension) => memoryDimensionCard(dimension));
  memoryCompass.replaceChildren(...cards);
  const first = dimensions.find((item) => Number(item.pages || 0) + Number(item.candidates || 0) > 0) || dimensions[0];
  if (first) loadMemoryDimension(first.dimension);
}

function renderMemoryStats(counts) {
  const rows = [
    ["稳定记忆", counts.pages || 0],
    ["候选信号", counts.candidates || 0],
    ["覆盖维度", counts.covered_dimensions || 0],
  ].map(([label, value]) => {
    const row = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    const span = document.createElement("span");
    span.textContent = label;
    row.append(strong, span);
    return row;
  });
  memoryStats.replaceChildren(...rows);
}

function memoryDimensionCard(dimension) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "memory-dimension-card";
  button.dataset.dimension = dimension.dimension;
  const title = document.createElement("strong");
  title.textContent = dimensionLabel(dimension.dimension);
  const count = document.createElement("span");
  count.textContent = `${dimension.pages || 0}/${dimension.candidates || 0}`;
  const summary = document.createElement("p");
  summary.textContent = dimension.summary || "尚未沉淀稳定信号。";
  const meter = document.createElement("i");
  meter.className = "memory-meter";
  const total = Number(dimension.pages || 0) + Number(dimension.candidates || 0);
  meter.style.setProperty("--level", `${Math.min(100, total * 18)}%`);
  button.append(title, count, summary, meter);
  button.addEventListener("click", () => loadMemoryDimension(dimension.dimension));
  return button;
}

function renderMemoryOrbit(dimensions) {
  if (!memoryOrbit) return;
  const cards = dimensions.map((dimension, index) => memoryOrbitButton(dimension, index, dimensions.length || 1));
  memoryOrbit.replaceChildren(...cards);
}

function memoryOrbitButton(dimension, index, total) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "memory-orbit-button";
  button.dataset.dimension = dimension.dimension;
  const angle = (-90 + (360 / Math.max(total, 1)) * index) * (Math.PI / 180);
  button.style.setProperty("--x", `${Math.cos(angle) * 42}%`);
  button.style.setProperty("--y", `${Math.sin(angle) * 42}%`);
  const order = document.createElement("span");
  order.textContent = String(index + 1).padStart(2, "0");
  const label = document.createElement("strong");
  label.textContent = dimensionLabel(dimension.dimension);
  const count = document.createElement("small");
  count.textContent = `${Number(dimension.pages || 0) + Number(dimension.candidates || 0)} 条`;
  button.append(order, label, count);
  button.addEventListener("click", () => loadMemoryDimension(dimension.dimension));
  return button;
}

async function loadMemoryDimension(dimensionName) {
  const key = String(dimensionName || "context");
  for (const card of memoryCompass.querySelectorAll(".memory-dimension-card")) {
    card.classList.toggle("active", card.dataset.dimension === key);
  }
  if (memoryOrbit) {
    for (const card of memoryOrbit.querySelectorAll(".memory-orbit-button")) {
      card.classList.toggle("active", card.dataset.dimension === key);
    }
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
  const header = document.createElement("div");
  header.className = "memory-layer-header";
  const title = document.createElement("strong");
  title.textContent = dimensionLabel(payload.dimension);
  const summary = document.createElement("p");
  summary.textContent = payload.summary || "";
  header.append(title, summary);

  const stable = memoryDetailSection("稳定记忆", payload.pages || []);
  const candidates = memoryDetailSection("候选信号", payload.candidates || []);
  memoryLayerDetail.replaceChildren(header, stable, candidates);
}

function memoryDetailSection(titleText, entries) {
  const section = document.createElement("section");
  section.className = "memory-detail-section";
  const title = document.createElement("h3");
  title.textContent = titleText;
  const list = document.createElement("div");
  list.className = "memory-detail-list";
  if (!entries.length) {
    list.appendChild(textRow("暂无内容。"));
  }
  for (const item of entries) {
    list.appendChild(memoryLayerItem(item));
  }
  section.append(title, list);
  return section;
}

function memoryLayerItem(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "memory-detail-card";
  const title = document.createElement("strong");
  title.textContent = item.title || "Memory";
  const summary = document.createElement("p");
  summary.textContent = item.summary || "";
  const meta = document.createElement("span");
  meta.textContent = [item.kind || item.status || "memory", confidenceLabel(item.confidence)].filter(Boolean).join(" · ");
  button.append(title, summary, meta);
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
  const panel = document.createElement("section");
  panel.className = "memory-item-panel";
  const title = document.createElement("strong");
  title.textContent = item.title || "Memory";
  const summary = document.createElement("p");
  summary.textContent = item.summary || "";
  const meta = document.createElement("span");
  meta.textContent = [dimensionLabel(item.dimension), item.status || item.type || "memory", confidenceLabel(item.confidence)].filter(Boolean).join(" · ");
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
    actionButton("忘记", () => prefillMemoryAction("forget", payload), "secondary-button small"),
    actionButton("查看详情", () => openMemoryMarkdown(payload), "secondary-button small"),
  );
  panel.append(title, summary, meta, evidence, actions);
  const existing = memoryLayerDetail.querySelector(".memory-item-panel");
  if (existing) existing.replaceWith(panel);
  else memoryLayerDetail.appendChild(panel);
  revealMemoryItemPanel(panel);
}

function revealMemoryItemPanel(panel) {
  window.requestAnimationFrame(() => {
    panel.scrollIntoView({ block: document.body.classList.contains("mobile-sheet-open") ? "center" : "nearest" });
  });
}

function memoryDetailEvidence(item) {
  const row = document.createElement("div");
  row.className = "memory-detail-evidence";
  const title = document.createElement("strong");
  title.textContent = item.kind || "evidence";
  const summary = document.createElement("p");
  summary.textContent = item.summary || item.reason || "";
  row.append(title, summary);
  return row;
}

function openMemoryMarkdown(payload) {
  const item = payload.item || {};
  memoryMarkdownTitle.textContent = item.title || "记忆详情";
  renderMarkdownInto(memoryMarkdownBody, payload.markdown || memoryPayloadMarkdown(payload));
  memoryMarkdownModal.hidden = false;
}

function closeMemoryMarkdown() {
  memoryMarkdownModal.hidden = true;
}

function memoryPayloadMarkdown(payload) {
  const item = payload.item || {};
  const lines = [
    `# ${item.title || "Memory"}`,
    "",
    `- 维度: ${dimensionLabel(item.dimension || "context")}`,
    `- 类型: ${item.type || "memory"}`,
    `- 状态: ${item.status || "unknown"}`,
    "",
    "## 摘要",
    "",
    item.summary || "",
  ];
  const evidence = payload.evidence || [];
  if (evidence.length) {
    lines.push("", "## 证据", "");
    for (const row of evidence) {
      lines.push(`- **${row.kind || "evidence"}**: ${row.summary || row.reason || ""}`);
    }
  }
  return lines.join("\n");
}

function prefillMemoryAction(intent, payload) {
  const item = payload.item || {};
  const title = item.title || "这条记忆";
  const summary = item.summary || "";
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

async function initMemoryAvatar() {
  if (state.avatarStarted || !memoryAvatar3d) return;
  state.avatarStarted = true;
  const fallbackTimer = window.setTimeout(() => {
    if (!state.avatarRendered) {
      state.avatarRendered = true;
      renderCanvasAvatar();
    }
  }, 450);
  try {
    const THREE = await import("https://unpkg.com/three@0.160.0/build/three.module.js");
    if (!state.avatarRendered) {
      state.avatarRendered = true;
      window.clearTimeout(fallbackTimer);
      renderThreeAvatar(THREE);
    }
  } catch (_error) {
    if (!state.avatarRendered) {
      state.avatarRendered = true;
      window.clearTimeout(fallbackTimer);
      renderCanvasAvatar();
    }
  }
}

function renderThreeAvatar(THREE) {
  const canvas = memoryAvatar3d;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 1.4, 5.2);
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(2.8, 4, 3);
  scene.add(key, new THREE.AmbientLight(0xdce8ff, 1.2));

  const group = new THREE.Group();
  const skin = new THREE.MeshStandardMaterial({ color: 0xf4d7c7, roughness: 0.58, metalness: 0.05 });
  const suit = new THREE.MeshStandardMaterial({ color: 0x1f2d3a, roughness: 0.42, metalness: 0.18 });
  const accent = new THREE.MeshStandardMaterial({ color: 0x21a6a0, roughness: 0.35, metalness: 0.25 });
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.42, 48, 48), skin);
  head.position.y = 1.45;
  const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.58, 1.15, 40), suit);
  torso.position.y = 0.55;
  const core = new THREE.Mesh(new THREE.TorusGeometry(1.35, 0.01, 16, 128), accent);
  core.rotation.x = Math.PI / 2.4;
  const halo = new THREE.Mesh(new THREE.TorusGeometry(1.82, 0.012, 16, 160), accent);
  halo.rotation.x = Math.PI / 2;
  const armLeft = limb(THREE, suit, -0.68, 0.7, 0.35);
  const armRight = limb(THREE, suit, 0.68, 0.7, -0.35);
  const legLeft = limb(THREE, suit, -0.25, -0.35, 0.08);
  const legRight = limb(THREE, suit, 0.25, -0.35, -0.08);
  group.add(head, torso, core, halo, armLeft, armRight, legLeft, legRight);
  scene.add(group);

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const size = Math.max(260, Math.min(rect.width || 420, rect.height || 420));
    renderer.setSize(size, size, false);
    camera.aspect = 1;
    camera.updateProjectionMatrix();
  }

  resize();
  if (window.ResizeObserver) {
    new ResizeObserver(resize).observe(canvas);
  } else {
    window.addEventListener("resize", resize);
  }

  function frame(time) {
    group.rotation.y = time * 0.00022;
    core.rotation.z = time * 0.00035;
    halo.rotation.z = -time * 0.00019;
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function limb(THREE, material, x, y, rotationZ) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.16, 0.9, 24), material);
  mesh.position.set(x, y, 0);
  mesh.rotation.z = rotationZ;
  return mesh;
}

function renderCanvasAvatar() {
  const canvas = memoryAvatar3d;
  const ctx = canvas.getContext("2d");
  function frame(time) {
    const width = canvas.width;
    const height = canvas.height;
    const centerX = width / 2;
    const centerY = height / 2 + 14;
    ctx.clearRect(0, 0, width, height);
    const gradient = ctx.createRadialGradient(centerX, centerY - 30, 28, centerX, centerY, width * 0.48);
    gradient.addColorStop(0, "rgba(255,255,255,0.98)");
    gradient.addColorStop(0.55, "rgba(228,243,240,0.42)");
    gradient.addColorStop(1, "rgba(33,166,160,0.04)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    drawAvatarGrid(ctx, width, height, centerX, centerY);
    ctx.strokeStyle = "rgba(11,125,120,0.26)";
    ctx.lineWidth = 2.2;
    for (let index = 0; index < 4; index += 1) {
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.rotate(time * 0.00018 + index * 0.78);
      ctx.beginPath();
      ctx.ellipse(0, 0, width * (0.21 + index * 0.045), height * 0.085, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
    const avatarGradient = ctx.createLinearGradient(centerX, centerY - 170, centerX, centerY + 150);
    avatarGradient.addColorStop(0, "rgba(255,255,255,0.88)");
    avatarGradient.addColorStop(0.48, "rgba(118,139,174,0.34)");
    avatarGradient.addColorStop(1, "rgba(11,125,120,0.11)");
    ctx.fillStyle = avatarGradient;
    ctx.strokeStyle = "rgba(98,84,199,0.24)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(centerX, centerY - 132, 35, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(centerX - 54, centerY - 82);
    ctx.bezierCurveTo(centerX - 44, centerY - 124, centerX + 44, centerY - 124, centerX + 54, centerY - 82);
    ctx.lineTo(centerX + 42, centerY + 58);
    ctx.bezierCurveTo(centerX + 34, centerY + 106, centerX - 34, centerY + 106, centerX - 42, centerY + 58);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(255,255,255,0.48)";
    ctx.lineWidth = 1;
    for (let y = -74; y <= 54; y += 24) {
      ctx.beginPath();
      ctx.moveTo(centerX - 38, centerY + y);
      ctx.quadraticCurveTo(centerX, centerY + y + 8, centerX + 38, centerY + y);
      ctx.stroke();
    }
    ctx.strokeStyle = "rgba(11,125,120,0.42)";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(centerX - 30, centerY - 35);
    ctx.lineTo(centerX + 30, centerY - 35);
    ctx.stroke();
    ctx.fillStyle = "rgba(11,125,120,0.12)";
    roundRect(ctx, centerX - 86, centerY + 120, 172, 20, 10);
    ctx.fill();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function drawAvatarGrid(ctx, width, height, centerX, centerY) {
  ctx.save();
  ctx.translate(centerX, centerY + 114);
  ctx.strokeStyle = "rgba(11,125,120,0.08)";
  ctx.lineWidth = 1;
  for (let index = 0; index < 6; index += 1) {
    ctx.beginPath();
    ctx.ellipse(0, 0, width * (0.08 + index * 0.052), height * (0.018 + index * 0.011), 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (let index = 0; index < 10; index += 1) {
    const angle = (Math.PI * 2 * index) / 10;
    ctx.beginPath();
    ctx.moveTo(Math.cos(angle) * 24, Math.sin(angle) * 8);
    ctx.lineTo(Math.cos(angle) * width * 0.36, Math.sin(angle) * height * 0.08);
    ctx.stroke();
  }
  ctx.restore();
}

function roundRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
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
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
    return anchor;
  }
  return document.createTextNode(token);
}

function safeHref(value) {
  try {
    const url = new URL(value, window.location.href);
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
  send.disabled = state.busy;
  reset.disabled = state.busy;
  stop.hidden = !state.busy;
  stop.disabled = !state.activeRunId || state.cancelRequested;
  input.disabled = state.busy;
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
