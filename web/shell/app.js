/* FlowPilot 极薄 Web 外壳。
   浏览器只持有 HttpOnly 不透明会话；tenant、role、subject 和权限均由 API 判定。
   事件只触发权威 Task 投影刷新，不形成业务事实或授权结论。 */

"use strict";

const view = document.getElementById("view");
const sseStatus = document.getElementById("sse-status");
const ticker = document.getElementById("event-ticker");
const modeBadge = document.getElementById("shell-mode");
const demoControls = document.getElementById("demo-controls");
const sessionStatus = document.getElementById("session-status");
const loginAction = document.getElementById("login-action");
const refreshAction = document.getElementById("refresh-action");
const logoutAction = document.getElementById("logout-action");

const SESSION = Object.freeze({
  CHECKING: "checking",
  DEMO: "demo",
  ACTIVE: "active",
  ANONYMOUS: "anonymous",
  REAUTH_REQUIRED: "reauth-required",
  SIGNING_OUT: "signing-out",
  REFRESH_FAILED: "refresh-failed",
  UNKNOWN_ERROR: "unknown-error",
});
const SAFE_AUTH_CODES = new Set([
  "API_AUTHENTICATION_REQUIRED",
  "API_AUTHENTICATION_INVALID",
  "API_AUTHORIZATION_DENIED",
  "API_AUTH_FLOW_INVALID",
  "API_DEPENDENCY_UNAVAILABLE",
  "API_INTERNAL_ERROR",
]);

let shellMode = "unknown";
let sessionState = SESSION.CHECKING;
let eventSource = null;
let authEpoch = 0;
let authController = new AbortController();
const seenEventIds = new Set();

function currentAuthOperation() {
  return Object.freeze({ epoch: authEpoch, signal: authController.signal });
}

function advanceAuthEpoch() {
  authController.abort();
  authEpoch += 1;
  authController = new AbortController();
  return currentAuthOperation();
}

function isCurrentAuthOperation(operation) {
  return (
    operation.epoch === authEpoch &&
    operation.signal === authController.signal &&
    !operation.signal.aborted
  );
}

function setSessionState(state, detail = "") {
  sessionState = state;
  const labels = {
    [SESSION.CHECKING]: "正在检查登录状态…",
    [SESSION.DEMO]: "合成演示会话（不代表真实身份）",
    [SESSION.ACTIVE]: detail ? "会话有效，过期时间：" + detail : "会话有效",
    [SESSION.ANONYMOUS]: "尚未登录",
    [SESSION.REAUTH_REQUIRED]: "会话已过期或已撤销，需要重新认证",
    [SESSION.SIGNING_OUT]: "正在安全退出…",
    [SESSION.REFRESH_FAILED]: "会话刷新失败，身份状态未确认",
    [SESSION.UNKNOWN_ERROR]: "无法确认会话状态",
  };
  sessionStatus.textContent = labels[state] || labels[SESSION.UNKNOWN_ERROR];
  const active = state === SESSION.ACTIVE;
  const demo = state === SESSION.DEMO;
  loginAction.hidden = active || demo || state === SESSION.SIGNING_OUT;
  refreshAction.hidden = demo || state === SESSION.SIGNING_OUT;
  logoutAction.hidden = demo || state === SESSION.ANONYMOUS;
  refreshAction.disabled = state === SESSION.CHECKING;
  logoutAction.disabled = state === SESSION.CHECKING;
}

async function applyMode() {
  const operation = currentAuthOperation();
  try {
    const response = await fetch("/health", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: operation.signal,
    });
    const health = await response.json();
    if (!isCurrentAuthOperation(operation)) {
      return "cancelled";
    }
    shellMode = health.mode === "live" ? "live" : "demo";
    modeBadge.textContent =
      shellMode === "live" ? "真实 API/SSE" : "合成 Fixture 演示";
    demoControls.hidden = shellMode === "live";
    if (shellMode === "demo") {
      setSessionState(SESSION.DEMO);
    }
  } catch (error) {
    if (!isCurrentAuthOperation(operation) || error.name === "AbortError") {
      return "cancelled";
    }
    shellMode = "unavailable";
    modeBadge.textContent = "后端未配置";
    setSessionState(SESSION.UNKNOWN_ERROR);
  }
  return shellMode;
}

function currentRoute() {
  const raw = (location.hash || "#/tasks").slice(1);
  let parsed;
  try {
    parsed = new URL(raw, location.origin);
  } catch (_error) {
    return "/tasks";
  }
  const taskRoute = /^\/tasks(?:\/[A-Za-z0-9_-]{8,128})?$/.test(
    parsed.pathname,
  );
  const governanceRoute = /^\/governance(?:\/correlations\/[A-Za-z0-9_.:-]{1,128})?$/.test(
    parsed.pathname,
  );
  const knowledgeRoute = parsed.pathname === "/knowledge";
  if (!taskRoute && !governanceRoute && !knowledgeRoute) {
    return "/tasks";
  }
  const safeQuery = new URLSearchParams();
  const seen = new Set();
  for (const [name, value] of parsed.searchParams) {
    if (seen.has(name)) {
      return governanceRoute ? "/governance" : knowledgeRoute ? "/knowledge" : "/tasks";
    }
    seen.add(name);
    if (taskRoute && name === "demo" && ["unavailable", "missing"].includes(value)) {
      safeQuery.set(name, value);
    } else if (taskRoute && name === "rebuild" && value === "1") {
      safeQuery.set(name, value);
    } else if (
      governanceRoute &&
      parsed.pathname === "/governance" &&
      name === "tab" &&
      ["versions", "decisions", "audit", "security"].includes(value)
    ) {
      safeQuery.set(name, value);
    } else if (
      governanceRoute &&
      parsed.pathname === "/governance" &&
      name === "limit" &&
      /^\d{1,3}$/.test(value) &&
      Number(value) >= 1 &&
      Number(value) <= 100
    ) {
      safeQuery.set(name, value);
    } else if (
      governanceRoute &&
      parsed.pathname === "/governance" &&
      name === "cursor" &&
      /^gcur_[A-Za-z0-9_-]{24,508}$/.test(value)
    ) {
      safeQuery.set(name, value);
    } else if (
      governanceRoute &&
      parsed.pathname === "/governance" &&
      name === "task_id" &&
      /^task_[A-Za-z0-9_-]{8,128}$/.test(value)
    ) {
      safeQuery.set(name, value);
    } else if (
      governanceRoute &&
      parsed.pathname === "/governance" &&
      name === "correlation_id" &&
      /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$/.test(value)
    ) {
      safeQuery.set(name, value);
    } else if (
      governanceRoute &&
      parsed.pathname === "/governance" &&
      ["occurred_after", "occurred_before"].includes(name) &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    ) {
      safeQuery.set(name, value);
    } else if (
      knowledgeRoute &&
      name === "document_id" &&
      /^doc_[A-Za-z0-9_-]{8,128}$/.test(value)
    ) {
      safeQuery.set(name, value);
    } else if (
      knowledgeRoute &&
      name === "document_version" &&
      /^\d{1,16}$/.test(value) &&
      Number.isSafeInteger(Number(value))
    ) {
      safeQuery.set(name, value);
    } else if (
      knowledgeRoute &&
      name === "expected_hash" &&
      /^sha256:[a-f0-9]{64}$/.test(value)
    ) {
      safeQuery.set(name, value);
    } else {
      return governanceRoute ? "/governance" : knowledgeRoute ? "/knowledge" : "/tasks";
    }
  }
  const query = safeQuery.toString();
  return parsed.pathname + (query ? "?" + query : "");
}

function viewUrl(route) {
  return "/views" + route;
}

function replaceViewMessage(title, message, login = false) {
  const panel = document.createElement("section");
  panel.className = "error-panel";
  panel.setAttribute("role", "alert");
  const heading = document.createElement("h2");
  heading.textContent = title;
  const text = document.createElement("p");
  text.textContent = message;
  panel.append(heading, text);
  if (login) {
    const link = document.createElement("a");
    link.className = "btn btn-primary";
    link.href = "/api/v1/auth/login";
    link.textContent = "重新登录";
    panel.append(link);
  }
  view.replaceChildren(panel);
  view.hidden = false;
  view.setAttribute("aria-busy", "false");
}

function clearProtectedView(message) {
  const text = document.createElement("p");
  text.className = "loading";
  text.textContent = message;
  view.replaceChildren(text);
  view.hidden = false;
  view.setAttribute("aria-busy", "false");
}

async function safeAuthCode(response) {
  try {
    const payload = await response.json();
    const code = payload && payload.error && payload.error.code;
    return SAFE_AUTH_CODES.has(code) ? code : "API_INTERNAL_ERROR";
  } catch (_error) {
    return "API_INTERNAL_ERROR";
  }
}

function requireReauthentication(operation = currentAuthOperation()) {
  if (!isCurrentAuthOperation(operation)) {
    return;
  }
  advanceAuthEpoch();
  closeSse();
  seenEventIds.clear();
  setSessionState(SESSION.REAUTH_REQUIRED);
  replaceViewMessage(
    "需要重新认证",
    "当前会话不能继续访问受保护内容，请重新登录。",
    true,
  );
}

async function loadRoute(route, operation = currentAuthOperation()) {
  if (!isCurrentAuthOperation(operation)) {
    return false;
  }
  if (shellMode === "live" && sessionState !== SESSION.ACTIVE) {
    return false;
  }
  view.hidden = false;
  view.setAttribute("aria-busy", "true");
  const loading = document.createElement("p");
  loading.className = "loading";
  loading.textContent = "加载中…";
  view.replaceChildren(loading);
  try {
    const response = await fetch(viewUrl(route), {
      credentials: "same-origin",
      headers: { Accept: "text/html" },
      signal: operation.signal,
    });
    if (!isCurrentAuthOperation(operation)) {
      return false;
    }
    if (response.status === 401) {
      requireReauthentication(operation);
      return false;
    }
    if (response.status === 403) {
      closeSse();
      setSessionState(SESSION.ACTIVE);
      replaceViewMessage("访问被拒绝", "当前会话无权访问该资源。", false);
      return false;
    }
    if (!response.ok) {
      replaceViewMessage("加载失败", "服务暂时不可用，请稍后重试。", false);
      return false;
    }
    const contentType = response.headers.get("Content-Type") || "";
    if (!contentType.toLowerCase().startsWith("text/html")) {
      throw new Error("unexpected view content type");
    }
    const fragment = await response.text();
    if (!isCurrentAuthOperation(operation)) {
      return false;
    }
    view.innerHTML = fragment;
    view.setAttribute("aria-busy", "false");
    if (shellMode === "live") {
      setSessionState(SESSION.ACTIVE);
    }
    return true;
  } catch (error) {
    if (!isCurrentAuthOperation(operation) || error.name === "AbortError") {
      return false;
    }
    replaceViewMessage("加载失败", "无法连接 FlowPilot 服务。", false);
    return false;
  }
}

function closeSse() {
  if (eventSource !== null) {
    eventSource.close();
    eventSource = null;
  }
  sseStatus.hidden = true;
}

async function refreshSession({ reconnect = false, silent = false } = {}) {
  if (shellMode !== "live") {
    return shellMode === "demo";
  }
  closeSse();
  const operation = advanceAuthEpoch();
  if (!silent) {
    setSessionState(SESSION.CHECKING);
  }
  try {
    const response = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: operation.signal,
    });
    if (!isCurrentAuthOperation(operation)) {
      return false;
    }
    if (response.status === 401) {
      await safeAuthCode(response);
      requireReauthentication(operation);
      return false;
    }
    if (response.status === 403) {
      await safeAuthCode(response);
      if (!isCurrentAuthOperation(operation)) {
        return false;
      }
      closeSse();
      setSessionState(SESSION.UNKNOWN_ERROR);
      replaceViewMessage("访问被拒绝", "当前会话不能刷新。", true);
      return false;
    }
    if (!response.ok) {
      await safeAuthCode(response);
      if (!isCurrentAuthOperation(operation)) {
        return false;
      }
      closeSse();
      setSessionState(SESSION.REFRESH_FAILED);
      replaceViewMessage(
        "会话刷新失败",
      "身份状态未确认，已停止受保护内容与事件访问。",
        true,
      );
      return false;
    }
    const payload = await response.json();
    if (!isCurrentAuthOperation(operation)) {
      return false;
    }
    if (
      payload.status !== "active" ||
      typeof payload.expires_at !== "string" ||
      !payload.expires_at
    ) {
      throw new Error("invalid session response");
    }
    setSessionState(SESSION.ACTIVE, payload.expires_at);
    if (reconnect) {
      connectSse();
    }
    return true;
  } catch (error) {
    if (!isCurrentAuthOperation(operation) || error.name === "AbortError") {
      return false;
    }
    closeSse();
    setSessionState(SESSION.REFRESH_FAILED);
    replaceViewMessage(
      "会话刷新失败",
      "无法确认身份状态，已停止受保护内容与事件访问。",
      true,
    );
    return false;
  }
}

async function logout() {
  const operation = advanceAuthEpoch();
  closeSse();
  seenEventIds.clear();
  setSessionState(SESSION.SIGNING_OUT);
  clearProtectedView("正在清理本地受保护视图…");
  try {
    const response = await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: operation.signal,
    });
    if (!isCurrentAuthOperation(operation)) {
      return;
    }
    if (response.status !== 204) {
      await safeAuthCode(response);
      if (!isCurrentAuthOperation(operation)) {
        return;
      }
      setSessionState(SESSION.UNKNOWN_ERROR);
      replaceViewMessage(
        "退出未确认",
        "服务端未确认会话已结束，请重试或重新登录。",
        true,
      );
      return;
    }
    setSessionState(SESSION.ANONYMOUS);
    clearProtectedView("已退出登录。受保护内容和事件状态已清除。");
  } catch (error) {
    if (!isCurrentAuthOperation(operation) || error.name === "AbortError") {
      return;
    }
    setSessionState(SESSION.UNKNOWN_ERROR);
    replaceViewMessage(
      "退出未确认",
      "无法联系认证服务，已停止显示受保护内容。",
      true,
    );
  }
}

async function refreshIfVisible(event, operation) {
  if (!isCurrentAuthOperation(operation)) {
    return;
  }
  let envelope;
  try {
    envelope = JSON.parse(event.data);
  } catch (_error) {
    ticker.textContent = "最近事件：无法解析";
    return;
  }
  if (
    !envelope ||
    typeof envelope.event_id !== "string" ||
    typeof envelope.event_type !== "string" ||
    typeof envelope.task_id !== "string"
  ) {
    ticker.textContent = "最近事件：格式无效";
    return;
  }
  if (event.lastEventId && event.lastEventId !== envelope.event_id) {
    ticker.textContent = "最近事件：标识不一致";
    return;
  }
  if (seenEventIds.has(envelope.event_id)) {
    return;
  }
  seenEventIds.add(envelope.event_id);
  ticker.textContent =
    "最近事件：" + envelope.event_type + " · " + envelope.task_id;
  const route = currentRoute();
  if (
    route.startsWith("/tasks/") ||
    route.startsWith("/governance") ||
    route.startsWith("/knowledge")
  ) {
    await loadRoute(route, operation);
  }
}

function connectSse() {
  if (eventSource !== null) {
    return;
  }
  if (shellMode === "live" && sessionState !== SESSION.ACTIVE) {
    return;
  }
  const operation = currentAuthOperation();
  const source = new EventSource("/api/v1/tasks/events", {
    withCredentials: true,
  });
  eventSource = source;
  sseStatus.hidden = false;
  sseStatus.textContent = "SSE 连接中…";
  sseStatus.className = "sse-status sse-connecting";
  source.onopen = function () {
    if (eventSource !== source || !isCurrentAuthOperation(operation)) {
      return;
    }
    sseStatus.textContent = "SSE 已连接";
    sseStatus.className = "sse-status sse-open";
  };
  source.onmessage = function (event) {
    if (eventSource === source && isCurrentAuthOperation(operation)) {
      void refreshIfVisible(event, operation);
    }
  };
  source.onerror = async function () {
    if (eventSource !== source || !isCurrentAuthOperation(operation)) {
      return;
    }
    source.close();
    eventSource = null;
    sseStatus.textContent = "SSE 断线，正在验证会话…";
    sseStatus.className = "sse-status sse-error";
    if (shellMode === "live") {
      await refreshSession({ reconnect: true, silent: true });
    } else {
      window.setTimeout(connectSse, 1000);
    }
  };
}

async function submitForm(form) {
  const operation = currentAuthOperation();
  if (shellMode === "live" && sessionState !== SESSION.ACTIVE) {
    return;
  }
  const body = new URLSearchParams(new FormData(form));
  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: operation.signal,
    });
    if (!isCurrentAuthOperation(operation)) {
      return;
    }
    if (response.status === 401) {
      requireReauthentication(operation);
      return;
    }
    if (response.status === 403) {
      ticker.textContent = "提交失败：当前会话无权执行此操作";
      return;
    }
    const payload = await response.json();
    if (!isCurrentAuthOperation(operation)) {
      return;
    }
    if (response.ok && payload.accepted) {
      const receiptId = payload.receipt.command_id || payload.receipt.event_id;
      ticker.textContent = "已受理：" + receiptId;
      if (payload.receipt.document_id) {
        const target =
          payload.receipt.operation === "retire"
            ? "/knowledge"
            : "/knowledge?" +
              new URLSearchParams({
                document_id: payload.receipt.document_id,
                document_version: String(payload.receipt.document_version),
              }).toString();
        location.hash = target;
        await loadRoute(target, operation);
      } else {
        await loadRoute(currentRoute(), operation);
      }
    } else {
      ticker.textContent = "提交失败：请求未被受理";
    }
  } catch (error) {
    if (!isCurrentAuthOperation(operation) || error.name === "AbortError") {
      return;
    }
    ticker.textContent = "提交失败：服务不可用";
  }
}

document.addEventListener("submit", function (event) {
  const form = event.target;
  if (form.id === "knowledge-lookup") {
    event.preventDefault();
    const data = new FormData(form);
    const query = new URLSearchParams();
    for (const name of ["document_id", "document_version", "expected_hash"]) {
      const value = String(data.get(name) || "").trim();
      if (value) {
        query.set(name, value);
      }
    }
    location.hash = "/knowledge" + (query.size ? "?" + query.toString() : "");
    return;
  }
  if (form.id === "governance-filter") {
    event.preventDefault();
    const data = new FormData(form);
    const query = new URLSearchParams();
    const tab = String(data.get("tab") || "versions");
    query.set("tab", tab);
    query.set("limit", "20");
    for (const name of ["task_id", "correlation_id"]) {
      const value = String(data.get(name) || "").trim();
      if (value) {
        query.set(name, value);
      }
    }
    for (const name of ["occurred_after", "occurred_before"]) {
      const value = String(data.get(name) || "").trim();
      if (value) {
        query.set(name, value + ":00Z");
      }
    }
    location.hash = "/governance?" + query.toString();
    return;
  }
  if (
    form.id === "completion-form" ||
    form.classList.contains("retry-form") ||
    form.id.startsWith("knowledge-")
  ) {
    event.preventDefault();
    submitForm(form);
  }
});

refreshAction.addEventListener("click", async function () {
  const active = await refreshSession();
  if (active) {
    await loadRoute(currentRoute());
    connectSse();
  }
});

logoutAction.addEventListener("click", logout);
loginAction.addEventListener("click", function () {
  advanceAuthEpoch();
  closeSse();
  seenEventIds.clear();
  clearProtectedView("正在前往安全登录入口…");
});

window.addEventListener("hashchange", async function () {
  if (shellMode === "live" && sessionState !== SESSION.ACTIVE) {
    requireReauthentication();
    return;
  }
  await loadRoute(currentRoute());
});

async function start() {
  const mode = await applyMode();
  if (mode === "cancelled") {
    return;
  }
  if (mode === "demo") {
    await loadRoute(currentRoute());
    connectSse();
    return;
  }
  if (mode === "live") {
    const active = await refreshSession({ silent: true });
    if (active) {
      await loadRoute(currentRoute());
      connectSse();
    }
    return;
  }
  replaceViewMessage("服务不可用", "无法检查登录状态。", false);
}

start();
