// frontend/ui.js
export function qs(sel, root = document) {
  return root.querySelector(sel);
}
export function qsa(sel, root = document) {
  return Array.from(root.querySelectorAll(sel));
}

export function setText(el, text) {
  if (!el) return;
  el.textContent = text;
}

export function show(el) {
  if (!el) return;
  el.style.display = "";
}
export function hide(el) {
  if (!el) return;
  el.style.display = "none";
}

export function toast(message, type = "info", ms = 3500) {
  let host = document.getElementById("toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast-host";
    host.style.position = "fixed";
    host.style.right = "16px";
    host.style.bottom = "16px";
    host.style.zIndex = "9999";
    host.style.display = "flex";
    host.style.flexDirection = "column";
    host.style.gap = "8px";
    document.body.appendChild(host);
  }

  const t = document.createElement("div");
  t.style.padding = "10px 12px";
  t.style.borderRadius = "12px";
  t.style.boxShadow = "0 10px 30px rgba(0,0,0,0.12)";
  t.style.fontSize = "14px";
  t.style.maxWidth = "360px";
  t.style.background = "#111827";
  t.style.color = "white";
  t.style.opacity = "0";
  t.style.transform = "translateY(6px)";
  t.style.transition = "all .15s ease";

  const tag = type === "error" ? "Error" : type === "success" ? "Success" : "Info";
  t.innerHTML = `<div style="font-weight:700;margin-bottom:2px;">${tag}</div>
                 <div style="opacity:.9;line-height:1.25;">${escapeHtml(message)}</div>`;

  host.appendChild(t);
  requestAnimationFrame(() => {
    t.style.opacity = "1";
    t.style.transform = "translateY(0)";
  });

  setTimeout(() => {
    t.style.opacity = "0";
    t.style.transform = "translateY(6px)";
    setTimeout(() => t.remove(), 250);
  }, ms);
}

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export async function withButtonLoading(btn, fn, loadingText = "Loading...") {
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