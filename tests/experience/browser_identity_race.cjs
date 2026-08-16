"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appSource = fs.readFileSync(
  path.resolve(__dirname, "../../web/shell/app.js"),
  "utf8",
);

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function response(status, { jsonValue = {}, textValue = "", type = "" } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => (name.toLowerCase() === "content-type" ? type : null) },
    json: async () => jsonValue,
    text: async () => textValue,
  };
}

function makeElement(id = "") {
  let html = "";
  return {
    id,
    hidden: false,
    disabled: false,
    textContent: "",
    className: "",
    children: [],
    listeners: {},
    classList: { contains: () => false },
    setAttribute() {},
    append(...items) {
      this.children.push(...items);
    },
    replaceChildren(...items) {
      html = "";
      this.children = items;
    },
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    },
    get innerHTML() {
      return html;
    },
    set innerHTML(value) {
      html = value;
      this.children = [];
    },
  };
}

function makeHarness(fetchImpl, initialHash = "#/tasks") {
  const ids = [
    "view",
    "sse-status",
    "event-ticker",
    "shell-mode",
    "demo-controls",
    "session-status",
    "login-action",
    "refresh-action",
    "logout-action",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, makeElement(id)]));
  const eventSources = [];
  class FakeEventSource {
    constructor(url, options) {
      this.url = url;
      this.options = options;
      this.closed = false;
      eventSources.push(this);
    }

    close() {
      this.closed = true;
    }
  }
  const documentListeners = {};
  const windowListeners = {};
  const context = vm.createContext({
    AbortController,
    EventSource: FakeEventSource,
    FormData,
    JSON,
    URL,
    URLSearchParams,
    clearTimeout,
    console,
    document: {
      addEventListener: (name, callback) => {
        documentListeners[name] = callback;
      },
      createElement: () => makeElement(),
      getElementById: (id) => elements[id],
    },
    fetch: fetchImpl,
    location: { hash: initialHash, origin: "http://shell.test" },
    setTimeout,
    window: {
      addEventListener: (name, callback) => {
        windowListeners[name] = callback;
      },
      setTimeout,
    },
  });
  vm.runInContext(appSource, context, { filename: "app.js" });
  return { elements, eventSources };
}

async function eventually(predicate, label) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("timed out waiting for " + label);
}

async function staleViewCannotReturnAfterLogout() {
  const route = deferred();
  let routeStarted = false;
  const harness = makeHarness(async (url) => {
    if (url === "/health") {
      return response(200, { jsonValue: { mode: "live" } });
    }
    if (url === "/api/v1/auth/refresh") {
      return response(200, {
        jsonValue: { status: "active", expires_at: "2026-08-11T16:00:00Z" },
      });
    }
    if (url === "/views/tasks") {
      routeStarted = true;
      return route.promise;
    }
    if (url === "/api/v1/auth/logout") {
      return response(204);
    }
    throw new Error("unexpected URL " + url);
  });
  await eventually(() => routeStarted, "initial protected view request");
  await harness.elements["logout-action"].listeners.click();
  route.resolve(
    response(200, {
      textValue: '<section id="stale-secret">stale protected data</section>',
      type: "text/html; charset=utf-8",
    }),
  );
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(harness.elements.view.innerHTML, "");
  assert.equal(harness.elements["session-status"].textContent, "尚未登录");
}

async function staleRefreshCannotRestoreSessionAfterLogout() {
  const reconnectRefresh = deferred();
  let refreshCalls = 0;
  const harness = makeHarness(async (url) => {
    if (url === "/health") {
      return response(200, { jsonValue: { mode: "live" } });
    }
    if (url === "/api/v1/auth/refresh") {
      refreshCalls += 1;
      if (refreshCalls === 1) {
        return response(200, {
          jsonValue: { status: "active", expires_at: "2026-08-11T16:00:00Z" },
        });
      }
      return reconnectRefresh.promise;
    }
    if (url === "/views/tasks") {
      return response(200, { textValue: "<section>tasks</section>", type: "text/html" });
    }
    if (url === "/api/v1/auth/logout") {
      return response(204);
    }
    throw new Error("unexpected URL " + url);
  });
  await eventually(() => harness.eventSources.length === 1, "initial SSE connection");
  const reconnect = harness.eventSources[0].onerror();
  await eventually(() => refreshCalls === 2, "SSE reconnect refresh");
  await harness.elements["logout-action"].listeners.click();
  reconnectRefresh.resolve(
    response(200, {
      jsonValue: { status: "active", expires_at: "2026-08-11T17:00:00Z" },
    }),
  );
  await reconnect;

  assert.equal(harness.elements["session-status"].textContent, "尚未登录");
  assert.equal(harness.eventSources.length, 1);
}

async function staleGovernanceViewCannotReturnAfterLogout() {
  const route = deferred();
  let routeStarted = false;
  const harness = makeHarness(async (url) => {
    if (url === "/health") {
      return response(200, { jsonValue: { mode: "live" } });
    }
    if (url === "/api/v1/auth/refresh") {
      return response(200, {
        jsonValue: { status: "active", expires_at: "2026-08-11T16:00:00Z" },
      });
    }
    if (url === "/views/governance") {
      routeStarted = true;
      return route.promise;
    }
    if (url === "/api/v1/auth/logout") {
      return response(204);
    }
    throw new Error("unexpected URL " + url);
  }, "#/governance");
  await eventually(() => routeStarted, "initial governance view request");
  await harness.elements["logout-action"].listeners.click();
  route.resolve(
    response(200, {
      textValue: '<section id="stale-governance-secret">stale governance</section>',
      type: "text/html; charset=utf-8",
    }),
  );
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(harness.elements.view.innerHTML, "");
  assert.equal(harness.elements["session-status"].textContent, "尚未登录");
}

Promise.resolve()
  .then(staleViewCannotReturnAfterLogout)
  .then(staleRefreshCannotRestoreSessionAfterLogout)
  .then(staleGovernanceViewCannotReturnAfterLogout)
  .then(() => process.stdout.write("browser identity race gate: PASS\n"))
  .catch((error) => {
    process.stderr.write(String(error.stack || error) + "\n");
    process.exitCode = 1;
  });
