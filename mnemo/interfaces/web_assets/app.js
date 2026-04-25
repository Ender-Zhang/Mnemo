const state = {
  conversationId: localStorage.getItem("mnemo.conversation_id") || "",
  missionId: localStorage.getItem("mnemo.mission_id") || "",
  lastRunId: localStorage.getItem("mnemo.last_run_id") || "",
  activeRunId: "",
  lastEventId: localStorage.getItem("mnemo.last_event_id") || "",
  renderedEventIds: new Set(),
  busy: false,
  assistantNode: null,
  actions: new Map(),
  artifacts: new Map(),
  cancelRequested: false,
};

const timeline = document.querySelector("#timeline");
const form = document.querySelector("#composer");
const input = document.querySelector("#message");
const send = document.querySelector("#send");
const stop = document.querySelector("#stop");
const reset = document.querySelector("#reset");
const statusText = document.querySelector("#status");

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || state.busy) return;
  input.value = "";
  resizeInput();
  runTurn(message);
});

input.addEventListener("input", resizeInput);
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
  state.cancelRequested = false;
  state.renderedEventIds.clear();
  state.artifacts.clear();
  localStorage.removeItem("mnemo.conversation_id");
  localStorage.removeItem("mnemo.mission_id");
  localStorage.removeItem("mnemo.last_run_id");
  localStorage.removeItem("mnemo.last_event_id");
  timeline.replaceChildren();
  updateComposerState();
  setStatus("Ready");
});

window.addEventListener("online", () => {
  resumeLastRun();
});

async function runTurn(message) {
  state.busy = true;
  state.cancelRequested = false;
  state.activeRunId = "";
  state.assistantNode = null;
  updateComposerState();
  addMessage("user", message);
  setStatus("Working");

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
      addCard("error", "Error", `HTTP ${response.status}`);
      return;
    }

    await readNdjson(response.body, handleEvent);
  } catch (error) {
    addCard("error", "Error", error.message || String(error));
  } finally {
    state.busy = false;
    state.cancelRequested = false;
    state.activeRunId = "";
    updateComposerState();
    state.assistantNode = null;
    await resumeLastRun({ incremental: true });
    setStatus("Ready");
    input.focus();
  }
}

async function requestCancel() {
  if (!state.busy || state.cancelRequested || !state.activeRunId) return;
  state.cancelRequested = true;
  updateComposerState();
  setStatus("Cancelling");
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
  const incremental = Boolean(options.incremental);
  const params = new URLSearchParams({ run_id: state.lastRunId, chat: "1" });
  if (incremental && state.lastEventId) {
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

  switch (event.type) {
    case "turn.started":
      setStatus("Started");
      break;
    case "conversation.hydrated":
    case "status.updated":
      setStatus(event.data?.text || event.data?.summary || "Working");
      break;
    case "assistant.delta":
      appendAssistant(event.data?.text || "");
      break;
    case "assistant.message":
      if (!state.assistantNode) addMessage("assistant", event.data?.text || "");
      break;
    case "action.queued":
    case "action.started":
    case "action.completed":
      renderAction(event);
      break;
    case "source.attached":
      renderSource(event.data?.source);
      break;
    case "artifact.card":
      renderArtifact(event.data?.artifact);
      break;
    case "learning.chip":
      renderLearning(event.data?.item);
      break;
    case "decision.card":
      renderDecision(event.data?.decision);
      break;
    case "run.completed":
      persistRun(event);
      state.cancelRequested = false;
      state.activeRunId = "";
      updateComposerState();
      setStatus("Ready");
      break;
    case "run.error":
    case "server.error":
      addCard("error", "Error", event.data?.error || "Run failed");
      break;
    default:
      break;
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
    if (state.busy) {
      state.activeRunId = event.run_id;
    }
    state.lastRunId = event.run_id;
    localStorage.setItem("mnemo.last_run_id", state.lastRunId);
  }
}

function appendAssistant(text) {
  if (!text) return;
  if (!state.assistantNode) {
    state.assistantNode = addMessage("assistant", "");
  }
  state.assistantNode.textContent += text;
  scrollToEnd();
}

function renderAction(event) {
  const action = event.data?.action || {};
  const actionId = event.data?.action_id || action.action_id || event.data?.provider_call_id;
  let card = state.actions.get(actionId);
  if (!card) {
    card = addCard("action", action.title || event.data?.tool_name || "Action", action.summary || "");
    state.actions.set(actionId, card);
  }

  const body = card.querySelector(".event-body");
  const badge = card.querySelector(".chip");
  if (event.type === "action.completed") {
    badge.textContent = event.data?.outcome || "completed";
    body.textContent = event.data?.summary || body.textContent || "Completed";
  } else {
    badge.textContent = event.type.replace("action.", "");
  }
}

function renderSource(source) {
  if (!source) return;
  const text = source.summary || source.title || "Source attached";
  addCard("", source.title || "Source", text);
}

function renderArtifact(artifact) {
  if (!artifact) return;
  const artifactId = artifact.artifact_id;
  const node = document.createElement("div");
  node.className = "event-card artifact";

  const titleRow = document.createElement("div");
  titleRow.className = "event-title";
  const titleNode = document.createElement("span");
  titleNode.textContent = artifact.title || "Artifact";

  const actions = document.createElement("div");
  actions.className = "artifact-actions";
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = artifact.kind || "updated";
  const toggle = document.createElement("button");
  toggle.className = "artifact-toggle";
  toggle.type = "button";
  toggle.textContent = "Open";
  toggle.disabled = !artifactId;
  actions.append(chip, toggle);
  titleRow.append(titleNode, actions);

  const summary = document.createElement("div");
  summary.className = "event-body";
  summary.textContent = artifact.kind || "updated";

  const viewer = document.createElement("div");
  viewer.className = "artifact-viewer";
  viewer.hidden = true;
  const body = document.createElement("pre");
  body.className = "artifact-body";
  viewer.appendChild(body);

  if (artifactId) {
    toggle.addEventListener("click", () => {
      toggleArtifact(artifactId, viewer, body, toggle);
    });
  }

  node.append(titleRow, summary, viewer);
  timeline.appendChild(node);
  scrollToEnd();
}

async function toggleArtifact(artifactId, viewer, body, toggle) {
  if (!viewer.hidden) {
    viewer.hidden = true;
    toggle.textContent = "Open";
    scrollToEnd();
    return;
  }

  if (!state.artifacts.has(artifactId)) {
    toggle.disabled = true;
    toggle.textContent = "Loading";
    try {
      const response = await fetch(`/api/artifacts?artifact_id=${encodeURIComponent(artifactId)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (payload.artifact) {
        state.artifacts.set(artifactId, payload.artifact);
      }
    } catch (error) {
      body.textContent = error.message || String(error);
      viewer.hidden = false;
      toggle.textContent = "Retry";
      toggle.disabled = false;
      scrollToEnd();
      return;
    }
    toggle.disabled = false;
  }

  const artifact = state.artifacts.get(artifactId) || {};
  body.textContent = artifact.body || "";
  viewer.hidden = false;
  toggle.textContent = "Hide";
  scrollToEnd();
}

function renderLearning(item) {
  if (!item) return;
  const node = document.createElement("div");
  node.className = "event-card learning";

  const titleRow = document.createElement("div");
  titleRow.className = "event-title";
  const title = document.createElement("span");
  title.textContent = item.kind === "memory" ? "Learning memory" : "Learning";
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = item.status || "draft";
  titleRow.append(title, chip);

  const body = document.createElement("div");
  body.className = "event-body";
  body.textContent = item.summary || "可能学到一个偏好或事实。";

  const actions = document.createElement("div");
  actions.className = "learning-actions";
  const itemId = item.item_id;
  if (item.kind === "memory") {
    actions.append(
      learningButton("以后这样", "accept", itemId, chip),
      learningButton("这次而已", "this_time", itemId, chip),
      learningButton("忽略", "reject", itemId, chip),
    );
  }

  node.append(titleRow, body, actions);
  timeline.appendChild(node);
  scrollToEnd();
}

function learningButton(label, action, itemId, statusChip) {
  const button = document.createElement("button");
  button.className = "learning-button";
  button.type = "button";
  button.textContent = label;
  button.disabled = !itemId;
  button.title = itemId ? label : "Learning item is not persisted";
  button.addEventListener("click", () => {
    resolveLearningMemory(itemId, action, statusChip, button.parentElement);
  });
  return button;
}

async function resolveLearningMemory(itemId, action, statusChip, actions) {
  if (!itemId || !actions) return;
  for (const button of actions.querySelectorAll("button")) {
    button.disabled = true;
  }
  statusChip.textContent = "resolving";
  try {
    const response = await fetch("/api/learning/memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_id: itemId, action }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    statusChip.textContent = payload.candidate?.status || action;
  } catch (error) {
    statusChip.textContent = "draft";
    for (const button of actions.querySelectorAll("button")) {
      button.disabled = false;
    }
    addCard("error", "Error", error.message || String(error));
  }
}

function renderDecision(decision) {
  if (!decision) return;
  const node = document.createElement("div");
  node.className = "event-card decision";

  const titleRow = document.createElement("div");
  titleRow.className = "event-title";
  const title = document.createElement("span");
  title.textContent = "Decision";
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = decision.status || "open";
  titleRow.append(title, chip);

  const body = document.createElement("div");
  body.className = "event-body";
  body.textContent = decision.reason
    ? `${decision.question || "Decision required"} ${decision.reason}`
    : decision.question || "Decision required";

  const actions = document.createElement("div");
  actions.className = "decision-actions";
  const itemId = decision.item_id;
  const buttons = [
    decisionButton("Approve", "accepted", itemId, chip),
    decisionButton("Reject", "rejected", itemId, chip),
    decisionButton("Ignore", "ignored", itemId, chip),
  ];
  actions.append(...buttons);

  node.append(titleRow, body, actions);
  timeline.appendChild(node);
  scrollToEnd();
}

function decisionButton(label, resolution, itemId, statusChip) {
  const button = document.createElement("button");
  button.className = "decision-button";
  button.type = "button";
  button.textContent = label;
  button.disabled = !itemId;
  button.title = itemId ? label : "Decision is not persisted";
  button.addEventListener("click", () => {
    resolveDecision(itemId, resolution, statusChip, button.parentElement);
  });
  return button;
}

async function resolveDecision(itemId, resolution, statusChip, actions) {
  if (!itemId || !actions) return;
  for (const button of actions.querySelectorAll("button")) {
    button.disabled = true;
  }
  statusChip.textContent = "resolving";
  try {
    const response = await fetch("/api/inbox/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, resolution }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    statusChip.textContent = payload.item?.resolution || resolution;
  } catch (error) {
    statusChip.textContent = "open";
    for (const button of actions.querySelectorAll("button")) {
      button.disabled = false;
    }
    addCard("error", "Error", error.message || String(error));
  }
}

function persistRun(event) {
  const result = event.data?.result || {};
  state.conversationId = event.conversation_id || result.conversation_id || state.conversationId;
  state.missionId = event.mission_id || result.mission_id || state.missionId;
  state.lastRunId = event.run_id || result.run_id || state.lastRunId;
  state.lastEventId = event.event_id || state.lastEventId;
  localStorage.setItem("mnemo.conversation_id", state.conversationId);
  localStorage.setItem("mnemo.mission_id", state.missionId);
  localStorage.setItem("mnemo.last_run_id", state.lastRunId);
  localStorage.setItem("mnemo.last_event_id", state.lastEventId);
}

function updateComposerState() {
  send.disabled = state.busy;
  reset.disabled = state.busy;
  stop.hidden = !state.busy;
  stop.disabled = !state.activeRunId || state.cancelRequested;
  stop.textContent = state.cancelRequested ? "Stopping" : "Stop";
}

function addMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  timeline.appendChild(node);
  scrollToEnd();
  return node;
}

function addCard(kind, title, bodyText) {
  const node = document.createElement("div");
  node.className = `event-card ${kind || ""}`.trim();
  const titleRow = document.createElement("div");
  titleRow.className = "event-title";
  const titleNode = document.createElement("span");
  titleNode.textContent = title;
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = kind || "updated";
  titleRow.append(titleNode, chip);
  const body = document.createElement("div");
  body.className = "event-body";
  body.textContent = bodyText || "";
  node.append(titleRow, body);
  timeline.appendChild(node);
  scrollToEnd();
  return node;
}

function setStatus(text) {
  statusText.textContent = text;
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

function scrollToEnd() {
  timeline.scrollTop = timeline.scrollHeight;
}

input.focus();
updateComposerState();
resumeLastRun();
