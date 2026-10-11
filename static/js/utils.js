/* utils.js — tiny helpers shared across the app. No deps. */
(function (global) {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) n.setAttribute(k, v);
    }
    for (const kid of kids) {
      if (kid == null) continue;
      if (typeof kid === "string" || typeof kid === "number") n.appendChild(document.createTextNode(String(kid)));
      else n.appendChild(kid);
    }
    return n;
  }

  function show(node) { node && node.classList.remove("hidden"); }
  function hide(node) { node && node.classList.add("hidden"); }
  function swap(viewId) {
    $$(".view").forEach((v) => { v.classList.remove("active"); v.classList.add("hidden"); });
    const v = $("#" + viewId);
    if (v) { v.classList.remove("hidden"); v.classList.add("active"); }
  }

  let toastTimer;
  function toast(msg, ms) {
    const t = $("#toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add("hidden"), ms || 2600);
  }

  function fmtTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function esc(s) {
    return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function truncate(s, n) {
    s = s || "";
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  // ---- theme (with auto-detect via prefers-color-scheme) ----
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const icon = $("#theme-icon");
    if (icon) icon.textContent = theme === "light" ? "🌙" : "☀️";
    if (global.CSGraph && global.CSGraph.rerender) global.CSGraph.rerender();
  }

  function initTheme() {
    const saved = localStorage.getItem("cs-theme");
    if (saved) {
      applyTheme(saved);
    } else {
      // auto-detect from system preference
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      applyTheme(prefersDark ? "dark" : "light");
    }
    const btn = $("#theme-toggle");
    if (btn) btn.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || "light";
      const next = cur === "light" ? "dark" : "light";
      localStorage.setItem("cs-theme", next);
      applyTheme(next);
    });
    // react to system theme changes (only if user hasn't set a preference)
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
        if (!localStorage.getItem("cs-theme")) {
          applyTheme(e.matches ? "dark" : "light");
        }
      });
    }
  }

  global.CSUtils = { $, $$, el, show, hide, swap, toast, fmtTime, esc, truncate, initTheme };
})(window);
