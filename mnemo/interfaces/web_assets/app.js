const state = {
  conversationId: localStorage.getItem("mnemo.conversation_id") || "",
  missionId: localStorage.getItem("mnemo.mission_id") || "",
  lastRunId: localStorage.getItem("mnemo.last_run_id") || "",
  busy: false,
  assistantNode: null,
  actions: new Map(),
};

const timeline = document.querySelector("#timeline");
const form = document.querySelector("#composer");
const input = document.querySelector("#message");
const send = document.querySelector("#send");
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

reset.addEventListener("click", () => {
  state.conversationId = "";
  state.missionId = "";
  state.lastRunId = "";
  localStorage.removeItem("mnemo.conversation_id");
  localStorage.removeItem("mnemo.mission_id");
  localStorage.removeItem("mnemo.last_run_id");
  timeline.replaceChildren();
  setStatus("Ready");
});

async function runTurn(message) {
  state.busy = true;
  state.assistantNode = null;
  send.disabled = true;
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
    send.disabled = false;
    state.assistantNode = null;
    setStatus("Ready");
    input.focus();
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
  addCard("", artifact.title || "Artifact", artifact.kind || "updated");
}

function renderLearning(item) {
  if (!item) return;
  const wrapper = document.createElement("div");
  wrapper.className = "event-card";
  const chips = document.createElement("div");
  chips.className = "chips";
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = `${item.kind || "learning"}: ${item.summary || item.status || "draft"}`;
  chips.appendChild(chip);
  wrapper.appendChild(chips);
  timeline.appendChild(wrapper);
  scrollToEnd();
}

function renderDecision(decision) {
  if (!decision) return;
  addCard("", "Decision", decision.question || "Decision required");
}

function persistRun(event) {
  const result = event.data?.result || {};
  state.conversationId = event.conversation_id || result.conversation_id || state.conversationId;
  state.missionId = event.mission_id || result.mission_id || state.missionId;
  state.lastRunId = event.run_id || result.run_id || state.lastRunId;
  localStorage.setItem("mnemo.conversation_id", state.conversationId);
  localStorage.setItem("mnemo.mission_id", state.missionId);
  localStorage.setItem("mnemo.last_run_id", state.lastRunId);
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
