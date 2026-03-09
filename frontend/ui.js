// frontend/ui.js
// Global utility helpers — loaded as plain <script>, no ES module exports.

window.setText = function(el, text) {
  if (!el) return;
  el.textContent = text;
};

window.show = function(el) {
  if (!el) return;
  el.style.display = "";
};

window.hide = function(el) {
  if (!el) return;
  el.style.display = "none";
};

window.withBtnLoading = async function(btn, fn, loadingText = "Loading...") {
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
};
