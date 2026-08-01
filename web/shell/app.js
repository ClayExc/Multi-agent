/* FlowPilot 轨道 C Web 外壳 — 极薄客户端层。
   职责：路由、拉取服务端渲染片段、SSE 消费与断线提示、表单/重试提交。
   所有渲染与状态判定都在服务端（web/src/flowpilot_shell/render），
   本文件不包含任何业务事实推断或审批写调用。 */

"use strict";

const view = document.getElementById("view");
const sseStatus = document.getElementById("sse-status");
const ticker = document.getElementById("event-ticker");

function currentRoute() {
  const hash = location.hash || "#/tasks";
  return hash.slice(1); // e.g. /tasks or /tasks/task_repair_003?demo=unavailable
}

function viewUrl(route) {
  // hash 路由 #/tasks、#/tasks/<id> 映射到服务端渲染视图 /views/*
  if (route === "/tasks" || route.startsWith("/tasks/")) {
    return "/views" + route;
  }
  return route;
}

async function loadRoute(route) {
  const url = viewUrl(route);
  view.innerHTML = '<p class="loading">加载中…</p>';
  try {
    const response = await fetch(url);
    const html = await response.text();
    view.innerHTML = html;
  } catch (err) {
    view.innerHTML =
      '<section class="error-panel"><h3>加载失败</h3>' +
      "<p>无法连接演示服务器。</p>" +
      '<a class="btn btn-primary" href="' +
      location.hash +
      '" data-action="retry">重试</a></section>';
  }
}

function refreshIfVisible(event) {
  const route = currentRoute();
  if (route.startsWith("/tasks/")) {
    loadRoute(route);
  }
  const data = event.data;
  try {
    const envelope = JSON.parse(data);
    ticker.textContent =
      "最近事件：" + envelope.event_type + " · " + envelope.task_id;
  } catch (_err) {
    ticker.textContent = "最近事件：无法解析";
  }
}

function connectSse() {
  const source = new EventSource("/api/v1/tasks/events");
  source.onopen = function () {
    sseStatus.textContent = "SSE 已连接";
    sseStatus.className = "sse-status sse-open";
  };
  source.onmessage = refreshIfVisible;
  source.onerror = function () {
    // EventSource 原生自动重连（携带 Last-Event-ID），服务端按重放语义补发。
    sseStatus.textContent = "SSE 断线，自动重连中…";
    sseStatus.className = "sse-status sse-error";
  };
  window.__shellEventSource = source;
}

async function submitForm(form) {
  const body = new URLSearchParams(new FormData(form));
  const response = await fetch(form.action, { method: "POST", body: body });
  const payload = await response.json();
  if (payload.accepted) {
    ticker.textContent = "已受理：" + payload.receipt.command_id;
    loadRoute(currentRoute());
  } else {
    ticker.textContent = "提交失败：" + (payload.error ? payload.error.message : "未知错误");
  }
}

document.addEventListener("submit", function (event) {
  const form = event.target;
  if (form.id === "completion-form" || form.classList.contains("retry-form")) {
    event.preventDefault();
    submitForm(form);
  }
});

window.addEventListener("hashchange", function () {
  loadRoute(currentRoute());
});

loadRoute(currentRoute());
connectSse();
