// frontend/app.js
// Top navbar + API/User/Token pills + guest-aware behavior.
// Requires api.js

const API_LABEL = "http://127.0.0.1:8000"; // display only

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pill(html, cls = "") {
  return `<span class="pill ${cls}">${html}</span>`;
}

function setTokenPill(state, text, tooltip = "") {
  const dot = document.getElementById("tokenDot");
  const label = document.getElementById("tokenPillText");
  if (!dot || !label) return;

  dot.classList.remove("ok", "bad", "warn");
  label.classList.remove("ok", "bad", "warn");

  if (state === "ok") {
    dot.classList.add("ok");
    label.classList.add("ok");
  } else if (state === "bad") {
    dot.classList.add("bad");
    label.classList.add("bad");
  } else {
    dot.classList.add("warn");
    label.classList.add("warn");
  }

  label.textContent = text;
  dot.title = tooltip || "";
  label.title = tooltip || "";
}

/* -----------------------------
   Optional toast helpers
------------------------------ */
function showToast(title, body = "") {
  const t = document.getElementById("toast");
  if (!t) return alert(body ? `${title}\n\n${body}` : title);

  const tt = document.getElementById("toastTitle");
  const tb = document.getElementById("toastBody");
  if (tt) tt.textContent = title;
  if (tb) tb.textContent = body;

  t.classList.add("show");
  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => t.classList.remove("show"), 2600);
}

function applyRequiresLoginBehavior() {
  document.querySelectorAll(".requiresLogin").forEach((el) => {
    // Prevent stacking multiple listeners if renderHeaderNav runs again
    el.dataset.rlWired = "1";

    el.addEventListener("click", (e) => {
      const token = getToken();
      if (token) return;
      e.preventDefault();
      showToast("Login required", "Please login to use this feature.");
    });
  });
}

/* -----------------------------
   Header nav
------------------------------ */
function renderHeaderNav() {
  const nav = document.getElementById("nav");
  if (!nav) return;

  const token = getToken();
  const username = getUsername();
  const isGuest = !token;

  // Decide what needs login
  const libraryCls = isGuest ? "requiresLogin" : "";
  const aiCls = isGuest ? "requiresLogin" : "";

  nav.innerHTML = `
    <div class="navLeft">
      <a class="navBtn" href="search.html">Search</a>
      <a class="navBtn ${libraryCls}" href="library.html" ${isGuest ? 'title="Login required"' : ""}>Saved Papers</a>
      <a class="navBtn ${aiCls}" href="ai.html" ${isGuest ? 'title="Login required"' : ""}>AI</a>
      <a class="navBtn" href="info.html">Info</a>
    </div>

    <div class="navRight">
      ${pill(`API: <span class="mono">${esc(API_LABEL)}</span>`, "muted")}
      ${pill(`User: <b id="userPill">${esc(username || (token ? "…" : "guest"))}</b>`, "muted")}
      ${pill(`<span class="dot" id="tokenDot"></span><span id="tokenPillText">token: ?</span>`, "muted")}
      ${
        token
          ? `<a class="navBtn danger" href="#" id="logoutLink">Logout</a>`
          : `<a class="navBtn" href="login.html">Login</a>`
      }
    </div>
  `;

  const logout = document.getElementById("logoutLink");
  if (logout) {
    logout.addEventListener("click", (e) => {
      e.preventDefault();
      clearToken();
      setUsername("");
      sessionStorage.removeItem("last_external");
      sessionStorage.removeItem("open_study_id");
      window.location.href = "search.html";
    });
  }

  applyRequiresLoginBehavior();
}

async function refreshUserPill() {
  const el = document.getElementById("userPill");
  if (!el) return;

  const token = getToken();
  if (!token) {
    el.textContent = getUsername() || "guest";
    return;
  }

  try {
    const me = await fetchJson("/me");
    if (me && me.username) {
      setUsername(me.username);
      el.textContent = me.username;
    }
  } catch {
    el.textContent = getUsername() || "guest";
  }
}

async function refreshTokenPill() {
  const token = getToken();
  if (!token) {
    setTokenPill("warn", "token: guest", "Guest mode: login only needed to save/comment/AI.");
    return;
  }

  try {
    const res = await fetchJson("/auth/token_status");
    if (res && res.valid) {
      const secs = typeof res.seconds_left === "number" ? res.seconds_left : 0;
      const mins = Math.max(0, Math.floor(secs / 60));
      setTokenPill("ok", `token: ok (${mins}m)`);
    } else {
      setTokenPill("bad", "token: bad", "Token invalid/expired. Login again.");
    }
  } catch (e) {
    setTokenPill("warn", "token: err", e?.message || String(e));
  }
}

/* -----------------------------
   Continue-as-guest support (login page)
------------------------------ */
function wireContinueAsGuest() {
  // Support BOTH ids so your login page works without more edits
  const ids = ["continueGuest", "continueGuest2", "guestBtn", "guestBtn2"];
  const btns = ids.map((id) => document.getElementById(id)).filter(Boolean);
  if (!btns.length) return;

  function goGuest(e) {
    e.preventDefault();
    clearToken();
    setUsername("");
    sessionStorage.removeItem("last_external");
    sessionStorage.removeItem("open_study_id");
    window.location.href = "search.html";
  }

  btns.forEach((b) => b.addEventListener("click", goGuest));
}

document.addEventListener("DOMContentLoaded", async () => {
  renderHeaderNav();
  wireContinueAsGuest();
  await refreshUserPill();
  await refreshTokenPill();
});