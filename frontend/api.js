// frontend/api.js
// Global helpers for ALL pages (no modules). Must be loaded before app.js.

(() => {
  const API_BASE = "http://127.0.0.1:8000"; // backend

  function qs(id) {
    return document.getElementById(id);
  }

  function getToken() {
    return localStorage.getItem("token") || "";
  }

  function setToken(token) {
    if (token) localStorage.setItem("token", token);
    else localStorage.removeItem("token");
  }

  function clearToken() {
    localStorage.removeItem("token");
  }

  function getUsername() {
    return localStorage.getItem("username") || "";
  }

  function setUsername(u) {
    if (u) localStorage.setItem("username", u);
    else localStorage.removeItem("username");
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // fetch wrapper that:
  // - prefixes API_BASE
  // - JSON serializes object bodies
  // - adds Authorization automatically if token exists (unless opts.auth === false)
  // - throws readable errors
  async function fetchJson(path, opts = {}) {
    const url = path.startsWith("http") ? path : API_BASE + path;

    const headers = new Headers(opts.headers || {});
    if (!headers.has("Accept")) headers.set("Accept", "application/json");

    // Auto JSON body
    let body = opts.body;
    const isPlainObject =
      body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof Blob);

    if (isPlainObject) {
      if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      body = JSON.stringify(body);
    } else if (typeof body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    // Auto auth (ALLOW OVERRIDE)
    // - opts.auth === false => never attach Authorization
    // - caller can also explicitly set headers.Authorization themselves
    if (opts.auth !== false && !headers.has("Authorization")) {
      const t = getToken();
      if (t) headers.set("Authorization", "Bearer " + t);
    }

    const res = await fetch(url, {
      method: opts.method || "GET",
      headers,
      body,
      credentials: "omit",
    });

    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      try {
        data = await res.json();
      } catch {
        data = null;
      }
    } else {
      const text = await res.text().catch(() => "");
      data = text ? { detail: text } : null;
    }

    if (!res.ok) {
      const msg =
        (data && (data.detail || data.message)) ||
        `HTTP ${res.status} ${res.statusText}` ||
        "Request failed";
      const err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }

    return data;
  }

  // expose globally
  window.API_BASE = API_BASE;
  window.qs = qs;
  window.getToken = getToken;
  window.setToken = setToken;
  window.clearToken = clearToken;
  window.getUsername = getUsername;
  window.setUsername = setUsername;
  window.escapeHtml = escapeHtml;
  window.fetchJson = fetchJson;
})();