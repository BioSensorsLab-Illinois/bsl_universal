"use strict";

const STATES = [
  ["CONNECTED", "connected"], ["CONNECTING", "connecting"], ["WARNING", "warning"],
  ["UNRECOVERABLE_FAILURE", "failure"], ["STALE_SESSION", "stale"], ["DISCONNECTED", "disconnected"],
];
const ACTIVE = new Set(["CONNECTING", "CONNECTED", "WARNING", "UNRECOVERABLE_FAILURE"]);
const ALERT_ON = new Set(["WARNING", "UNRECOVERABLE_FAILURE"]);
const LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"];
const LVL_COLOR = { TRACE: "var(--text-3)", DEBUG: "var(--text-3)", INFO: "var(--s-connecting)", SUCCESS: "var(--s-connected)", WARNING: "var(--s-warning)", ERROR: "var(--s-unrecoverable_failure)", CRITICAL: "var(--s-unrecoverable_failure)" };
const LVL_BG = { TRACE: "var(--surface-2)", DEBUG: "var(--surface-2)", INFO: "var(--s-connecting-bg)", SUCCESS: "var(--s-connected-bg)", WARNING: "var(--s-warning-bg)", ERROR: "var(--s-unrecoverable_failure-bg)", CRITICAL: "var(--s-unrecoverable_failure-bg)" };

const app = {
  view: "overview",
  payload: { devices: [], counts: {}, events: [], server: {} },
  filter: "", activeOnly: false, statusFilter: null,
  selectedKey: null, prevStatus: {}, primed: false,
  notify: localStorage.getItem("bsl-notify") === "1",
  evtFilter: "", evtLevel: "", eventsList: [],
  ovStats: null, ovAnalytics: null,
  logs: { levels: new Set(), q: "", module: "", hours: 6, follow: false },
  timer: null, dataTimer: null,
};

// ---- DOM helpers --------------------------------------------------------- //
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) for (const k in attrs) {
    const v = attrs[k];
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2).toLowerCase(), v);
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) { if (kid == null || kid === false) continue; e.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return e;
}
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs) { const e = document.createElementNS(NS, tag); for (const k in (attrs || {})) e.setAttribute(k, attrs[k]); return e; }
function icon(id) { const s = svgEl("svg", { class: "ic" }); s.setAttribute("aria-hidden", "true"); s.append(svgEl("use", { href: "#" + id })); return s; }
const $ = (id) => document.getElementById(id);

function statusSlug(s) { const k = String(s || "").toUpperCase(); return STATES.some((x) => x[0] === k) ? k.toLowerCase() : "unknown"; }
function statusClass(s) { return "s-" + statusSlug(s); }
function statusVar(s) { return "var(--s-" + statusSlug(s) + ")"; }
function statusBg(s) { return "var(--s-" + statusSlug(s) + "-bg)"; }
function labelFor(s) { const m = STATES.find((x) => x[0] === String(s).toUpperCase()); return m ? m[1] : String(s || "").toLowerCase(); }
function lvlVar(l) { return LVL_COLOR[String(l).toUpperCase()] || "var(--text-3)"; }
function lvlBg(l) { return LVL_BG[String(l).toUpperCase()] || "var(--surface-2)"; }
function liveUptime(d) { if (!d) return null; if (d.connected_since != null) return Date.now() / 1000 - d.connected_since; return d.uptime_seconds; }

function relTime(iso) {
  if (!iso) return "—";
  const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  if (isNaN(t)) return String(iso);
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return s + "s ago"; if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago"; return Math.floor(s / 86400) + "d ago";
}
function fmtClock(ts) { try { return new Date(ts * 1000).toLocaleTimeString(); } catch (e) { return "—"; } }
function fmtUptime(sec) {
  if (sec == null) return "—"; sec = Math.floor(sec);
  const d = Math.floor(sec / 86400), hh = Math.floor((sec % 86400) / 3600), mm = Math.floor((sec % 3600) / 60);
  if (d) return d + "d " + hh + "h"; if (hh) return hh + "h " + mm + "m"; if (mm) return mm + "m " + (sec % 60) + "s"; return sec + "s";
}
function pct(x) { return Math.round((x || 0) * 1000) / 10 + "%"; }
function shortMod(m) { const p = String(m || "").split("."); return p.length > 3 ? "…" + p.slice(-2).join(".") : m; }

// ---- toasts / notifications --------------------------------------------- //
function toast(msg, kind) {
  const t = h("div", { class: "toast " + (kind || ""), text: msg });
  $("toasts").append(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(() => t.remove(), 300); }, 4000);
}
let actx;
function beep() {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain();
    o.type = "sine"; o.frequency.value = 660; o.connect(g); g.connect(actx.destination);
    g.gain.setValueAtTime(0.0001, actx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.22, actx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + 0.4);
    o.start(); o.stop(actx.currentTime + 0.4);
  } catch (e) { /* ignore */ }
}
function fireAlert(model, status) {
  const title = model + " → " + labelFor(status);
  toast(title, status === "UNRECOVERABLE_FAILURE" ? "err" : "");
  if (!app.notify) return;
  beep();
  try { if ("Notification" in window && Notification.permission === "granted") new Notification("BSL monitor", { body: title, tag: "bsl-" + model }); } catch (e) { /* ignore */ }
}
function setLive(on) { const el = $("live"); el.classList.toggle("off", !on); $("liveText").textContent = on ? "live" : "reconnecting…"; }

// ---- mini status pill ---------------------------------------------------- //
function statusPill(s, small) {
  const st = String(s || "").toUpperCase();
  return h("span", { class: "pill " + statusClass(st) + (small ? "" : ""), style: small ? "padding:1px 8px;font-size:11px" : "" },
    h("span", { class: "swatch" }), labelFor(st));
}

// ====================================================================== //
//  CHARTS (zero-dependency inline SVG / divs)
// ====================================================================== //
function donut(el, segs, centerVal, centerLabel) {
  el.textContent = "";
  const total = segs.reduce((a, s) => a + s.value, 0);
  const size = 150, r = 54, cx = size / 2, cy = size / 2, circ = 2 * Math.PI * r, sw = 20;
  const svg = svgEl("svg", { viewBox: `0 0 ${size} ${size}`, height: "150" });
  svg.append(svgEl("circle", { cx, cy, r, fill: "none", stroke: "var(--surface-2)", "stroke-width": sw }));
  let off = 0;
  for (const s of segs) {
    if (s.value <= 0) continue;
    const len = circ * s.value / total;
    svg.append(svgEl("circle", { cx, cy, r, fill: "none", stroke: s.color, "stroke-width": sw, "stroke-dasharray": `${len} ${circ - len}`, "stroke-dashoffset": `${-off}`, transform: `rotate(-90 ${cx} ${cy})` }));
    off += len;
  }
  const t1 = svgEl("text", { x: cx, y: cy - 1, "text-anchor": "middle", "font-size": "26", "font-weight": "600", fill: "var(--text)" }); t1.textContent = String(centerVal != null ? centerVal : total);
  const t2 = svgEl("text", { x: cx, y: cy + 16, "text-anchor": "middle", "font-size": "11", fill: "var(--text-3)" }); t2.textContent = centerLabel || "total";
  svg.append(t1, t2);
  const legend = h("div", { class: "legend" });
  for (const s of segs) {
    if (s.value <= 0) continue;
    legend.append(h("div", { class: "legend-item" },
      h("span", { class: "legend-sw", style: "background:" + s.color }),
      h("span", { class: "legend-lbl", text: s.label }),
      h("span", { class: "legend-val", text: String(s.value) })));
  }
  el.append(h("div", { class: "chart-row" }, svg, legend));
}

function barsH(el, items) {
  el.textContent = "";
  if (!items.length) { el.append(h("div", { class: "feed-empty", text: "No data yet." })); return; }
  const max = Math.max(1, ...items.map((i) => i.value));
  for (const it of items) {
    el.append(h("div", { class: "bar-row", onclick: it.onclick, style: it.onclick ? "cursor:pointer" : "" },
      h("div", { class: "bar-label", title: it.label, text: it.label }),
      h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: `width:${Math.round(100 * it.value / max)}%;background:${it.color || "var(--accent)"}` })),
      h("div", { class: "bar-val", text: it.text != null ? it.text : String(it.value) })));
  }
}

function stackedTimeline(el, stats) {
  el.textContent = "";
  const buckets = (stats && stats.buckets) || [];
  if (!buckets.length) { el.append(h("div", { class: "feed-empty", text: "No log activity in this window." })); return; }
  const sums = buckets.map((b) => Object.values(b.counts || {}).reduce((a, c) => a + c, 0));
  const maxv = Math.max(1, ...sums);
  const W = buckets.length, H = 44;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none" });
  svg.style.width = "100%"; svg.style.height = "140px";
  // faint horizontal gridlines so a sparse window still reads as a chart
  for (const f of [0.25, 0.5, 0.75]) {
    svg.append(svgEl("line", { x1: 0, x2: W, y1: (H * f).toFixed(2), y2: (H * f).toFixed(2), stroke: "var(--border)", "stroke-width": "0.12" }));
  }
  const bw = W / buckets.length;
  buckets.forEach((b, i) => {
    let y = H;
    for (const lv of LOG_LEVELS) {
      const v = (b.counts || {})[lv] || 0; if (!v) continue;
      const hgt = Math.max(0.6, (v / maxv) * (H - 1));  // min height keeps tiny counts visible
      svg.append(svgEl("rect", { x: (i * bw).toFixed(3), width: Math.max(0.25, bw * 0.84).toFixed(3), y: (y - hgt).toFixed(3), height: hgt.toFixed(3), fill: lvlVar(lv) }));
      y -= hgt;
    }
  });
  el.append(svg);
  const ax = h("div", { class: "axis" }, h("span", { text: fmtClock(stats.since) }), h("span", { text: fmtClock(stats.now) }));
  el.append(ax);
  const leg = h("div", { class: "legend wrap" });
  for (const lv of LOG_LEVELS) {
    const v = (stats.totals || {})[lv] || 0; if (!v) continue;
    leg.append(h("div", { class: "legend-item" }, h("span", { class: "legend-sw", style: "background:" + lvlVar(lv) }), h("span", { class: "legend-lbl", text: lv.toLowerCase() }), h("span", { class: "legend-val", text: String(v) })));
  }
  el.append(leg);
}

// ====================================================================== //
//  VIEW: DEVICES
// ====================================================================== //
function visibleDevices() {
  const q = app.filter.trim().toLowerCase();
  return app.payload.devices.filter((d) => {
    const st = String(d.status || "").toUpperCase();
    if (app.statusFilter && st !== app.statusFilter) return false;
    if (app.activeOnly && !ACTIVE.has(st)) return false;
    if (q) { const hay = [d.model, d.device_type, d.serial_number, d.status, d.last_error].join(" ").toLowerCase(); if (!hay.includes(q)) return false; }
    return true;
  });
}
function renderCards() {
  const counts = app.payload.counts || {}; const wrap = $("cards"); wrap.textContent = "";
  for (const [state, label] of STATES) {
    const sel = app.statusFilter === state;
    const card = h("div", { class: "card clickable" + (sel ? " sel" : ""), style: sel ? "color:" + statusVar(state) : "", role: "button", tabindex: "0",
      onclick: () => { app.statusFilter = sel ? null : state; renderDevices(); } },
      h("div", { class: "label" }, h("span", { class: "swatch", style: "color:" + statusVar(state) }), label),
      h("div", { class: "num", text: String(counts[state] || 0) }));
    card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); card.click(); } });
    wrap.append(card);
  }
}
function renderTable() {
  const rows = $("rows"); const list = visibleDevices(); rows.textContent = ""; $("empty").hidden = list.length > 0;
  for (const d of list) {
    const st = String(d.status || "").toUpperCase();
    const changed = app.primed && app.prevStatus[d.key] && app.prevStatus[d.key] !== st;
    const tr = h("tr", { class: (changed ? "flash " : "") + (st === "DISCONNECTED" || st === "STALE_SESSION" ? "dim" : ""), onclick: () => openDrawer(d.key) },
      h("td", { class: "c-model model-cell", text: d.model || "—" }),
      h("td", { class: "c-type muted", text: d.device_type || "—" }),
      h("td", { class: "c-sn mono", text: d.serial_number || "—" }),
      h("td", { class: "c-status" }, statusPill(st)),
      h("td", { class: "c-updated muted", title: d.updated_at || "", text: relTime(d.updated_at) }),
      h("td", { class: "c-pid mono", text: d.process_id ? String(d.process_id) : "—" }),
      h("td", { class: "c-err", title: d.last_error || "", text: d.last_error || "" }));
    rows.append(tr);
  }
}
function renderFootnote() {
  const s = app.payload.server || {}; const n = (app.payload.counts || {}).TOTAL || 0;
  $("footnote").textContent = `${n} device${n === 1 ? "" : "s"} · serving on ${s.lan_url || "—"} · updated ${relTime(app.payload.generated_at)}`;
  $("subline").textContent = `${(app.payload.counts || {}).ACTIVE || 0} active · ${n} total`;
  if (s.lan_url) $("lanUrl").textContent = (s.lan_ip || "") + ":" + (s.port || "");
}
function renderDevices() { renderCards(); renderTable(); renderFootnote(); if (app.selectedKey) renderDrawer(); }

// ====================================================================== //
//  VIEW: OVERVIEW
// ====================================================================== //
function renderKpis() {
  const c = app.payload.counts || {}, s = app.ovStats, a = app.ovAnalytics;
  const issues = (c.WARNING || 0) + (c.UNRECOVERABLE_FAILURE || 0);
  const tiles = [
    { icon: "i-cpu", label: "active devices", val: c.ACTIVE || 0, sub: `${c.TOTAL || 0} total tracked` },
    { icon: "i-alert", label: "issues now", val: issues, sub: `${c.WARNING || 0} warning · ${c.UNRECOVERABLE_FAILURE || 0} failure`, color: issues ? "var(--s-unrecoverable_failure)" : "var(--text)" },
    { icon: "i-file", label: "log errors · 6h", val: s ? s.error_count : "—", sub: s ? `${pct(s.error_rate)} of ${s.total} lines` : "—", color: s && s.error_count ? "var(--s-unrecoverable_failure)" : "var(--text)" },
    { icon: "i-refresh", label: "reconnects", val: a ? a.totals.reconnects : "—", sub: a ? `${a.totals.events} transitions seen` : "—" },
  ];
  const wrap = $("kpis"); wrap.textContent = "";
  for (const t of tiles) wrap.append(h("div", { class: "kpi" },
    h("div", { class: "k-label" }, icon(t.icon), t.label),
    h("div", { class: "k-val", style: t.color ? "color:" + t.color : "", text: String(t.val) }),
    h("div", { class: "k-sub", text: t.sub })));
}
function donutStatus() {
  const c = app.payload.counts || {};
  const segs = STATES.filter(([k]) => (c[k] || 0) > 0).map(([k, lbl]) => ({ label: lbl, value: c[k] || 0, color: statusVar(k) }));
  donut($("chart-status"), segs.length ? segs : [{ label: "none", value: 0, color: "var(--text-3)" }], c.TOTAL || 0, "devices");
}
function instrBars() {
  const a = app.ovAnalytics;
  if (!a) { barsH($("chart-instr"), []); return; }
  const items = a.instruments.slice(0, 8).map((i) => ({
    label: i.model || i.key, value: i.transitions,
    color: i.failures ? "var(--s-unrecoverable_failure)" : (i.warnings ? "var(--s-warning)" : "var(--s-connecting)"),
    text: `${i.transitions}× · ${i.reconnects} re`, onclick: () => { switchView("devices"); openDrawer(i.key); },
  }));
  barsH($("chart-instr"), items);
}
function renderIssues() {
  const feed = $("ov-issues"); feed.textContent = "";
  const evs = (app.payload.events || []).filter((e) => ["WARNING", "UNRECOVERABLE_FAILURE", "DISCONNECTED"].includes(String(e.to).toUpperCase())).slice(0, 8);
  if (!evs.length) { feed.append(h("div", { class: "feed-empty", text: "No issues. All clear." })); return; }
  for (const ev of evs) feed.append(eventItem(ev));
}
function renderOverviewLight() { renderKpis(); donutStatus(); instrBars(); renderIssues(); }
async function refreshOverview() {
  try {
    const [stats, analytics] = await Promise.all([
      fetch("/api/logs/stats?hours=6&buckets=48").then((r) => r.json()),
      fetch("/api/analytics").then((r) => r.json()),
    ]);
    app.ovStats = stats; app.ovAnalytics = analytics;
    if (app.view === "overview") {
      stackedTimeline($("chart-logvol"), stats);
      $("logvol-sub").textContent = `${stats.total} lines · ${pct(stats.error_rate)} err`;
    }
  } catch (e) { /* keep last */ }
  if (app.view === "overview") renderOverviewLight();
}

// ====================================================================== //
//  VIEW: EVENTS
// ====================================================================== //
function eventItem(ev) {
  const to = String(ev.to || "").toUpperCase();
  return h("div", { class: "feed-item click", onclick: () => { switchView("devices"); openDrawer(ev.key); } },
    h("span", { class: "fdot", style: "background:" + statusVar(to) }),
    h("div", { class: "f-main" },
      h("div", { class: "f-title" }, h("b", { text: ev.model || ev.key }), "  ",
        statusPill(ev.from || "—", true), " → ", statusPill(to, true)),
      ev.error ? h("div", { class: "f-meta", title: ev.error, text: ev.error }) : null),
    h("span", { class: "f-time", title: ev.iso, text: relTime(ev.iso || ev.ts) }));
}
function renderEvents() {
  const feed = $("eventsFeed"); const f = app.evtFilter.trim().toLowerCase(); const sel = app.evtLevel;
  const list = (app.eventsList.length ? app.eventsList : (app.payload.events || []));
  const evs = list.filter((ev) => {
    const to = String(ev.to || "").toUpperCase();
    if (sel === "issues" && !(to === "WARNING" || to === "UNRECOVERABLE_FAILURE")) return false;
    if (sel && sel !== "issues" && to !== sel) return false;
    if (f) { const hay = [ev.model, ev.to, ev.from, ev.error, ev.device_type].join(" ").toLowerCase(); if (!hay.includes(f)) return false; }
    return true;
  });
  feed.textContent = "";
  if (!evs.length) { feed.append(h("div", { class: "feed-empty", text: "No matching events yet." })); return; }
  for (const ev of evs) feed.append(eventItem(ev));
}
async function refreshEvents() {
  try { const d = await (await fetch("/api/events")).json(); app.eventsList = d.events || []; } catch (e) { /* ignore */ }
  if (app.view === "events") renderEvents();
}

// ====================================================================== //
//  VIEW: LOGS (analyzer)
// ====================================================================== //
function renderLogChips(facets) {
  const wrap = $("logLevels"); wrap.textContent = "";
  const lv = (facets && facets.levels) || {};
  for (const L of LOG_LEVELS) {
    const on = app.logs.levels.has(L);
    const chip = h("div", { class: "lvchip", "data-on": on ? "1" : "0",
      style: on ? `background:${lvlVar(L)}` : "",
      onclick: () => { if (app.logs.levels.has(L)) app.logs.levels.delete(L); else app.logs.levels.add(L); refreshLogs(); } },
      L.toLowerCase(), " ", h("span", { class: "cnt", text: String(lv[L] || 0) }));
    wrap.append(chip);
  }
}
function renderLogModules(facets) {
  const sel = $("logModule"); const cur = app.logs.module;
  sel.textContent = ""; sel.append(h("option", { value: "", text: "all modules" }));
  for (const m of ((facets && facets.modules) || [])) sel.append(h("option", { value: m.module, text: `${shortMod(m.module)} (${m.count})` }));
  sel.value = cur;
}
function renderLogStats(stats, logs) {
  const wrap = $("logStats"); wrap.textContent = "";
  const tiles = [
    { label: "matched", val: logs.matched, sub: `of ${logs.scanned} scanned` },
    { label: "errors", val: stats.error_count, color: stats.error_count ? "var(--s-unrecoverable_failure)" : "var(--text)" },
    { label: "warnings", val: stats.warning_count, color: stats.warning_count ? "var(--s-warning)" : "var(--text)" },
    { label: "error rate", val: pct(stats.error_rate) },
    { label: "total · window", val: stats.total },
  ];
  for (const t of tiles) wrap.append(h("div", { class: "logstat" }, h("div", { class: "ls-label", text: t.label }), h("div", { class: "ls-val", style: t.color ? "color:" + t.color : "", text: String(t.val) })));
}
function renderTopLists(stats) {
  const errs = $("logTopErrors"); errs.textContent = "";
  if (!(stats.top_errors || []).length) errs.append(h("div", { class: "feed-empty", text: "No warnings or errors." }));
  for (const e of (stats.top_errors || [])) {
    errs.append(h("div", { class: "feed-item click", onclick: () => { app.logs.q = e.message.slice(0, 40); $("logSearch").value = app.logs.q; refreshLogs(); } },
      h("span", { class: "fdot", style: "background:" + lvlVar(e.level) }),
      h("div", { class: "f-main" }, h("div", { class: "f-title", text: e.message }), h("div", { class: "f-meta", text: e.level.toLowerCase() })),
      h("span", { class: "f-time", text: "×" + e.count })));
  }
  const mods = $("logTopModules"); mods.textContent = "";
  if (!(stats.top_modules || []).length) mods.append(h("div", { class: "feed-empty", text: "No modules." }));
  for (const m of (stats.top_modules || [])) {
    mods.append(h("div", { class: "feed-item click", onclick: () => { app.logs.module = m.module; refreshLogs(); } },
      h("div", { class: "f-main" }, h("div", { class: "f-title mono", style: "font-size:12px", text: shortMod(m.module) })),
      h("span", { class: "f-time", text: "×" + m.count })));
  }
}
function logDetailRow(r) {
  const td = h("td", { colspan: "4" });
  const kv = h("div", { class: "ld-kv" },
    h("span", {}, h("b", { text: "function " }), r.function || "—"),
    h("span", {}, h("b", { text: "where " }), (r.file || "?") + ":" + r.line),
    h("span", {}, h("b", { text: "pid " }), String(r.pid || "—")),
    h("span", {}, h("b", { text: "level " }), r.level),
    h("span", {}, h("b", { text: "time " }), new Date(r.ts * 1000).toLocaleString()));
  td.append(kv, h("pre", { text: r.message + (r.exception ? "\n\n" + r.exception : "") }));
  return h("tr", { class: "log-detail" }, td);
}
function renderLogRows(records) {
  const tb = $("logRows"); tb.textContent = ""; $("logEmpty").hidden = records.length > 0;
  for (const r of records) {
    const lv = String(r.level).toUpperCase();
    const tr = h("tr", { class: "lr" },
      h("td", { class: "lt-time", title: new Date(r.ts * 1000).toLocaleString(), text: fmtClock(r.ts) }),
      h("td", { class: "lt-lvl" }, h("span", { class: "lvl" + (lv === "CRITICAL" ? " crit-tag" : ""), style: `color:${lvlVar(lv)};background:${lvlBg(lv)}`, text: lv.toLowerCase() })),
      h("td", { class: "lt-mod", title: r.module, text: shortMod(r.module) + ":" + r.line }),
      h("td", { class: "lt-msg", text: r.message + (r.exception ? "  ⤷ exception" : "") }));
    tr.addEventListener("click", () => {
      const open = tr.classList.toggle("open");
      if (open) tr.after(logDetailRow(r));
      else if (tr.nextSibling && tr.nextSibling.classList && tr.nextSibling.classList.contains("log-detail")) tr.nextSibling.remove();
    });
    tb.append(tr);
  }
}
function updateLogExportHref() {
  const p = new URLSearchParams();
  if (app.logs.levels.size) p.set("level", [...app.logs.levels].join(","));
  if (app.logs.q) p.set("q", app.logs.q);
  if (app.logs.module) p.set("module", app.logs.module);
  if (app.logs.hours > 0) p.set("hours", String(app.logs.hours));
  $("logExport").href = "/api/logs.csv?" + p.toString();
}
async function refreshLogs(opts) {
  opts = opts || {};
  const ls = app.logs;
  const p = new URLSearchParams();
  if (ls.levels.size) p.set("level", [...ls.levels].join(","));
  if (ls.q) p.set("q", ls.q);
  if (ls.module) p.set("module", ls.module);
  if (ls.hours > 0) p.set("hours", String(ls.hours));
  p.set("limit", "600");
  const sp = new URLSearchParams({ hours: String(ls.hours || 6), buckets: "60" });
  try {
    const [logs, stats] = await Promise.all([
      fetch("/api/logs?" + p).then((r) => r.json()),
      fetch("/api/logs/stats?" + sp).then((r) => r.json()),
    ]);
    renderLogChips(logs.facets); renderLogModules(logs.facets);
    renderLogStats(stats, logs); stackedTimeline($("chart-logtimeline"), stats);
    $("logtl-sub").textContent = `${stats.total} lines · ${pct(stats.error_rate)} err`;
    renderTopLists(stats); renderLogRows(logs.records); updateLogExportHref();
    $("logFootnote").textContent = `showing ${logs.returned} of ${logs.matched} matched · scanned ${logs.scanned} · updated ${fmtClock(Date.now() / 1000)}`;
  } catch (e) { if (!opts.quiet) toast("Could not load logs", "err"); }
}

// ====================================================================== //
//  ROUTER
// ====================================================================== //
function switchView(name) {
  app.view = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== "view-" + name; });
  if (app.dataTimer) { clearInterval(app.dataTimer); app.dataTimer = null; }
  if (name === "overview") { renderOverviewLight(); refreshOverview(); app.dataTimer = setInterval(refreshOverview, 12000); }
  else if (name === "devices") { renderDevices(); }
  else if (name === "events") { renderEvents(); refreshEvents(); app.dataTimer = setInterval(refreshEvents, 5000); }
  else if (name === "logs") { refreshLogs(); app.dataTimer = setInterval(() => { if (app.logs.follow) refreshLogs({ quiet: true }); }, 3000); }
}

// ---- SSE / apply --------------------------------------------------------- //
function apply(payload) {
  if (!payload || !Array.isArray(payload.devices)) return;
  const next = {};
  for (const d of payload.devices) {
    const st = String(d.status || "").toUpperCase(); next[d.key] = st;
    if (app.primed && app.prevStatus[d.key] !== st && ALERT_ON.has(st)) fireAlert(d.model || d.key, st);
  }
  app.payload = payload;
  if (app.view === "overview") renderOverviewLight();
  else if (app.view === "devices") renderDevices();
  else if (app.view === "events") renderEvents();
  renderFootnote();
  app.prevStatus = next; app.primed = true;
}

// ---- drawer -------------------------------------------------------------- //
function findDevice(key) { return app.payload.devices.find((d) => d.key === key); }
function openDrawer(key) { app.selectedKey = key; renderDrawer(); $("drawer").classList.add("open"); $("drawer").setAttribute("aria-hidden", "false"); $("drawerScrim").hidden = false; }
function closeDrawer() { app.selectedKey = null; $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); $("drawerScrim").hidden = true; }
function renderDrawer() {
  const d = findDevice(app.selectedKey); if (!d) { closeDrawer(); return; }
  const st = String(d.status || "").toUpperCase();
  $("d-model").textContent = d.model || "—"; $("d-type").textContent = d.device_type || "—";
  const body = $("drawerBody"); body.textContent = "";
  body.append(h("div", { style: "margin-bottom:16px" }, statusPill(st)));
  const kv = h("dl", { class: "kv" });
  const add = (k, v) => { kv.append(h("dt", { text: k }), h("dd", {}, v == null || v === "" ? h("span", { class: "muted", text: "—" }) : h("span", { text: String(v) }))); };
  add("serial", d.serial_number); add("status", labelFor(st));
  add("uptime", st === "CONNECTED" ? fmtUptime(liveUptime(d)) : "—");
  add("updated", d.updated_at); add("owner pid", d.process_id || "—"); add("session", d.session_id); add("key", d.key);
  // per-device analytics
  const a = (app.ovAnalytics && app.ovAnalytics.instruments || []).find((x) => x.key === d.key);
  if (a) { add("transitions", a.transitions); add("reconnects", a.reconnects); add("failures", a.failures); add("warnings", a.warnings); }
  body.append(kv);
  if (d.last_error) { body.append(h("p", { class: "section-label", text: "last error" })); body.append(h("div", { class: "errbox", text: d.last_error })); }
  const hist = Array.isArray(d.history) ? d.history : [];
  body.append(h("p", { class: "section-label", style: "margin-top:18px", text: "status history" }));
  if (hist.length) {
    const tl = h("div", { class: "timeline" });
    for (const ev of hist) tl.append(h("span", { style: "background:" + statusVar(ev.status), title: labelFor(ev.status) + " · " + ev.ts }));
    body.append(tl);
    const ul = h("ul", { class: "histlist" });
    for (const ev of hist.slice(-8).reverse()) ul.append(h("li", {}, statusPill(ev.status, true), h("time", { text: relTime(ev.ts), title: ev.ts })));
    body.append(ul);
  } else body.append(h("p", { class: "hint", text: "No transitions observed yet this session." }));
}

// ---- actions ------------------------------------------------------------- //
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return r.json();
}
async function doClear(scope) {
  closeMenus();
  try { const r = await postJSON("/api/clear", { scope }); toast(r.ok ? `Removed ${r.removed} row${r.removed === 1 ? "" : "s"}` : (r.error || "Clear failed"), r.ok ? "ok" : "err"); }
  catch (e) { toast("Clear failed", "err"); }
}
function applyTheme(mode) {
  document.documentElement.setAttribute("data-theme", mode); localStorage.setItem("bsl-theme", mode);
  const dark = mode === "dark" || (mode === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  $("themeBtn").replaceChildren(icon(dark ? "i-sun" : "i-moon"));
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme");
  const dark = cur === "dark" || (cur === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  applyTheme(dark ? "light" : "dark");
  // re-render charts so SVG var() colors repaint crisply
  if (app.view === "overview") renderOverviewLight();
  if (app.view === "logs" && app.logs) refreshLogs({ quiet: true });
}
async function toggleNotify() {
  if (!app.notify) {
    if ("Notification" in window && Notification.permission !== "granted") { try { await Notification.requestPermission(); } catch (e) { /* ignore */ } }
    app.notify = true; beep();
  } else app.notify = false;
  localStorage.setItem("bsl-notify", app.notify ? "1" : "0");
  const b = $("notifyBtn"); b.classList.toggle("active", app.notify); b.title = "alerts: " + (app.notify ? "on" : "off");
}
function closeMenus() { $("clearMenu").hidden = true; $("exportMenu").hidden = true; }

// ---- email modal --------------------------------------------------------- //
async function openEmail() {
  let cfg;
  try { cfg = await (await fetch("/api/email-config")).json(); } catch (e) { toast("Could not load email config", "err"); return; }
  buildEmailForm(cfg); $("emailModal").hidden = false; $("modalScrim").hidden = false;
}
function closeEmail() { $("emailModal").hidden = true; $("modalScrim").hidden = true; }
function buildEmailForm(cfg) {
  const body = $("emailBody"); body.textContent = "";
  const cats = cfg.supported_categories || []; const defaults = new Set((cfg.default_categories || []).map((c) => c.toUpperCase()));
  const enabled = h("input", { type: "checkbox" }); enabled.checked = !!cfg.enabled;
  body.append(h("div", { class: "field" }, h("label", { class: "switch" }, enabled, "enable alert emails")));
  const recipient = h("input", { type: "email", value: cfg.recipient_email || "", placeholder: "lab-oncall@bsl-uiuc.com" });
  body.append(h("div", { class: "field" }, h("label", { text: "recipient" }), recipient));
  const ok = cfg.oauth && cfg.oauth.authorized;
  body.append(h("div", { class: "oauth-status " + (ok ? "ok" : "no"), text: (cfg.oauth && cfg.oauth.detail) || "" }));
  body.append(h("p", { class: "section-label", text: "default alert categories" }));
  const defWrap = h("div", { class: "cats" }); const defInputs = {};
  for (const c of cats) { const cb = h("input", { type: "checkbox" }); cb.checked = defaults.has(c.toUpperCase()); defInputs[c] = cb; defWrap.append(h("label", {}, cb, labelFor(c))); }
  body.append(defWrap);
  const matrix = cfg.instrument_category_matrix || {}; const instruments = cfg.instruments || [];
  body.append(h("p", { class: "section-label", style: "margin-top:18px", text: "per-instrument overrides (connected)" }));
  const matInputs = {};
  if (instruments.length) {
    const table = h("table", { class: "matrix" });
    const head = h("tr", {}, h("th", { text: "instrument" }), h("th", { text: "override" })); for (const c of cats) head.append(h("th", { text: labelFor(c) }));
    table.append(h("thead", {}, head)); const tb = h("tbody");
    for (const inst of instruments) {
      const present = Object.prototype.hasOwnProperty.call(matrix, inst); const cur = new Set((matrix[inst] || []).map((c) => c.toUpperCase()));
      const ov = h("input", { type: "checkbox" }); ov.checked = present; const boxes = {}; const tds = [h("td", { text: inst }), h("td", {}, ov)];
      for (const c of cats) { const cb = h("input", { type: "checkbox" }); cb.checked = present && cur.has(c.toUpperCase()); cb.disabled = !present; boxes[c] = cb; tds.push(h("td", {}, cb)); }
      ov.addEventListener("change", () => { for (const c of cats) boxes[c].disabled = !ov.checked; });
      matInputs[inst] = { ov, boxes }; tb.append(h("tr", {}, ...tds));
    }
    table.append(tb); body.append(table);
  } else body.append(h("p", { class: "hint", text: "No connected instruments to override right now." }));
  const sender = h("input", { type: "email", value: cfg.sender_email || "students@bsl-uiuc.com" });
  const secret = h("input", { type: "text", value: cfg.oauth_client_secrets_file || "", readonly: "", title: "configured locally" });
  const token = h("input", { type: "text", value: cfg.oauth_token_file || "", readonly: "", title: "configured locally" });
  body.append(h("details", { class: "adv" }, h("summary", { text: "advanced — sender, OAuth paths" }),
    h("div", { class: "field", style: "margin-top:12px" }, h("label", { text: "sender workspace email" }), sender),
    h("div", { class: "field" }, h("label", { text: "OAuth client secret JSON path (read-only)" }), secret, h("p", { class: "hint", text: "default: " + (cfg.default_oauth_client_secret_file || "—") })),
    h("div", { class: "field" }, h("label", { text: "OAuth token file path (read-only)" }), token, h("p", { class: "hint", text: "OAuth file paths are set locally (env / config file), not over the network, for security." }))));
  const collect = () => ({
    enabled: enabled.checked, recipient_email: recipient.value.trim(), sender_email: sender.value.trim() || "students@bsl-uiuc.com",
    default_categories: cats.filter((c) => defInputs[c].checked),
    instrument_category_matrix: Object.fromEntries(Object.entries(matInputs).filter(([, v]) => v.ov.checked).map(([inst, v]) => [inst, cats.filter((c) => v.boxes[c].checked)])),
  });
  const saveBtn = h("button", { class: "btn primary" }, icon("i-settings"), "save");
  const authBtn = h("button", { class: "btn" }, icon("i-key"), "authorize google");
  const testBtn = h("button", { class: "btn" }, icon("i-send"), "send test");
  saveBtn.addEventListener("click", async () => { try { const r = await postJSON("/api/email-config", collect()); buildEmailForm(r); toast("Saved email settings", "ok"); } catch (e) { toast("Save failed", "err"); } });
  authBtn.addEventListener("click", async () => { toast("Authorizing… complete the Google login in the browser on the host machine."); try { const r = await postJSON("/api/authorize", { sender_email: sender.value.trim(), recipient_email: recipient.value.trim() }); toast(r.message || (r.ok ? "Authorized" : "Authorization failed"), r.ok ? "ok" : "err"); openEmail(); } catch (e) { toast("Authorization failed", "err"); } });
  testBtn.addEventListener("click", async () => { try { const r = await postJSON("/api/test-email", {}); toast(r.message || (r.ok ? "Test sent" : "Test failed"), r.ok ? "ok" : "err"); } catch (e) { toast("Test failed", "err"); } });
  body.append(h("div", { class: "modal-actions" }, saveBtn, authBtn, testBtn));
}

// ---- wiring -------------------------------------------------------------- //
let searchTimer;
function wire() {
  applyTheme(localStorage.getItem("bsl-theme") || "auto");
  $("notifyBtn").classList.toggle("active", app.notify); $("notifyBtn").title = "alerts: " + (app.notify ? "on" : "off");

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchView(t.dataset.view)));

  $("filter").addEventListener("input", (e) => { app.filter = e.target.value; renderTable(); });
  $("activeOnly").addEventListener("change", (e) => { app.activeOnly = e.target.checked; renderTable(); });
  $("evtFilter").addEventListener("input", (e) => { app.evtFilter = e.target.value; renderEvents(); });
  $("evtLevel").addEventListener("change", (e) => { app.evtLevel = e.target.value; renderEvents(); });

  $("logRange").addEventListener("change", (e) => { app.logs.hours = parseFloat(e.target.value); refreshLogs(); });
  $("logModule").addEventListener("change", (e) => { app.logs.module = e.target.value; refreshLogs(); });
  $("logSearch").addEventListener("input", (e) => { clearTimeout(searchTimer); const v = e.target.value; searchTimer = setTimeout(() => { app.logs.q = v; refreshLogs(); }, 300); });
  $("logFollow").addEventListener("change", (e) => { app.logs.follow = e.target.checked; if (e.target.checked) refreshLogs({ quiet: true }); });
  $("logRefresh").addEventListener("click", () => refreshLogs());

  $("themeBtn").addEventListener("click", toggleTheme);
  $("notifyBtn").addEventListener("click", toggleNotify);
  $("emailBtn").addEventListener("click", openEmail);
  $("drawerClose").addEventListener("click", closeDrawer);
  $("drawerScrim").addEventListener("click", closeDrawer);
  $("modalClose").addEventListener("click", closeEmail);
  $("modalScrim").addEventListener("click", closeEmail);
  $("urlChip").addEventListener("click", async () => { const url = (app.payload.server || {}).lan_url || ""; try { await navigator.clipboard.writeText(url); toast("Copied " + url, "ok"); } catch (e) { toast(url); } });

  const menu = (b, p) => $(b).addEventListener("click", (e) => { e.stopPropagation(); const pop = $(p); const open = pop.hidden; closeMenus(); pop.hidden = !open; });
  menu("clearBtn", "clearMenu"); menu("exportBtn", "exportMenu");
  $("clearMenu").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => doClear(b.dataset.scope)));
  $("exportMenu").querySelectorAll("a").forEach((a) => a.addEventListener("click", closeMenus));
  document.addEventListener("click", closeMenus);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeDrawer(); closeEmail(); closeMenus(); }
    if ((e.key >= "1" && e.key <= "4") && !/input|select|textarea/i.test((e.target.tagName || ""))) switchView(["overview", "devices", "events", "logs"][+e.key - 1]);
  });

  // periodic relative-time refresh for the active view + live uptime
  app.timer = setInterval(() => {
    if (app.view === "devices") { renderTable(); renderFootnote(); }
    else if (app.view === "events") renderEvents();
    if (app.selectedKey) renderDrawer();
  }, 15000);
}

function connect() {
  if (!("EventSource" in window)) {
    const poll = async () => { try { apply(await (await fetch("/api/snapshot")).json()); setLive(true); } catch (e) { setLive(false); } };
    poll(); setInterval(poll, 2000); return;
  }
  const es = new EventSource("/api/stream");
  es.addEventListener("snapshot", (e) => { try { apply(JSON.parse(e.data)); setLive(true); } catch (err) { /* ignore */ } });
  es.onopen = () => setLive(true);
  es.onerror = () => setLive(false);
}

wire();
switchView("overview");
connect();
