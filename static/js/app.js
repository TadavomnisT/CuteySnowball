/* app.js — CuteySnowball SPA controller. No deps. */
(function () {
  "use strict";
  const { $, $$, el, show, hide, swap, toast, fmtTime, esc, truncate } = window.CSUtils;
  const api = window.CSApi;

  // ---- app state ----
  const S = {
    mode: null,            // "paper" | "keyword"
    runId: null,
    stream: null,
    run: null,             // last loaded run snapshot
    selectedSeeds: new Set(),  // for keyword picker
    searchResults: [],
    filter: { minRel: 0, yearFrom: null, yearTo: null, text: "", seeds: true, included: true, excluded: false },
  };

  // ============================================================
  // nav
  // ============================================================
  function wireNav() {
    $("#nav-new").addEventListener("click", goHome);
    $("#nav-runs").addEventListener("click", goRuns);
    $("#nav-help").addEventListener("click", () => swap("view-help"));
    $("#nav-settings").addEventListener("click", goSettings);
    $("#nav-compare").addEventListener("click", goCompare);
    const burger = $("#nav-burger");
    if (burger) {
      burger.addEventListener("click", () => {
        const nav = burger.parentElement;
        nav.classList.toggle("expanded");
      });
    }
    $("#card-paper").addEventListener("click", () => showForm("paper"));
    $("#card-keyword").addEventListener("click", () => showForm("keyword"));
    $$("#form-paper [data-back], #form-keyword [data-back]").forEach((b) =>
      b.addEventListener("click", goHome)
    );
    $("#form-paper").addEventListener("submit", (e) => { e.preventDefault(); startPaperRun(); });
    $("#form-keyword").addEventListener("submit", (e) => { e.preventDefault(); startKeywordRun(); });
    $("#search-requery").addEventListener("click", () => { swap("view-home"); showForm("keyword"); });
    $("#search-back").addEventListener("click", () => { swap("view-home"); showForm("keyword"); });
    $("#search-snowball").addEventListener("click", startKeywordSnowball);
    $("#search-box").addEventListener("input", renderSearchResults);
    $("#run-stop").addEventListener("click", stopRun);

    // results tabs
    $$(".tab[data-tab]").forEach((t) =>
      t.addEventListener("click", () => switchTab(t.dataset.tab))
    );
    // export buttons
    $$(".tab.export").forEach((b) =>
      b.addEventListener("click", () => exportData(b.dataset.export))
    );
    // filters
    $("#filter-rel").addEventListener("input", (e) => {
      S.filter.minRel = parseFloat(e.target.value);
      $("#filter-rel-out").textContent = S.filter.minRel.toFixed(2);
      renderAll();
    });
    $("#filter-year-from").addEventListener("input", (e) => { S.filter.yearFrom = e.target.value ? +e.target.value : null; renderAll(); });
    $("#filter-year-to").addEventListener("input", (e) => { S.filter.yearTo = e.target.value ? +e.target.value : null; renderAll(); });
    $("#filter-text").addEventListener("input", (e) => { S.filter.text = e.target.value.toLowerCase(); renderAll(); });
    $("#filter-seeds").addEventListener("change", (e) => { S.filter.seeds = e.target.checked; renderAll(); });
    $("#filter-included").addEventListener("change", (e) => { S.filter.included = e.target.checked; renderAll(); });
    $("#filter-excluded").addEventListener("change", (e) => { S.filter.excluded = e.target.checked; renderAll(); });

    // graph options
    $("#graph-fit").addEventListener("click", () => window.CSGraph.fit());
    $("#graph-relayout").addEventListener("click", () => window.CSGraph.relayout());
    const gl = $("#graph-layout");
    if (gl) gl.addEventListener("change", (e) => window.CSGraph.setLayout(e.target.value));
    const ges = $("#graph-export-svg");
    if (ges) ges.addEventListener("click", () => exportGraphSVG());
    const gep = $("#graph-export-png");
    if (gep) gep.addEventListener("click", () => exportGraphPNG());
    const gs2 = $("#graph-straight");
    if (gs2) gs2.addEventListener("change", (e) => window.CSGraph.setOption("straight", e.target.checked));
    const gsz = $("#graph-size");
    if (gsz) gsz.addEventListener("change", (e) => window.CSGraph.setOption("sizeMode", e.target.value));
    $("#graph-abstracts").addEventListener("change", (e) => window.CSGraph.setOption("abstracts", e.target.checked));
    $("#graph-forward").addEventListener("change", (e) => window.CSGraph.setOption("forward", e.target.checked));
    $("#graph-backward").addEventListener("change", (e) => window.CSGraph.setOption("backward", e.target.checked));
    $("#graph-grid").addEventListener("change", (e) => window.CSGraph.setOption("grid", e.target.checked));
    $("#graph-drag").addEventListener("change", (e) => window.CSGraph.setOption("drag", e.target.checked));
    $("#graph-select").addEventListener("change", (e) => window.CSGraph.setSelectMode(e.target.checked));
    const gs = $("#graph-search");
    if (gs) gs.addEventListener("input", (e) => window.CSGraph.setSearch(e.target.value));
    // year brush
    const yf = $("#year-from"), yt = $("#year-to");
    const applyYear = () => window.CSGraph.setYearRange(yf.value, yt.value);
    if (yf) yf.addEventListener("input", applyYear);
    if (yt) yt.addEventListener("input", applyYear);
    const ybc = $("#year-brush-clear");
    if (ybc) ybc.addEventListener("click", () => { yf.value = ""; yt.value = ""; applyYear(); });
    // resume button
    const rb = $("#run-resume");
    if (rb) rb.addEventListener("click", resumeRun);

    // ranked abstracts toggle
    const ra = $("#ranked-abstracts");
    if (ra) ra.addEventListener("change", (e) => {
      const ol = $("#ranked-list");
      if (ol) ol.classList.toggle("show-abs", e.target.checked);
      // save to localStorage
      try { localStorage.setItem("cs-ranked-abs", e.target.checked ? "1" : "0"); } catch (_) {}
    });
    try { if (localStorage.getItem("cs-ranked-abs") === "1") { ra.checked = true; } } catch (_) {}

    // detail panel close
    $("#detail-close").addEventListener("click", closeDetail);
    $("#detail-backdrop").addEventListener("click", closeDetail);

    // PDF dropzone
    const dz = $("#paper-dropzone");
    const fileInput = $("#paper-pdfs");
    dz.addEventListener("click", () => fileInput.click());
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("drag");
      fileInput.files = e.dataTransfer.files;
    });

    // weight sliders — show output + persist
    $$(".weights-grid").forEach((wg) => {
      const which = wg.dataset.wg;  // "paper" or "keyword"
      wg.querySelectorAll("input.wg").forEach((inp) => {
        const out = inp.parentElement.querySelector("output");
        inp.addEventListener("input", () => {
          if (out) out.textContent = parseFloat(inp.value).toFixed(2);
          // persist
          try {
            const key = "cs-weights-" + which;
            const obj = JSON.parse(localStorage.getItem(key) || "{}");
            obj[inp.dataset.w] = parseFloat(inp.value);
            localStorage.setItem(key, JSON.stringify(obj));
          } catch (_) {}
        });
      });
      // restore from localStorage
      try {
        const obj = JSON.parse(localStorage.getItem("cs-weights-" + which) || "{}");
        wg.querySelectorAll("input.wg").forEach((inp) => {
          if (obj[inp.dataset.w] != null) {
            inp.value = obj[inp.dataset.w];
            const out = inp.parentElement.querySelector("output");
            if (out) out.textContent = parseFloat(inp.value).toFixed(2);
          }
        });
      } catch (_) {}
    });

    // graph focus → open detail panel
    document.addEventListener("cs:graph-focus", (e) => {
      openDetail(e.detail);
    });

    // graph box-select → bulk export
    document.addEventListener("cs:graph-export-selection", (e) => {
      const { keys, format } = e.detail || {};
      if (keys && keys.length) {
        S.bulkSelected = new Set(keys);
        bulkExport(format);
      }
    });

    // keyboard shortcuts
    document.addEventListener("keydown", (e) => {
      // ignore when typing in an input/textarea
      const tag = (e.target.tagName || "").toLowerCase();
      const isText = tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable;
      if (e.key === "Escape") {
        if (!closeCheatsheet()) closeDetail();
        return;
      }
      if (isText) return;
      if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
        e.preventDefault();
        toggleCheatsheet();
        return;
      }
      if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const f = $("#filter-text"); if (f) { f.focus(); }
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const map = { g: "graph", r: "ranked", s: "stats", t: "tree", b: "table" };
      if (map[e.key]) {
        // only switch if results visible
        if (!document.getElementById("run-results").classList.contains("hidden")) {
          switchTab(map[e.key]);
        }
      }
      if (e.key === "n") { goHome(); }
      if (e.key === "c") { goCompare(); }
      // 'a' to annotate the focused ranked paper
      if (e.key === "a" && !document.getElementById("run-results").classList.contains("hidden")) {
        const panelRanked = document.getElementById("panel-ranked");
        if (panelRanked && panelRanked.classList.contains("active")) {
          const focused = document.querySelector("#ranked-list li.focused");
          if (focused) {
            // open detail then click the annotation button
            focused.click();
            setTimeout(() => {
              const annBtn = document.querySelector("#detail-body .ann-btn");
              if (annBtn) annBtn.click();
            }, 1500);
          }
        }
      }
      // number keys 1-5: jump to top-N ranked papers (open detail)
      if (e.key >= "1" && e.key <= "5" && !document.getElementById("run-results").classList.contains("hidden")) {
        const panelRanked = document.getElementById("panel-ranked");
        if (!panelRanked || !panelRanked.classList.contains("active")) return;
        e.preventDefault();
        const items = document.querySelectorAll("#ranked-list li:not(.empty-state)");
        const idx = parseInt(e.key, 10) - 1;
        if (idx < items.length) items[idx].click();
      }
      // vim-style j/k nav (same as arrow down/up)
      if ((e.key === "j" || e.key === "k") && !document.getElementById("run-results").classList.contains("hidden")) {
        const panelRanked = document.getElementById("panel-ranked");
        if (!panelRanked || !panelRanked.classList.contains("active")) return;
        e.preventDefault();
        const items = Array.from(document.querySelectorAll("#ranked-list li"));
        if (!items.length) return;
        let idx = items.findIndex((li) => li.classList.contains("focused"));
        if (idx === -1) {
          idx = e.key === "j" ? 0 : items.length - 1;
        } else {
          items[idx].classList.remove("focused");
          idx = e.key === "j" ? Math.min(items.length - 1, idx + 1) : Math.max(0, idx - 1);
        }
        items[idx].classList.add("focused");
        items[idx].scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      // arrow-key navigation in ranked list
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !document.getElementById("run-results").classList.contains("hidden")) {
        const panelRanked = document.getElementById("panel-ranked");
        if (!panelRanked || !panelRanked.classList.contains("active")) return;
        e.preventDefault();
        const items = Array.from(document.querySelectorAll("#ranked-list li"));
        if (!items.length) return;
        let idx = items.findIndex((li) => li.classList.contains("focused"));
        if (idx === -1) {
          idx = e.key === "ArrowDown" ? 0 : items.length - 1;
        } else {
          items[idx].classList.remove("focused");
          idx = e.key === "ArrowDown" ? Math.min(items.length - 1, idx + 1) : Math.max(0, idx - 1);
        }
        items[idx].classList.add("focused");
        items[idx].scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      // Enter opens the focused ranked item's detail
      if (e.key === "Enter" && !document.getElementById("run-results").classList.contains("hidden")) {
        const focused = document.querySelector("#ranked-list li.focused");
        if (focused) focused.click();
      }
    });

    // persist filters
    try {
      const saved = JSON.parse(localStorage.getItem("cs-filter") || "null");
      if (saved) Object.assign(S.filter, saved);
    } catch (_) {}
  }

  function goHome() {
    swap("view-home");
    $("#form-paper").classList.add("hidden");
    $("#form-keyword").classList.add("hidden");
  }

  function showForm(which) {
    swap("view-home");
    $("#form-paper").classList.toggle("hidden", which !== "paper");
    $("#form-keyword").classList.toggle("hidden", which !== "keyword");
    if (which === "paper") $("#form-paper").scrollIntoView({ behavior: "smooth", block: "nearest" });
    else $("#form-keyword").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ============================================================
  // sources panel
  // ============================================================
  async function loadSources() {
    const list = $("#sources-list");
    list.innerHTML = "<span class='muted'>loading…</span>";
    try {
      const [cfg, srcs] = await Promise.all([api.getJSON("/api/config"), api.getJSON("/api/sources")]);
      list.innerHTML = "";
      const enabled = cfg.sources;
      const healthMap = {};
      (srcs || []).forEach((s) => (healthMap[s.name] = s.healthy));
      for (const [name, on] of Object.entries(enabled)) {
        const healthy = healthMap[name];
        const chip = el("span", {
          class: "source-chip " + (on ? (healthy ? "ok" : "off") : "off"),
          title: name + (on ? (healthy ? " (healthy)" : " (unavailable)") : " (disabled)"),
        });
        chip.appendChild(el("span", { class: "dot" }));
        chip.appendChild(document.createTextNode(name));
        list.appendChild(chip);
      }
    } catch (e) {
      list.innerHTML = "<span class='muted'>could not load sources</span>";
    }
  }

  // ============================================================
  // start a run — paper mode
  // ============================================================
  async function startPaperRun() {
    const dois = $("#paper-dois").value.trim();
    const files = $("#paper-pdfs").files;
    const seeds = dois.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!seeds.length && !files.length) {
      toast("Add at least one DOI or PDF.");
      return;
    }
    // duplicate detection (only for DOI seeds, not PDFs)
    if (seeds.length && !files.length) {
      const shown = await checkDuplicate(seeds, []);
      if (shown) return; // user chose to view the existing run
    }
    const options = collectOptions("paper");
    const fd = new FormData();
    fd.append("mode", "paper");
    fd.append("dois", seeds.join("\n"));
    fd.append("options", JSON.stringify(options));
    for (let i = 0; i < files.length; i++) fd.append("pdfs", files[i]);
    await launchRun(fd);
  }

  async function checkDuplicate(seeds, keywords) {
    try {
      const r = await api.postJSON("/api/check-duplicate", { seeds, keywords });
      if (!r.duplicate) return false;
      // show a warning with the matching runs
      const form = $("#form-paper");
      // remove any existing warning
      const old = form.querySelector(".dup-warning");
      if (old) old.remove();
      const warn = el("div", { class: "dup-warning" });
      warn.appendChild(el("span", { class: "dup-icon" }, "⚠️"));
      const body = el("div", { class: "dup-body" });
      body.appendChild(el("div", {}, el("strong", {}, "Similar run found!"), document.createTextNode(" You may be duplicating an existing snowball. View it or start anyway:")));
      (r.matches || []).forEach((m) => {
        const chip = el("span", { class: "dup-match", title: "click to open this run" });
        chip.appendChild(el("span", { class: "stat" }, m.run_id.slice(0, 8)));
        chip.appendChild(document.createTextNode(` · ${m.paper_count || 0} papers · ${m.overlap ? m.overlap.join(", ") : m.keyword_match || ""}`));
        chip.addEventListener("click", () => {
          S.runId = m.run_id;
          loadResults(m.run_id);
          swap("view-run");
          warn.remove();
        });
        body.appendChild(chip);
      });
      const actions = el("div", { class: "dup-actions" });
      const proceed = el("button", { class: "btn primary tiny" }, "Start anyway ▸");
      proceed.addEventListener("click", () => {
        warn.remove();
        // actually launch the run now
        const options = collectOptions("paper");
        const fd = new FormData();
        fd.append("mode", "paper");
        fd.append("dois", seeds.join("\n"));
        fd.append("options", JSON.stringify(options));
        launchRun(fd);
      });
      const cancel = el("button", { class: "btn ghost tiny" }, "Cancel");
      cancel.addEventListener("click", () => warn.remove());
      actions.appendChild(proceed);
      actions.appendChild(cancel);
      body.appendChild(actions);
      warn.appendChild(body);
      form.insertBefore(warn, form.querySelector(".form-actions"));
      return true;
    } catch (e) {
      // if duplicate check fails, just proceed
      return false;
    }
  }

  // ============================================================
  // start a run — keyword mode (search first)
  // ============================================================
  async function startKeywordRun() {
    const q = $("#kw-input").value.trim();
    if (!q) { toast("Enter keywords first."); return; }
    swap("view-search");
    $("#search-results").innerHTML = "<li class='muted'>searching…</li>";
    $("#search-box").value = "";
    S.selectedSeeds.clear();
    try {
      const r = await api.postJSON("/api/search", { query: q, limit: 15 });
      S.searchResults = (r && r.results) || [];
      renderSearchResults();
    } catch (e) {
      $("#search-results").innerHTML = `<li class='muted'>search failed: ${esc(e.message)}</li>`;
    }
  }

  function renderSearchResults() {
    const ul = $("#search-results");
    const q = $("#search-box").value.toLowerCase().trim();
    ul.innerHTML = "";
    const items = S.searchResults.filter((p) => {
      if (!q) return true;
      const blob = ((p.title || "") + " " + (p.authors || "") + " " + (p.doi || "")).toLowerCase();
      return blob.includes(q);
    });
    if (!items.length) { ul.innerHTML = "<li class='muted'>no results</li>"; updateSearchCount(); return; }
    for (const p of items) {
      const li = el("li");
      const id = p.key || ("doi:" + p.doi) || ("t:" + p.title);
      const chk = el("input", { type: "checkbox", "data-id": id });
      chk.checked = S.selectedSeeds.has(id);
      chk.addEventListener("change", () => {
        if (chk.checked) S.selectedSeeds.add(id);
        else S.selectedSeeds.delete(id);
        updateSearchCount();
      });
      const body = el("div", { class: "r-body", style: "flex:1;min-width:0" });
      body.appendChild(el("div", { class: "r-title" }, p.title || "(untitled)"));
      const meta = el("div", { class: "r-meta" });
      meta.textContent =
        (p.authors ? truncate(p.authors, 60) + " · " : "") +
        (p.year || "—") + " · " +
        (p.num_citations || 0) + " cites" +
        (p.doi ? " · " + p.doi : "");
      body.appendChild(meta);
      if (p.abstract) body.appendChild(el("div", { class: "r-src", style: "color:var(--ink-soft);font-size:0.8rem;margin-top:4px" }, truncate(p.abstract, 160)));
      const src = el("div", { class: "r-src" }, (p.sources || []).join(", "));
      li.appendChild(chk);
      li.appendChild(body);
      li.appendChild(src);
      ul.appendChild(li);
    }
    updateSearchCount();
  }

  function updateSearchCount() {
    const n = S.selectedSeeds.size;
    $("#search-count").textContent = n + " selected";
    $("#search-snowball").disabled = n === 0;
  }

  async function startKeywordSnowball() {
    const seeds = S.searchResults.filter((p) => {
      const id = p.key || ("doi:" + p.doi) || ("t:" + p.title);
      return S.selectedSeeds.has(id);
    }).map((p) => p.doi || p.title);
    if (!seeds.length) { toast("Select at least one seed."); return; }
    const options = collectOptions("keyword");
    const fd = new FormData();
    fd.append("mode", "paper");  // we already resolved the seeds; treat as paper mode
    fd.append("dois", seeds.join("\n"));
    fd.append("keywords", $("#kw-input").value);
    fd.append("options", JSON.stringify(options));
    await launchRun(fd);
  }

  function collectOptions(prefix) {
    const opt = {
      max_iterations: +($("#" + (prefix === "paper" ? "opt-max-iter" : "opt-kw-max-iter")).value),
      min_relevance: parseFloat($("#" + (prefix === "paper" ? "opt-min-rel" : "opt-kw-min-rel")).value),
      per_round_cap: +($("#" + (prefix === "paper" ? "opt-per-round" : "opt-kw-per-round")).value),
      max_total_papers: +($("#opt-max-total").value),
      keyword_top_n: prefix === "keyword" ? +$("#opt-kw-topn").value : 8,
      direction: $("#" + (prefix === "paper" ? "opt-direction" : "opt-kw-direction")).value || "both",
    };
    // collect relevance weights from the matching weights-grid
    const wg = document.querySelector(`.weights-grid[data-wg="${prefix}"]`);
    if (wg) {
      const weights = {};
      wg.querySelectorAll("input.wg").forEach((inp) => {
        weights[inp.dataset.w] = parseFloat(inp.value);
      });
      // only send if any non-zero (avoid sending all-defaults)
      const sum = Object.values(weights).reduce((a, b) => a + b, 0);
      if (sum > 0) opt.weights = weights;
    }
    return opt;
  }

  // ============================================================
  // launch + stream a run
  // ============================================================
  async function launchRun(fd) {
    swap("view-run");
    $("#run-progress").classList.remove("hidden");
    $("#run-results").classList.add("hidden");
    $("#progress-feed").innerHTML = "";
    $("#progress-fill").style.width = "0%";
    updatePhase("identification", 0);
    updatePhase("screening", 0);
    updatePhase("eligibility", 0);
    updatePhase("included", 0);
    try {
      const r = await api.postForm("/api/run", fd);
      S.runId = r.run_id;
      streamRun(r.run_id);
    } catch (e) {
      addFeed("error", "Failed to start: " + e.message);
    }
  }

  function streamRun(runId) {
    if (S.stream) S.stream.close();
    let lastStats = {};
    let loaded = false;
    S.stream = api.streamEvents(runId, {
      onProgress: (ev) => {
        if (ev.msg) addFeed(ev.phase || "info", ev.msg, ev.phase === "error");
        if (ev.stats) { lastStats = ev.stats; updateStats(ev.stats); }
        // rough progress estimate
        const total = lastStats.total_papers || 0;
        const pct = Math.min(95, total * 0.6 + (ev.phase === "included" ? 10 : 0));
        $("#progress-fill").style.width = pct + "%";
        if (ev.phase) setActivePhase(ev.phase);
      },
      onSnapshot: (run) => {
        S.run = run;
      },
      onDone: () => {
        if (loaded) return;
        loaded = true;
        $("#progress-fill").style.width = "100%";
        addFeed("done", "Run finished. Loading results…");
        loadResults(runId);
      },
    });
    // ---- Polling fallback (in case SSE done event is missed/raced) ----
    const poll = async () => {
      if (loaded) return;
      try {
        const st = await api.getJSON(`/api/run/${runId}/stats`);
        if (st && (st.status === "done" || st.status === "error")) {
          if (loaded) return;
          loaded = true;
          addFeed("done", `Run ${st.status}. Loading results…`);
          loadResults(runId);
        } else if (st) {
          updateStats(st);
        }
      } catch (_) {}
    };
    const pollTimer = setInterval(() => { if (!loaded) poll(); }, 4000);
    // stop polling after 30 min regardless
    setTimeout(() => clearInterval(pollTimer), 30 * 60 * 1000);
    // store so we can clear on new run
    S._pollTimer = pollTimer;
  }

  function addFeed(phase, msg, isError) {
    const feed = $("#progress-feed");
    const li = el("li", { class: isError ? "err" : "" });
    li.appendChild(el("span", { class: "ts" }, fmtTime(Date.now() / 1000)));
    if (phase && phase !== "info") li.appendChild(el("span", { class: "ph" }, phase));
    li.appendChild(document.createTextNode(msg));
    feed.insertBefore(li, feed.firstChild);
    while (feed.children.length > 200) feed.removeChild(feed.lastChild);
  }

  function setActivePhase(phase) {
    $$(".prisma .phase").forEach((d) => d.classList.toggle("active", d.dataset.phase === phase));
  }
  function updatePhase(name, n) {
    const map = { identification: "cnt-id", screening: "cnt-sc", eligibility: "cnt-el", included: "cnt-in" };
    const el2 = $("#" + map[name]); if (el2) el2.textContent = n;
  }
  function updateStats(st) {
    updatePhase("identification", (st.seeds || 0) + (st.total_papers || 0));
    updatePhase("screening", st.total_papers || 0);
    updatePhase("eligibility", st.included || 0);
    updatePhase("included", st.included || 0);
  }

  async function stopRun() {
    if (!S.runId) return;
    try { await api.postJSON(`/api/run/${S.runId}/stop`, {}); toast("Stop signal sent."); }
    catch (e) { toast("Could not stop: " + e.message); }
  }

  // ============================================================
  // results
  // ============================================================
  async function loadResults(runId) {
    try {
      S.runId = runId;
      const run = await api.getJSON(`/api/run/${runId}`);
      S.run = run;
      // show Resume button if the run was stopped/errored (not a clean done)
      const rb = $("#run-resume");
      if (rb) {
        if (run.status === "error" || (run.stats && run.stats.phase === "eligibility" && run.status !== "done")) {
          rb.classList.remove("hidden");
        } else {
          rb.classList.add("hidden");
        }
      }
      $("#run-progress").classList.add("hidden");
      $("#run-results").classList.remove("hidden");
      $("#results-title").textContent = `Snowball corpus — ${run.paper_count} papers, ${run.edge_count} edges`;
      // render tags row
      renderTagsRow(run.tags || []);
      updateStats(run.stats || {});
      renderAll();
    } catch (e) {
      addFeed("error", "Failed to load results: " + e.message);
    }
  }

  function renderTagsRow(tags) {
    let row = document.querySelector(".results-header .tags-row");
    if (!row) {
      row = el("div", { class: "tags-row" });
      const header = document.querySelector(".results-header");
      if (header) header.appendChild(row);
    }
    row.innerHTML = "";
    (tags || []).forEach((t) => {
      const chip = el("span", { class: "tag-chip" }, t);
      const x = el("span", { class: "x", title: "remove tag" }, "✕");
      x.addEventListener("click", async (e) => {
        e.stopPropagation();
        const newTags = (S.run.tags || []).filter((x2) => x2 !== t);
        try {
          const r = await api.postJSON(`/api/run/${S.runId}/tags`, { tags: newTags });
          S.run.tags = r.tags || [];
          renderTagsRow(S.run.tags);
        } catch (err) { toast("Tag update failed: " + err.message); }
      });
      chip.appendChild(x);
      row.appendChild(chip);
    });
    const input = el("input", { type: "text", class: "tag-input", placeholder: "+ add tag", maxlength: 30 });
    input.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        const val = input.value.trim().toLowerCase();
        if (val && !(S.run.tags || []).includes(val)) {
          const newTags = [...(S.run.tags || []), val];
          try {
            const r = await api.postJSON(`/api/run/${S.runId}/tags`, { tags: newTags });
            S.run.tags = r.tags || [];
            renderTagsRow(S.run.tags);
            input.value = "";
          } catch (err) { toast("Tag update failed: " + err.message); }
        }
      }
    });
    row.appendChild(input);
  }

  function filteredPapers() {
    if (!S.run) return [];
    const f = S.filter;
    return S.run.papers.filter((p) => {
      if (p.relevance < f.minRel) return false;
      if (f.yearFrom && (!p.year || p.year < f.yearFrom)) return false;
      if (f.yearTo && (!p.year || p.year > f.yearTo)) return false;
      if (f.text) {
        const blob = ((p.title || "") + " " + (p.authors || "") + " " + (p.doi || "")).toLowerCase();
        if (!blob.includes(f.text)) return false;
      }
      if (p.seed) return f.seeds;
      if (p.included) return f.included;
      return f.excluded;
    });
  }

  function renderAll() {
    if (!S.run) return;
    const papers = filteredPapers();
    const keyset = new Set(papers.map((p) => p.key));
    const edges = (S.run.edges || []).filter((e) => keyset.has(e.source) && keyset.has(e.target));
    // persist filter
    try { localStorage.setItem("cs-filter", JSON.stringify(S.filter)); } catch (_) {}
    // graph
    window.CSGraph.init("graph-svg");
    window.CSGraph.setData(papers, edges);
    renderRanked(papers);
    renderTree(papers, edges);
    renderTable(papers);
    renderStats(papers, edges);
    // update count display
    const rc = $("#ranked-count");
    if (rc) rc.textContent = papers.length + " papers";
  }

  function avatarText(p) {
    let a = (p.authors || "").split(/[;,]/)[0].trim();
    if (!a) return "?";
    // "Family, Given" -> "FG"; "Given Family" -> "GF"
    if (a.includes(",")) {
      const [f, g] = a.split(",").map((s) => s.trim());
      return ((g[0] || "") + (f[0] || "")).toUpperCase() || a[0].toUpperCase();
    }
    return a[0].toUpperCase();
  }

  function renderRanked(papers) {
    const ul = $("#ranked-list");
    ul.innerHTML = "";
    const sorted = papers.slice().sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
    let i = 0;
    for (const p of sorted) {
      i++;
      const li = el("li");
      li.setAttribute("data-key", p.key);
      li.addEventListener("click", () => openDetail(p));
      const ava = el("div", { class: "rank-ava", title: p.authors || "" }, avatarText(p));
      const num = el("span", { class: "rank-num" }, String(i));
      const body = el("div", { class: "rank-body" });
      body.appendChild(el("div", { class: "rank-title" }, p.title || "(untitled)"));
      const meta = el("div", { class: "rank-meta" });
      meta.textContent =
        (p.authors ? truncate(p.authors, 80) + " · " : "") +
        (p.year || "—") + " · " +
        (p.num_citations || 0) + " cites · depth " + (p.depth || 0) +
        (p.doi ? " · " + p.doi : "") +
        " · " + (p.sources || []).join(", ");
      body.appendChild(meta);
      if (p.abstract) {
        body.appendChild(el("div", { class: "rank-abs toggle" }, truncate(p.abstract, 220)));
      }
      // relevance bar
      const barWrap = el("div", { class: "rel-bar", title: "relevance " + (p.relevance || 0).toFixed(3) });
      const bar = el("div");
      bar.style.width = Math.round((p.relevance || 0) * 100) + "%";
      barWrap.appendChild(bar);
      body.appendChild(barWrap);
      const rel = el("div", { class: "rank-rel" });
      rel.appendChild(el("div", { class: "val" }, ((p.relevance || 0)).toFixed(2)));
      rel.appendChild(el("div", { class: "lbl" }, p.seed ? "seed" : "rel"));
      li.appendChild(ava);
      li.appendChild(num);
      li.appendChild(body);
      li.appendChild(rel);
      ul.appendChild(li);
    }
    if (!sorted.length) ul.innerHTML = "<li class='empty-state'><span class='emoji'>📭</span><span class='title'>No papers match the filter</span>Adjust the relevance/year/text filters above.</li>";
  }

  // ============================================================
  // stats dashboard
  // ============================================================
  function renderStats(papers, edges) {
    const grid = $("#stats-grid");
    if (!grid) return;
    grid.innerHTML = "";
    if (!papers.length) {
      grid.innerHTML = "<div class='stat-empty'>No papers to summarise. Run a snowball first.</div>";
      return;
    }
    // batch-summary panel (only if there are papers with abstracts)
    const withAbs = papers.filter((p) => p.abstract && p.abstract.length > 40);
    if (withAbs.length > 0) {
      const bs = el("div", { class: "batch-summary" });
      bs.appendChild(el("h4", {}, "✨ Batch AI summaries"));
      const btn = el("button", { class: "btn primary tiny" }, `Summarise top ${Math.min(20, withAbs.length)} papers`);
      btn.addEventListener("click", () => runBatchSummary(bs, Math.min(20, withAbs.length)));
      bs.appendChild(btn);
      const hint = el("span", { class: "muted", style: "font-size:0.78rem;margin-left:8px" }, `(uses z-ai CLI; ~3s per paper)`);
      bs.appendChild(hint);
      grid.appendChild(bs);
    }
    // big stats
    const total = papers.length;
    const seeds = papers.filter((p) => p.seed).length;
    const included = papers.filter((p) => p.included).length;
    const years = papers.map((p) => p.year).filter((y) => y);
    const ymin = years.length ? Math.min(...years) : null;
    const ymax = years.length ? Math.max(...years) : null;
    const avgRel = total ? (papers.reduce((s, p) => s + (p.relevance || 0), 0) / total) : 0;
    const totalCites = papers.reduce((s, p) => s + (p.num_citations || 0), 0);

    // card 1: overview
    const c1 = el("div", { class: "stat-card" });
    c1.appendChild(el("h4", {}, "Overview"));
    const big = el("div", { class: "stat-big" });
    const mkStat = (v, l) => { const s = el("div", { class: "stat" }); s.appendChild(el("div", { class: "v" }, String(v))); s.appendChild(el("div", { class: "l" }, l)); return s; };
    big.appendChild(mkStat(total, "Papers"));
    big.appendChild(mkStat(seeds, "Seeds"));
    big.appendChild(mkStat(included, "Included"));
    big.appendChild(mkStat(avgRel.toFixed(2), "Avg rel"));
    big.appendChild(mkStat(edges.length, "Edges"));
    big.appendChild(mkStat(totalCites, "Total cites"));
    c1.appendChild(big);
    if (ymin && ymax) c1.appendChild(el("div", { class: "muted", style: "font-size:0.82rem" }, `Year range: ${ymin}–${ymax}`));
    grid.appendChild(c1);

    // card 2: papers by year (mini bar chart)
    const byYear = {};
    papers.forEach((p) => { if (p.year) byYear[p.year] = (byYear[p.year] || 0) + 1; });
    const yrKeys = Object.keys(byYear).sort();
    const c2 = el("div", { class: "stat-card" });
    c2.appendChild(el("h4", {}, "Papers by year"));
    if (yrKeys.length) {
      const maxC = Math.max(...Object.values(byYear));
      const bars = el("div", { class: "stat-bars stat-bars-wrap" });
      // limit to ~24 bars max
      const step = yrKeys.length > 24 ? Math.ceil(yrKeys.length / 24) : 1;
      for (let i = 0; i < yrKeys.length; i += step) {
        const yk = yrKeys[i];
        const cnt = byYear[yk];
        const b = el("div", { class: "bar", "data-year": yk, title: `${yk}: ${cnt} papers` });
        b.style.height = Math.round((cnt / maxC) * 100) + "%";
        bars.appendChild(b);
      }
      c2.appendChild(bars);
    } else {
      c2.appendChild(el("div", { class: "stat-empty" }, "no year data"));
    }
    grid.appendChild(c2);

    // card 3: relevance distribution (histogram, 10 bins)
    const c3 = el("div", { class: "stat-card" });
    c3.appendChild(el("h4", {}, "Relevance distribution"));
    const bins = new Array(10).fill(0);
    papers.forEach((p) => {
      const r = Math.max(0, Math.min(0.999, p.relevance || 0));
      bins[Math.floor(r * 10)]++;
    });
    const maxBin = Math.max(...bins, 1);
    const histo = el("div", { class: "stat-histo" });
    bins.forEach((cnt, idx) => {
      const h = el("div", { class: "h", title: `${(idx / 10).toFixed(1)}–${((idx + 1) / 10).toFixed(1)}: ${cnt} papers` });
      h.style.height = Math.round((cnt / maxBin) * 100) + "%";
      histo.appendChild(h);
    });
    c3.appendChild(histo);
    c3.appendChild(el("div", { class: "muted", style: "font-size:0.72rem;margin-top:6px" }, "0.0 → 1.0"));
    grid.appendChild(c3);

    // card 4: top venues
    const byVenue = {};
    papers.forEach((p) => { if (p.venue) byVenue[p.venue] = (byVenue[p.venue] || 0) + 1; });
    const venueArr = Object.entries(byVenue).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const c4 = el("div", { class: "stat-card" });
    c4.appendChild(el("h4", {}, "Top venues"));
    if (venueArr.length) {
      const ul2 = el("ul", { class: "stat-list" });
      venueArr.forEach(([v, c]) => {
        const li = el("li");
        li.appendChild(el("span", { class: "nm", title: v }, truncate(v, 36)));
        li.appendChild(el("span", { class: "cnt" }, String(c)));
        ul2.appendChild(li);
      });
      c4.appendChild(ul2);
    } else {
      c4.appendChild(el("div", { class: "stat-empty" }, "no venue data"));
    }
    grid.appendChild(c4);

    // card 5: source coverage
    const bySrc = {};
    papers.forEach((p) => (p.sources || []).forEach((s) => { bySrc[s] = (bySrc[s] || 0) + 1; }));
    const srcColors = { openalex: "#d97757", semantic_scholar: "#6b8e7f", crossref: "#c89b3c", opencitations: "#8a857c", scholarly: "#c0504d", scholar_scrape: "#7b6cb0", pdf: "#5c5a55" };
    const c5 = el("div", { class: "stat-card" });
    c5.appendChild(el("h4", {}, "Source coverage"));
    if (Object.keys(bySrc).length) {
      const pie = el("div", { class: "stat-pie" });
      Object.entries(bySrc).sort((a, b) => b[1] - a[1]).forEach(([s, c]) => {
        const seg = el("span", { class: "seg" });
        const sw = el("span", { class: "sw" });
        sw.style.background = srcColors[s] || "#999";
        seg.appendChild(sw);
        seg.appendChild(document.createTextNode(`${s} (${c})`));
        pie.appendChild(seg);
      });
      c5.appendChild(pie);
    } else {
      c5.appendChild(el("div", { class: "stat-empty" }, "no source data"));
    }
    grid.appendChild(c5);

    // card 6: depth distribution
    const byDepth = {};
    papers.forEach((p) => { const d = p.depth || 0; byDepth[d] = (byDepth[d] || 0) + 1; });
    const c6 = el("div", { class: "stat-card" });
    c6.appendChild(el("h4", {}, "Snowball depth"));
    const dKeys = Object.keys(byDepth).sort();
    if (dKeys.length) {
      const maxD = Math.max(...Object.values(byDepth));
      const bars = el("div", { class: "stat-bars stat-bars-wrap" });
      dKeys.forEach((d) => {
        const cnt = byDepth[d];
        const b = el("div", { class: "bar", "data-year": "d=" + d, title: `depth ${d}: ${cnt} papers` });
        b.style.height = Math.round((cnt / maxD) * 100) + "%";
        bars.appendChild(b);
      });
      c6.appendChild(bars);
    } else {
      c6.appendChild(el("div", { class: "stat-empty" }, "no depth data"));
    }
    grid.appendChild(c6);

    // card 7: per-source contribution stacked bar
    const c7 = el("div", { class: "stat-card" });
    c7.appendChild(el("h4", {}, "Per-source contribution"));
    if (Object.keys(bySrc).length) {
      const total = Object.values(bySrc).reduce((a, b) => a + b, 0);
      const stacked = el("div", { class: "stat-stacked", title: "share of papers found by each source" });
      Object.entries(bySrc).sort((a, b) => b[1] - a[1]).forEach(([s, c]) => {
        const pct = (c / total) * 100;
        const seg = el("div", { class: "seg", title: `${s}: ${c} papers (${pct.toFixed(1)}%)`, style: `flex: ${pct}; background: ${srcColors[s] || "#999"};` });
        if (pct > 8) seg.textContent = s.slice(0, 6);
        stacked.appendChild(seg);
      });
      c7.appendChild(stacked);
      // legend below
      const legend = el("div", { class: "stat-pie" });
      Object.entries(bySrc).sort((a, b) => b[1] - a[1]).forEach(([s, c]) => {
        const seg = el("span", { class: "seg" });
        const sw = el("span", { class: "sw" });
        sw.style.background = srcColors[s] || "#999";
        seg.appendChild(sw);
        seg.appendChild(document.createTextNode(`${s} ${((c / total) * 100).toFixed(0)}%`));
        legend.appendChild(seg);
      });
      c7.appendChild(legend);
    } else {
      c7.appendChild(el("div", { class: "stat-empty" }, "no source data"));
    }
    grid.appendChild(c7);

    // card 8: per-round contribution
    const byRound = {};
    papers.forEach((p) => { const r = p.discovered_round || 0; byRound[r] = (byRound[r] || 0) + 1; });
    const c8 = el("div", { class: "stat-card" });
    c8.appendChild(el("h4", {}, "Papers per round"));
    const rKeys = Object.keys(byRound).sort((a, b) => +a - +b);
    if (rKeys.length) {
      const maxR = Math.max(...Object.values(byRound));
      const rbs = el("div", { class: "stat-roundbars" });
      const roundColors = ["#d97757", "#6b8e7f", "#c89b3c", "#8a857c", "#c0504d", "#7b6cb0"];
      rKeys.forEach((r) => {
        const cnt = byRound[r];
        const row = el("div", { class: "rb" });
        row.appendChild(el("span", { class: "lbl" }, r === "0" ? "seed" : "r" + r));
        const bw = el("div", { class: "bar-wrap" });
        const b = el("div", { class: "b", style: `width: ${(cnt / maxR) * 100}%; background: ${roundColors[+r % roundColors.length]};` });
        bw.appendChild(b);
        row.appendChild(bw);
        row.appendChild(el("span", { class: "cnt" }, String(cnt)));
        rbs.appendChild(row);
      });
      c8.appendChild(rbs);
    } else {
      c8.appendChild(el("div", { class: "stat-empty" }, "no round data"));
    }
    grid.appendChild(c8);

    // card 9: corpus growth timeline (async)
    if (S.runId) {
      const c9 = el("div", { class: "stat-card" });
      c9.appendChild(el("h4", {}, "Corpus growth timeline"));
      c9.appendChild(el("div", { class: "muted", style: "font-size:0.82rem" }, "loading…"));
      grid.appendChild(c9);
      // fetch timeline data
      api.getJSON(`/api/run/${S.runId}/timeline`).then((d) => {
        c9.innerHTML = "";
        c9.appendChild(el("h4", {}, "Corpus growth timeline"));
        if (!d.papers || !d.papers.length) {
          c9.appendChild(el("div", { class: "stat-empty" }, "no timeline data"));
          return;
        }
        const maxNew = Math.max(...d.papers.map((t) => t.new));
        const tl = el("div", { class: "stat-timeline" });
        d.papers.forEach((t) => {
          const bar = el("div", { class: "tl-bar", title: `Round ${t.round}: +${t.new} papers(s), total: ${t.cumulative}` });
          bar.appendChild(el("div", { class: "cnt" }, String(t.new)));
          const b = el("div", { class: "bar" });
          b.style.height = Math.round((t.new / maxNew) * 80) + "%";
          bar.appendChild(b);
          bar.appendChild(el("div", { class: "lbl" }, t.round === 0 ? "seed" : "r" + t.round));
          tl.appendChild(bar);
        });
        c9.appendChild(tl);
        if (d.papers.length) {
          c9.appendChild(el("div", { class: "muted", style: "font-size:0.72rem;margin-top:4px" }, `Final: ${d.papers[d.papers.length - 1].cumulative} papers over ${d.total_rounds} rounds`));
        }
      }).catch(() => {
        c9.innerHTML = "";
        c9.appendChild(el("h4", {}, "Corpus growth timeline"));
        c9.appendChild(el("div", { class: "stat-empty" }, "could not load timeline"));
      });
    }
  }

  // ============================================================
  // batch LLM summary (stats tab)
  // ============================================================
  async function runBatchSummary(container, limit) {
    if (!S.runId) return;
    // build UI
    container.innerHTML = "";
    container.appendChild(el("h4", {}, "✨ Batch AI summaries"));
    const bar = el("div", { class: "bs-bar" });
    const fill = el("div");
    fill.style.width = "0%";
    bar.appendChild(fill);
    container.appendChild(bar);
    const status = el("div", { class: "muted", style: "font-size:0.82rem" }, "Starting…");
    container.appendChild(status);
    const results = el("div", { class: "bs-results" });
    container.appendChild(results);
    // SSE
    const es = new EventSource(`/api/run/${S.runId}/summarise-batch?limit=${limit}`);
    es.addEventListener("start", (e) => {
      try { const d = JSON.parse(e.data); status.textContent = `Summarising ${d.count} papers…`; } catch (_) {}
    });
    es.addEventListener("summary", (e) => {
      try {
        const d = JSON.parse(e.data);
        fill.style.width = Math.round((d.done / d.total) * 100) + "%";
        status.textContent = `${d.done}/${d.total} done`;
        const item = el("div", { class: "bs-item" });
        item.appendChild(el("div", { class: "title" }, truncate(d.title || "(untitled)", 70)));
        item.appendChild(el("div", { class: "sum" }, d.summary));
        results.insertBefore(item, results.firstChild);
      } catch (_) {}
    });
    es.addEventListener("error", (e) => {
      try {
        const d = JSON.parse(e.data);
        status.textContent = `Error on ${d.key?.slice(0, 20)}: ${d.error}`;
      } catch (_) { status.textContent = "Stream error"; }
    });
    es.addEventListener("done", (e) => {
      try {
        const d = JSON.parse(e.data);
        status.textContent = `Done — ${d.done}/${d.total} summarised.`;
      } catch (_) {}
      es.close();
    });
    es.onerror = () => { try { es.close(); } catch (_) {} status.textContent = "Connection lost."; };
  }

  function encodeKey(key) {
    // encode for URL path but keep / (DOIs contain /)
    return encodeURIComponent(key).replace(/%2F/g, "/");
  }

  // ============================================================
  // detail panel
  // ============================================================
  async function openDetail(paper) {
    if (!paper) return;
    const panel = $("#detail-panel");
    const body = $("#detail-body");
    panel.classList.remove("hidden");
    panel.setAttribute("aria-hidden", "false");
    // highlight in graph
    if (window.CSGraph && window.CSGraph.focusByKey) window.CSGraph.focusByKey(paper.key);
    // build the body — first with local data (instant), then fetch neighbours
    body.innerHTML = "";
    body.appendChild(buildDetailHead(paper));
    body.appendChild(buildDetailActions(paper));
    body.appendChild(buildDetailRel(paper));
    // annotation section (async load + edit)
    const annSec = el("div", { class: "d-section d-annotation" });
    body.appendChild(annSec);
    if (S.runId) {
      try {
        const keyEnc = encodeKey(paper.key);
        const a = await api.getJSON(`/api/run/${S.runId}/annotation/${keyEnc}`);
        renderAnnotation(annSec, paper, a.note);
      } catch (e) {
        renderAnnotation(annSec, paper, null);
      }
    } else {
      renderAnnotation(annSec, paper, null);
    }
    let absDiv = null;
    // inclusion/exclusion toggle
    const toggleSec = el("div", { class: "d-section d-toggle" });
    const tgBtn = el("button", { class: "tg-btn " + (paper.included ? "included" : "excluded") },
      paper.included ? "✓ Included (click to exclude)" : "✗ Excluded (click to include)");
    tgBtn.addEventListener("click", async () => {
      try {
        const keyEnc = encodeKey(paper.key);
        const r = await api.postJSON(`/api/run/${S.runId}/toggle/${keyEnc}`, {});
        if (r.ok) {
          paper.included = r.included;
          tgBtn.className = "tg-btn " + (r.included ? "included" : "excluded");
          tgBtn.textContent = r.included ? "✓ Included (click to exclude)" : "✗ Excluded (click to include)";
          toast(r.included ? "Paper included." : "Paper excluded.");
        }
      } catch (e) { toast("Toggle failed: " + e.message); }
    });
    toggleSec.appendChild(tgBtn);
    body.appendChild(toggleSec);
    if (paper.abstract) {
      const sec = el("div", { class: "d-section" });
      sec.appendChild(el("h5", {}, "Abstract"));
      absDiv = el("div", { class: "d-abstract" }, paper.abstract);
      sec.appendChild(absDiv);
      body.appendChild(sec);
      // LLM summary button
      const sumSec = el("div", { class: "d-summary" });
      const btn = el("button", { class: "sum-btn" }, "✨ Summarise with AI");
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.innerHTML = '<span class="spin"></span> Summarising…';
        try {
          const keyEnc = encodeKey(paper.key);
          const r = await api.postJSON(`/api/run/${S.runId}/summarise/${keyEnc}`, {});
          if (r.summary) {
            const result = el("div", { class: "sum-result" }, r.summary);
            sumSec.appendChild(result);
            btn.remove();
          } else {
            const err = el("div", { class: "sum-error" }, r.error || "Summarisation failed");
            sumSec.appendChild(err);
            btn.disabled = false;
            btn.innerHTML = "✨ Summarise with AI";
          }
        } catch (e) {
          const err = el("div", { class: "sum-error" }, "Error: " + e.message);
          sumSec.appendChild(err);
          btn.disabled = false;
          btn.innerHTML = "✨ Summarise with AI";
        }
      });
      sumSec.appendChild(btn);
      body.appendChild(sumSec);
    }
    // relevance-score explainer (async)
    const exSec = el("div", { class: "d-section d-explain" });
    exSec.appendChild(el("h5", {}, "Relevance breakdown"));
    exSec.appendChild(el("div", { class: "muted", style: "font-size:0.82rem" }, "computing…"));
    body.appendChild(exSec);
    if (S.runId) {
      try {
        const keyEnc = encodeKey(paper.key);
        const ex = await api.getJSON(`/api/run/${S.runId}/explain/${keyEnc}`);
        exSec.innerHTML = "";
        exSec.appendChild(el("h5", {}, "Relevance breakdown"));
        const terms = ex.terms || {};
        for (const [name, t] of Object.entries(terms)) {
          const row = el("div", { class: "ex-row" });
          row.appendChild(el("span", { class: "ex-name" }, name));
          const bar = el("div", { class: "ex-bar" });
          const fill = el("div");
          fill.style.width = Math.round((t.contribution / (ex.total || 1)) * 100) + "%";
          bar.appendChild(fill);
          row.appendChild(bar);
          const vals = el("span", { class: "ex-vals" });
          vals.innerHTML = `<span class="contrib">${t.contribution.toFixed(3)}</span> = ${t.weight.toFixed(2)}×${t.raw.toFixed(2)}`;
          row.appendChild(vals);
          exSec.appendChild(row);
        }
        if (ex.overlap_keywords && ex.overlap_keywords.length) {
          const kw = el("div", { class: "ex-kw" });
          ex.overlap_keywords.forEach((k) => kw.appendChild(el("span", { class: "chip" }, k)));
          exSec.appendChild(kw);
        }
        // highlight top TF-IDF tokens in the abstract (if abstract exists)
        if (ex.top_tokens && ex.top_tokens.length && typeof absDiv !== "undefined" && absDiv) {
          try { highlightTokens(absDiv, ex.top_tokens); } catch (htErr) { /* non-fatal */ }
        }
      } catch (e) {
        exSec.innerHTML = "";
        exSec.appendChild(el("h5", {}, "Relevance breakdown"));
        exSec.appendChild(el("div", { class: "muted", style: "font-size:0.82rem" }, "could not compute"));
      }
    }
    const neighSec = el("div", { class: "d-section" });
    neighSec.appendChild(el("h5", {}, "Citation graph"));
    neighSec.appendChild(el("div", { class: "muted", style: "font-size:0.82rem" }, "loading neighbours…"));
    body.appendChild(neighSec);
    // fetch neighbours
    if (S.runId) {
      try {
        const keyEnc = encodeKey(paper.key);
        const d = await api.getJSON(`/api/run/${S.runId}/paper/${keyEnc}`);
        neighSec.innerHTML = "";
        neighSec.appendChild(el("h5", {}, "Citation graph"));
        const inc = (d.incoming || []).length;
        const out = (d.outgoing || []).length;
        neighSec.appendChild(el("div", { class: "muted", style: "font-size:0.82rem;margin-bottom:6px" },
          `${inc} incoming · ${out} outgoing`));
        const ul = el("ul", { class: "d-neigh" });
        const renderNeigh = (n, dir) => {
          const np = n.paper;
          const li = el("li");
          li.addEventListener("click", () => openDetail(np));
          const dirLabel = dir === "forward" ? "cites →" : (dir === "backward" ? "← cited" : "");
          li.appendChild(el("span", { class: "dir" }, dirLabel));
          li.appendChild(document.createTextNode(truncate(np.title || "(untitled)", 50)));
          if (np.year) li.appendChild(el("span", { class: "yr" }, String(np.year)));
          return li;
        };
        (d.incoming || []).forEach((n) => ul.appendChild(renderNeigh(n, n.direction === "forward" ? "forward" : "backward")));
        (d.outgoing || []).forEach((n) => ul.appendChild(renderNeigh(n, n.direction === "forward" ? "forward" : "backward")));
        if (!ul.children.length) ul.appendChild(el("li", { class: "muted" }, "(no edges)"));
        neighSec.appendChild(ul);
      } catch (e) {
        neighSec.innerHTML = "";
        neighSec.appendChild(el("h5", {}, "Citation graph"));
        neighSec.appendChild(el("div", { class: "muted", style: "font-size:0.82rem" }, "could not load neighbours: " + e.message));
      }
    }
  }

  function renderAnnotation(container, paper, note) {
    container.innerHTML = "";
    container.appendChild(el("h5", {}, "Annotation"));
    if (note) {
      // show the note + edit/delete buttons
      const noteEl = el("div", { class: "ann-note" }, note);
      container.appendChild(noteEl);
      const actions = el("div", { class: "ann-actions" });
      const edit = el("button", { class: "btn ghost tiny" }, "✎ Edit");
      edit.addEventListener("click", () => renderAnnotationEditor(container, paper, note));
      const del = el("button", { class: "btn danger tiny" }, "✕ Delete");
      del.addEventListener("click", async () => {
        try {
          await api.postJSON(`/api/run/${S.runId}/annotation/${encodeKey(paper.key)}`, { note: "" });
          renderAnnotation(container, paper, null);
          toast("Annotation deleted.");
        } catch (e) { toast("Delete failed: " + e.message); }
      });
      actions.appendChild(edit);
      actions.appendChild(del);
      container.appendChild(actions);
    } else {
      // show an "add note" button
      const btn = el("button", { class: "ann-btn" }, "📝 Add note");
      btn.addEventListener("click", () => renderAnnotationEditor(container, paper, ""));
      container.appendChild(btn);
    }
  }

  function renderAnnotationEditor(container, paper, initial) {
    container.innerHTML = "";
    container.appendChild(el("h5", {}, "Annotation"));
    const ta = el("textarea", { placeholder: "Write your note about this paper…", rows: 3 });
    ta.value = initial || "";
    container.appendChild(ta);
    const actions = el("div", { class: "ann-actions" });
    const save = el("button", { class: "btn primary tiny" }, "💾 Save");
    save.addEventListener("click", async () => {
      const note = ta.value.trim();
      try {
        await api.postJSON(`/api/run/${S.runId}/annotation/${encodeKey(paper.key)}`, { note });
        renderAnnotation(container, paper, note || null);
        toast(note ? "Annotation saved." : "Annotation cleared.");
      } catch (e) { toast("Save failed: " + e.message); }
    });
    const cancel = el("button", { class: "btn ghost tiny" }, "Cancel");
    cancel.addEventListener("click", () => renderAnnotation(container, paper, initial || null));
    actions.appendChild(save);
    actions.appendChild(cancel);
    container.appendChild(actions);
    ta.focus();
  }

  function highlightTokens(container, tokens) {
    // wrap occurrences of each token in <mark class="tfidf"> within the container's text
    if (!container || !tokens || !tokens.length) return;
    const text = container.textContent;
    // build a regex of word-boundary matches for all tokens (longest first)
    const sorted = tokens.slice().sort((a, b) => b.length - a.length);
    const escaped = sorted.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const re = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");
    container.innerHTML = esc(text).replace(re, '<mark class="tfidf">$1</mark>');
  }

  function buildDetailHead(p) {
    const head = el("div");
    head.appendChild(el("h3", {}, p.title || "(untitled)"));
    const meta = el("div", { class: "d-meta" });
    let html = "";
    if (p.authors) html += esc(truncate(p.authors, 120));
    if (p.year) html += ` · ${esc(String(p.year))}`;
    if (p.venue) html += ` · <em>${esc(p.venue)}</em>`;
    if (p.doi) html += ` · <a href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">${esc(p.doi)}</a>`;
    if (p.num_citations) html += ` · ${esc(String(p.num_citations))} cites`;
    if (p.depth != null) html += ` · depth ${esc(String(p.depth))}`;
    meta.innerHTML = html;
    head.appendChild(meta);
    if ((p.sources || []).length) {
      const srcs = el("div", { class: "muted", style: "font-size:0.78rem;margin-top:4px" }, "sources: " + (p.sources || []).join(", "));
      head.appendChild(srcs);
    }
    return head;
  }

  function buildDetailRel(p) {
    const rel = el("div", { class: "d-rel" });
    rel.appendChild(el("div", { class: "v" }, (p.relevance || 0).toFixed(3)));
    const bar = el("div", { class: "bar" });
    const fill = el("div");
    fill.style.width = Math.round((p.relevance || 0) * 100) + "%";
    bar.appendChild(fill);
    rel.appendChild(bar);
    rel.appendChild(el("div", { class: "muted", style: "font-size:0.74rem" }, p.seed ? "seed paper" : "relevance score"));
    return rel;
  }

  function safeUrl(url) {
    return url && /^https?:\/\//i.test(url) ? url : null;
  }

  function buildDetailActions(p) {
    const acts = el("div", { class: "d-actions" });
    const url = safeUrl(p.url);
    if (url) {
      const a = el("a", { class: "btn ghost tiny", href: url, target: "_blank", rel: "noopener noreferrer" }, "Open ↗");
      acts.appendChild(a);
    }
    const pdfUrl = safeUrl(p.pdf_url);
    if (pdfUrl) {
      const a = el("a", { class: "btn ghost tiny", href: pdfUrl, target: "_blank", rel: "noopener noreferrer" }, "PDF ↗");
      acts.appendChild(a);
    }
    if (S.runId && p.key) {
      const keyEnc = encodeKey(p.key);
      const bibtex = el("button", { class: "btn ghost tiny", onclick: () => api.download(`/api/run/${S.runId}/paper/${keyEnc}?format=bibtex`) }, "BibTeX");
      const ris = el("button", { class: "btn ghost tiny", onclick: () => api.download(`/api/run/${S.runId}/paper/${keyEnc}?format=ris`) }, "RIS");
      acts.appendChild(bibtex);
      acts.appendChild(ris);
    }
    return acts;
  }

  function closeDetail() {
    const panel = $("#detail-panel");
    if (!panel) return;
    panel.classList.add("hidden");
    panel.setAttribute("aria-hidden", "true");
    if (window.CSGraph && window.CSGraph.focusByKey) window.CSGraph.focusByKey(null);
  }

  // ============================================================
  // keyboard shortcuts cheatsheet
  // ============================================================
  function toggleCheatsheet() {
    const c = $("#cheatsheet");
    if (!c) return;
    c.classList.toggle("hidden");
  }
  function closeCheatsheet() {
    const c = $("#cheatsheet");
    if (!c || c.classList.contains("hidden")) return false;
    c.classList.add("hidden");
    return true;
  }

  function renderTree(papers, edges) {
    const root = $("#tree-list");
    root.innerHTML = "";
    // build adjacency: for each paper, which papers it cites (backward edges target)
    const bySrc = {}, byTgt = {};
    for (const e of edges) {
      (bySrc[e.source] = bySrc[e.source] || []).push(e);
      (byTgt[e.target] = byTgt[e.target] || []).push(e);
    }
    const keyset = new Set(papers.map((p) => p.key));
    const seeds = papers.filter((p) => p.seed).sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
    if (!seeds.length) { root.innerHTML = "<li class='muted'>no seeds</li>"; return; }
    const seen = new Set();
    function node(p, depth) {
      if (depth > 4) return null;
      if (seen.has(p.key)) return el("li", {}, "↻ " + truncate(p.title || "", 50));
      seen.add(p.key);
      const li = el("li");
      const row = el("div", { class: "node" });
      row.appendChild(el("span", { class: "nm" }, truncate(p.title || "(untitled)", 70)));
      if (p.year) row.appendChild(el("span", { class: "yr" }, String(p.year)));
      row.appendChild(el("span", { class: "rel" }, (p.relevance || 0).toFixed(2)));
      li.appendChild(row);
      // children = papers that this paper cites (backward edges from p)
      const childEdges = (bySrc[p.key] || []).filter((e) => e.direction === "backward");
      const parentEdges = (bySrc[p.key] || []).filter((e) => e.direction === "forward");
      if (childEdges.length || parentEdges.length) {
        const ul = el("ul");
        for (const e of childEdges) {
          if (!keyset.has(e.target)) continue;
          const cp = S.run.papers.find((x) => x.key === e.target);
          if (cp) {
            const sub = node(cp, depth + 1);
            if (sub) { const li2 = el("li", {}, el("span", { class: "dir" }, "← cited "), sub.firstChild); ul.appendChild(li2); }
          }
        }
        for (const e of parentEdges) {
          if (!keyset.has(e.target)) continue;
          const cp = S.run.papers.find((x) => x.key === e.target);
          if (cp) {
            const sub = node(cp, depth + 1);
            if (sub) { const li2 = el("li", {}, el("span", { class: "dir" }, "cites → "), sub.firstChild); ul.appendChild(li2); }
          }
        }
        if (ul.children.length) li.appendChild(ul);
      }
      return li;
    }
    for (const s of seeds) {
      const n = node(s, 0);
      if (n) root.appendChild(n);
    }
  }

  function renderTable(papers) {
    const tb = $("#paper-tbody");
    tb.innerHTML = "";
    const sorted = papers.slice().sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
    sorted.forEach((p, i) => {
      const isSel = S.bulkSelected && S.bulkSelected.has(p.key);
      const tr = el("tr", { class: (p.seed ? "seed" : (!p.included ? "exc" : "")) + (isSel ? " sel" : ""), style: "cursor:pointer", "data-key": p.key });
      tr.addEventListener("click", () => openDetail(p));
      // checkbox cell (stopPropagation so row-click doesn't fire)
      const chkTd = el("td", {});
      const chk = el("input", { type: "checkbox", "data-key": p.key });
      chk.checked = !!isSel;
      chk.addEventListener("click", (e) => e.stopPropagation());
      chk.addEventListener("change", () => {
        if (chk.checked) S.bulkSelected.add(p.key);
        else S.bulkSelected.delete(p.key);
        tr.classList.toggle("sel", chk.checked);
        const cnt = $("#bulk-count");
        if (cnt) cnt.textContent = S.bulkSelected.size + " selected";
        const sa = $("#select-all-chk");
        if (sa) {
          const visible = document.querySelectorAll("#paper-tbody tr");
          sa.checked = visible.length > 0 && Array.from(visible).every((t) => S.bulkSelected.has(t.dataset.key));
        }
      });
      chkTd.appendChild(chk);
      tr.appendChild(chkTd);
      tr.appendChild(el("td", {}, String(i + 1)));
      tr.appendChild(el("td", {}, truncate(p.title || "(untitled)", 120)));
      tr.appendChild(el("td", {}, truncate(p.authors || "", 60)));
      tr.appendChild(el("td", {}, p.year ? String(p.year) : "—"));
      tr.appendChild(el("td", {}, String(p.num_citations || 0)));
      tr.appendChild(el("td", {}, (p.relevance || 0).toFixed(2)));
      tr.appendChild(el("td", {}, String(p.depth || 0)));
      tr.appendChild(el("td", {}, (p.sources || []).join(", ")));
      const doiTd = el("td", {});
      if (p.doi) {
        const a = el("a", { href: "https://doi.org/" + p.doi, target: "_blank", rel: "noopener" }, p.doi);
        a.addEventListener("click", (e) => e.stopPropagation());
        doiTd.appendChild(a);
      }
      tr.appendChild(doiTd);
      tb.appendChild(tr);
    });
    if (!sorted.length) tb.innerHTML = "<tr><td colspan='10' class='muted'>no papers match the filter</td></tr>";
  }

  function switchTab(name) {
    $$(".tab[data-tab]").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + name));
    if (name === "graph") window.CSGraph.rerender && window.CSGraph.rerender();
  }

  function exportData(fmt) {
    if (!S.runId) return;
    if (fmt === "prisma") {
      api.download(`/api/run/${S.runId}/prisma?format=svg`, `prisma_${S.runId}.svg`);
      toast("Downloading PRISMA flow diagram (SVG)…");
      return;
    }
    if (fmt === "coins") {
      window.open(`/cs/api/run/${S.runId}/coins`, "_blank");
      toast("Opened COinS page — use the Zotero connector to import.");
      return;
    }
    const all = S.filter.excluded ? 1 : 0;
    api.download(`/api/run/${S.runId}/export?format=${fmt}&all=${all}`, `cuteysnowball_${S.runId}.${fmt === "bibtex" ? "bib" : fmt}`);
    toast(`Exporting ${fmt.toUpperCase()}…`);
  }

  function exportGraphSVG() {
    const svg = document.getElementById("graph-svg");
    if (!svg) return;
    // clone the SVG, inline styles, and download
    const clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const T = window.CSUtils;
    const style = getComputedStyle(document.documentElement);
    const bg = style.getPropertyValue("--surface").trim() || "#fff";
    // add a background rect
    const bgRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bgRect.setAttribute("x", "0"); bgRect.setAttribute("y", "0");
    bgRect.setAttribute("width", "100%"); bgRect.setAttribute("height", "100%");
    bgRect.setAttribute("fill", bg);
    clone.insertBefore(bgRect, clone.firstChild);
    const data = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([data], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `graph_${S.runId || "export"}.svg`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    toast("Graph exported as SVG.");
  }

  function exportGraphPNG() {
    const svg = document.getElementById("graph-svg");
    if (!svg) return;
    const clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const style = getComputedStyle(document.documentElement);
    const bg = style.getPropertyValue("--surface").trim() || "#fff";
    const bgRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bgRect.setAttribute("x", "0"); bgRect.setAttribute("y", "0");
    bgRect.setAttribute("width", "100%"); bgRect.setAttribute("height", "100%");
    bgRect.setAttribute("fill", bg);
    clone.insertBefore(bgRect, clone.firstChild);
    const data = new XMLSerializer().serializeToString(clone);
    const svgBlob = new Blob([data], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = svg.clientWidth * 2;
      canvas.height = svg.clientHeight * 2;
      const ctx = canvas.getContext("2d");
      ctx.scale(2, 2);
      ctx.drawImage(img, 0, 0);
      canvas.toBlob((blob) => {
        const dlUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = dlUrl; a.download = `graph_${S.runId || "export"}.png`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(dlUrl);
        URL.revokeObjectURL(url);
        toast("Graph exported as PNG.");
      });
    };
    img.onerror = () => { toast("PNG export failed."); URL.revokeObjectURL(url); };
    img.src = url;
  }

  async function resumeRun() {
    if (!S.runId) return;
    try {
      const r = await api.postJSON(`/api/run/${S.runId}/resume`, {});
      if (r && r.status === "resumed") {
        toast("Resuming snowball…");
        $("#run-resume").classList.add("hidden");
        $("#run-stop").classList.remove("hidden");
        streamRun(S.runId);
      } else {
        toast(r.error || "Could not resume.");
      }
    } catch (e) { toast("Resume failed: " + e.message); }
  }

  // ============================================================
  // run comparison
  // ============================================================
  async function goCompare() {
    swap("view-compare");
    const selA = $("#compare-a"), selB = $("#compare-b");
    // wire export buttons (once)
    const csvBtn = $("#cmp-export-csv"), jsonBtn = $("#cmp-export-json");
    if (csvBtn && !csvBtn.dataset.wired) {
      csvBtn.dataset.wired = "1";
      csvBtn.addEventListener("click", () => exportCompareDiff("csv"));
      jsonBtn.addEventListener("click", () => exportCompareDiff("json"));
    }
    try {
      const runs = await api.getJSON("/api/runs");
      // populate dropdowns
      const fill = (sel) => {
        sel.innerHTML = "";
        runs.forEach((r) => {
          const o = el("option", { value: r.run_id });
          o.textContent = `${r.run_id.slice(0,8)} · ${r.mode} · ${new Date(r.created_at * 1000).toLocaleDateString()} · ${r.status}`;
          sel.appendChild(o);
        });
      };
      fill(selA); fill(selB);
      if (runs.length >= 2) selB.value = runs[1].run_id;
      $("#compare-results").classList.add("hidden");
    } catch (e) { toast("Could not load runs: " + e.message); }
  }

  async function runCompare() {
    const a = $("#compare-a").value, b = $("#compare-b").value;
    if (!a || !b) { toast("Pick two runs."); return; }
    if (a === b) { toast("Pick two different runs."); return; }
    try {
      const d = await api.getJSON(`/api/compare?a=${a}&b=${b}`);
      // summary
      const sum = $("#compare-summary");
      sum.innerHTML = "";
      const mk = (v, l) => { const s = el("div", { class: "cs-stat" }); s.appendChild(el("div", { class: "v" }, String(v))); s.appendChild(el("div", { class: "l" }, l)); return s; };
      sum.appendChild(mk(d.a.paper_count, "Run A papers"));
      sum.appendChild(el("div", { class: "cs-divider" }));
      sum.appendChild(mk(d.b.paper_count, "Run B papers"));
      sum.appendChild(el("div", { class: "cs-divider" }));
      sum.appendChild(mk(d.common, "Common"));
      sum.appendChild(el("div", { class: "cs-divider" }));
      sum.appendChild(mk(d.only_a_count, "Only in A"));
      sum.appendChild(mk(d.only_b_count, "Only in B"));
      sum.appendChild(el("div", { class: "cs-divider" }));
      sum.appendChild(mk(d.shifted_count, "Relevance shifts"));
      // only_a
      const oa = $("#compare-only_a"); oa.innerHTML = "";
      d.only_a.forEach((p) => {
        const li = el("li");
        li.style.cursor = "pointer";
        li.addEventListener("click", () => { S.runId = $("#compare-a").value; openDetail(p); });
        li.appendChild(el("span", { class: "rank-rel" }, ((p.relevance || 0)).toFixed(2)));
        li.appendChild(el("div", { class: "rank-body" }, truncate(p.title || "(untitled)", 80)));
        oa.appendChild(li);
      });
      if (!d.only_a.length) oa.innerHTML = "<li class='empty-state'>No papers unique to run A.</li>";
      // only_b
      const ob = $("#compare-only_b"); ob.innerHTML = "";
      d.only_b.forEach((p) => {
        const li = el("li");
        li.style.cursor = "pointer";
        li.addEventListener("click", () => { S.runId = $("#compare-b").value; openDetail(p); });
        li.appendChild(el("span", { class: "rank-rel" }, ((p.relevance || 0)).toFixed(2)));
        li.appendChild(el("div", { class: "rank-body" }, truncate(p.title || "(untitled)", 80)));
        ob.appendChild(li);
      });
      if (!d.only_b.length) ob.innerHTML = "<li class='empty-state'>No papers unique to run B.</li>";
      // shifted
      const sh = $("#compare-shifted"); sh.innerHTML = "";
      d.shifted.forEach((s) => {
        const li = el("li");
        li.appendChild(el("span", { class: "sh-title", title: s.title }, truncate(s.title || "(untitled)", 60)));
        const rels = el("span", { class: "sh-rels" });
        rels.appendChild(el("span", { class: "a" }, s.rel_a.toFixed(2)));
        rels.appendChild(document.createTextNode(" → "));
        rels.appendChild(el("span", { class: "b" }, s.rel_b.toFixed(2)));
        li.appendChild(rels);
        const dClass = s.delta > 0 ? "pos" : "neg";
        li.appendChild(el("span", { class: "sh-delta " + dClass }, (s.delta > 0 ? "+" : "") + s.delta.toFixed(2)));
        sh.appendChild(li);
      });
      if (!d.shifted.length) sh.innerHTML = "<li class='empty-state'>No relevance shifts ≥ 0.01.</li>";
      $("#compare-results").classList.remove("hidden");
    } catch (e) { toast("Compare failed: " + e.message); }
  }

  function exportCompareDiff(fmt) {
    const a = $("#compare-a").value, b = $("#compare-b").value;
    if (!a || !b) { toast("Pick two runs first."); return; }
    api.download(`/api/compare?a=${a}&b=${b}&format=${fmt}`, `compare_${a.slice(0,8)}_${b.slice(0,8)}.${fmt}`);
    toast(`Exporting diff as ${fmt.toUpperCase()}…`);
  }

  // ============================================================
  // bulk select (table)
  // ============================================================
  function initBulkSelect() {
    S.bulkSelected = new Set();
    const updateCount = () => {
      const el = $("#bulk-count");
      if (el) el.textContent = S.bulkSelected.size + " selected";
      const sa = $("#select-all-chk");
      if (sa) {
        const visible = document.querySelectorAll("#paper-tbody tr");
        const allSel = visible.length > 0 && Array.from(visible).every((tr) => S.bulkSelected.has(tr.dataset.key));
        sa.checked = allSel;
      }
    };
    const sa = $("#select-all-chk");
    if (sa) sa.addEventListener("change", () => {
      const visible = document.querySelectorAll("#paper-tbody tr");
      if (sa.checked) visible.forEach((tr) => S.bulkSelected.add(tr.dataset.key));
      else visible.forEach((tr) => S.bulkSelected.delete(tr.dataset.key));
      document.querySelectorAll("#paper-tbody tr").forEach((tr) => tr.classList.toggle("sel", S.bulkSelected.has(tr.dataset.key)));
      document.querySelectorAll("#paper-tbody input[type=checkbox]").forEach((cb) => { cb.checked = sa.checked; });
      updateCount();
    });
    const bsa = $("#bulk-select-all");
    if (bsa) bsa.addEventListener("click", () => {
      document.querySelectorAll("#paper-tbody tr").forEach((tr) => {
        S.bulkSelected.add(tr.dataset.key);
        tr.classList.add("sel");
        const cb = tr.querySelector("input[type=checkbox]");
        if (cb) cb.checked = true;
      });
      updateCount();
    });
    const bc = $("#bulk-clear");
    if (bc) bc.addEventListener("click", () => {
      S.bulkSelected.clear();
      document.querySelectorAll("#paper-tbody tr").forEach((tr) => { tr.classList.remove("sel"); const cb = tr.querySelector("input[type=checkbox]"); if (cb) cb.checked = false; });
      updateCount();
    });
    $$("[data-bulk-fmt]").forEach((b) => b.addEventListener("click", () => bulkExport(b.dataset.bulkFmt)));
    updateCount();
    // compare-view sub-tabs
    $$(".tab[data-ctab]").forEach((t) =>
      t.addEventListener("click", () => {
        $$(".tab[data-ctab]").forEach((x) => x.classList.toggle("active", x === t));
        $$("#cpanel-only_a, #cpanel-only_b, #cpanel-shifted").forEach((p) => p.classList.add("hidden"));
        const panel = $("#cpanel-" + t.dataset.ctab);
        if (panel) panel.classList.remove("hidden");
      })
    );
    // compare-go button
    const cg = $("#compare-go");
    if (cg) cg.addEventListener("click", runCompare);
  }

  async function bulkExport(fmt) {
    if (!S.runId || S.bulkSelected.size === 0) { toast("Select papers first."); return; }
    const keys = Array.from(S.bulkSelected);
    toast(`Exporting ${keys.length} papers as ${fmt.toUpperCase()}…`);
    try {
      const resp = await fetch(`/api/run/${S.runId}/export-selected`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keys, format: fmt }),
      });
      if (!resp.ok) {
        let msg = "Export failed: " + resp.status;
        try { const j = await resp.json(); if (j.error) msg += ": " + j.error; } catch (_) {}
        toast(msg); return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `cuteysnowball_${S.runId}_selected.${fmt === "bibtex" ? "bib" : fmt}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { toast("Export error: " + e.message); }
  }

  // ============================================================
  // settings view
  // ============================================================
  async function goSettings() {
    swap("view-settings");
    try {
      const s = await api.getJSON("/api/settings");
      $("#set-mailto").value = s.mailto || "";
      $("#set-min-rel").value = s.min_relevance;
      $("#set-max-iter").value = s.max_iterations;
      $("#set-per-round").value = s.per_round_cap;
      // sources
      const sl = $("#settings-sources");
      sl.innerHTML = "";
      for (const [name, on] of Object.entries(s.sources || {})) {
        const chip = el("span", { class: "source-chip " + (on ? "ok" : "off") });
        chip.appendChild(el("span", { class: "dot" }));
        chip.appendChild(document.createTextNode(name + (on ? " (on)" : " (off)")));
        sl.appendChild(chip);
      }
      // cache
      const ci = $("#cache-info");
      if (ci) ci.textContent = `Cached DOIs: ${s.cache?.entries || 0} entries` + (s.cache?.newest ? ` · last: ${new Date(s.cache.newest * 1000).toLocaleString()}` : "");
    } catch (e) {
      toast("Could not load settings: " + e.message);
    }
  }

  // ============================================================
  // runs list
  // ============================================================
  async function goRuns() {
    swap("view-runs");
    const ul = $("#runs-list");
    ul.innerHTML = "<li class='muted'>loading…</li>";
    // add run search bar (once)
    let searchbar = document.querySelector(".run-search-bar");
    if (!searchbar) {
      searchbar = el("div", { class: "run-search-bar" });
      const inp = el("input", { type: "search", placeholder: "search across all runs by paper title or DOI…", id: "run-search-input" });
      const count = el("span", { class: "rs-count" }, "");
      searchbar.appendChild(inp);
      searchbar.appendChild(count);
      ul.parentElement.insertBefore(searchbar, ul);
      let stimer;
      inp.addEventListener("input", () => {
        clearTimeout(stimer);
        const q = inp.value.trim();
        count.textContent = q ? "searching…" : "";
        if (q.length < 2) { document.querySelector(".run-search-results")?.remove(); return; }
        stimer = setTimeout(() => runSearch(q, count), 400);
      });
    }
    let filterBar = document.querySelector(".runs-filter");
    try {
      const runs = await api.getJSON("/api/runs");
      ul.innerHTML = "";
      if (!runs.length) { ul.innerHTML = "<li class='muted'>no runs yet</li>"; return; }
      // build tag filter bar
      const allTags = new Set();
      runs.forEach((r) => (r.tags || []).forEach((t) => allTags.add(t)));
      if (allTags.size > 0 && !filterBar) {
        filterBar = el("div", { class: "runs-filter" });
        ul.parentElement.insertBefore(filterBar, ul);
      }
      if (filterBar) {
        filterBar.innerHTML = "";
        filterBar.appendChild(el("span", { class: "muted", style: "margin-right:4px" }, "Filter by tag:"));
        allTags.forEach((t) => {
          const chip = el("span", { class: "rf-chip", "data-tag": t }, t);
          chip.addEventListener("click", () => {
            chip.classList.toggle("active");
            renderFilteredRuns(runs, ul);
          });
          filterBar.appendChild(chip);
        });
        const clear = el("span", { class: "rf-chip" }, "clear");
        clear.addEventListener("click", () => {
          filterBar.querySelectorAll(".rf-chip.active").forEach((c) => c.classList.remove("active"));
          renderFilteredRuns(runs, ul);
        });
        filterBar.appendChild(clear);
      }
      S._allRuns = runs;
      renderFilteredRuns(runs, ul);
    } catch (e) {
      ul.innerHTML = `<li class='muted'>failed: ${esc(e.message)}</li>`;
    }
  }

  async function runSearch(q, countEl) {
    try {
      const d = await api.getJSON(`/api/search-runs?q=${encodeURIComponent(q)}`);
      const results = d.results || [];
      countEl.textContent = `${results.length} match${results.length === 1 ? "" : "es"}`;
      let resultsEl = document.querySelector(".run-search-results");
      if (!resultsEl) {
        resultsEl = el("ul", { class: "run-search-results" });
        const ul = $("#runs-list");
        ul.parentElement.insertBefore(resultsEl, ul);
      }
      resultsEl.innerHTML = "";
      if (!results.length) {
        resultsEl.innerHTML = "<li class='muted'>No papers found across runs.</li>";
        return;
      }
      results.forEach((r) => {
        const li = el("li");
        li.addEventListener("click", () => {
          S.runId = r.run_id;
          loadResults(r.run_id);
          swap("view-run");
        });
        li.appendChild(el("div", { class: "rsr-title" }, truncate(r.paper.title || "(untitled)", 80)));
        const meta = el("div", { class: "rsr-meta" });
        meta.textContent = (r.paper.authors ? truncate(r.paper.authors, 60) + " · " : "") + (r.paper.year || "—") + " · " + (r.paper.num_citations || 0) + " cites · rel " + (r.paper.relevance || 0).toFixed(2);
        li.appendChild(meta);
        const run = el("div", { class: "rsr-run" });
        run.textContent = `run ${r.run_id.slice(0, 8)} · ${r.run_mode} · tags: ${(r.run_tags || []).join(", ") || "none"}`;
        li.appendChild(run);
        resultsEl.appendChild(li);
      });
    } catch (e) { countEl.textContent = "error"; }
  }

  function renderFilteredRuns(runs, ul) {
    const activeTags = Array.from(document.querySelectorAll(".runs-filter .rf-chip.active")).map((c) => c.dataset.tag);
    const filtered = activeTags.length === 0 ? runs : runs.filter((r) => (r.tags || []).some((t) => activeTags.includes(t)));
    ul.innerHTML = "";
    if (!filtered.length) { ul.innerHTML = "<li class='muted'>no runs match the filter</li>"; return; }
    for (const r of filtered) {
        const li = el("li");
        li.appendChild(el("span", { class: "r-status " + r.status }, r.status));
        const body = el("span", { style: "flex:1" });
        body.appendChild(el("div", {}, `${r.mode} · ${new Date(r.created_at * 1000).toLocaleString()} · ${r.paper_count || 0} papers` + (r.message ? " · " + truncate(r.message, 60) : "")));
        const tagsDiv = el("div", { class: "r-tags" });
        (r.tags || []).forEach((t) => tagsDiv.appendChild(el("span", { class: "tag-chip" }, t)));
        if (!(r.tags || []).length) tagsDiv.appendChild(el("span", { class: "muted", style: "font-size:0.72rem" }, "no tags"));
        body.appendChild(tagsDiv);
        li.appendChild(body);
        li.appendChild(el("span", { class: "muted" }, r.run_id));
        li.addEventListener("click", () => {
          S.runId = r.run_id;
          if (r.status === "running") streamRun(r.run_id);
          else loadResults(r.run_id);
          swap("view-run");
        });
        ul.appendChild(li);
    }
  }

  // ============================================================
  // boot
  // ============================================================
  document.addEventListener("DOMContentLoaded", () => {
    window.CSUtils.initTheme();
    wireNav();
    initBulkSelect();
    loadSources();
    // settings form submit
    const sf = $("#settings-form");
    if (sf) sf.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {
        mailto: $("#set-mailto").value || undefined,
        min_relevance: parseFloat($("#set-min-rel").value),
        max_iterations: parseInt($("#set-max-iter").value, 10),
        per_round_cap: parseInt($("#set-per-round").value, 10),
      };
      Object.keys(body).forEach((k) => (body[k] == null || body[k] === "" || isNaN(body[k])) && delete body[k]);
      try {
        await api.postJSON("/api/settings", body);
        toast("Settings saved — apply to new runs.");
      } catch (err) { toast("Save failed: " + err.message); }
    });
    const cc = $("#cache-clear");
    if (cc) cc.addEventListener("click", async () => {
      try { await api.postJSON("/api/cache/clear", {}); toast("Cache cleared."); goSettings(); }
      catch (e) { toast("Clear failed: " + e.message); }
    });
    // cheatsheet close
    const cheatClose = $("#cheat-close"), cheatBg = $("#cheat-backdrop");
    if (cheatClose) cheatClose.addEventListener("click", closeCheatsheet);
    if (cheatBg) cheatBg.addEventListener("click", closeCheatsheet);
  });
})();
