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
  activityRows: new Map(),
  artifacts: new Map(),
  artifactRelated: new Map(),
  settings: null,
  cancelRequested: false,
  lastUserIntent: localStorage.getItem("mnemo.last_user_intent") || "",
};

const timeline = document.querySelector("#timeline");
const appShell = document.querySelector(".app-shell");
const form = document.querySelector("#composer");
const input = document.querySelector("#message");
const send = document.querySelector("#send");
const stop = document.querySelector("#stop");
const reset = document.querySelector("#reset");
const statusText = document.querySelector("#status");
const runBadge = document.querySelector("#runBadge");
const settingsOpen = document.querySelector("#settingsOpen");
const settingsOverlay = document.querySelector("#settingsOverlay");
const settingsClose = document.querySelector("#settingsClose");
const settingsContent = document.querySelector("#settingsContent");
const settingsStatus = document.querySelector("#settingsStatus");
const activityToggle = document.querySelector("#activityToggle");
const activityList = document.querySelector("#activityList");
const activityCount = document.querySelector("#activityCount");
const contextUserPrompt = document.querySelector("#contextUserPrompt");
const contextConversation = document.querySelector("#contextConversation");
const contextMission = document.querySelector("#contextMission");
const contextRun = document.querySelector("#contextRun");
const attachButton = document.querySelector("#attachButton");
const voiceButton = document.querySelector("#voiceButton");
const mentionButton = document.querySelector("#mentionButton");

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
  state.artifactRelated.clear();
  state.activityRows.clear();
  state.lastUserIntent = "";
  localStorage.removeItem("mnemo.conversation_id");
  localStorage.removeItem("mnemo.mission_id");
  localStorage.removeItem("mnemo.last_run_id");
  localStorage.removeItem("mnemo.last_event_id");
  localStorage.removeItem("mnemo.last_user_intent");
  timeline.replaceChildren();
  clearActivity();
  updateContextPanel();
  updateComposerState();
  setStatus("Ready");
});

settingsOpen.addEventListener("click", () => {
  openSettings();
});

settingsClose.addEventListener("click", () => {
  closeSettings();
});

settingsOverlay.addEventListener("click", (event) => {
  if (event.target === settingsOverlay) closeSettings();
});

activityToggle.addEventListener("click", () => {
  appShell.classList.toggle("activity-collapsed");
});

attachButton.addEventListener("click", () => {
  prefillMessage("Use this file: ");
});

voiceButton.addEventListener("click", () => {
  prefillMessage("Voice note: ");
});

mentionButton.addEventListener("click", () => {
  prefillMessage("@");
});

window.addEventListener("online", () => {
  resumeLastRun();
});

async function runTurn(message) {
  state.busy = true;
  state.cancelRequested = false;
  state.activeRunId = "";
  state.assistantNode = null;
  rememberUserIntent(message);
  updateComposerState();
  addMessage("user", message);
  upsertActivity("turn", "run", "Turn started", message);
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
  if (!isInternalLearningEvent(event)) {
    renderActivity(event);
  }

  switch (event.type) {
    case "turn.started":
      handleTurnStarted(event);
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
      finalizeAssistantMarkdown(event.data?.text || "");
      break;
    case "action.queued":
    case "action.started":
    case "action.completed":
      if (!isInternalLearningEvent(event)) renderAction(event);
      break;
    case "source.attached":
      renderSource(event.data?.source);
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
      state.cancelRequested = false;
      state.activeRunId = "";
      if (state.assistantNode) finalizeAssistantMarkdown("");
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
  updateContextPanel();
}

function handleTurnStarted(event) {
  const summary = event.data?.input_summary || "";
  if (summary) {
    rememberUserIntent(summary);
    if (!state.busy) {
      addMessage("user", summary);
    }
  }
}

function rememberUserIntent(text) {
  const compact = String(text || "").trim();
  if (!compact) return;
  state.lastUserIntent = compact;
  localStorage.setItem("mnemo.last_user_intent", compact);
  updateContextPanel();
}

function updateContextPanel() {
  if (contextUserPrompt) contextUserPrompt.textContent = state.lastUserIntent || "No recent prompt";
  if (contextConversation) contextConversation.textContent = compactId(state.conversationId, "new");
  if (contextMission) contextMission.textContent = compactId(state.missionId, "new");
  if (contextRun) contextRun.textContent = compactId(state.lastRunId || state.activeRunId, "none");
}

function compactId(value, fallback) {
  const text = String(value || "").trim();
  if (!text) return fallback;
  if (text.length <= 18) return text;
  return `${text.slice(0, 8)}...${text.slice(-4)}`;
}

function isInternalLearningEvent(event) {
  if (event.type === "status.updated" && event.data?.tone === "learning") {
    return true;
  }
  if (event.type?.startsWith("action.")) {
    return (event.data?.tool_name || event.data?.action?.title) === "learning_discard";
  }
  return false;
}

function renderActivity(event) {
  switch (event.type) {
    case "turn.started":
      upsertActivity("turn", "run", "Run started", event.data?.input_summary || event.run_id || "");
      break;
    case "conversation.hydrated":
      upsertActivity("context", "run", "Context restored", event.data?.summary || "");
      break;
    case "status.updated":
      upsertActivity("status", "run", "Status", event.data?.text || event.data?.summary || "");
      break;
    case "assistant.delta":
      upsertActivity("assistant-stream", "run", "Streaming answer", "Receiving model output");
      break;
    case "action.queued":
    case "action.started":
    case "action.completed":
      upsertActivity(
        `action:${activityActionId(event)}`,
        "action",
        event.data?.action?.title || event.data?.tool_name || "Action",
        event.data?.summary || event.type.replace("action.", ""),
      );
      break;
    case "artifact.card":
      upsertActivity(
        `artifact:${event.data?.artifact?.artifact_id || Date.now()}`,
        "artifact",
        event.data?.artifact?.title || "Artifact",
        event.data?.artifact?.kind || "",
      );
      break;
    case "recall.card":
      upsertActivity("recall", "recall", "Recall", event.data?.recall?.query || "");
      break;
    case "learning.chip":
      upsertActivity(
        `learning:${event.data?.item?.item_id || Date.now()}`,
        "learning",
        "Memory candidate",
        event.data?.item?.summary || event.data?.item?.status || "",
      );
      break;
    case "decision.card":
      upsertActivity(
        `decision:${event.data?.decision?.item_id || Date.now()}`,
        "decision",
        "Decision needed",
        event.data?.decision?.question || "",
      );
      break;
    case "run.completed":
      upsertActivity("completed", "run", "Run completed", event.data?.status || "completed");
      break;
    case "run.error":
    case "server.error":
      upsertActivity("error", "error", "Error", event.data?.error || "Run failed");
      break;
    default:
      break;
  }
}

function activityActionId(event) {
  return event.data?.action_id
    || event.data?.action?.action_id
    || event.data?.provider_call_id
    || event.data?.tool_name
    || "unknown";
}

function upsertActivity(key, kind, title, detail) {
  if (!activityList) return;
  let row = state.activityRows.get(key);
  if (!row) {
    row = activityRow(kind);
    state.activityRows.set(key, row);
    activityList.prepend(row.node);
  }
  row.node.className = `activity-item ${kind || "run"}`;
  row.title.textContent = title || "Activity";
  row.detail.textContent = detail || "";
  if (row.node !== activityList.firstElementChild) {
    activityList.prepend(row.node);
  }
  while (activityList.children.length > 24) {
    const last = activityList.lastElementChild;
    for (const [activityKey, activityRowValue] of state.activityRows.entries()) {
      if (activityRowValue.node === last) state.activityRows.delete(activityKey);
    }
    last.remove();
  }
  updateActivityCount();
}

function pushActivity(kind, title, detail) {
  upsertActivity(`note:${Date.now()}:${activityList?.children.length || 0}`, kind, title, detail);
}

function activityRow(kind) {
  const node = document.createElement("div");
  node.className = `activity-item ${kind || "run"}`;
  const dot = document.createElement("span");
  dot.className = "activity-dot";
  const copy = document.createElement("div");
  const title = document.createElement("div");
  title.className = "activity-title";
  const detail = document.createElement("div");
  detail.className = "activity-detail";
  copy.append(title, detail);
  node.append(dot, copy);
  return { node, title, detail };
}

function clearActivity() {
  if (!activityList) return;
  state.activityRows.clear();
  activityList.replaceChildren();
  updateActivityCount();
}

function updateActivityCount() {
  if (!activityCount || !activityList) return;
  activityCount.textContent = String(activityList.children.length);
}

function appendAssistant(text) {
  if (!text) return;
  if (!state.assistantNode) {
    state.assistantNode = addMessage("assistant", "");
  }
  state.assistantNode.classList.add("streaming");
  const rawText = `${state.assistantNode.dataset.rawText || state.assistantNode.textContent || ""}${text}`;
  state.assistantNode.dataset.rawText = rawText;
  state.assistantNode.textContent = rawText;
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
  const toggle = artifactButton("Open", () => {
    toggleArtifact(artifactId, viewer, body, toggle);
  });
  toggle.disabled = !artifactId;
  const continueButton = artifactButton("Continue", () => {
    prefillMessage(`Continue editing artifact ${artifactId}: `);
  });
  continueButton.disabled = !artifactId;
  const exportButton = artifactButton("Export", () => {
    exportArtifact(artifactId);
  });
  exportButton.disabled = !artifactId;
  const compareButton = artifactButton("Compare", () => {
    toggleArtifactRelated(artifactId, related, compareButton);
  });
  compareButton.disabled = !artifactId;
  const sendButton = artifactButton("Send", () => {
    prefillMessage(`Send artifact ${artifactId} to: `);
  });
  sendButton.disabled = !artifactId;
  actions.append(chip, toggle, continueButton, exportButton, compareButton, sendButton);
  if (artifactId && isPatchArtifact(artifact.kind)) {
    actions.append(
      artifactButton("Apply", () => {
        prefillMessage(`Apply artifact ${artifactId} as a patch: `);
      }),
      artifactButton("Revert", () => {
        prefillMessage(`Revert changes from artifact ${artifactId}: `);
      }),
    );
  }
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

  const related = document.createElement("div");
  related.className = "artifact-related";
  related.hidden = true;

  node.append(titleRow, summary, viewer, related);
  timeline.appendChild(node);
  scrollToEnd();
}

function artifactButton(label, onClick) {
  const button = document.createElement("button");
  button.className = "artifact-toggle";
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

async function toggleArtifact(artifactId, viewer, body, toggle) {
  if (!viewer.hidden) {
    viewer.hidden = true;
    toggle.textContent = "Open";
    scrollToEnd();
    return;
  }

  toggle.disabled = true;
  toggle.textContent = "Loading";
  try {
    await loadArtifact(artifactId);
  } catch (error) {
    body.textContent = error.message || String(error);
    viewer.hidden = false;
    toggle.textContent = "Retry";
    toggle.disabled = false;
    scrollToEnd();
    return;
  }
  toggle.disabled = false;

  const artifact = state.artifacts.get(artifactId) || {};
  body.textContent = artifact.body || "";
  viewer.hidden = false;
  toggle.textContent = "Hide";
  scrollToEnd();
}

async function loadArtifact(artifactId) {
  if (state.artifacts.has(artifactId)) return state.artifacts.get(artifactId);
  const response = await fetch(`/api/artifacts?artifact_id=${encodeURIComponent(artifactId)}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  if (payload.artifact) {
    state.artifacts.set(artifactId, payload.artifact);
    state.artifactRelated.set(artifactId, Array.isArray(payload.related) ? payload.related : []);
  }
  return state.artifacts.get(artifactId) || {};
}

async function exportArtifact(artifactId) {
  if (!artifactId) return;
  try {
    const artifact = await loadArtifact(artifactId);
    const blob = new Blob([artifact.body || ""], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = artifactFilename(artifact);
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    addCard("error", "Error", error.message || String(error));
  }
}

async function toggleArtifactRelated(artifactId, related, button) {
  if (!artifactId) return;
  if (!related.hidden) {
    related.hidden = true;
    button.textContent = "Compare";
    scrollToEnd();
    return;
  }
  button.disabled = true;
  button.textContent = "Loading";
  try {
    await loadArtifact(artifactId);
  } catch (error) {
    related.replaceChildren(artifactRelatedMessage(error.message || String(error)));
    related.hidden = false;
    button.textContent = "Retry";
    button.disabled = false;
    scrollToEnd();
    return;
  }
  button.disabled = false;
  button.textContent = "Hide";
  const items = state.artifactRelated.get(artifactId) || [];
  related.replaceChildren();
  if (items.length === 0) {
    related.appendChild(artifactRelatedMessage("No related artifacts in this mission."));
  } else {
    for (const item of items) {
      related.appendChild(artifactRelatedRow(artifactId, item));
    }
  }
  related.hidden = false;
  scrollToEnd();
}

function artifactRelatedRow(artifactId, item) {
  const row = document.createElement("div");
  row.className = "artifact-related-row";
  const title = document.createElement("div");
  title.className = "artifact-related-title";
  title.textContent = item.title || item.id || "Artifact";
  const detail = document.createElement("div");
  detail.className = "event-body";
  detail.textContent = item.kind || "artifact";
  const actions = document.createElement("div");
  actions.className = "artifact-actions";
  actions.append(
    artifactButton("Compare", () => {
      prefillMessage(`Compare artifact ${artifactId} with artifact ${item.id}: `);
    }),
    artifactButton("Revert to", () => {
      prefillMessage(`Revert artifact ${artifactId} to artifact ${item.id}: `);
    }),
  );
  row.append(title, detail, actions);
  return row;
}

function artifactRelatedMessage(text) {
  const node = document.createElement("div");
  node.className = "event-body";
  node.textContent = text;
  return node;
}

function artifactFilename(artifact) {
  const title = String(artifact.title || artifact.id || "artifact")
    .trim()
    .replace(/[^a-z0-9._-]+/gi, "-")
    .replace(/^-+|-+$/g, "");
  const extension = artifact.kind === "markdown" ? "md" : "txt";
  return `${title || "artifact"}.${extension}`;
}

function isPatchArtifact(kind) {
  const value = String(kind || "").toLowerCase();
  return value.includes("diff") || value.includes("patch");
}

function renderLearning(item) {
  if (!item) return;
  const needsConfirmation = Boolean(item.requires_confirmation) || String(item.status || "").startsWith("needs_review");
  const node = document.createElement("div");
  node.className = "event-card learning";
  if (needsConfirmation) node.classList.add("confirmation");

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
  body.textContent = item.summary || (needsConfirmation ? "这条学习需要你确认后才会长期记住。" : "可能学到一个偏好或事实。");

  const actions = document.createElement("div");
  actions.className = "learning-actions";
  const itemId = item.item_id;
  if (item.kind === "memory") {
    actions.append(
      learningButton(needsConfirmation ? "确认记住" : "以后这样", "accept", itemId, chip),
      learningButton("这次而已", "this_time", itemId, chip),
      learningButton("忽略", "reject", itemId, chip),
    );
  }

  node.append(titleRow, body, actions);
  timeline.appendChild(node);
  scrollToEnd();
}

function renderRecall(recall) {
  if (!recall) return;
  const items = Array.isArray(recall.items) ? recall.items : [];
  const node = document.createElement("div");
  node.className = "event-card recall";

  const titleRow = document.createElement("div");
  titleRow.className = "event-title";
  const title = document.createElement("span");
  title.textContent = "Recall";
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = `${items.length} found`;
  titleRow.append(title, chip);

  const body = document.createElement("div");
  body.className = "event-body";
  body.textContent = recall.query ? `“${recall.query}”` : "Past context";

  const list = document.createElement("div");
  list.className = "recall-items";
  for (const item of items) {
    list.appendChild(recallItem(item));
  }

  node.append(titleRow, body, list);
  timeline.appendChild(node);
  scrollToEnd();
}

function recallItem(item) {
  const row = document.createElement("div");
  row.className = "recall-item";

  const titleRow = document.createElement("div");
  titleRow.className = "recall-title";
  const title = document.createElement("span");
  title.textContent = item.title || "Untitled";
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = item.kind || item.source_type || "context";
  titleRow.append(title, chip);

  const summary = document.createElement("div");
  summary.className = "event-body";
  summary.textContent = item.summary || "";

  const actions = document.createElement("div");
  actions.className = "recall-actions";

  row.append(titleRow, summary, actions);
  appendRecallActions(actions, item, row, chip);
  return row;
}

function appendRecallActions(actions, item, row, statusChip) {
  if (item.kind === "artifact" && item.artifact_id) {
    const viewer = document.createElement("div");
    viewer.className = "artifact-viewer";
    viewer.hidden = true;
    const body = document.createElement("pre");
    body.className = "artifact-body";
    viewer.appendChild(body);
    actions.appendChild(recallButton("Open", () => {
      toggleArtifact(item.artifact_id, viewer, body, actions.querySelector("button"));
    }));
    actions.appendChild(recallButton("Reuse", () => {
      prefillMessage(`Reuse artifact ${item.artifact_id}: `);
    }));
    row.appendChild(viewer);
    return;
  }

  if (item.kind === "decision" && item.status === "open" && item.item_id) {
    actions.append(
      decisionButton("Approve", "accepted", item.item_id, statusChip),
      decisionButton("Reject", "rejected", item.item_id, statusChip),
      decisionButton("Ignore", "ignored", item.item_id, statusChip),
    );
    return;
  }

  if (item.kind === "past_work") {
    actions.appendChild(recallButton("Continue", () => {
      prefillMessage(`Continue from run ${item.run_id || item.item_id}: `);
    }));
    return;
  }

  actions.appendChild(recallButton("Use", () => {
    prefillMessage(`Use recalled context ${item.item_id || ""}: `);
  }));
}

function recallButton(label, onClick) {
  const button = document.createElement("button");
  button.className = "recall-button";
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function prefillMessage(text) {
  input.value = text;
  resizeInput();
  input.focus();
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
  const previousStatus = statusChip.textContent || "draft";
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
    if (action === "undo") {
      actions.replaceChildren();
    } else {
      actions.replaceChildren(learningButton("撤销", "undo", itemId, statusChip));
    }
  } catch (error) {
    statusChip.textContent = previousStatus;
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
    if (payload.tool_result) {
      const tool = payload.tool_result;
      addCard(tool.ok ? "action" : "error", tool.tool || tool.name || "Action", tool.summary || "Tool completed");
    }
  } catch (error) {
    statusChip.textContent = "open";
    for (const button of actions.querySelectorAll("button")) {
      button.disabled = false;
    }
    addCard("error", "Error", error.message || String(error));
  }
}

async function openSettings() {
  settingsOverlay.hidden = false;
  settingsContent.replaceChildren(settingsLoadingRow("Loading"));
  settingsStatus.textContent = "Loading";
  settingsClose.focus();
  try {
    const response = await fetch("/api/settings");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.settings = payload;
    renderSettings(payload);
    settingsStatus.textContent = "Ready";
  } catch (error) {
    settingsStatus.textContent = "Error";
    settingsContent.replaceChildren(settingsLoadingRow(error.message || String(error)));
  }
}

function closeSettings() {
  settingsOverlay.hidden = true;
  settingsOpen.focus();
}

function renderSettings(payload) {
  settingsContent.replaceChildren(
    settingsConnectedSection(payload.connected_apps || []),
    settingsPermissionSection(payload.permissions || {}),
    settingsQuietHoursSection(payload.quiet_hours || payload.settings?.quiet_hours || {}),
    settingsPreferenceSection(payload.learned_preferences || {}),
    settingsDataControlSection(payload.data_controls || {}),
  );
}

function settingsConnectedSection(items) {
  const body = document.createElement("div");
  body.className = "settings-list";
  for (const item of items) {
    body.appendChild(settingsRow(item.label || item.id || "Connection", item.status || "", item.detail || ""));
  }
  return settingsSection("Connected Apps", body);
}

function settingsPermissionSection(permissions) {
  const body = document.createElement("div");
  body.className = "settings-list";
  for (const policy of permissions.risk_policy || []) {
    body.appendChild(settingsRow(policy.risk || "risk", policy.behavior || "", ""));
  }
  const openDecisions = Number(permissions.open_decisions || 0);
  const row = settingsRow("Open decisions", String(openDecisions), "");
  const button = settingsActionButton("Review", () => {
    closeSettings();
    prefillMessage("Show my open decisions.");
  });
  row.appendChild(button);
  body.appendChild(row);
  return settingsSection("Permissions", body);
}

function settingsQuietHoursSection(quietHours) {
  const body = document.createElement("form");
  body.className = "settings-form";
  const enabledLabel = document.createElement("label");
  enabledLabel.className = "settings-check";
  const enabled = document.createElement("input");
  enabled.type = "checkbox";
  enabled.checked = Boolean(quietHours.enabled);
  enabledLabel.append(enabled, document.createTextNode("Quiet hours"));

  const range = document.createElement("div");
  range.className = "settings-time-grid";
  const start = settingsTimeInput("Start", quietHours.start || "22:00");
  const end = settingsTimeInput("End", quietHours.end || "07:00");
  range.append(start.label, end.label);

  const save = settingsActionButton("Save", async () => {
    save.disabled = true;
    settingsStatus.textContent = "Saving";
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quiet_hours: {
            enabled: enabled.checked,
            start: start.input.value,
            end: end.input.value,
            timezone: quietHours.timezone || "local",
          },
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      state.settings = payload;
      renderSettings(payload);
      settingsStatus.textContent = "Saved";
    } catch (error) {
      settingsStatus.textContent = "Error";
      addCard("error", "Error", error.message || String(error));
      save.disabled = false;
    }
  });

  body.append(enabledLabel, range, save);
  return settingsSection("Quiet Hours", body);
}

function settingsPreferenceSection(preferences) {
  const body = document.createElement("div");
  body.className = "settings-list";
  const items = Array.isArray(preferences.items) ? preferences.items : [];
  if (items.length === 0) {
    body.appendChild(settingsRow("Learned preferences", "0", ""));
  } else {
    for (const item of items) {
      body.appendChild(settingsRow(item.title || "Preference", confidenceLabel(item.confidence), item.summary || ""));
    }
  }
  body.appendChild(settingsActionButton("Review", () => {
    closeSettings();
    prefillMessage(preferences.review_prompt || "Review my learned preferences.");
  }));
  return settingsSection("Learned Preferences", body);
}

function settingsDataControlSection(dataControls) {
  const body = document.createElement("div");
  body.className = "settings-list";
  const counts = dataControls.counts || {};
  body.append(
    settingsRow("Memory", String(counts.memory_pages || 0), `${counts.memory_candidates || 0} candidates`),
    settingsRow("Artifacts", String(counts.artifacts || 0), ""),
    settingsRow("Scheduled", String(counts.scheduled_items || 0), ""),
  );
  const actions = document.createElement("div");
  actions.className = "settings-actions";
  for (const item of dataControls.actions || []) {
    actions.appendChild(settingsActionButton(item.label || item.id || "Action", () => {
      closeSettings();
      prefillMessage(item.prompt || "");
    }));
  }
  body.appendChild(actions);
  return settingsSection("Data Controls", body);
}

function settingsSection(title, body) {
  const section = document.createElement("section");
  section.className = "settings-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading, body);
  return section;
}

function settingsRow(label, value, detail) {
  const row = document.createElement("div");
  row.className = "settings-row";
  const main = document.createElement("div");
  const labelNode = document.createElement("span");
  labelNode.className = "settings-label";
  labelNode.textContent = label;
  const detailNode = document.createElement("span");
  detailNode.className = "settings-detail";
  detailNode.textContent = detail || "";
  main.append(labelNode, detailNode);
  const valueNode = document.createElement("span");
  valueNode.className = "settings-value";
  valueNode.textContent = value || "";
  row.append(main, valueNode);
  return row;
}

function settingsTimeInput(label, value) {
  const wrapper = document.createElement("label");
  wrapper.className = "settings-time";
  const text = document.createElement("span");
  text.textContent = label;
  const inputNode = document.createElement("input");
  inputNode.type = "time";
  inputNode.value = value;
  wrapper.append(text, inputNode);
  return { label: wrapper, input: inputNode };
}

function settingsActionButton(label, onClick) {
  const button = document.createElement("button");
  button.className = "settings-action";
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function settingsLoadingRow(text) {
  const node = document.createElement("div");
  node.className = "settings-row";
  node.textContent = text;
  return node;
}

function confidenceLabel(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return `${Math.round(number * 100)}%`;
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
  updateContextPanel();
}

function updateComposerState() {
  send.disabled = state.busy;
  reset.disabled = state.busy;
  stop.hidden = !state.busy;
  stop.disabled = !state.activeRunId || state.cancelRequested;
  stop.textContent = state.cancelRequested ? "Stopping" : "Stop";
  runBadge.textContent = state.cancelRequested ? "Stopping" : state.busy ? "Running" : "Idle";
}

function addMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  if (role === "assistant") {
    renderMarkdownInto(node, text || "");
  } else {
    node.textContent = text;
  }
  timeline.appendChild(node);
  scrollToEnd();
  return node;
}

function finalizeAssistantMarkdown(text) {
  if (!state.assistantNode) {
    state.assistantNode = addMessage("assistant", "");
  }
  const finalText = text || state.assistantNode.dataset.rawText || state.assistantNode.textContent || "";
  state.assistantNode.classList.remove("streaming");
  renderMarkdownInto(state.assistantNode, finalText);
  scrollToEnd();
}

function renderMarkdownInto(node, text) {
  node.dataset.rawText = text || "";
  node.replaceChildren();
  node.classList.add("markdown");
  const blocks = markdownBlocks(text || "");
  for (const block of blocks) {
    node.appendChild(block);
  }
  if (blocks.length === 0) {
    node.appendChild(document.createTextNode(""));
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

    if (line.trim().startsWith("```")) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = codeLines.join("\n");
      pre.appendChild(code);
      blocks.push(pre);
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = String(heading[1]).length;
      const node = document.createElement(`h${level + 2}`);
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

    const paragraphLines = [];
    while (
      index < lines.length
      && lines[index].trim()
      && !lines[index].trim().startsWith("```")
      && !/^(#{1,3})\s+/.test(lines[index])
      && !/^\s*[-*]\s+/.test(lines[index])
      && !/^\s*\d+\.\s+/.test(lines[index])
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = document.createElement("p");
    appendInlineMarkdown(paragraph, paragraphLines.join(" "));
    blocks.push(paragraph);
  }
  return blocks;
}

function appendInlineMarkdown(parent, text) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  let cursor = 0;
  for (const match of String(text || "").matchAll(pattern)) {
    if (match.index > cursor) {
      parent.appendChild(document.createTextNode(text.slice(cursor, match.index)));
    }
    parent.appendChild(inlineMarkdownNode(match[0]));
    cursor = match.index + match[0].length;
  }
  if (cursor < String(text || "").length) {
    parent.appendChild(document.createTextNode(String(text).slice(cursor)));
  }
}

function inlineMarkdownNode(token) {
  if (token.startsWith("`") && token.endsWith("`")) {
    const code = document.createElement("code");
    code.textContent = token.slice(1, -1);
    return code;
  }
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
  const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(token);
  if (link) {
    const anchor = document.createElement("a");
    anchor.textContent = link[1];
    anchor.href = link[2];
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    return anchor;
  }
  return document.createTextNode(token);
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
updateContextPanel();
resumeLastRun();
