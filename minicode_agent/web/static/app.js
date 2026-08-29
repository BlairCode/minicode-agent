"use strict";

const state = {
  token: "",
  settings: null,
  conversationId: null,
  runId: null,
  fileWorkspaceId: null,
  pollAfter: -1,
  pollTimer: null,
  running: false,
  pendingApproval: null,
  outputPaths: new Set(),
  currentExecution: null,
  activeStep: null,
  renderedFinal: false,
};

const $ = (selector) => document.querySelector(selector);
const elements = {
  empty: $("#empty-state"),
  stream: $("#message-stream"),
  conversation: $("#conversation"),
  input: $("#task-input"),
  send: $("#send-task"),
  stop: $("#stop-run"),
  status: $("#run-status"),
  agent: $("#agent-select"),
  agentLocked: $("#agent-locked"),
  model: $("#model-label"),
  history: $("#history-list"),
  fileList: $("#file-list"),
  fileEmpty: $("#files-empty"),
  fileCount: $("#file-count"),
  settingsModal: $("#settings-modal"),
  settingsForm: $("#settings-form"),
  approvalModal: $("#approval-modal"),
  approvalMessage: $("#approval-message"),
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function getToken() {
  const url = new URL(window.location.href);
  const queryToken = url.searchParams.get("token") || "";
  const pageToken = document.querySelector('meta[name="minicode-session-token"]')?.getAttribute("content") || "";
  const token = pageToken || queryToken;
  url.searchParams.delete("token");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  return token;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-MiniCode-Token", state.token);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  let payload = {};
  try { payload = await response.json(); } catch (_) { payload = {}; }
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

function toast(message, isError = false) {
  const node = element("div", `toast${isError ? " error" : ""}`, message);
  $("#toast-region").append(node);
  window.setTimeout(() => node.remove(), 3600);
}

function setStatus(kind, label) {
  elements.status.className = `run-status ${kind}`;
  elements.status.querySelector("span").textContent = label;
}

function setAgentLocked(locked) {
  const value = elements.agent.value === "leetcode" ? "LeetCode" : "Coding";
  elements.agent.hidden = locked;
  elements.agentLocked.hidden = !locked;
  elements.agentLocked.textContent = value;
  elements.agent.closest(".agent-picker").classList.toggle("locked", locked);
}

function setRunning(value) {
  state.running = value;
  elements.send.disabled = value;
  elements.stop.hidden = !value;
  elements.agent.disabled = value;
  setAgentLocked(value || Boolean(state.conversationId));
  if (value) setStatus("running", "执行中");
}

function timeLabel(value) {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "历史记录";
  return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function compactJson(value) {
  if (typeof value === "string") return value;
  try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
}

function showConversation() {
  elements.empty.hidden = true;
}

function scrollConversation() {
  window.requestAnimationFrame(() => {
    elements.conversation.scrollTop = elements.conversation.scrollHeight;
  });
}

function appendInlineMarkdown(parent, source) {
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|~~[^~\n]+~~|\*[^*\n]+\*|\[[^\]\n]+\]\(([^)\s]+)\))/g;
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    if (match.index > cursor) parent.append(document.createTextNode(source.slice(cursor, match.index)));
    const token = match[0];
    if (token.startsWith("`")) {
      parent.append(element("code", "inline-code", token.slice(1, -1)));
    } else if (token.startsWith("**")) {
      parent.append(element("strong", "", token.slice(2, -2)));
    } else if (token.startsWith("~~")) {
      parent.append(element("del", "", token.slice(2, -2)));
    } else if (token.startsWith("*")) {
      parent.append(element("em", "", token.slice(1, -1)));
    } else {
      const labelEnd = token.indexOf("](");
      const label = token.slice(1, labelEnd);
      const rawUrl = token.slice(labelEnd + 2, -1);
      const link = element("a", "", label);
      try {
        const url = new URL(rawUrl, window.location.href);
        if (["http:", "https:", "mailto:"].includes(url.protocol)) {
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
      } catch (_) {
        link.removeAttribute("href");
      }
      parent.append(link);
    }
    cursor = match.index + token.length;
  }
  if (cursor < source.length) parent.append(document.createTextNode(source.slice(cursor)));
}

function tableCells(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isTableDivider(line) {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function startsMarkdownBlock(lines, index) {
  const line = lines[index] || "";
  return /^```/.test(line) || /^#{1,6}\s+/.test(line) || /^>\s?/.test(line) || /^\s*[-+*]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line) || /^\s*(---+|___+|\*\*\*+)\s*$/.test(line) || (line.includes("|") && isTableDivider(lines[index + 1] || ""));
}

function renderMarkdown(container, source) {
  container.replaceChildren();
  const lines = String(source || "").replaceAll("\r\n", "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }

    const fence = line.match(/^```([A-Za-z0-9_+-]*)\s*$/);
    if (fence) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) codeLines.push(lines[index++]);
      if (index < lines.length) index += 1;
      const pre = element("pre", "markdown-code");
      const code = element("code", fence[1] ? `language-${fence[1]}` : "", codeLines.join("\n"));
      pre.append(code);
      container.append(pre);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const node = element(`h${heading[1].length}`, "");
      appendInlineMarkdown(node, heading[2]);
      container.append(node);
      index += 1;
      continue;
    }

    if (/^\s*(---+|___+|\*\*\*+)\s*$/.test(line)) {
      container.append(document.createElement("hr"));
      index += 1;
      continue;
    }

    if (line.includes("|") && isTableDivider(lines[index + 1] || "")) {
      const table = element("table", "");
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      for (const value of tableCells(line)) {
        const cell = document.createElement("th");
        appendInlineMarkdown(cell, value);
        headRow.append(cell);
      }
      head.append(headRow);
      table.append(head);
      index += 2;
      const body = document.createElement("tbody");
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const row = document.createElement("tr");
        for (const value of tableCells(lines[index])) {
          const cell = document.createElement("td");
          appendInlineMarkdown(cell, value);
          row.append(cell);
        }
        body.append(row);
        index += 1;
      }
      table.append(body);
      const wrapper = element("div", "markdown-table");
      wrapper.append(table);
      container.append(wrapper);
      continue;
    }

    const listMatch = line.match(/^\s*([-+*]|\d+[.)])\s+(.+)$/);
    if (listMatch) {
      const ordered = /^\d/.test(listMatch[1]);
      const list = document.createElement(ordered ? "ol" : "ul");
      const listPattern = ordered ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-+*]\s+(.+)$/;
      while (index < lines.length) {
        const item = lines[index].match(listPattern);
        if (!item) break;
        const node = document.createElement("li");
        appendInlineMarkdown(node, item[1]);
        list.append(node);
        index += 1;
      }
      container.append(list);
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) quoteLines.push(lines[index++].replace(/^>\s?/, ""));
      const quote = document.createElement("blockquote");
      appendInlineMarkdown(quote, quoteLines.join(" "));
      container.append(quote);
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;
    while (index < lines.length && lines[index].trim() && !startsMarkdownBlock(lines, index)) paragraphLines.push(lines[index++].trim());
    const paragraph = document.createElement("p");
    appendInlineMarkdown(paragraph, paragraphLines.join(" "));
    container.append(paragraph);
  }
}

function appendMessage(role, text, label, timestamp) {
  if (!text) return null;
  showConversation();
  const root = element("article", `message ${role}`);
  root.append(element("div", "avatar", role === "user" ? "YOU" : "AI"));
  const body = element("div", "message-body");
  const meta = element("div", "message-meta");
  meta.append(element("strong", "", label || (role === "user" ? "你" : "MiniCode")));
  meta.append(element("span", "", timestamp ? timeLabel(timestamp) : "现在"));
  const content = element("div", "message-text markdown-body");
  renderMarkdown(content, text);
  body.append(meta, content);
  root.append(body);
  elements.stream.append(root);
  scrollConversation();
  return root;
}

function executionGroup() {
  if (!state.currentExecution || !state.currentExecution.isConnected) {
    state.currentExecution = element("section", "execution-group");
    state.currentExecution.setAttribute("aria-label", "执行过程");
    elements.stream.append(state.currentExecution);
  }
  return state.currentExecution;
}

function appendStep(number) {
  finishActiveStep();
  setStatus("running", `步骤 ${number}`);
  const marker = element("div", "step-marker active");
  marker.append(element("span", "step-label", `步骤 ${number}`), element("span", "step-loading"));
  executionGroup().append(marker);
  state.activeStep = marker;
  scrollConversation();
}

function finishActiveStep(failed = false) {
  if (!state.activeStep || !state.activeStep.isConnected) {
    state.activeStep = null;
    return;
  }
  state.activeStep.classList.remove("active");
  state.activeStep.classList.add(failed ? "failed" : "done");
  const indicator = state.activeStep.querySelector(".step-loading");
  if (indicator) indicator.textContent = failed ? "×" : "✓";
  state.activeStep = null;
}

function appendAction(summary, tools) {
  setStatus("running", "执行中");
  const text = summary || (tools && tools.length ? `准备调用 ${tools.join("、")}` : "正在规划下一步操作");
  executionGroup().append(element("div", "action-summary", text));
  scrollConversation();
}

function appendToolCall(payload) {
  const card = element("article", "tool-card pending");
  card.dataset.toolName = payload.name || "tool";
  const head = element("div", "tool-head");
  head.append(element("span", "tool-icon", "↗"), element("strong", "", payload.name || "tool"), element("span", "", "调用中"));
  card.append(head, element("pre", "tool-payload", compactJson(payload.arguments || {})));
  executionGroup().append(card);
  scrollConversation();
}

function lastPendingTool(name) {
  const cards = [...elements.stream.querySelectorAll(".tool-card.pending")];
  return cards.reverse().find((card) => card.dataset.toolName === name) || null;
}

function appendToolResult(payload) {
  const result = payload.result || {};
  let card = lastPendingTool(payload.name);
  if (!card) {
    appendToolCall({ name: payload.name, arguments: {} });
    card = lastPendingTool(payload.name);
  }
  if (!card) return;
  card.classList.remove("pending");
  card.classList.add(result.success ? "success" : "error");
  const status = card.querySelector(".tool-head > span:last-child");
  status.textContent = result.success ? "完成" : "失败";
  const output = result.success ? (result.output || result.data || "操作完成") : (result.error || "工具执行失败");
  card.querySelector(".tool-payload").textContent = compactJson(output);
  if (result.success && ["write_file", "patch_file"].includes(payload.name) && result.data && result.data.path) {
    addOutputFile(String(result.data.path), payload.name);
  }
  scrollConversation();
}

function appendNote(text) {
  executionGroup().append(element("div", "event-note", text));
  scrollConversation();
}

function appendCompletion(payload) {
  const stateName = payload.state || "COMPLETED";
  const failed = !["COMPLETED", "SUCCEEDED"].includes(stateName);
  finishActiveStep(failed);
  const strip = element("div", `completion-strip${failed ? " failed" : ""}`);
  const details = [];
  if (payload.steps !== undefined) details.push(`${payload.steps} 步`);
  if (payload.tool_calls !== undefined) details.push(`${payload.tool_calls} 次工具调用`);
  details.push(failed ? (payload.reason || stateName) : "任务完成");
  strip.textContent = details.join(" · ");
  elements.stream.append(strip);
  state.currentExecution = null;
}

function handleEvent(item, historical = false) {
  const name = item.event;
  const payload = item.payload || {};
  const timestamp = item.timestamp || "";
  if (name === "run_started") {
    if (historical) {
      state.currentExecution = null;
      state.activeStep = null;
      state.renderedFinal = false;
      appendMessage("user", payload.task, "你", timestamp);
    }
  } else if (name === "step") {
    appendStep(payload.number || "—");
  } else if (name === "model_action") {
    appendAction(payload.summary, payload.tools);
  } else if (name === "tool_call") {
    appendToolCall(payload);
  } else if (name === "tool_result") {
    appendToolResult(payload);
  } else if (name === "model_retry") {
    setStatus("running", `重试 ${payload.attempt || 1}`);
    appendNote(`模型请求失败，${payload.delay_seconds || 0} 秒后重试（第 ${payload.attempt || 1} 次）：${payload.error || "未知错误"}`);
  } else if (name === "model_error") {
    finishActiveStep(true);
    appendNote(`模型请求失败：${payload.error || "未知错误"}`);
  } else if (name === "approval_prompt") {
    openApproval(payload.id, payload.message);
  } else if (name === "approval_requested") {
    setStatus("waiting", "等待确认");
  } else if (name === "final") {
    finishActiveStep();
    if (!state.renderedFinal) appendMessage("agent", payload.text, "MiniCode", timestamp);
    state.renderedFinal = true;
    state.currentExecution = null;
  } else if (name === "run_finished") {
    if (historical) appendCompletion(payload);
  } else if (name === "run_complete") {
    if (!state.renderedFinal && payload.response) appendMessage("agent", payload.response, "MiniCode");
    state.renderedFinal = true;
    appendCompletion(payload);
  }
}

function resetView() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.runId = null;
  state.conversationId = null;
  state.fileWorkspaceId = null;
  state.pollAfter = -1;
  state.currentExecution = null;
  state.activeStep = null;
  state.renderedFinal = false;
  state.pendingApproval = null;
  state.outputPaths.clear();
  elements.stream.replaceChildren();
  elements.fileList.replaceChildren();
  elements.fileEmpty.hidden = false;
  elements.fileCount.textContent = "0";
  $("#file-preview").hidden = true;
  elements.approvalModal.hidden = true;
  elements.empty.hidden = false;
  document.querySelectorAll(".history-item.active").forEach((node) => node.classList.remove("active"));
  setRunning(false);
  elements.agent.disabled = false;
  setAgentLocked(false);
  setStatus("ready", "就绪");
}

function newConversation() {
  if (state.running) {
    toast("当前任务仍在执行，请先停止后再新建对话。", true);
    return;
  }
  resetView();
  elements.input.value = "";
  resizeInput();
  elements.input.focus();
  $("#sidebar").classList.remove("open");
}

function pathParts(path) {
  const normalized = path.replaceAll("\\", "/");
  const parts = normalized.split("/");
  const name = parts.pop() || normalized;
  return { name, parent: parts.join("/") || ".", ext: name.includes(".") ? name.split(".").pop().slice(0, 4) : "file" };
}

function addOutputFile(path, action = "write_file") {
  if (state.outputPaths.has(path)) return;
  state.outputPaths.add(path);
  elements.fileEmpty.hidden = true;
  elements.fileCount.textContent = String(state.outputPaths.size);
  const parts = pathParts(path);
  const button = element("button", "file-item");
  button.type = "button";
  button.dataset.path = path;
  button.append(element("span", "file-kind", parts.ext));
  const copy = element("span", "file-copy");
  copy.append(element("strong", "", parts.name), element("small", "", `${action === "patch_file" ? "已修改" : "已创建"} · ${parts.parent}`));
  button.append(copy, element("span", "file-arrow", "›"));
  button.addEventListener("click", () => previewFile(path, button));
  elements.fileList.append(button);
}

async function previewFile(path, button) {
  try {
    const workspace = state.fileWorkspaceId ? `&workspace_id=${encodeURIComponent(state.fileWorkspaceId)}` : "";
    const payload = await api(`/api/file?path=${encodeURIComponent(path)}${workspace}`);
    document.querySelectorAll(".file-item.active").forEach((node) => node.classList.remove("active"));
    button.classList.add("active");
    $("#preview-name").textContent = payload.path;
    $("#preview-content").textContent = payload.content;
    $("#file-preview").hidden = false;
  } catch (error) {
    toast(error.message, true);
  }
}

async function pollRun() {
  if (!state.runId) return;
  try {
    const payload = await api(`/api/runs/${state.runId}?after=${state.pollAfter}`);
    for (const item of payload.events || []) handleEvent(item);
    state.pollAfter = payload.next_after;
    if (payload.status === "RUNNING" || payload.status === "WAITING_APPROVAL") {
      state.pollTimer = window.setTimeout(pollRun, 500);
      return;
    }
    setRunning(false);
    if (payload.status === "COMPLETED") setStatus("ready", "已完成");
    else if (payload.status === "CANCELLED") setStatus("ready", "已停止");
    else setStatus("failed", "未完成");
    await loadHistory();
  } catch (error) {
    setRunning(false);
    finishActiveStep(true);
    setStatus("failed", "连接异常");
    toast(error.message, true);
  }
}

async function startRun() {
  const task = elements.input.value.trim();
  if (!task || state.running) return;
  state.currentExecution = null;
  state.activeStep = null;
  state.renderedFinal = false;
  showConversation();
  appendMessage("user", task, "你");
  elements.input.value = "";
  resizeInput();
  setRunning(true);
  try {
    const payload = await api("/api/runs", { method: "POST", body: JSON.stringify({ task, agent: elements.agent.value, conversation_id: state.conversationId || "" }) });
    state.runId = payload.id;
    state.conversationId = payload.id;
    state.fileWorkspaceId = payload.id;
    state.pollAfter = Number.isInteger(payload.after) ? payload.after : -1;
    setAgentLocked(true);
    pollRun();
  } catch (error) {
    setRunning(false);
    finishActiveStep(true);
    setStatus("failed", "启动失败");
    appendNote(error.message);
  }
}

async function stopRun() {
  if (!state.runId) return;
  try {
    await api(`/api/runs/${state.runId}/cancel`, { method: "POST", body: "{}" });
    setStatus("waiting", "正在停止");
  } catch (error) {
    toast(error.message, true);
  }
}

function historyItem(session) {
  const button = element("button", "history-item");
  button.type = "button";
  button.dataset.id = session.id;
  button.append(element("span", "history-icon", session.agent === "leetcode" ? "LC" : "{}"));
  const copy = element("span", "history-copy");
  copy.append(element("strong", "", session.task || "未命名任务"), element("small", "", timeLabel(session.timestamp)));
  button.append(copy);
  button.addEventListener("click", () => openHistory(session, button));
  return button;
}

async function loadHistory() {
  try {
    const sessions = await api("/api/history");
    elements.history.replaceChildren();
    if (!sessions.length) {
      elements.history.append(element("div", "history-placeholder", "完成一次任务后，记录会出现在这里。"));
      return;
    }
    sessions.forEach((session) => elements.history.append(historyItem(session)));
  } catch (error) {
    elements.history.replaceChildren(element("div", "history-placeholder", "历史记录暂时无法读取。"));
  }
}

async function openHistory(session, button) {
  if (state.running) {
    toast("请先停止当前任务，再查看历史记录。", true);
    return;
  }
  resetView();
  button.classList.add("active");
  elements.empty.hidden = true;
  elements.agent.value = session.agent === "leetcode" ? "leetcode" : "coding";
  state.conversationId = session.id;
  state.runId = session.id;
  state.fileWorkspaceId = session.workspace_id || session.id;
  setAgentLocked(true);
  try {
    const events = await api(`/api/history/${session.id}`);
    events.forEach((item) => handleEvent(item, true));
    setStatus(session.state === "COMPLETED" ? "ready" : "failed", session.state === "COMPLETED" ? "历史记录" : session.state);
    scrollConversation();
  } catch (error) {
    setStatus("failed", "读取失败");
    toast(error.message, true);
  }
  $("#sidebar").classList.remove("open");
}

function fillSettings(settings) {
  state.settings = settings;
  const form = elements.settingsForm.elements;
  for (const name of ["provider", "model", "base_url", "request_timeout", "workspace", "command_mode", "code_style", "comment_level", "default_language", "leetcode_language", "leetcode_mode"]) {
    if (form[name]) form[name].value = settings[name] ?? "";
  }
  form.network_access.checked = Boolean(settings.network_access);
  form.remove_api_key.checked = false;
  form.api_key.value = "";
  const credentialMessages = {
    system: "✓ API Key 已安全保存在系统凭据库",
    environment: "✓ 当前进程已从环境变量读取 API Key",
    none: "未检测到 API Key，请保存凭据或设置环境变量",
  };
  $("#credential-status").textContent = credentialMessages[settings.credential_source] || credentialMessages.none;
  elements.model.textContent = `${settings.provider === "qwen" ? "Qwen" : "Compatible"} · ${settings.model}`;
}

function openSettings() {
  fillSettings(state.settings || {});
  $("#save-message").textContent = "";
  elements.settingsModal.hidden = false;
  elements.settingsForm.elements.model.focus();
}

function closeSettings() {
  elements.settingsModal.hidden = true;
}

async function saveSettings(event) {
  event.preventDefault();
  const form = new FormData(elements.settingsForm);
  const payload = {};
  for (const name of ["provider", "model", "base_url", "workspace", "command_mode", "code_style", "comment_level", "default_language", "leetcode_language", "leetcode_mode"]) {
    payload[name] = String(form.get(name) || "").trim();
  }
  payload.request_timeout = Number(form.get("request_timeout"));
  payload.network_access = elements.settingsForm.elements.network_access.checked;
  payload.remove_api_key = elements.settingsForm.elements.remove_api_key.checked;
  const apiKey = String(form.get("api_key") || "").trim();
  if (apiKey) payload.api_key = apiKey;
  const submit = elements.settingsForm.querySelector("button[type=submit]");
  submit.disabled = true;
  $("#save-message").textContent = "正在保存…";
  try {
    const settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    fillSettings(settings);
    $("#save-message").textContent = "设置已保存，可继续调整或关闭";
  } catch (error) {
    $("#save-message").textContent = "";
    toast(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

function openApproval(id, message) {
  state.pendingApproval = id;
  elements.approvalMessage.textContent = message || "该操作需要授权。";
  elements.approvalModal.hidden = false;
  setStatus("waiting", "等待确认");
}

async function resolveApproval(answer) {
  if (!state.pendingApproval) return;
  const approvalId = state.pendingApproval;
  state.pendingApproval = null;
  elements.approvalModal.hidden = true;
  try {
    await api(`/api/approvals/${approvalId}`, { method: "POST", body: JSON.stringify({ answer }) });
    if (state.running) setStatus("running", "执行中");
  } catch (error) {
    toast(error.message, true);
  }
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 150)}px`;
}

function bindEvents() {
  elements.send.addEventListener("click", startRun);
  elements.stop.addEventListener("click", stopRun);
  elements.input.addEventListener("input", resizeInput);
  elements.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey) { event.preventDefault(); startRun(); }
  });
  $("#new-chat").addEventListener("click", newConversation);
  $("#refresh-history").addEventListener("click", loadHistory);
  $("#open-settings").addEventListener("click", openSettings);
  $("#close-settings").addEventListener("click", closeSettings);
  $("#cancel-settings").addEventListener("click", closeSettings);
  elements.settingsForm.addEventListener("submit", saveSettings);
  $("#close-preview").addEventListener("click", () => { $("#file-preview").hidden = true; });
  $("#toggle-sidebar").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $("#toggle-files").addEventListener("click", () => $("#files-panel").classList.toggle("open"));
  $("#close-files").addEventListener("click", () => $("#files-panel").classList.remove("open"));
  document.querySelectorAll(".starter").forEach((button) => button.addEventListener("click", () => { elements.input.value = button.dataset.prompt || ""; resizeInput(); elements.input.focus(); }));
  document.querySelectorAll("[data-answer]").forEach((button) => button.addEventListener("click", () => resolveApproval(button.dataset.answer)));
  document.addEventListener("keydown", (event) => {
    if (!elements.settingsModal.hidden) {
      if (event.key === "Escape") closeSettings();
      return;
    }
    if (event.ctrlKey && event.key.toLowerCase() === "k") { event.preventDefault(); newConversation(); }
  });
}

async function bootstrap() {
  state.token = getToken();
  bindEvents();
  if (!state.token) {
    setStatus("failed", "会话无效");
    toast("缺少本地会话令牌，请从启动终端中的完整地址重新打开。", true);
    return;
  }
  try {
    const payload = await api("/api/bootstrap");
    fillSettings(payload.settings || {});
    const agents = payload.agents || ["coding"];
    elements.agent.value = agents.includes(payload.default_agent) ? payload.default_agent : agents[0];
    elements.history.replaceChildren();
    if ((payload.history || []).length) payload.history.forEach((session) => elements.history.append(historyItem(session)));
    else elements.history.append(element("div", "history-placeholder", "完成一次任务后，记录会出现在这里。"));
    setStatus("ready", "就绪");
  } catch (error) {
    setStatus("failed", "连接失败");
    toast(error.message, true);
  }
}

bootstrap();
