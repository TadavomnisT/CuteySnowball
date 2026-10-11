/* api.js — fetch wrappers + SSE consumer. No deps. */
(function (global) {
  "use strict";
  const { toast } = global.CSUtils;

  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { const j = await r.json(); if (j.error) msg += ": " + j.error; } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  async function postForm(url, form) {
    const r = await fetch(url, { method: "POST", body: form });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { const j = await r.json(); if (j.error) msg += ": " + j.error; } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  function download(url, filename) {
    const a = document.createElement("a");
    a.href = url;
    if (filename) a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // ---- SSE stream with auto-reconnect ----
  // Returns a controller object with .close()
  function streamEvents(runId, handlers) {
    let es = null;
    let closed = false;
    let reconnectTimer = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT = 3;
    const h = handlers || {};

    function open() {
      es = new EventSource(`/api/run/${runId}/events`);
      es.addEventListener("progress", (e) => {
        try { h.onProgress && h.onProgress(JSON.parse(e.data)); } catch (_) {}
      });
      es.addEventListener("snapshot", (e) => {
        try { h.onSnapshot && h.onSnapshot(JSON.parse(e.data)); } catch (_) {}
      });
      es.addEventListener("done", () => {
        h.onDone && h.onDone();
        if (es) es.close();
        closed = true;
      });
      es.onerror = () => {
        if (closed) return;
        try { es && es.close(); } catch (_) {}
        if (reconnectAttempts < MAX_RECONNECT) {
          reconnectAttempts++;
          if (!reconnectTimer) {
            reconnectTimer = setTimeout(() => {
              reconnectTimer = null;
              if (!closed) open();
            }, 2000);
          }
        } else {
          closed = true;
          h.onDone && h.onDone();
        }
      };
    }
    open();

    return {
      close() {
        closed = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        try { es && es.close(); } catch (_) {}
      },
    };
  }

  global.CSApi = { getJSON, postJSON, postForm, download, streamEvents };
})(window);
