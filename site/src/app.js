/* Greatest of All Time — dashboard. Renders every panel from window.FG (built by research/scripts/build_data.py). */
(function () {
  "use strict";
  const FG = window.FG;
  const d3 = window.d3;
  const PR = FG.profile;  // Ronaldo's match-by-match detail

  // ---------- helpers ----------
  const fmtInt = d3.format(",");
  const fmt1 = d3.format(",.1f");
  const fmt2 = d3.format(".2f");
  const pct0 = d3.format(".0%");
  const byId = (id) => document.getElementById(id);
  const P = Object.fromEntries(FG.players.map((p) => [p.id, p]));
  const METRICS = FG.metrics;
  const MI = Object.fromEntries(METRICS.map((m) => [m.id, m]));
  const FAM = FG.families;
  const V = FG.values, VN = FG.valueNotes;
  const AS_OF = new Date("2026-10-30");
  const ageNow = (p) => (AS_OF - new Date(p.born)) / (365.2425 * 864e5);
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "style") n.setAttribute("style", v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k)));
    return n;
  }
  function fmtVal(v, m) {
    if (v == null || Number.isNaN(v)) return "—";
    if (m && m.dec) return d3.format(`,.${m.dec}f`)(v);
    return fmtInt(v);
  }
  function onResize(el, fn) {
    let w = 0, t;
    new ResizeObserver((entries) => {
      const nw = Math.round(entries[0].contentRect.width);
      if (nw && Math.abs(nw - w) > 2) { w = nw; clearTimeout(t); t = setTimeout(() => fn(nw), 60); }
    }).observe(el);
  }
  function table(container, head, rows) {
    const t = h("table", { class: "data" });
    t.append(h("thead", null, h("tr", null, head.map((c) => h("th", { scope: "col" }, c)))));
    t.append(h("tbody", null, rows.map((r) => h("tr", null, r.map((c, i) => i === 0 ? h("th", { scope: "row" }, c) : h("td", null, c))))));
    container.textContent = "";
    container.append(t);
  }
  function segment(box, options, current, onPick) {
    box.textContent = "";
    for (const [id, label] of options) {
      box.append(h("button", { type: "button", "aria-pressed": String(current === id), "data-id": id, onclick: () => onPick(id) }, label));
    }
  }
  const syncSeg = (box, current) => box.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === current)));

  // ---------- tooltip ----------
  const tip = byId("tip");
  function showTip(evt, title, rows, note) {
    tip.textContent = "";
    tip.append(h("div", { class: "t-h" }, title));
    for (const r of rows || []) tip.append(h("div", { class: "t-row" }, h("span", { class: "key", style: `--c:${r.c || "var(--peer)"}` }), h("span", { class: "n" }, r.name), h("span", { class: "v" }, r.v)));
    if (note) tip.append(h("div", { class: "t-note" }, note));
    tip.classList.add("on");
    moveTip(evt);
  }
  function moveTip(evt) {
    let x, y;
    if (evt && evt.clientX != null && evt.type !== "focus") { x = evt.clientX; y = evt.clientY; }
    else if (evt && evt.target && evt.target.getBoundingClientRect) { const b = evt.target.getBoundingClientRect(); x = b.left + b.width / 2; y = b.top; }
    else return;
    const tw = tip.offsetWidth, th = tip.offsetHeight, vw = window.innerWidth;
    let left = x + 14, top = y - th - 12;
    if (left + tw > vw - 8) left = x - tw - 14;
    if (left < 8) left = 8;
    if (top < 8) top = y + 16;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  const hideTip = () => tip.classList.remove("on");
  window.addEventListener("scroll", hideTip, { passive: true });
  const hover = (sel, show) => sel.on("pointerenter", show).on("pointermove", moveTip).on("pointerleave", hideTip).on("focus", show).on("blur", hideTip);

  // ---------- state ----------
  const NORMS = [["ratio", "Share of best"], ["minmax", "Min–max"], ["z", "Z-score"], ["rank", "Rank"]];
  const NORM_LABEL = Object.fromEntries(NORMS);
  const NORM_HINT = {
    ratio: "Value as a share of the best value in the group (distance to a reference).",
    minmax: "Rescaled so the lowest value is 0 and the highest 100.",
    z: "Standardised: distance from the group mean in standard deviations. The overall score is the mean z-score.",
    rank: "Rank position rescaled to 0–100; ties share the better rank.",
  };
  const GROUPS = [["all", "All 21"], ["legends", "Legends"], ["modern", "Modern era"]];
  const GROUP_HINT = { all: "All 21 players.", legends: "Careers that began before 1990, plus Ronaldo.", modern: "Careers that began in 1990 or later." };
  const inGroup = (p, g) => g === "all" || p.role === "cr" || (g === "legends" ? p.debut < 1990 : p.debut >= 1990);
  const coreWeights = () => Object.fromEntries(METRICS.map((m) => [m.id, FG.presets[0].weights[m.id] || 0]));
  const state = { group: "all", norm: "ratio", preset: FG.presets[0].id, w: coreWeights(), focus: null, explore: "goals", alltime: "career", msort: null, mdir: -1, mmode: "values", ageHidden: new Set() };

  const players = () => FG.players.filter((p) => inGroup(p, state.group));
  const selected = () => Object.entries(state.w).filter(([, w]) => w > 0);

  // ---------- scoring (OECD/JRC 2008 normalisations, linear aggregation) ----------
  const cache = new Map();
  function norm(method, mid, group) {
    const key = `${method}|${mid}|${state.group}`;
    if (cache.has(key)) return cache.get(key);
    const vals = group.map((p) => [p.id, V[p.id][mid]]).filter(([, v]) => v != null);
    const out = {};
    if (vals.length) {
      const xs = vals.map((d) => d[1]);
      const max = d3.max(xs), min = d3.min(xs), mean = d3.mean(xs), sd = d3.deviation(xs) || 0;
      if (method === "ratio") for (const [id, v] of vals) out[id] = max ? 100 * v / max : 0;
      else if (method === "minmax") for (const [id, v] of vals) out[id] = max > min ? 100 * (v - min) / (max - min) : 100;
      else if (method === "z") for (const [id, v] of vals) out[id] = sd ? (v - mean) / sd : 0;
      else {
        const sorted = vals.slice().sort((a, b) => b[1] - a[1]), n = sorted.length;
        sorted.forEach(([id, v], i) => { let r = i; while (r > 0 && sorted[r - 1][1] === v) r--; out[id] = n > 1 ? 100 * (n - 1 - r) / (n - 1) : 100; });
      }
    }
    cache.set(key, out);
    return out;
  }
  function composite(method, weights, group) {
    const sel = Object.entries(weights).filter(([, w]) => w > 0);
    const S = sel.map(([mid]) => norm(method, mid, group));
    const ranked = [], missing = [];
    for (const p of group) {
      let v = 0, ww = 0;
      const lack = [];
      sel.forEach(([mid, w], j) => { const s = S[j][p.id]; if (s == null) lack.push(mid); else { v += w * s; ww += w; } });
      if (!ww) { missing.push(p.id); continue; }
      ranked.push({ id: p.id, score: v / ww, partial: lack.length ? lack : null });
    }
    ranked.sort((a, b) => b.score - a.score);
    return { sel, ranked, missing };
  }
  // Monte Carlo uncertainty analysis (Saisana, Saltelli & Tarantola 2005): random weights (flat Dirichlet) x random normalisation
  const simCache = new Map();
  function simulate(group, sel, runs = 5000) {
    const key = `${state.group}|${sel.map(([m]) => m).join(",")}`;
    if (simCache.has(key)) return simCache.get(key);
    if (!sel.length) return null;
    const methods = NORMS.map((n) => n[0]);
    const T = methods.map((mt) => sel.map(([mid]) => norm(mt, mid, group)));
    const ids = group.filter((p) => sel.some(([mid]) => V[p.id][mid] != null)).map((p) => p.id);
    const ranks = Object.fromEntries(ids.map((id) => [id, new Uint8Array(runs)]));
    let seed = 20261030;
    const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return (seed + 0.5) / 4294967296; };
    const comp = new Array(ids.length);
    for (let k = 0; k < runs; k++) {
      const t = T[Math.floor(rnd() * methods.length)];
      const w = sel.map(() => -Math.log(rnd()));
      for (let i = 0; i < ids.length; i++) {
        let v = 0, ww = 0;
        for (let j = 0; j < w.length; j++) { const s = t[j][ids[i]]; if (s != null) { v += w[j] * s; ww += w[j]; } }
        comp[i] = [i, v / ww];
      }
      comp.sort((a, b) => b[1] - a[1]);
      for (let r = 0; r < comp.length; r++) ranks[ids[comp[r][0]]][k] = r + 1;
    }
    const out = ids.map((id) => {
      const a = Array.from(ranks[id]).sort((x, y) => x - y);
      return { id, p1: a.filter((r) => r === 1).length / runs, median: d3.quantileSorted(a, 0.5), p5: d3.quantileSorted(a, 0.05), p95: d3.quantileSorted(a, 0.95) };
    }).sort((a, b) => a.median - b.median || b.p1 - a.p1 || a.p5 - b.p5);
    simCache.set(key, out);
    return out;
  }
  const fmtScore = (s) => state.norm === "z" ? (s >= 0 ? "+" : "−") + fmt2(Math.abs(s)) : fmt1(s);
  const colorOf = (pid) => (P[pid].role === "cr" ? "var(--cr7)" : pid === focusId() ? "var(--sel)" : "var(--peer)");
  let current = null;  // latest composite
  const focusId = () => (state.focus && players().some((p) => p.id === state.focus) ? state.focus : current && current.ranked[0] ? current.ranked[0].id : "ronaldo");
  function leaders(mid, group) {
    const vals = group.map((p) => [p.id, V[p.id][mid]]).filter(([, v]) => v != null);
    const best = d3.max(vals, (d) => d[1]);
    return { ids: vals.filter(([, v]) => v === best).map(([id]) => id), best, rankOf: (id) => { const v = V[id][mid]; return v == null ? null : 1 + vals.filter(([, x]) => x > v).length; }, n: vals.length };
  }
  function selectPlayer(id) { state.focus = state.focus === id ? null : id; update(); }

  // ---------- settings rail ----------
  function renderSettings() {
    segment(byId("group-seg"), GROUPS, state.group, (id) => { state.group = id; update(); });
    segment(byId("norm-seg"), NORMS, state.norm, (id) => { state.norm = id; update(); });
    const pbox = byId("presets");
    for (const pr of FG.presets) pbox.append(h("button", { class: "chip", type: "button", "data-p": pr.id, onclick: () => { state.preset = pr.id; for (const m of METRICS) state.w[m.id] = pr.weights[m.id] || 0; update(); } }, pr.label));
    const list = byId("crit-list");
    for (const f of FAM) {
      const fs = h("fieldset", { class: "fam" }, h("legend", null, f.label));
      for (const m of METRICS.filter((x) => x.family === f.id)) {
        const name = `w-${m.id}`;
        const wt = h("div", { class: "wt", role: "radiogroup", "aria-label": `Weight for ${m.label}` });
        for (const [v, lab] of [[0, "Off"], [1, "1×"], [2, "2×"]]) {
          wt.append(h("label", { for: `${name}-${v}`, title: `${m.label}: ${lab}` },
            h("input", { type: "radio", name, id: `${name}-${v}`, value: String(v), onchange: () => { state.w[m.id] = v; state.preset = null; update(); } }), h("span", null, lab)));
        }
        fs.append(h("div", { class: "crit", "data-m": m.id }, h("div", { class: "c-name" }, m.label, h("small", null, m.desc)), wt));
      }
      list.append(fs);
    }
    byId("reset").addEventListener("click", () => { Object.assign(state, { group: "all", norm: "ratio", preset: FG.presets[0].id, w: coreWeights(), focus: null }); update(); });
    if (window.matchMedia("(max-width: 1080px)").matches) byId("settings").open = false;
  }
  function syncSettings() {
    syncSeg(byId("group-seg"), state.group);
    syncSeg(byId("norm-seg"), state.norm);
    byId("group-hint").textContent = GROUP_HINT[state.group];
    byId("norm-hint").textContent = NORM_HINT[state.norm];
    byId("presets").querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.p === state.preset)));
    for (const m of METRICS) {
      const el = document.getElementById(`w-${m.id}-${state.w[m.id] || 0}`);
      if (el) el.checked = true;
      const row = document.querySelector(`.crit[data-m="${m.id}"]`);
      if (row) row.classList.toggle("off", !state.w[m.id]);
    }
  }

  // ---------- ranking ----------
  function renderRanking() {
    const { sel, ranked, missing } = current;
    byId("rank-sub").textContent = sel.length ? `Weighted mean of ${sel.length} normalised criteria (${NORM_LABEL[state.norm].toLowerCase()}).` : "Select at least one criterion.";
    const stat = byId("rank-stat");
    stat.textContent = "";
    if (sel.length) {
      const top = ranked[0];
      stat.append(h("span", null, "First: ", h("b", null, P[top.id].name)), h("span", null, "Score: ", h("b", null, fmtScore(top.score))),
        h("span", null, "Players: ", h("b", null, String(ranked.length))));
    }
    const list = byId("rank-list");
    list.textContent = "";
    const lo = d3.min(ranked, (r) => r.score), hi = d3.max(ranked, (r) => r.score);
    const width = (s) => state.norm === "z" ? (hi > lo ? 4 + 96 * (s - lo) / (hi - lo) : 100) : Math.max(0, s);
    const fid = focusId();
    ranked.forEach((r, i) => {
      const p = P[r.id];
      list.append(h("li", { class: "rank-row" + (p.role === "cr" ? " me" : "") + (r.id === fid && state.focus ? " sel" : "") },
        h("span", { class: "rk" }, String(i + 1)),
        h("button", { type: "button", class: "nm", title: r.partial ? `${p.name}: scored without ${r.partial.map((m) => MI[m].short).join(", ")}` : `Select ${p.name}`, onclick: () => selectPlayer(r.id) }, p.name + (r.partial ? " †" : "")),
        h("span", { class: "bar", "aria-hidden": "true" }, h("i", { style: `width:${width(r.score).toFixed(1)}%;--c:${colorOf(r.id)}` })),
        h("span", { class: "sc" }, fmtScore(r.score))));
    });
    const notes = [];
    const partial = ranked.filter((r) => r.partial);
    if (partial.length) notes.push(`† Scored on the criteria he has data for: ${partial.map((r) => `${P[r.id].short} (no ${r.partial.map((m) => MI[m].short).join(", ")})`).join("; ")}.`);
    if (missing.length && sel.length) notes.push(`No data for any selected criterion: ${missing.map((id) => P[id].short).join(", ")}.`);
    byId("na-note").textContent = notes.join(" ");
  }

  // ---------- rank stability ----------
  function renderStability(sim) {
    const el = byId("chart-stab"), stat = byId("stab-stat");
    stat.textContent = "";
    el.textContent = "";
    if (!sim || sim.length < 2) { el.append(h("p", { class: "hint" }, "Select at least one criterion.")); return; }
    for (const s of sim.filter((x) => x.p1 >= 0.005).slice(0, 3)) stat.append(h("span", null, `${P[s.id].short} first in `, h("b", null, pct0(s.p1)), " of runs"));
    const W = el.clientWidth || 500, n = sim.length, rh = 21, m = { t: 30, r: 54, b: 6, l: 128 };
    const Ht = m.t + m.b + n * rh;
    const svg = d3.select(el).append("svg").attr("width", W).attr("height", Ht).attr("role", "img").attr("aria-label", "Median rank and 90% interval for each player across 5,000 simulations");
    const x = d3.scaleLinear().domain([1, n]).range([m.l + 8, W - m.r]);
    const ticks = [1, ...d3.range(5, n + 1, 5)];
    svg.append("g").attr("transform", `translate(0,${m.t - 6})`).call(d3.axisTop(x).tickValues(ticks).tickFormat(d3.format("d")).tickSize(-(n * rh)))
      .call((g) => g.select(".domain").remove()).call((g) => g.selectAll(".tick line").attr("stroke", "var(--grid)"));
    const fid = focusId();
    sim.forEach((s, i) => {
      const cy = m.t + i * rh + rh / 2, c = colorOf(s.id), strong = P[s.id].role === "cr" || s.id === fid;
      svg.append("text").attr("x", m.l - 8).attr("y", cy + 4).attr("text-anchor", "end").attr("class", strong ? "lbl-strong" : "lbl-2").text(P[s.id].name);
      svg.append("line").attr("x1", x(s.p5)).attr("x2", x(Math.max(s.p95, s.p5 + 0.001))).attr("y1", cy).attr("y2", cy).style("stroke", c).attr("stroke-width", 3).attr("stroke-linecap", "round").style("opacity", 0.55);
      svg.append("circle").attr("cx", x(s.median)).attr("cy", cy).attr("r", 5).style("fill", c).style("stroke", "var(--surface)").attr("stroke-width", 2);
      svg.append("text").attr("x", W - m.r + 8).attr("y", cy + 4).attr("class", strong ? "lbl-strong" : "lbl-2").text(s.p1 >= 0.005 ? pct0(s.p1) : "");
      const hit = svg.append("rect").attr("x", 0).attr("y", cy - rh / 2).attr("width", W).attr("height", rh).attr("fill", "transparent").attr("tabindex", "0").style("cursor", "pointer");
      hover(hit, (e) => showTip(e, P[s.id].name, [{ c, name: "Median rank", v: String(s.median) }, { c, name: "90% of runs", v: `${s.p5}–${s.p95}` }, { c, name: "Ranked first", v: pct0(s.p1) }], null));
      hit.on("click", () => selectPlayer(s.id));
    });
    svg.append("text").attr("x", m.l + 8).attr("y", 4).attr("class", "lbl-2").style("font-size", "11px").text("Rank");
    svg.append("text").attr("x", W - m.r + 8).attr("y", 4).attr("class", "lbl-2").style("font-size", "11px").text("Top");
    table(byId("tbl-stab"), ["Player", "Median rank", "5th pct", "95th pct", "Ranked first"], sim.map((s) => [P[s.id].name, String(s.median), String(s.p5), String(s.p95), pct0(s.p1)]));
  }

  // ---------- matrix ----------
  function renderMatrix(group) {
    const tbl = byId("matrix-table");
    const scores = Object.fromEntries(METRICS.map((m) => [m.id, norm(state.norm, m.id, group)]));
    const shade = (mid, id) => {
      const s = scores[mid][id];
      if (s == null) return null;
      if (state.norm !== "z") return s;
      const xs = Object.values(scores[mid]), lo = d3.min(xs), hi = d3.max(xs);
      return hi > lo ? 100 * (s - lo) / (hi - lo) : 100;
    };
    const order = new Map(current.ranked.map((r, i) => [r.id, i]));
    const rows = group.slice().sort((a, b) => {
      if (state.msort) { const va = V[a.id][state.msort], vb = V[b.id][state.msort]; return ((vb ?? -Infinity) - (va ?? -Infinity)) * (state.mdir === -1 ? 1 : -1); }
      return (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99);
    });
    const best = Object.fromEntries(METRICS.map((m) => [m.id, leaders(m.id, group).best]));
    tbl.textContent = "";
    const thr = h("tr", null, h("th", { scope: "col" }, h("span", { class: "sr-only" }, "Player")));
    for (const m of METRICS) {
      const fam = FAM.find((f) => f.id === m.family);
      const b = h("button", { type: "button", title: `${m.label}. ${m.desc}`, onclick: () => { if (state.msort === m.id) state.mdir *= -1; else { state.msort = m.id; state.mdir = -1; } renderMatrix(players()); } },
        h("span", { class: "fam-tag" }, (state.w[m.id] ? "● " : "") + (fam ? fam.short : "")), m.short);
      if (state.msort === m.id) b.setAttribute("aria-sort", state.mdir === -1 ? "descending" : "ascending");
      thr.append(h("th", { scope: "col" }, b));
    }
    tbl.append(h("thead", null, thr));
    const tb = h("tbody");
    const fid = focusId();
    for (const p of rows) {
      const tr = h("tr", { class: [p.role === "cr" ? "me" : "", p.id === fid && state.focus ? "sel" : ""].join(" ").trim() || null },
        h("th", { scope: "row" }, h("button", { type: "button", style: `--c:${colorOf(p.id)}`, onclick: () => selectPlayer(p.id) }, p.name)));
      for (const m of METRICS) {
        const v = V[p.id][m.id], note = VN[p.id] && VN[p.id][m.id];
        if (v == null) { tr.append(h("td", { class: "na", title: `${p.name}: ${note || "no comparable data"}` }, "—")); continue; }
        const s = shade(m.id, p.id), raw = scores[m.id][p.id];
        const td = h("td", { class: (v === best[m.id] ? "lead " : "") + (s >= 58 ? "hi" : ""), style: `--cell: color-mix(in oklab, var(--seq-hi) ${s.toFixed(1)}%, var(--seq-lo))`, tabindex: "0" },
          state.mmode === "values" ? fmtVal(v, m) : (state.norm === "z" ? fmtScore(raw) : fmtInt(Math.round(raw))));
        const show = (e) => showTip(e, p.name, [{ c: colorOf(p.id), name: m.label, v: fmtVal(v, m) }, { c: "var(--seq-hi)", name: `Score (${NORM_LABEL[state.norm].toLowerCase()})`, v: state.norm === "z" ? fmtScore(raw) : fmt1(raw) }], note || m.desc);
        td.addEventListener("pointerenter", show); td.addEventListener("pointermove", moveTip); td.addEventListener("pointerleave", hideTip);
        td.addEventListener("focus", show); td.addEventListener("blur", hideTip);
        tr.append(td);
      }
      tb.append(tr);
    }
    tbl.append(tb);
  }

  // ---------- bars ----------
  function hbars(el, rows, opts) {
    const W = el.clientWidth || 500;
    el.textContent = "";
    const rh = opts.rowH || 26, m = { t: 2, r: opts.right || 70, b: 2, l: opts.labelW || 140 };
    const Ht = m.t + m.b + rows.length * rh;
    const svg = d3.select(el).append("svg").attr("width", W).attr("height", Ht).attr("role", "img").attr("aria-label", opts.aria);
    const x = d3.scaleLinear().domain([0, opts.max || d3.max(rows, (d) => d.v) || 1]).range([m.l, W - m.r]);
    rows.forEach((d, i) => {
      const yy = m.t + i * rh, bh = Math.min(14, rh - 8), by = yy + (rh - bh) / 2;
      const strong = d.strong;
      svg.append("text").attr("x", m.l - 8).attr("y", yy + rh / 2 + 4).attr("text-anchor", "end").attr("class", strong ? "lbl-strong" : "lbl-2").text(d.label);
      const w = d.v > 0 ? Math.max(2, x(d.v) - m.l) : 0, r = Math.min(4, w);
      if (w > 0) svg.append("path").attr("d", `M${m.l},${by}H${m.l + w - r}Q${m.l + w},${by} ${m.l + w},${by + r}V${by + bh - r}Q${m.l + w},${by + bh} ${m.l + w - r},${by + bh}H${m.l}Z`).style("fill", d.color || "var(--peer)");
      svg.append("text").attr("x", m.l + w + 6).attr("y", yy + rh / 2 + 4).attr("class", strong ? "lbl-strong" : "lbl-2").text(d.display || fmtInt(d.v));
      const hit = svg.append("rect").attr("x", 0).attr("y", yy).attr("width", W).attr("height", rh).attr("fill", "transparent").attr("tabindex", "0");
      hover(hit, (e) => showTip(e, d.label, [{ c: d.color || "var(--peer)", name: opts.valueName, v: d.display || fmtInt(d.v) }].concat(d.extra || []), d.note));
      if (d.onclick) hit.style("cursor", "pointer").on("click", d.onclick);
    });
    if (opts.ref) svg.append("line").attr("x1", x(opts.ref)).attr("x2", x(opts.ref)).attr("y1", 0).attr("y2", Ht).attr("stroke", "var(--ink-2)").attr("stroke-width", 1);
  }

  // ---------- criterion explorer ----------
  function renderExplorer(group) {
    const mid = state.explore, m = MI[mid];
    const L = leaders(mid, group);
    byId("explore-title").textContent = m.label;
    byId("explore-sub").textContent = `${m.desc}. Best in group: ${L.ids.map((id) => P[id].name).join(", ")} (${fmtVal(L.best, m)}).`;
    const minAge = { goals30: 30, goals35: 35 }[mid];
    const fid = focusId();
    const rows = group.filter((p) => V[p.id][mid] != null).map((p) => {
      const young = minAge && ageNow(p) < minAge;
      return { id: p.id, label: p.name, v: V[p.id][mid], color: colorOf(p.id), strong: p.role === "cr" || p.id === fid, note: VN[p.id][mid] || null, young,
        display: young ? `not yet ${minAge}` : fmtVal(V[p.id][mid], m), onclick: () => selectPlayer(p.id) };
    }).sort((a, b) => (a.young - b.young) || (b.v - a.v));
    hbars(byId("chart-explore"), rows, { aria: `Bar chart of ${m.label} for each player`, valueName: m.label, labelW: byId("chart-explore").clientWidth < 420 ? 120 : 140, rowH: 22 });
    table(byId("tbl-explore"), ["Player", m.label, "Note"], rows.map((r) => [r.label, r.display, r.note || ""]));
  }

  // ---------- leaders table ----------
  function renderLeaders(group) {
    const fid = focusId(), fp = P[fid];
    const sub = byId("leaders-sub");
    sub.textContent = `Best value in the group on each criterion, and where ${fp.name} stands${state.focus ? "" : " (ranked first under the current settings; click any name to choose another player)"}. `;
    if (state.focus) sub.append(h("button", { type: "button", class: "linkbtn", onclick: () => { state.focus = null; update(); } }, "Clear selection"));
    const t = byId("leaders-table");
    t.textContent = "";
    t.append(h("thead", null, h("tr", null, h("th", { scope: "col" }, "Criterion"), h("th", { scope: "col" }, "Best"), h("th", { scope: "col", class: "hide-sm", style: "text-align:right" }, "Value"),
      h("th", { scope: "col", style: "text-align:right" }, fp.short), h("th", { scope: "col", style: "text-align:right" }, "Rank"))));
    const tb = h("tbody");
    for (const f of FAM) {
      tb.append(h("tr", { class: "grp" }, h("td", { colspan: "5" }, f.label)));
      for (const m of METRICS.filter((x) => x.family === f.id)) {
        const L = leaders(m.id, group), v = V[fid][m.id], lead = L.ids.includes(fid);
        tb.append(h("tr", null,
          h("td", null, h("button", { type: "button", style: "border:0;background:none;padding:0;cursor:pointer;text-align:left;text-decoration:underline;text-decoration-color:var(--rule)", onclick: () => { state.explore = m.id; byId("explore-sel").value = m.id; renderExplorer(players()); byId("p-explorer").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" }); } }, m.short)),
          h("td", null, L.ids.map((id) => h("span", { style: "white-space:nowrap;margin-right:6px" }, h("span", { class: "dot", style: `--c:${colorOf(id)}` }), P[id].short))),
          h("td", { class: "r hide-sm" }, fmtVal(L.best, m)),
          h("td", { class: "r" + (lead ? " strong" : "") }, fmtVal(v, m)),
          h("td", { class: "r" + (lead ? " strong" : "") }, v == null ? "—" : `${L.rankOf(fid)}`)));
      }
    }
    t.append(tb);
  }

  // ---------- age chart ----------
  function renderAge(group) {
    const el = byId("chart-age");
    const W = el.clientWidth || 800;
    el.textContent = "";
    const legend = byId("age-legend");
    legend.textContent = "";
    const fid = focusId();
    const ids = group.map((p) => p.id).filter((id) => FG.ageCurves[id]).sort((a, b) => (P[a].role === "cr" ? -1 : P[b].role === "cr" ? 1 : P[a].short.localeCompare(P[b].short)));
    for (const id of ids) {
      const hidden = state.ageHidden.has(id);
      legend.append(h("li", null, h("button", { type: "button", class: "tog", "aria-pressed": String(!hidden), title: hidden ? `Show ${P[id].name}` : `Hide ${P[id].name}`,
        onclick: () => { hidden ? state.ageHidden.delete(id) : state.ageHidden.add(id); renderAge(players()); } }, h("span", { class: "ln", style: `--c:${colorOf(id)}` }), P[id].short)));
    }
    const narrow = W < 560;
    const m = { t: 14, r: narrow ? 84 : 124, b: 36, l: 44 };
    const Ht = narrow ? 320 : 420;
    const svg = d3.select(el).append("svg").attr("width", W).attr("height", Ht).attr("role", "img").attr("aria-label", "Line chart of cumulative official goals by age");
    const x = d3.scaleLinear().domain([15, 44]).range([m.l, W - m.r]);
    const ymax = d3.max(ids, (id) => d3.max(FG.ageCurves[id], (d) => d[1]));
    const y = d3.scaleLinear().domain([0, Math.ceil(ymax / 100) * 100]).nice().range([Ht - m.b, m.t]);
    svg.append("g").attr("transform", `translate(0,${Ht - m.b})`).call(d3.axisBottom(x).ticks(narrow ? 6 : 14).tickSizeOuter(0)).call((g) => g.select(".domain").attr("stroke", "var(--axis)"));
    svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(6).tickSize(-(W - m.l - m.r)).tickFormat(fmtInt)).call((g) => g.select(".domain").remove()).call((g) => g.selectAll(".tick line").attr("stroke", "var(--grid)"));
    svg.append("text").attr("x", W - m.r).attr("y", Ht - 4).attr("text-anchor", "end").text("Age (years)");
    const line = d3.line().x((d) => x(d[0])).y((d) => y(d[1]));
    const rank = (id) => (P[id].role === "cr" ? 2 : id === fid ? 1 : 0);
    const order = ids.filter((id) => !state.ageHidden.has(id)).sort((a, b) => rank(a) - rank(b));
    for (const id of order) {
      const data = FG.ageCurves[id], r = rank(id);
      svg.append("path").datum(data).attr("fill", "none").attr("d", line).attr("stroke-width", r ? 2.5 : 1.4).attr("stroke-linejoin", "round").style("stroke", colorOf(id)).style("opacity", r ? 1 : 0.85);
      const last = data[data.length - 1];
      svg.append("circle").attr("cx", x(last[0])).attr("cy", y(last[1])).attr("r", r ? 4.5 : 3).style("fill", colorOf(id)).style("stroke", "var(--surface)").attr("stroke-width", 2);
    }
    const valueAt = (id, age) => { const d = FG.ageCurves[id]; if (age < d[0][0]) return null; let v = 0, i = 0; for (; i < d.length && d[i][0] <= age; i++) v = d[i][1]; return { v, done: i === d.length }; };
    const ronaldoY = (age) => { const r = valueAt("ronaldo", age); return r ? y(r.v) : null; };
    const labels = order.map((id) => { const last = FG.ageCurves[id][FG.ageCurves[id].length - 1]; return { id, age: last[0], x: x(last[0]) + 8, y: y(last[1]), v: last[1], pri: rank(id) }; }).sort((a, b) => b.pri - a.pri || b.v - a.v);
    const placed = [];
    for (const lb of labels) {
      const onR = lb.id !== "ronaldo" && [0, 1.5, 3].some((dx) => { const ry = ronaldoY(lb.age + dx); return ry != null && Math.abs(ry - lb.y) < 14; });
      if (!lb.pri && (narrow || onR || placed.some((p) => Math.abs(p.y - lb.y) < 14 && Math.abs(p.x - lb.x) < 110))) continue;
      placed.push(lb);
      svg.append("text").attr("x", lb.x).attr("y", lb.y + 4).attr("class", lb.pri ? "lbl-strong" : "lbl-2").text(`${P[lb.id].short} ${fmtInt(lb.v)}`);
    }
    const cross = svg.append("line").attr("y1", m.t).attr("y2", Ht - m.b).attr("stroke", "var(--axis)").style("display", "none");
    const ov = svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", Ht - m.t - m.b).attr("fill", "transparent").style("cursor", "crosshair");
    const move = (evt) => {
      const [px] = d3.pointer(evt, svg.node());
      const age = Math.max(15, Math.min(44, x.invert(px)));
      cross.style("display", null).attr("x1", x(age)).attr("x2", x(age));
      const rows = order.map((id) => ({ id, r: valueAt(id, age) })).filter((d) => d.r).sort((p, q) => q.r.v - p.r.v)
        .map(({ id, r }) => ({ c: colorOf(id), name: P[id].short + (r.done ? (P[id].active ? " (to date)" : " (final)") : ""), v: fmtInt(r.v) }));
      showTip(evt, `Goals before age ${Math.floor(age) + 1}`, rows.slice(0, 12), rows.length > 12 ? `+${rows.length - 12} more` : null);
    };
    ov.on("pointermove", move).on("pointerenter", move).on("pointerleave", () => { cross.style("display", "none"); hideTip(); });
    const ages = [20, 25, 30, 33, 35, 37, 39, 41];
    table(byId("tbl-age"), ["Player", ...ages.map((a) => `By ${a}`), "Total"], ids.map((id) => {
      const d = FG.ageCurves[id], lastAge = d[d.length - 1][0];
      return [P[id].name, ...ages.map((a) => { const r = valueAt(id, a); return r && lastAge >= a - 0.01 ? fmtInt(r.v) : "—"; }), fmtInt(d[d.length - 1][1])];
    }));
    byId("age-source").textContent = FG.meta.ageSource;
  }

  // ---------- all-time lists ----------
  const roleColor = (role) => (role === "cr" ? "var(--cr7)" : "var(--peer)");
  function renderAllTime() {
    const LB = FG.leaderboards;
    segment(byId("alltime-seg"), [["career", "Official goals"], ["intl", "International goals"], ["ucl", "Champions League goals"]], state.alltime, (id) => { state.alltime = id; syncSeg(byId("alltime-seg"), id); draw(); });
    const body = byId("alltime-body");
    const draw = () => {
      body.textContent = "";
      if (state.alltime === "career") {
        byId("alltime-title").textContent = "All-time official goals, three counts";
        byId("alltime-sub").textContent = `The counts differ on lower divisions, reserve and regional selections. Guinness lists ${LB.guinness.player} with ${fmtInt(LB.guinness.goals)} in ${fmtInt(LB.guinness.apps)} games, including friendlies.`;
        const grid = h("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px 24px" });
        body.append(grid);
        const charts = LB.career.map((list) => {  // lay out all three columns first, then measure and draw
          const ch = h("div", { class: "chart" });
          grid.append(h("div", { style: "min-width:0" }, h("div", { style: "font-weight:700;font-size:13px" }, list.label), h("div", { class: "hint", style: "margin:2px 0 8px" }, `${list.desc}. As of ${list.asOf}.`), ch));
          return [ch, list];
        });
        for (const [ch, list] of charts) {
          hbars(ch, list.rows.map((r) => ({ label: r.player, v: r.goals, display: fmtInt(r.goals) + (r.plus ? "+" : ""), color: roleColor(r.role), strong: r.role === "cr", note: r.plus ? "Lower bound given by the source." : null })),
            { aria: `${list.label}: all-time official goals`, valueName: "Goals", labelW: 124, right: 50, rowH: 22 });
        }
        table(byId("tbl-alltime"), ["List", "Rank", "Player", "Goals"], LB.career.flatMap((l) => l.rows.map((r, i) => [l.label, String(i + 1), r.player, fmtInt(r.goals) + (r.plus ? "+" : "")])));
        byId("alltime-source").textContent = "Sources: Wikipedia, list of footballers with 500 or more goals (IFFHS-style, 29 October 2026); RSSSF, most prolific goalscorers in official matches (19 July 2026); Guinness World Records.";
      } else {
        const intl = state.alltime === "intl";
        byId("alltime-title").textContent = intl ? "Men's all-time international goals" : "All-time European Cup and Champions League goals";
        byId("alltime-sub").textContent = intl ? "Full senior internationals; caps on hover." : "Qualifiers excluded; games on hover.";
        const rows = (intl ? LB.intl : LB.ucl).slice(0, 15);
        const ch = h("div", { class: "chart" });
        body.append(ch);
        hbars(ch, rows.map((d) => ({ label: d.player, v: d.goals, color: roleColor(d.role), strong: d.role === "cr", note: intl ? d.country : null,
          extra: [{ c: "var(--peer)", name: intl ? "Caps" : "Games", v: fmtInt(intl ? d.caps : d.apps) }] })), { aria: "All-time scorers", valueName: "Goals", labelW: 150, rowH: 24 });
        table(byId("tbl-alltime"), intl ? ["Player", "Country", "Goals", "Caps"] : ["Player", "Goals", "Games"], rows.map((d) => intl ? [d.player, d.country, fmtInt(d.goals), fmtInt(d.caps)] : [d.player, fmtInt(d.goals), fmtInt(d.apps)]));
        byId("alltime-source").textContent = intl ? FG.meta.intlSource : FG.meta.uclSource;
      }
    };
    onResize(body, draw); draw();
  }

  // ---------- Ronaldo panels ----------
  function renderRonaldo() {
    const R = PR.uclRounds;
    const el = byId("chart-ucl");
    const rounds = [["Group", "Group stage", ""], ["R16", "Round of 16", ""], ["QF", "Quarter-finals", " · record"], ["SF", "Semi-finals", " · record"], ["F", "Finals", " · record since 1992"]];
    const rows = rounds.map(([k, label, rec]) => ({ label, v: R[k].goals, color: "var(--cr7)", display: `${R[k].goals} in ${R[k].apps}${rec}`, extra: [{ c: "var(--peer)", name: "Goals per game", v: fmt2(R[k].goals / R[k].apps) }] }));
    const drawU = () => hbars(el, rows, { aria: "Champions League goals by round", valueName: "Goals", labelW: 112, right: 160, rowH: 32 });
    onResize(el, drawU); drawU();
    table(byId("tbl-ucl"), ["Round", "Goals", "Games", "Goals per game"], rounds.map(([k, l]) => [l, fmtInt(R[k].goals), fmtInt(R[k].apps), fmt2(R[k].goals / R[k].apps)]));

    const G = PR.goalTypes;
    byId("types-sub").textContent = `All ${fmtInt(G.total)} official goals. He is right-footed.`;
    const elT = byId("chart-types");
    const drawT = () => {
      const W = elT.clientWidth || 600;
      elT.textContent = "";
      const svg = d3.select(elT).append("svg").attr("width", W).attr("height", 34).attr("role", "img").attr("aria-label", "Goals by body part");
      const x = d3.scaleLinear().domain([0, G.total]).range([0, W]);
      let acc = 0;
      for (const [k, label, fill] of [["strong", "Right foot", "var(--peer)"], ["weak", "Left foot", "var(--cr7)"], ["head", "Header", "color-mix(in oklab, var(--cr7) 55%, var(--surface))"], ["other", "Other", "var(--axis)"]]) {
        const v = G[k];
        if (!v) continue;
        const x0 = x(acc) + (acc ? 1 : 0), w = Math.max(0, x(acc + v) - 1 - x0);
        acc += v;
        const r = svg.append("rect").attr("x", x0).attr("y", 3).attr("width", w).attr("height", 28).attr("rx", 4).style("fill", fill).attr("tabindex", "0");
        hover(r, (e) => showTip(e, label, [{ c: fill, name: "Goals", v: fmtInt(v) }, { c: fill, name: "Share", v: d3.format(".1%")(v / G.total) }], null));
        const txt = `${fmtInt(v)} · ${pct0(v / G.total)}`;
        if (w > txt.length * 7 + 14) svg.append("text").attr("x", x0 + 8).attr("y", 21.5).style("fill", k === "weak" ? "#ffffff" : "var(--ink)").style("font-weight", 700).style("pointer-events", "none").text(txt);
      }
    };
    onResize(elT, drawT); drawT();
    const ts = byId("types-stat");
    ts.append(h("span", null, "Headers ", h("b", null, fmtInt(G.head))), h("span", null, "Left foot ", h("b", null, fmtInt(G.weak))),
      h("span", null, "Left, right and head in one match ", h("b", null, String(PR.perfectHatTricks))), h("span", null, "Penalties ", h("b", null, `${PR.pens.scored}/${PR.pens.taken}`)), h("span", null, "Free kicks ", h("b", null, String(G.fk))));
    table(byId("tbl-types"), ["Body part", "Goals", "Share"], [["Right foot", G.strong], ["Left foot", G.weak], ["Header", G.head], ["Other", G.other]].map(([l, v]) => [l, fmtInt(v), d3.format(".1%")(v / G.total)]));

    const T = PR.tournaments.map((t) => ({ ...t, name: t.name.replace("Euro ", "European Championship ") }));
    const el3 = byId("chart-tourn");
    const drawTo = () => {
      const W = el3.clientWidth || 800;
      el3.textContent = "";
      const mark = (svg, t, cx, cy, r) => {
        const g = svg.append("g").attr("tabindex", "0");
        const shape = t.type === "wc" ? g.append("circle").attr("cx", cx).attr("cy", cy).attr("r", r) : g.append("rect").attr("x", cx - r).attr("y", cy - r).attr("width", 2 * r).attr("height", 2 * r).attr("rx", 4);
        if (t.goals > 0) shape.style("fill", "var(--cr7)").style("stroke", "var(--surface)").attr("stroke-width", 2); else shape.style("fill", "var(--surface)").style("stroke", "var(--cr7)").attr("stroke-width", 2);
        if (t.goals > 0) g.append("text").attr("x", cx).attr("y", cy + 4).attr("text-anchor", "middle").style("fill", "#ffffff").style("font-weight", 700).text(t.goals);
        hover(g, (e) => showTip(e, t.name, [{ c: "var(--cr7)", name: "Goals", v: `${t.goals} in ${t.apps} games` }], t.result || null));
      };
      if (W < 620) {
        const rowH = 32, Ht = 12 + T.length * rowH;
        const svg = d3.select(el3).append("svg").attr("width", W).attr("height", Ht).attr("role", "img").attr("aria-label", "Goals at each major tournament");
        const rr = d3.scaleSqrt().domain([0, 5]).range([8, 13]);
        T.forEach((t, i) => {
          const cy = 6 + i * rowH + rowH / 2;
          svg.append("text").attr("x", 0).attr("y", cy + 4).text(t.year);
          mark(svg, t, 68, cy, rr(t.goals));
          svg.append("text").attr("x", 90).attr("y", cy + 4).attr("class", "lbl-2").text(`${t.type === "wc" ? "World Cup" : "Euro"} · ${t.result || ""}`);
        });
        return;
      }
      const m = { r: 22, b: 28, l: 22 }, Ht = 112;
      const svg = d3.select(el3).append("svg").attr("width", W).attr("height", Ht).attr("role", "img").attr("aria-label", "Timeline of goals at each major tournament");
      const x = d3.scaleLinear().domain([2003.4, 2026.6]).range([m.l, W - m.r]);
      svg.append("g").attr("transform", `translate(0,${Ht - m.b})`).call(d3.axisBottom(x).tickValues(d3.range(2004, 2027, 2)).tickFormat(d3.format("d")).tickSizeOuter(0)).call((g) => g.select(".domain").attr("stroke", "var(--axis)"));
      const cy = (Ht - m.b) / 2 + 4;
      svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", cy).attr("y2", cy).attr("stroke", "var(--grid)");
      const rr = d3.scaleSqrt().domain([0, 5]).range([10, 21]);
      for (const t of T) mark(svg, t, x(t.year), cy, rr(t.goals));
    };
    onResize(el3, drawTo); drawTo();
    table(byId("tbl-tourn"), ["Tournament", "Goals", "Games", "Result"], T.map((t) => [t.name, String(t.goals), String(t.apps), t.result || ""]));

    const elc = byId("chart-clubs");
    const crow = PR.clubs.map((c) => ({ label: c.club, v: c.goals, color: "var(--cr7)", note: c.years, extra: [{ c: "var(--peer)", name: "Games", v: fmtInt(c.apps) }] }));
    const drawC = () => hbars(elc, crow, { aria: "Goals by club", valueName: "Goals", labelW: 138, ref: 100, right: 44 });
    onResize(elc, drawC); drawC();
    table(byId("tbl-clubs"), ["Club", "Years", "Goals", "Games"], PR.clubs.map((c) => [c.club, c.years, fmtInt(c.goals), fmtInt(c.apps)]));

    byId("records-sub").textContent = `${FG.records.length} records, measured against every player in history. Next best where the source names one.`;
    const t = byId("records-table");
    t.append(h("thead", null, h("tr", null, h("th", { scope: "col" }, "Record"), h("th", { scope: "col", style: "text-align:right" }, "Ronaldo"), h("th", { scope: "col" }, "Next best"), h("th", { scope: "col", class: "hide-sm" }, "Source"))));
    const tb = h("tbody");
    let grp = null;
    for (const r of FG.records) {
      if (r.group !== grp) { grp = r.group; tb.append(h("tr", { class: "grp" }, h("td", { colspan: "4" }, grp))); }
      tb.append(h("tr", null, h("td", null, r.record), h("td", { class: "r strong" }, r.value), h("td", null, r.next || "—"),
        h("td", { class: "hide-sm" }, r.href ? h("a", { href: r.href, target: "_blank", rel: "noopener" }, r.source) : r.source)));
    }
    t.append(tb);
  }

  // ---------- methods & footer ----------
  function renderMethods() {
    const box = byId("methods");
    const refIndex = Object.fromEntries(FG.references.map((r, i) => [r.key, i + 1]));
    for (const blk of FG.method) {
      const d = h("div");
      d.append(h("h4", null, blk.title, blk.cites ? h("span", { class: "cite", style: "font-weight:500;margin-left:6px" }, blk.cites.map((c) => `[${refIndex[c]}]`).join(" ")) : null));
      for (const p of blk.paras || []) d.append(h("p", null, p));
      if (blk.formula) d.append(h("div", { class: "formula" }, blk.formula));
      if (blk.list) d.append(h("ul", null, blk.list.map((li) => h("li", null, li.href ? h("a", { href: li.href, target: "_blank", rel: "noopener" }, li.text) : li.text, li.after ? ` ${li.after}` : ""))));
      if (blk.refs) d.append(h("ol", { class: "refs" }, FG.references.map((r) => h("li", null, r.href ? h("a", { href: r.href, target: "_blank", rel: "noopener" }, r.text) : r.text, h("span", { class: "use" }, `Used for: ${r.use}.`)))));
      box.append(d);
    }
    const f = byId("footer-body");
    for (const line of FG.footer) f.append(h("p", null, line));
    byId("meta-date").textContent = `Data to ${FG.meta.asOfLabel}`;
  }

  // ---------- update loop ----------
  function update() {
    syncSettings();
    const group = players();
    byId("meta-players").textContent = `${group.length} players`;
    byId("meta-criteria").textContent = `${selected().length} of ${METRICS.length} criteria`;
    current = composite(state.norm, state.w, group);
    const sim = simulate(group, current.sel);
    renderRanking();
    renderStability(sim);
    renderMatrix(group);
    renderExplorer(group);
    renderLeaders(group);
    renderAge(group);
  }

  function boot() {
    renderSettings();
    const sel = byId("explore-sel");
    for (const f of FAM) {
      const og = h("optgroup", { label: f.label });
      for (const m of METRICS.filter((x) => x.family === f.id)) og.append(h("option", { value: m.id }, m.label));
      sel.append(og);
    }
    sel.value = state.explore;
    sel.addEventListener("change", () => { state.explore = sel.value; renderExplorer(players()); });
    segment(byId("matrix-mode"), [["values", "Values"], ["scores", "Scores"]], state.mmode, (id) => { state.mmode = id; syncSeg(byId("matrix-mode"), id); renderMatrix(players()); });
    byId("matrix-source").textContent = FG.meta.matrixSource;
    renderAllTime();
    renderRonaldo();
    renderMethods();
    update();
    for (const [id, fn] of [["chart-stab", () => renderStability(simulate(players(), current.sel))], ["chart-explore", () => renderExplorer(players())], ["chart-age", () => renderAge(players())]]) onResize(byId(id), fn);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
