// frontend/api.js
// Global helpers for ALL pages (no modules). Must be loaded before app.js.

(() => {
  const API_BASE = window.API_BASE || "http://127.0.0.1:8000"; // backend

  function qs(id) { return document.getElementById(id); }
  function $(id) { return qs(id); }

  // ---- Auth storage ----
  function getToken() { return localStorage.getItem("token") || ""; }
  function getUsername() { return localStorage.getItem("username") || ""; }

  function _emitAuthChanged() {
    window.dispatchEvent(new CustomEvent("auth:changed"));
  }

  // prevent auth:changed storms (esp. 401 bursts)
  function _emitAuthChangedOncePer(ms = 1500) {
    const now = Date.now();
    const last = window.__ME_LAST_AUTH_EMIT_AT__ || 0;
    if (now - last < ms) return;
    window.__ME_LAST_AUTH_EMIT_AT__ = now;
    _emitAuthChanged();
  }

  function setToken(token) {
    const prev = getToken();
    if (token) localStorage.setItem("token", token);
    else localStorage.removeItem("token");
    const next = getToken();
    if (prev !== next) _emitAuthChanged();
  }

  function clearToken() {
    const had = !!getToken();
    localStorage.removeItem("token");
    if (had) _emitAuthChanged();
  }

  function setUsername(u) {
    const prev = getUsername();
    if (u) localStorage.setItem("username", u);
    else localStorage.removeItem("username");
    const next = getUsername();
    return prev !== next;
  }

  // ---- HTML escaping ----
  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // ---- Toast ----
  function ensureToastHost() {
    let host = document.getElementById("toastHost");
    if (host) return host;

    host = document.createElement("div");
    host.id = "toastHost";
    host.style.position = "fixed";
    host.style.right = "16px";
    host.style.bottom = "16px";
    host.style.zIndex = "9999";
    host.style.display = "flex";
    host.style.flexDirection = "column";
    host.style.gap = "10px";
    document.body.appendChild(host);
    return host;
  }

  function showToast(title, body = "", type = "info", ms = 2600) {
    const host = ensureToastHost();

    const card = document.createElement("div");
    card.style.padding = "10px 12px";
    card.style.borderRadius = "14px";
    card.style.boxShadow = "0 10px 30px rgba(0,0,0,0.18)";
    card.style.background = "#0b1220";
    card.style.color = "white";
    card.style.border = "1px solid rgba(255,255,255,0.08)";
    card.style.maxWidth = "380px";
    card.style.opacity = "0";
    card.style.transform = "translateY(6px)";
    card.style.transition = "all .14s ease";

    const tag =
      type === "error" ? "Error" :
      type === "success" ? "Success" :
      "Info";

    card.innerHTML = `
      <div style="font-weight:900; margin-bottom:2px;">${escapeHtml(tag)} — ${escapeHtml(title)}</div>
      ${body ? `<div style="opacity:.9; line-height:1.25;">${escapeHtml(body)}</div>` : ""}
    `;

    host.appendChild(card);
    requestAnimationFrame(() => {
      card.style.opacity = "1";
      card.style.transform = "translateY(0)";
    });

    setTimeout(() => {
      card.style.opacity = "0";
      card.style.transform = "translateY(6px)";
      setTimeout(() => card.remove(), 200);
    }, ms);
  }

  // ---- Robust JSON parsing ----
  async function safeParseJson(res) {
    try { return await res.json(); } catch { return null; }
  }

  function extractErrorMessage(data, res) {
    if (data?.error?.message) return data.error.message;
    if (data?.detail) {
      if (typeof data.detail === "string") return data.detail;
      return "Invalid request";
    }
    return `HTTP ${res.status} ${res.statusText}`.trim();
  }

  function makeNetworkError(original) {
    const err = new Error(
      "Network/CORS error (request reached server or was blocked). If it actually saved, refresh Library to confirm."
    );
    err.isNetwork = true;
    err.cause = original;
    err.status = 0;
    return err;
  }

  /* ======================================================
     request dedupe + endpoint throttling
     ====================================================== */

  const __INFLIGHT__ = new Map();   // key -> Promise
  const __THROTTLE__ = new Map();   // pathKey -> last timestamp (ms)

  function __fullUrl(path) {
    return path.startsWith("http") ? path : API_BASE + path;
  }

  function __pathKeyFromUrl(url) {
    try {
      const u = new URL(url, API_BASE);
      return u.pathname;
    } catch {
      return url;
    }
  }

  function __throttleMsFor(pathname) {
    if (pathname === "/me") return 4000;
    if (pathname === "/auth/token_status") return 4000;
    if (pathname === "/folders") return 2500;
    if (/^\/studies\/\d+\/comments$/.test(pathname)) return 1500;
    return 0;
  }

  async function fetchJson(path, opts = {}) {
    const url = __fullUrl(path);

    const method = String(opts.method || "GET").toUpperCase();
    const authOn = opts.auth !== false;

    let body = opts.body;
    const isPlainObject =
      body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof Blob);

    const bodyKey = isPlainObject
      ? JSON.stringify(body)
      : (typeof body === "string" ? body : "");

    const headersKey = (() => {
      const h = opts.headers || {};
      const ct = (h["Content-Type"] || h["content-type"] || "");
      return `${authOn ? "auth" : "noauth"}|ct:${ct}`;
    })();

    const dedupeKey = `${method} ${url} ${headersKey} ${bodyKey}`;

    if (__INFLIGHT__.has(dedupeKey)) {
      return __INFLIGHT__.get(dedupeKey);
    }

    const p = (async () => {
      const pathname = __pathKeyFromUrl(url);
      const tMs = (method === "GET") ? __throttleMsFor(pathname) : 0;
      if (tMs) {
        const last = __THROTTLE__.get(pathname) || 0;
        const now = Date.now();
        const wait = tMs - (now - last);
        if (wait > 0) await new Promise(r => setTimeout(r, wait));
        __THROTTLE__.set(pathname, Date.now());
      }

      const headers = new Headers(opts.headers || {});
      if (!headers.has("Accept")) headers.set("Accept", "application/json");

      if (isPlainObject) {
        if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
        body = JSON.stringify(body);
      } else if (typeof body === "string" && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }

      // Track whether we actually sent Authorization.
      let sentAuth = false;

      if (authOn && !headers.has("Authorization")) {
        const t = getToken();
        if (t) {
          headers.set("Authorization", "Bearer " + t);
          sentAuth = true;
        }
      } else if (headers.has("Authorization")) {
        sentAuth = true;
      }

      let res;
      try {
        res = await fetch(url, {
          method,
          headers,
          body,
          credentials: "omit",
          signal: opts.signal, // optional AbortController support
        });
      } catch (e) {
        // Network / CORS / connection reset
        throw makeNetworkError(e);
      }

      if (res.status === 204) return { ok: true };

      const ct = (res.headers.get("content-type") || "").toLowerCase();
      let data = null;

      if (ct.includes("application/json")) {
        data = await safeParseJson(res);
      } else {
        const text = await res.text().catch(() => "");
        data = text ? { detail: text } : null;
      }

      if (!res.ok) {
        const msg = extractErrorMessage(data, res);

        // Only auto-clear token if we actually sent auth.
        if (res.status === 401 && getToken() && sentAuth) {
          localStorage.removeItem("token");
          localStorage.removeItem("username");
          _emitAuthChangedOncePer(1500);
        }

        const err = new Error(msg || "Request failed");
        err.status = res.status;
        err.data = data;
        throw err;
      }

      return data;
    })();

    __INFLIGHT__.set(dedupeKey, p);
    try {
      return await p;
    } finally {
      __INFLIGHT__.delete(dedupeKey);
    }
  }

  // ---- confirmModal / promptModal ----
  function ensureConfirmModal() {
    if (document.getElementById("meConfirmOverlay")) return;

    const el = document.createElement("div");
    el.id = "meConfirmOverlay";
    el.innerHTML = `
      <div class="meConfirmBackdrop"></div>
      <div class="meConfirmCard" role="dialog" aria-modal="true">
        <div class="meConfirmTitle" id="meConfirmTitle">Confirm</div>
        <div class="meConfirmBody" id="meConfirmBody">Are you sure?</div>
        <div class="meConfirmActions">
          <button class="btn" id="meConfirmCancel">Cancel</button>
          <button class="btn danger" id="meConfirmOk">Delete</button>
        </div>
      </div>
    `;
    document.body.appendChild(el);

    el.querySelector(".meConfirmBackdrop").addEventListener("click", () => {
      const cancel = document.getElementById("meConfirmCancel");
      cancel && cancel.click();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!el.classList.contains("show")) return;
      const cancel = document.getElementById("meConfirmCancel");
      cancel && cancel.click();
    });
  }

  function confirmModal({
    title = "Confirm",
    message = "Are you sure?",
    okText = "Delete",
    cancelText = "Cancel",
    danger = true,
  } = {}) {
    ensureConfirmModal();

    const overlay = document.getElementById("meConfirmOverlay");
    const t = document.getElementById("meConfirmTitle");
    const b = document.getElementById("meConfirmBody");
    const ok = document.getElementById("meConfirmOk");
    const cancel = document.getElementById("meConfirmCancel");

    t.textContent = title;
    b.textContent = message;

    ok.textContent = okText;
    cancel.textContent = cancelText;

    ok.classList.toggle("danger", !!danger);
    overlay.classList.add("show");

    return new Promise((resolve) => {
      const cleanup = () => {
        ok.onclick = null;
        cancel.onclick = null;
        overlay.classList.remove("show");
      };

      ok.onclick = () => { cleanup(); resolve(true); };
      cancel.onclick = () => { cleanup(); resolve(false); };

      setTimeout(() => ok.focus(), 0);
    });
  }

  function ensurePromptModal() {
    if (document.getElementById("mePromptOverlay")) return;

    const el = document.createElement("div");
    el.id = "mePromptOverlay";
    el.innerHTML = `
      <div class="mePromptBackdrop"></div>
      <div class="mePromptCard" role="dialog" aria-modal="true">
        <div class="mePromptTitle" id="mePromptTitle">Input</div>
        <div class="mePromptBody" id="mePromptBody">Enter a value</div>

        <input class="mePromptInput" id="mePromptInput" placeholder="Type here..." />

        <div class="mePromptActions">
          <button class="btn" id="mePromptCancel">Cancel</button>
          <button class="btn primary" id="mePromptOk">OK</button>
        </div>
      </div>
    `;
    document.body.appendChild(el);

    el.querySelector(".mePromptBackdrop").addEventListener("click", () => {
      const cancel = document.getElementById("mePromptCancel");
      cancel && cancel.click();
    });

    document.addEventListener("keydown", (e) => {
      const overlay = document.getElementById("mePromptOverlay");
      if (!overlay || !overlay.classList.contains("show")) return;
      if (e.key === "Escape") {
        const cancel = document.getElementById("mePromptCancel");
        cancel && cancel.click();
      }
      if (e.key === "Enter") {
        const ok = document.getElementById("mePromptOk");
        ok && ok.click();
      }
    });
  }

  function promptModal({
    title = "Folder name?",
    message = "Enter a name",
    placeholder = "e.g. Cardiology",
    okText = "OK",
    cancelText = "Cancel",
    initialValue = "",
  } = {}) {
    ensurePromptModal();

    const overlay = document.getElementById("mePromptOverlay");
    const t = document.getElementById("mePromptTitle");
    const b = document.getElementById("mePromptBody");
    const input = document.getElementById("mePromptInput");
    const ok = document.getElementById("mePromptOk");
    const cancel = document.getElementById("mePromptCancel");

    t.textContent = title;
    b.textContent = message;
    input.placeholder = placeholder;
    input.value = initialValue || "";

    ok.textContent = okText;
    cancel.textContent = cancelText;

    overlay.classList.add("show");

    return new Promise((resolve) => {
      const cleanup = () => {
        ok.onclick = null;
        cancel.onclick = null;
        overlay.classList.remove("show");
      };

      ok.onclick = () => {
        const v = (input.value || "").trim();
        cleanup();
        resolve(v || null);
      };
      cancel.onclick = () => {
        cleanup();
        resolve(null);
      };

      setTimeout(() => input.focus(), 0);
    });
  }

  async function withBtnLoading(btn, fn, loadingText = "Loading...") {
    if (!btn) return fn();
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = loadingText;
    try {
      return await fn();
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  // expose globally
  window.API_BASE = API_BASE;
  window.qs = qs;
  window.$ = $;
  window.getToken = getToken;
  window.setToken = setToken;
  window.clearToken = clearToken;
  window.getUsername = getUsername;
  window.setUsername = setUsername;
  window.escapeHtml = escapeHtml;
  window.fetchJson = fetchJson;

  window.showToast = showToast;
  window.withBtnLoading = withBtnLoading;
  window.confirmModal = confirmModal;
  window.promptModal = promptModal;
})();