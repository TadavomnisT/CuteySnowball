/* graph.js — pure-JS directed graph renderer (SVG, no D3/vis/CDN).

Layout: "timeline layered".
  * X axis = publication year (chronological left→right).
  * Y axis = snowball depth (seeds at top, deeper hops cascade downward),
    with small vertical jitter so sibling clusters don't fully overlap.
  * Edges drawn as bezier curves; forward (citing→cited) coral, backward
    (cited→citing) sage dashed.
  * Pan (drag), zoom (wheel), fit, relayout, hover tooltip, click-to-focus.

Nodes are circles sized by citation count, colored by status
(seed=honey, included=sage, excluded=grey).
*/
(function (global) {
  "use strict";
  const { $, el } = global.CSUtils;

  const State = {
    svg: null,
    root: null,            // <g> transform group
    nodes: [],
    edges: [],
    pos: {},               // key -> {x,y,r}
    view: { tx: 0, ty: 0, scale: 1 },
    drag: null,            // pan drag
    nodeDrag: null,        // node-drag state
    selected: null,
    width: 0,
    height: 0,
    showForward: true,
    showBackward: true,
    showGrid: true,
    showAbstractsOnHover: false,
    allowNodeDrag: false,  // when true, nodes are draggable
    straight: false,      // when true, edges are straight lines (not bezier)
    sizeMode: "citations", // "citations" | "relevance" | "degree" | "fixed"
    search: "",
    yearFrom: null,
    yearTo: null,
    layout: "timeline",   // "timeline" or "force"
    papers: [],
    edgesRaw: [],
  };

  // ---- theming helper (reads CSS vars so dark mode works) ----
  function theme() {
    const s = getComputedStyle(document.documentElement);
    return {
      ink: s.getPropertyValue("--ink").trim(),
      muted: s.getPropertyValue("--muted").trim(),
      line: s.getPropertyValue("--line").trim(),
      lineStrong: s.getPropertyValue("--line-strong").trim(),
      accent: s.getPropertyValue("--accent").trim(),
      accent2: s.getPropertyValue("--accent2").trim(),
      accent3: s.getPropertyValue("--accent3").trim(),
      surface: s.getPropertyValue("--surface").trim(),
      snow: s.getPropertyValue("--snow").trim(),
    };
  }

  function init(containerId) {
    State.svg = document.getElementById(containerId);
    if (!State.svg) return;
    State.svg.innerHTML = "";
    const ns = "http://www.w3.org/2000/svg";

    // defs (arrow markers, glow filter)
    const defs = document.createElementNS(ns, "defs");
    const mk = (id, color, dash) => {
      const m = document.createElementNS(ns, "marker");
      m.setAttribute("id", id);
      m.setAttribute("viewBox", "0 0 10 10");
      m.setAttribute("refX", "9"); m.setAttribute("refY", "5");
      m.setAttribute("markerWidth", "6"); m.setAttribute("markerHeight", "6");
      m.setAttribute("orient", "auto-start-reverse");
      const p = document.createElementNS(ns, "path");
      p.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      p.setAttribute("fill", color);
      m.appendChild(p);
      defs.appendChild(m);
    };
    mk("arr-forward", theme().accent, "");
    mk("arr-backward", theme().accent2, "");
    // radial gradients for seed + high-relevance nodes
    const mkGrad = (id, c1, c2) => {
      const rad = document.createElementNS(ns, "radialGradient");
      rad.setAttribute("id", id); rad.setAttribute("cx", "0.35"); rad.setAttribute("cy", "0.35"); rad.setAttribute("r", "0.7");
      const s1 = document.createElementNS(ns, "stop"); s1.setAttribute("offset", "0%"); s1.setAttribute("stop-color", c1);
      const s2 = document.createElementNS(ns, "stop"); s2.setAttribute("offset", "100%"); s2.setAttribute("stop-color", c2);
      rad.appendChild(s1); rad.appendChild(s2);
      defs.appendChild(rad);
    };
    const T0 = theme();
    mkGrad("grad-seed", T0.accent3, T0.accent);
    mkGrad("grad-hot", T0.accent, T0.accent2);
    State.svg.appendChild(defs);

    // background rect (for pan/zoom capture)
    const bg = document.createElementNS(ns, "rect");
    bg.setAttribute("x", "0"); bg.setAttribute("y", "0");
    bg.setAttribute("width", "100%"); bg.setAttribute("height", "100%");
    bg.setAttribute("fill", "transparent");
    bg.style.cursor = "grab";
    State.svg.appendChild(bg);
    State.bg = bg;

    // root transform group
    const g = document.createElementNS(ns, "g");
    g.setAttribute("id", "graph-root");
    State.svg.appendChild(g);
    State.root = g;

    // edge + node layers + grid layer (grid drawn first, behind edges/nodes)
    const gg = document.createElementNS(ns, "g"); gg.setAttribute("id", "grid"); g.appendChild(gg);
    const eg = document.createElementNS(ns, "g"); eg.setAttribute("id", "edges"); g.appendChild(eg);
    const ng = document.createElementNS(ns, "g"); ng.setAttribute("id", "nodes"); g.appendChild(ng);
    State.gridLayer = gg;
    State.edgeLayer = eg;
    State.nodeLayer = ng;

    State.tooltip = $("#graph-tooltip");

    // measure
    const rect = State.svg.getBoundingClientRect();
    State.width = rect.width;
    State.height = rect.height;
    State.svg.setAttribute("viewBox", `0 0 ${State.width} ${State.height}`);

    // pan + zoom
    bg.addEventListener("mousedown", panStart);
    State.svg.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", () => {
      const r = State.svg.getBoundingClientRect();
      State.width = r.width; State.height = r.height;
      State.svg.setAttribute("viewBox", `0 0 ${State.width} ${State.height}`);
    });
    // node drag listeners (once)
    if (!State._dragInit) {
      initNodeDrag();
      State._dragInit = true;
    }
  }

  // ---- compute layout ----
  function layout() {
    if (State.layout === "force") {
      layoutForce();
    } else {
      layoutTimeline();
    }
  }

  function layoutTimeline() {
    const W = State.width || 800;
    const H = State.height || 560;
    const padX = 60, padY = 50;
    const papers = State.papers;
    if (!papers.length) return;

    // year domain
    const years = papers.map((p) => p.year).filter((y) => y).sort((a, b) => a - b);
    const ymin = years.length ? years[0] : 2000;
    const ymax = years.length ? years[years.length - 1] : 2025;
    const yspan = Math.max(1, ymax - ymin);
    // depth domain
    const depths = papers.map((p) => p.depth || 0);
    const dmax = Math.max(2, ...depths);

    // group papers by year (for x jitter within a column)
    const byYear = {};
    papers.forEach((p) => {
      const y = p.year || (ymin + yspan / 2 | 0);
      (byYear[y] = byYear[y] || []).push(p);
    });

    const colW = (W - 2 * padX) / Math.max(1, yspan);
    const rowH = (H - 2 * padY) / Math.max(1, dmax + 1);
    State.pos = {};

    Object.keys(byYear).forEach((ystr) => {
      const y = +ystr;
      const group = byYear[y];
      const x = padX + ((y - ymin) / Math.max(1, yspan)) * (W - 2 * padX);
      // vertical stack within the column
      const stepY = Math.min(rowH, (H - 2 * padY) / Math.max(group.length, dmax + 1));
      group.forEach((p, i) => {
        const depth = p.depth || 0;
        const baseY = padY + depth * rowH;
        const jitter = (i - (group.length - 1) / 2) * stepY * 0.7;
        State.pos[p.key] = { x, y: baseY + jitter, r: nodeRadius(p) };
      });
    });
  }

  function nodeRadius(p) {
    const mode = State.sizeMode || "citations";
    if (mode === "fixed") return 6;
    if (mode === "relevance") {
      const r = p.relevance || 0;
      return 4 + Math.round(r * 10);
    }
    if (mode === "degree") {
      // count edges touching this node
      let deg = 0;
      for (const e of State.edgesRaw) {
        if (e.source === p.key || e.target === p.key) deg++;
      }
      return 4 + Math.min(10, Math.log2(deg + 1) * 2);
    }
    // default: citations
    const c = p.num_citations || 0;
    return 4 + Math.min(10, Math.log2(c + 1) * 1.6);
  }

  // ---- force-directed layout (simple spring model, 60 iterations) ----
  function layoutForce() {
    const W = State.width || 800;
    const H = State.height || 560;
    const papers = State.papers;
    if (!papers.length) return;
    State.pos = {};
    // initialize with random positions in a circle around center
    const cx = W / 2, cy = H / 2;
    const R = Math.min(W, H) * 0.35;
    papers.forEach((p, i) => {
      const angle = (i / papers.length) * 2 * Math.PI;
      State.pos[p.key] = {
        x: cx + Math.cos(angle) * R * (0.5 + Math.random() * 0.5),
        y: cy + Math.sin(angle) * R * (0.5 + Math.random() * 0.5),
        r: nodeRadius(p),
        vx: 0, vy: 0,
      };
    });
    // build adjacency
    const adj = {};
    papers.forEach((p) => { adj[p.key] = []; });
    for (const e of State.edgesRaw) {
      if (adj[e.source]) adj[e.source].push(e.target);
      if (adj[e.target]) adj[e.target].push(e.source);
    }
    // iterate
    const k = 1.5; // spring length
    const iterations = 60;
    const dt = 0.1;
    for (let iter = 0; iter < iterations; iter++) {
      // repulsive forces (all pairs, simplified — only n^2 for small graphs)
      for (let i = 0; i < papers.length; i++) {
        const a = State.pos[papers[i].key];
        if (!a) continue;
        for (let j = i + 1; j < papers.length; j++) {
          const b = State.pos[papers[j].key];
          if (!b) continue;
          let dx = a.x - b.x, dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const force = (k * k) / (dist * dist) * 2;
          const fx = (dx / dist) * force * dt;
          const fy = (dy / dist) * force * dt;
          a.vx += fx; a.vy += fy;
          b.vx -= fx; b.vy -= fy;
        }
      }
      // attractive forces (edges)
      for (const e of State.edgesRaw) {
        const a = State.pos[e.source], b = State.pos[e.target];
        if (!a || !b) continue;
        let dx = b.x - a.x, dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (dist * dist) / k * 0.5;
        const fx = (dx / dist) * force * dt;
        const fy = (dy / dist) * force * dt;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
      // apply velocity + centering
      for (const p of papers) {
        const pos = State.pos[p.key];
        if (!pos) continue;
        pos.x += pos.vx;
        pos.y += pos.vy;
        pos.vx *= 0.85; // damping
        pos.vy *= 0.85;
        // keep within bounds
        pos.x = Math.max(20, Math.min(W - 20, pos.x));
        pos.y = Math.max(20, Math.min(H - 20, pos.y));
      }
    }
    // remove velocity props (not needed for rendering)
    for (const p of papers) {
      const pos = State.pos[p.key];
      if (pos) { delete pos.vx; delete pos.vy; }
    }
  }

  function setLayout(name) {
    State.layout = name || "timeline";
    layout();
    render();
    fit();
    renderMinimap();
  }

  // ---- render ----
  function render() {
    if (!State.root) return;
    const ns = "http://www.w3.org/2000/svg";
    const T = theme();
    State.edgeLayer.innerHTML = "";
    State.nodeLayer.innerHTML = "";
    if (State.gridLayer) State.gridLayer.innerHTML = "";

    // ---- grid: year axis vertical lines + depth horizontal labels ----
    if (State.showGrid && State.papers.length) {
      const years = State.papers.map((p) => p.year).filter((y) => y).sort((a, b) => a - b);
      if (years.length) {
        const ymin = years[0], ymax = years[years.length - 1];
        const yspan = Math.max(1, ymax - ymin);
        const padX = 60, padY = 50;
        const W = State.width;
        const depths = State.papers.map((p) => p.depth || 0);
        const dmax = Math.max(2, ...depths);
        const rowH = (State.height - 2 * padY) / Math.max(1, dmax + 1);
        // vertical gridlines every ~5 years (or every year if span < 10)
        const step = yspan > 30 ? 5 : (yspan > 10 ? 2 : 1);
        for (let y = Math.ceil(ymin / step) * step; y <= ymax; y += step) {
          const x = padX + ((y - ymin) / yspan) * (W - 2 * padX);
          const ln = document.createElementNS(ns, "line");
          ln.setAttribute("x1", x); ln.setAttribute("y1", padY - 10);
          ln.setAttribute("x2", x); ln.setAttribute("y2", State.height - padY);
          ln.setAttribute("class", "graph-gridline");
          State.gridLayer.appendChild(ln);
          const lbl = document.createElementNS(ns, "text");
          lbl.setAttribute("x", x); lbl.setAttribute("y", padY - 14);
          lbl.setAttribute("class", "graph-gridlabel");
          lbl.setAttribute("text-anchor", "middle");
          lbl.textContent = y;
          State.gridLayer.appendChild(lbl);
        }
        // depth labels on the left
        for (let d = 0; d <= dmax; d++) {
          const yy = padY + d * rowH;
          const lbl = document.createElementNS(ns, "text");
          lbl.setAttribute("x", padX - 8); lbl.setAttribute("y", yy + 3);
          lbl.setAttribute("class", "graph-depthlabel");
          lbl.textContent = "d=" + d;
          State.gridLayer.appendChild(lbl);
        }
      }
    }

    // ---- edges ----
    const search = (State.search || "").toLowerCase().trim();
    const matchSet = new Set();
    if (search) {
      for (const p of State.papers) {
        const blob = ((p.title || "") + " " + (p.authors || "") + " " + (p.doi || "")).toLowerCase();
        if (blob.includes(search)) matchSet.add(p.key);
      }
    }
    // year-range filter set (built once; nodes loop adds to it but we need
    // it here too for edge filtering — so compute upfront)
    const yearFilterSet = new Set();
    if (State.yearFrom || State.yearTo) {
      for (const p of State.papers) {
        if (State.yearFrom && (!p.year || p.year < State.yearFrom)) continue;
        if (State.yearTo && (!p.year || p.year > State.yearTo)) continue;
        yearFilterSet.add(p.key);
      }
    }
    // map paper key -> relevance for edge weighting
    const relByKey = {};
    for (const p of State.papers) relByKey[p.key] = p.relevance || 0;
    for (const e of State.edgesRaw) {
      if (e.direction === "forward" && !State.showForward) continue;
      if (e.direction === "backward" && !State.showBackward) continue;
      const a = State.pos[e.source], b = State.pos[e.target];
      if (!a || !b) continue;
      // skip edges where either endpoint is filtered out by year-range
      if ((State.yearFrom || State.yearTo) && (!yearFilterSet.has(e.source) || !yearFilterSet.has(e.target))) {
        continue;
      }
      // dim edges that don't touch a matched node when searching
      if (search && !matchSet.has(e.source) && !matchSet.has(e.target)) {
        continue; // skip non-matching edges entirely for clarity
      }
      const path = document.createElementNS(ns, "path");
      // bezier from a to b (or straight line if State.straight)
      let d;
      if (State.straight) {
        d = `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
      } else {
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2 + (a.y - b.y) * 0.2;
        d = `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`;
      }
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      // edge weight by average relevance of endpoints
      const avgRel = ((relByKey[e.source] || 0) + (relByKey[e.target] || 0)) / 2;
      let wClass = "graph-edge-weak";
      if (avgRel > 0.45) wClass = "graph-edge-strong";
      else if (avgRel > 0.25) wClass = "graph-edge-mid";
      if (e.direction === "forward") {
        path.setAttribute("stroke", T.accent);
        path.setAttribute("class", wClass);
        path.setAttribute("marker-end", "url(#arr-forward)");
      } else {
        path.setAttribute("stroke", T.accent2);
        path.setAttribute("class", wClass);
        path.setAttribute("stroke-dasharray", "4 3");
        path.setAttribute("opacity", "0.55");
        path.setAttribute("marker-end", "url(#arr-backward)");
      }
      State.edgeLayer.appendChild(path);
    }

    // nodes
    for (const p of State.papers) {
      const pos = State.pos[p.key];
      if (!pos) continue;
      // year-range filter
      if (State.yearFrom && (!p.year || p.year < State.yearFrom)) continue;
      if (State.yearTo && (!p.year || p.year > State.yearTo)) continue;
      // skip nodes that don't match search (when searching)
      const blob = ((p.title || "") + " " + (p.authors || "") + " " + (p.doi || "")).toLowerCase();
      if (search && !blob.includes(search)) continue;
      const g = document.createElementNS(ns, "g");
      g.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
      g.style.cursor = State.allowNodeDrag ? "grab" : "pointer";
      g.setAttribute("data-key", p.key);
      if (State.selected === p.key) g.setAttribute("class", "graph-node-focus");
      if (search && matchSet.has(p.key)) g.setAttribute("class", (g.getAttribute("class") || "") + " graph-node-match");
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("r", pos.r);
      let fill = T.accent2, stroke = T.lineStrong;
      if (p.seed) { fill = T.accent3; stroke = T.ink; }
      else if (!p.included) { fill = T.lineStrong; stroke = T.lineStrong; }
      // gradient fill for seeds + high-relevance included
      if (p.seed || (p.included && (p.relevance || 0) > 0.4)) {
        const gid = "grad-" + (p.seed ? "seed" : "hot");
        fill = `url(#${gid})`;
      }
      c.setAttribute("fill", fill);
      c.setAttribute("stroke", stroke);
      c.setAttribute("stroke-width", p.seed ? 2 : 1);
      if (!p.included) c.setAttribute("opacity", "0.45");
      g.appendChild(c);

      // label (title only, truncated)
      const t = document.createElementNS(ns, "text");
      t.setAttribute("x", pos.r + 4);
      t.setAttribute("y", 4);
      t.setAttribute("font-size", "10");
      t.setAttribute("fill", T.ink);
      t.textContent = (p.title || "").slice(0, 38) + (p.title && p.title.length > 38 ? "…" : "");
      g.appendChild(t);

      // events
      g.addEventListener("mouseenter", (ev) => showTooltip(p, ev));
      g.addEventListener("mousemove", (ev) => moveTooltip(ev));
      g.addEventListener("mouseleave", hideTooltip);
      g.addEventListener("click", (ev) => {
        if (State.nodeDrag && State.nodeDrag.moved) {
          // suppress click after a drag
          ev.stopPropagation();
          return;
        }
        focusNode(p);
      });
      // node drag (when allowNodeDrag is on)
      g.addEventListener("mousedown", (ev) => {
        if (!State.allowNodeDrag || ev.button !== 0) return;
        ev.stopPropagation();  // prevent pan
        State.nodeDrag = {
          key: p.key,
          startX: ev.clientX,
          startY: ev.clientY,
          origX: State.pos[p.key].x,
          origY: State.pos[p.key].y,
          moved: false,
        };
        g.style.cursor = "grabbing";
      });
      State.nodeLayer.appendChild(g);
    }
    applyTransform();
  }

  // ---- node drag move/up (global listeners) ----
  function initNodeDrag() {
    document.addEventListener("mousemove", (ev) => {
      if (!State.nodeDrag) return;
      const dx = (ev.clientX - State.nodeDrag.startX) / State.view.scale;
      const dy = (ev.clientY - State.nodeDrag.startY) / State.view.scale;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) State.nodeDrag.moved = true;
      const pos = State.pos[State.nodeDrag.key];
      if (pos) {
        pos.x = State.nodeDrag.origX + dx;
        pos.y = State.nodeDrag.origY + dy;
        // update the node group transform directly (fast, no full re-render)
        const gEl = State.nodeLayer.querySelector(`g[data-key="${CSS.escape(State.nodeDrag.key)}"]`);
        if (gEl) gEl.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
        // re-render edges to follow the dragged node
        rerenderEdges();
      }
    });
    document.addEventListener("mouseup", () => {
      if (State.nodeDrag) {
        const gEl = State.nodeLayer.querySelector(`g[data-key="${CSS.escape(State.nodeDrag.key)}"]`);
        if (gEl) gEl.style.cursor = State.allowNodeDrag ? "grab" : "pointer";
        State.nodeDrag = null;
      }
    });
  }

  function rerenderEdges() {
    if (!State.edgeLayer) return;
    const ns = "http://www.w3.org/2000/svg";
    const T = theme();
    State.edgeLayer.innerHTML = "";
    const search = (State.search || "").toLowerCase().trim();
    const matchSet = new Set();
    if (search) {
      for (const p of State.papers) {
        const blob = ((p.title || "") + " " + (p.authors || "") + " " + (p.doi || "")).toLowerCase();
        if (blob.includes(search)) matchSet.add(p.key);
      }
    }
    const yearFilterSet = new Set();
    if (State.yearFrom || State.yearTo) {
      for (const p of State.papers) {
        if (State.yearFrom && (!p.year || p.year < State.yearFrom)) continue;
        if (State.yearTo && (!p.year || p.year > State.yearTo)) continue;
        yearFilterSet.add(p.key);
      }
    }
    const relByKey = {};
    for (const p of State.papers) relByKey[p.key] = p.relevance || 0;
    for (const e of State.edgesRaw) {
      if (e.direction === "forward" && !State.showForward) continue;
      if (e.direction === "backward" && !State.showBackward) continue;
      const a = State.pos[e.source], b = State.pos[e.target];
      if (!a || !b) continue;
      if ((State.yearFrom || State.yearTo) && (!yearFilterSet.has(e.source) || !yearFilterSet.has(e.target))) continue;
      if (search && !matchSet.has(e.source) && !matchSet.has(e.target)) continue;
      const path = document.createElementNS(ns, "path");
      if (State.straight) {
        path.setAttribute("d", `M ${a.x} ${a.y} L ${b.x} ${b.y}`);
      } else {
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2 + (a.y - b.y) * 0.2;
        path.setAttribute("d", `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`);
      }
      path.setAttribute("fill", "none");
      const avgRel = ((relByKey[e.source] || 0) + (relByKey[e.target] || 0)) / 2;
      let wClass = "graph-edge-weak";
      if (avgRel > 0.45) wClass = "graph-edge-strong";
      else if (avgRel > 0.25) wClass = "graph-edge-mid";
      if (e.direction === "forward") {
        path.setAttribute("stroke", T.accent);
        path.setAttribute("class", wClass);
        path.setAttribute("marker-end", "url(#arr-forward)");
      } else {
        path.setAttribute("stroke", T.accent2);
        path.setAttribute("class", wClass);
        path.setAttribute("stroke-dasharray", "4 3");
        path.setAttribute("marker-end", "url(#arr-backward)");
      }
      State.edgeLayer.appendChild(path);
    }
  }

  function showTooltip(p, ev) {
    if (!State.tooltip) return;
    const T = theme();
    State.tooltip.innerHTML = "";
    const h = el("h4", {}, p.title || "(untitled)");
    const meta = el("div", { class: "meta" });
    meta.innerHTML =
      `${p.authors ? global.CSUtils.esc(p.authors.split(";")[0]) + " et al. · " : ""}` +
      `${p.year || "—"} · ${p.num_citations || 0} cites · rel ${p.relevance || 0}` +
      `${p.doi ? " · " + global.CSUtils.esc(p.doi) : ""}`;
    State.tooltip.appendChild(h);
    State.tooltip.appendChild(meta);
    if (State.showAbstractsOnHover && p.abstract) {
      const abs = el("div", { class: "abs" });
      abs.textContent = global.CSUtils.truncate(p.abstract, 280);
      State.tooltip.appendChild(abs);
    }
    State.tooltip.classList.remove("hidden");
    moveTooltip(ev);
  }
  function moveTooltip(ev) {
    if (!State.tooltip) return;
    const r = State.svg.parentElement.getBoundingClientRect();
    let x = ev.clientX - r.left + 12;
    let y = ev.clientY - r.top + 12;
    if (x > r.width - 340) x = ev.clientX - r.left - 330;
    if (y > r.height - 160) y = ev.clientY - r.top - 160;
    State.tooltip.style.left = x + "px";
    State.tooltip.style.top = y + "px";
  }
  function hideTooltip() {
    if (State.tooltip) State.tooltip.classList.add("hidden");
  }

  function focusNode(p) {
    State.selected = p.key;
    // dispatch event so app.js can show details
    document.dispatchEvent(new CustomEvent("cs:graph-focus", { detail: p }));
  }

  // ---- pan / zoom ----
  function applyTransform() {
    if (!State.root) return;
    const { tx, ty, scale } = State.view;
    State.root.setAttribute("transform", `translate(${tx} ${ty}) scale(${scale})`);
  }
  function panStart(ev) {
    if (ev.button !== 0) return;
    State.drag = { x: ev.clientX, y: ev.clientY, tx: State.view.tx, ty: State.view.ty };
    window.addEventListener("mousemove", panMove);
    window.addEventListener("mouseup", panEnd);
    document.body.style.cursor = "grabbing";
  }
  function panMove(ev) {
    if (!State.drag) return;
    State.view.tx = State.drag.tx + (ev.clientX - State.drag.x);
    State.view.ty = State.drag.ty + (ev.clientY - State.drag.y);
    applyTransform();
  }
  function panEnd() {
    State.drag = null;
    window.removeEventListener("mousemove", panMove);
    window.removeEventListener("mouseup", panEnd);
    document.body.style.cursor = "";
  }
  function onWheel(ev) {
    ev.preventDefault();
    const delta = -ev.deltaY * 0.0015;
    const ns2 = "http://www.w3.org/2000/svg";
    const rect = State.svg.getBoundingClientRect();
    const cx = ev.clientX - rect.left;
    const cy = ev.clientY - rect.top;
    const newScale = Math.max(0.25, Math.min(4, State.view.scale * (1 + delta)));
    // zoom around cursor
    const k = newScale / State.view.scale;
    State.view.tx = cx - (cx - State.view.tx) * k;
    State.view.ty = cy - (cy - State.view.ty) * k;
    State.view.scale = newScale;
    applyTransform();
  }
  function fit() {
    if (!State.papers.length) return;
    // compute bounding box of node positions
    const xs = Object.values(State.pos).map((p) => p.x);
    const ys = Object.values(State.pos).map((p) => p.y);
    if (!xs.length) return;
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const w = maxX - minX + 120, h = maxY - minY + 120;
    const sx = State.width / w, sy = State.height / h;
    State.view.scale = Math.min(sx, sy, 1.5);
    State.view.tx = -minX * State.view.scale + (State.width - w * State.view.scale) / 2;
    State.view.ty = -minY * State.view.scale + (State.height - h * State.view.scale) / 2;
    applyTransform();
  }

  function setData(papers, edges) {
    State.papers = papers || [];
    State.edgesRaw = edges || [];
    layout();
    render();
    fit();
    renderMinimap();
    if (!State._selectInit) {
      initSelect();
      State._selectInit = true;
    }
  }

  function setOption(key, val) {
    if (key === "forward") State.showForward = val;
    if (key === "backward") State.showBackward = val;
    if (key === "grid") State.showGrid = val;
    if (key === "straight") State.straight = val;
    if (key === "sizeMode") { State.sizeMode = val; layout(); render(); return; }
    if (key === "abstracts") State.showAbstractsOnHover = val;
    if (key === "drag") {
      State.allowNodeDrag = val;
      const canvas = document.getElementById("graph-canvas");
      if (canvas) canvas.classList.toggle("drag-mode", val);
      render();
      return;
    }
    if (key === "search") { State.search = val || ""; }
    render();
  }

  function setSearch(s) { State.search = s || ""; render(); }

  function setYearRange(from, to) {
    State.yearFrom = from ? +from : null;
    State.yearTo = to ? +to : null;
    render();
  }

  function focusByKey(key) { State.selected = key; render(); }

  function rerender() {
    // re-read theme colours and redraw (e.g. on dark-mode toggle)
    if (!State.svg) return;
    // re-create arrow markers with new colours
    const ns = "http://www.w3.org/2000/svg";
    const defs = State.svg.querySelector("defs");
    if (defs) defs.innerHTML = "";
    const T = theme();
    const mk = (id, color) => {
      const m = document.createElementNS(ns, "marker");
      m.setAttribute("id", id);
      m.setAttribute("viewBox", "0 0 10 10");
      m.setAttribute("refX", "9"); m.setAttribute("refY", "5");
      m.setAttribute("markerWidth", "6"); m.setAttribute("markerHeight", "6");
      m.setAttribute("orient", "auto-start-reverse");
      const p = document.createElementNS(ns, "path");
      p.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      p.setAttribute("fill", color);
      m.appendChild(p);
      defs.appendChild(m);
    };
    mk("arr-forward", T.accent);
    mk("arr-backward", T.accent2);
    // recreate gradients with new theme colours
    const mkGrad = (id, c1, c2) => {
      const rad = document.createElementNS(ns, "radialGradient");
      rad.setAttribute("id", id); rad.setAttribute("cx", "0.35"); rad.setAttribute("cy", "0.35"); rad.setAttribute("r", "0.7");
      const s1 = document.createElementNS(ns, "stop"); s1.setAttribute("offset", "0%"); s1.setAttribute("stop-color", c1);
      const s2 = document.createElementNS(ns, "stop"); s2.setAttribute("offset", "100%"); s2.setAttribute("stop-color", c2);
      rad.appendChild(s1); rad.appendChild(s2);
      defs.appendChild(rad);
    };
    mkGrad("grad-seed", T.accent3, T.accent);
    mkGrad("grad-hot", T.accent, T.accent2);
    render();
  }

  // ---- drag-select (box selection of multiple nodes) ----
  let selectMode = false;
  let selectDrag = null;
  let selectedNodes = new Set();
  let selectRect = null;
  let selBar = null;

  function setSelectMode(on) {
    selectMode = on;
    const canvas = document.getElementById("graph-canvas");
    if (canvas) canvas.classList.toggle("select-mode", on);
    if (!on) {
      clearSelection();
    }
  }

  function clearSelection() {
    selectedNodes.clear();
    document.querySelectorAll("#graph-svg .graph-node-selected").forEach((n) => n.classList.remove("graph-node-selected"));
    updateSelBar();
  }

  function updateSelBar() {
    if (!selBar) {
      selBar = document.createElement("div");
      selBar.className = "graph-sel-bar hidden";
      selBar.innerHTML = '<span class="cnt">0 selected</span><button class="btn tiny primary" data-sel-export="ris">RIS</button><button class="btn tiny ghost" data-sel-export="csv">CSV</button><button class="btn tiny ghost" data-sel-clear>✕</button>';
      const canvas = document.getElementById("graph-canvas");
      if (canvas) canvas.appendChild(selBar);
      selBar.querySelector("[data-sel-clear]").addEventListener("click", clearSelection);
      selBar.querySelector('[data-sel-export="ris"]').addEventListener("click", () => exportSelection("ris"));
      selBar.querySelector('[data-sel-export="csv"]').addEventListener("click", () => exportSelection("csv"));
    }
    const cnt = selBar.querySelector(".cnt");
    cnt.textContent = selectedNodes.size + " selected";
    selBar.classList.toggle("hidden", selectedNodes.size === 0);
  }

  function exportSelection(fmt) {
    if (selectedNodes.size === 0) return;
    // dispatch event so app.js can do the bulk export with the run's context
    document.dispatchEvent(new CustomEvent("cs:graph-export-selection", { detail: { keys: Array.from(selectedNodes), format: fmt } }));
  }

  function initSelect() {
    const svg = State.svg;
    if (!svg) return;
    svg.addEventListener("mousedown", (ev) => {
      if (!selectMode) return;
      if (ev.target !== State.bg && ev.target.tagName !== "rect") return;
      const rect = svg.getBoundingClientRect();
      selectDrag = { x0: ev.clientX - rect.left, y0: ev.clientY - rect.top, x1: 0, y1: 0 };
      // create overlay rect
      selectRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      selectRect.setAttribute("class", "graph-select-overlay");
      State.root.appendChild(selectRect);
      ev.preventDefault();
    });
    document.addEventListener("mousemove", (ev) => {
      if (!selectDrag || !selectRect) return;
      const rect = svg.getBoundingClientRect();
      selectDrag.x1 = ev.clientX - rect.left;
      selectDrag.y1 = ev.clientY - rect.top;
      const x = Math.min(selectDrag.x0, selectDrag.x1);
      const y = Math.min(selectDrag.y0, selectDrag.y1);
      const w = Math.abs(selectDrag.x1 - selectDrag.x0);
      const h = Math.abs(selectDrag.y1 - selectDrag.y0);
      // convert screen coords to graph coords (inverse of view transform)
      const { tx, ty, scale } = State.view;
      const gx = (x - tx) / scale;
      const gy = (y - ty) / scale;
      const gw = w / scale;
      const gh = h / scale;
      selectRect.setAttribute("x", gx);
      selectRect.setAttribute("y", gy);
      selectRect.setAttribute("width", gw);
      selectRect.setAttribute("height", gh);
    });
    document.addEventListener("mouseup", () => {
      if (!selectDrag || !selectRect) return;
      // find nodes inside the rect
      const x = Math.min(selectDrag.x0, selectDrag.x1);
      const y = Math.min(selectDrag.y0, selectDrag.y1);
      const w = Math.abs(selectDrag.x1 - selectDrag.x0);
      const h = Math.abs(selectDrag.y1 - selectDrag.y0);
      if (w > 5 && h > 5) {
        const rect = svg.getBoundingClientRect();
        const { tx, ty, scale } = State.view;
        const gx0 = (x - tx) / scale, gy0 = (y - ty) / scale;
        const gx1 = (x + w - tx) / scale, gy1 = (y + h - ty) / scale;
        for (const p of State.papers) {
          const pos = State.pos[p.key];
          if (!pos) continue;
          if (pos.x >= gx0 && pos.x <= gx1 && pos.y >= gy0 && pos.y <= gy1) {
            selectedNodes.add(p.key);
          }
        }
        // highlight them
        document.querySelectorAll("#graph-svg g[data-key]").forEach((g) => {
          if (selectedNodes.has(g.getAttribute("data-key"))) g.classList.add("graph-node-selected");
        });
        updateSelBar();
      }
      selectRect.remove();
      selectRect = null;
      selectDrag = null;
    });
  }

  // ---- minimap ----
  function renderMinimap() {
    const canvas = document.getElementById("graph-canvas");
    if (!canvas) return;
    let mm = canvas.querySelector(".graph-minimap");
    if (!mm) {
      mm = document.createElement("div");
      mm.className = "graph-minimap";
      mm.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 90"></svg>';
      canvas.appendChild(mm);
      // click-to-pan: clicking the minimap recenters the graph viewport
      mm.addEventListener("click", (ev) => {
        const r = mm.getBoundingClientRect();
        const cx = (ev.clientX - r.left) / r.width;
        const cy = (ev.clientY - r.top) / r.height;
        if (!State.papers.length) return;
        const xs = Object.values(State.pos).map((p) => p.x);
        const ys = Object.values(State.pos).map((p) => p.y);
        if (!xs.length) return;
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        const targetX = minX + cx * (maxX - minX);
        const targetY = minY + cy * (maxY - minY);
        // center the viewport on (targetX, targetY)
        State.view.tx = State.width / 2 - targetX * State.view.scale;
        State.view.ty = State.height / 2 - targetY * State.view.scale;
        applyTransform();
        updateMinimapViewport();
      });
    }
    const svg = mm.querySelector("svg");
    svg.innerHTML = "";
    if (!State.papers.length) return;
    const xs = Object.values(State.pos).map((p) => p.x);
    const ys = Object.values(State.pos).map((p) => p.y);
    if (!xs.length) return;
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const sx = 130 / Math.max(1, maxX - minX);
    const sy = 80 / Math.max(1, maxY - minY);
    const ns = "http://www.w3.org/2000/svg";
    for (const p of State.papers) {
      const pos = State.pos[p.key];
      if (!pos) continue;
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", 5 + (pos.x - minX) * sx);
      c.setAttribute("cy", 5 + (pos.y - minY) * sy);
      c.setAttribute("r", p.seed ? 2.5 : 1.5);
      c.setAttribute("class", "mm-node" + (p.seed ? " seed" : ""));
      svg.appendChild(c);
    }
    // viewport indicator rect (draggable to pan)
    const vp = document.createElementNS(ns, "rect");
    vp.setAttribute("class", "mm-viewport");
    const vx = -State.view.tx / State.view.scale;
    const vy = -State.view.ty / State.view.scale;
    const vw = State.width / State.view.scale;
    const vh = State.height / State.view.scale;
    vp.setAttribute("x", 5 + (vx - minX) * sx);
    vp.setAttribute("y", 5 + (vy - minY) * sy);
    vp.setAttribute("width", Math.max(4, vw * sx));
    vp.setAttribute("height", Math.max(3, vh * sy));
    // drag the viewport rect to pan
    vp.addEventListener("mousedown", (ev) => {
      ev.stopPropagation();
      const mmRect = mm.getBoundingClientRect();
      const mmStartX = ev.clientX - mmRect.left;
      const mmStartY = ev.clientY - mmRect.top;
      const origTx = State.view.tx;
      const origTy = State.view.ty;
      const onMove = (e2) => {
        const dx = (e2.clientX - mmRect.left - mmStartX) / sx * State.view.scale;
        const dy = (e2.clientY - mmRect.top - mmStartY) / sy * State.view.scale;
        State.view.tx = origTx - dx;
        State.view.ty = origTy - dy;
        applyTransform();
        updateMinimapViewport();
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
    svg.appendChild(vp);
  }

  function updateMinimapViewport() {
    const mm = document.querySelector(".graph-minimap");
    if (!mm) return;
    const vp = mm.querySelector(".mm-viewport");
    if (!vp) return;
    const xs = Object.values(State.pos).map((p) => p.x);
    const ys = Object.values(State.pos).map((p) => p.y);
    if (!xs.length) return;
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const sx = 130 / Math.max(1, maxX - minX);
    const sy = 80 / Math.max(1, maxY - minY);
    const vx = -State.view.tx / State.view.scale;
    const vy = -State.view.ty / State.view.scale;
    const vw = State.width / State.view.scale;
    const vh = State.height / State.view.scale;
    vp.setAttribute("x", 5 + (vx - minX) * sx);
    vp.setAttribute("y", 5 + (vy - minY) * sy);
    vp.setAttribute("width", Math.max(4, vw * sx));
    vp.setAttribute("height", Math.max(3, vh * sy));
  }

  global.CSGraph = { init, setData, setOption, setSearch, setYearRange, setLayout, focusByKey, fit, relayout: () => { layout(); render(); fit(); renderMinimap(); }, rerender, setSelectMode, clearSelection, getSelection: () => Array.from(selectedNodes) };
})(window);
