/* fishbowl dashboard - zero dependencies, hash routing, polling */
"use strict";

/* ---------------------------------------------------------------- utils */
const $ = (id) => document.getElementById(id);

async function api(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.json();
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtTokens(n) {
  if (n == null) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

function fmtUsd(v) {
  if (v == null) return "—";
  return "$" + (v >= 100 ? v.toFixed(0) : v.toFixed(2));
}

function parseTs(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  return isNaN(t) ? null : t;
}

function ago(iso) {
  const t = parseTs(iso);
  if (t == null) return "—";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return Math.floor(s) + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

function since(iso) {
  const t = parseTs(iso);
  if (t == null) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "for " + Math.floor(s) + "s";
  if (s < 3600) return "for " + Math.floor(s / 60) + "m" +
    (s % 60 >= 30 ? "+" : "");
  return "for " + (s / 3600).toFixed(1) + "h";
}

function fmtMs(ms) {
  if (ms == null) return "";
  if (ms < 1000) return ms + "ms";
  if (ms < 60000) return (ms / 1000).toFixed(1) + "s";
  return (ms / 60000).toFixed(1) + "m";
}

function fmtTime(iso) {
  const t = parseTs(iso);
  if (t == null) return "";
  const d = new Date(t);
  return d.toTimeString().slice(0, 8);
}

function fmtCost(c) { return c == null ? "—" : "$" + c.toFixed(2); }

/* ---------------------------------------------------------------- theme */
const THEME_KEY = "fishbowl-theme";
function applyTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const dark = saved ? saved === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}
applyTheme();
$("theme-toggle").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme;
  localStorage.setItem(THEME_KEY, cur === "dark" ? "light" : "dark");
  applyTheme();
});

/* ---------------------------------------------------------------- router */
const POLL = { sessions: 3000, session: 2000, stats: 30000 };
let pollTimer = null;

function route() {
  const h = location.hash || "#/";
  let view, render, ms;
  if (h.startsWith("#/session/")) {
    const sid = decodeURIComponent(h.slice("#/session/".length));
    view = "view-session"; render = () => renderSession(sid);
    ms = POLL.session;
    $("nav-sessions").classList.add("active");
    $("nav-stats").classList.remove("active");
  } else if (h.startsWith("#/stats")) {
    view = "view-stats"; render = renderStats; ms = POLL.stats;
    $("nav-stats").classList.add("active");
    $("nav-sessions").classList.remove("active");
  } else {
    view = "view-sessions"; render = renderSessions; ms = POLL.sessions;
    $("nav-sessions").classList.add("active");
    $("nav-stats").classList.remove("active");
  }
  for (const el of document.querySelectorAll(".view")) {
    el.classList.toggle("active", el.id === view);
  }
  if (pollTimer) clearInterval(pollTimer);
  const tick = () => render().catch((e) => console.warn(e));
  tick();
  pollTimer = setInterval(tick, ms);
  refreshTopbar().catch(() => {});
}
window.addEventListener("hashchange", route);

async function refreshTopbar() {
  const h = await api("/api/health");
  const b = $("mode-badge");
  b.textContent = h.mode === "demo" ? "demo" : "live";
  b.className = "badge " + (h.mode === "demo" ? "warn" : "ok");
  $("indexing").hidden = !h.indexing;
  $("scan-info").textContent =
    h.files_watched + " files · " + h.lines_parsed + " lines" +
    (h.parse_errors ? " · " + h.parse_errors + " parse errors" : "");
}

/* ------------------------------------------------------------- sessions */
async function renderSessions() {
  const data = await api("/api/sessions");
  const sessions = data.sessions;
  const root = $("view-sessions");
  refreshTopbar();

  const active = sessions.filter((s) => s.status === "active").length;
  const stalled = sessions.filter((s) => s.status === "stalled").length;
  const a = $("count-active"), st = $("count-stalled");
  a.hidden = active === 0; a.textContent = active + " active";
  st.hidden = stalled === 0; st.textContent = stalled + " stalled";

  if (!sessions.length) {
    root.innerHTML = "<div class='card'>No sessions found yet. " +
      "fishbowl watches <code>~/.claude/projects</code> by default — " +
      "or start a Claude Code session and wait a couple of seconds.</div>";
    return;
  }

  const groups = new Map();
  for (const s of sessions) {
    if (!groups.has(s.project)) groups.set(s.project, []);
    groups.get(s.project).push(s);
  }

  let html = "";
  for (const [project, list] of groups) {
    html += "<h2 class='project'>" + esc(project) +
      " <span class='muted'>(" + list.length + ")</span></h2>";
    html += "<table class='rows'><thead><tr>" +
      "<th>Status</th><th>Session</th><th>Current action</th>" +
      "<th class='num'>Tokens</th><th class='num'>Cost</th>" +
      "<th>Last</th></tr></thead><tbody>";
    for (const s of list) {
      const ca = s.current_action;
      const actionHtml = ca
        ? "<span class='action'>" + esc(ca.summary) +
          (ca.kind === "tool_call"
            ? " <span class='elapsed'>" +
              esc(since(ca.ts)) + "</span>" : "") + "</span>"
        : "<span class='muted'>—</span>";
      const u = s.usage;
      html += "<tr class='rowlink' data-sid='" + esc(s.session_id) + "'>" +
        "<td><span class='pill " + s.status + "'>" + s.status + "</span></td>" +
        "<td class='title-cell'>" + esc(s.title) +
        "<div class='sub'>" + esc(s.git_branch || "") +
        (s.subagents.length
          ? " · " + s.subagents.length + " subagents" : "") +
        "</div></td>" +
        "<td>" + actionHtml + "</td>" +
        "<td class='num'>" + fmtTokens(
          u.input_tokens + u.cache_read_tokens + u.cache_write_tokens +
          u.output_tokens) + "</td>" +
        "<td class='num'>" + fmtCost(s.cost_usd) + "</td>" +
        "<td class='nowrap muted'>" + ago(s.last_activity_at) + "</td>" +
        "</tr>";
    }
    html += "</tbody></table>";
  }
  root.innerHTML = html;
  for (const tr of root.querySelectorAll("tr.rowlink")) {
    tr.addEventListener("click", () => {
      location.hash = "#/session/" + tr.dataset.sid;
    });
  }
  $("last-refresh").textContent = "updated " +
    new Date().toTimeString().slice(0, 8);
}

/* -------------------------------------------------------------- session */
const KIND_LABEL = {
  user_prompt: "you", assistant_text: "agent", thinking: "thinking",
  tool_call: "tool", tool_result: "result", workflow: "workflow",
  queue: "queue", parse_error: "parse?",
};

function timelineHtml(activities) {
  // merge tool_call + tool_result pairs, newest first for display
  const byCall = new Map();
  const rows = [];
  for (const a of activities) {
    if (a.kind === "tool_result" && a.tool_use_id &&
        byCall.has(a.tool_use_id)) {
      const row = byCall.get(a.tool_use_id);
      row.result = a;
      continue;
    }
    const row = { call: a, result: null };
    if (a.tool_use_id) byCall.set(a.tool_use_id, row);
    rows.push(row);
  }
  rows.reverse();                       // newest first
  return rows.map((r) => {
    const main = r.result || r.call;
    const kind = r.result ? "tool_result" : r.call.kind;
    let body = esc(main.summary);
    let extra = "";
    if (r.result && r.result.duration_ms != null) {
      extra = " <span class='t-dur'>· " +
        fmtMs(r.result.duration_ms) + "</span>";
    } else if (r.call.kind === "tool_call" && r.result == null &&
               main.kind !== "user_prompt") {
      extra = " <span class='t-dur'>· running " +
        esc(since(r.call.ts)) + "</span>";
    }
    if (main.is_error) body = "<span class='t-err'>" + body + "</span>";
    return "<li" + (main.sidechain ? " class='sidechain'" : "") + ">" +
      "<span class='t-time'>" + fmtTime(main.ts) + "</span>" +
      "<span class='t-kind " + kind + "'>" +
      (KIND_LABEL[kind] || kind) + "</span>" +
      "<span class='t-body'>" + body + extra + "</span></li>";
  }).join("");
}

async function renderSession(sid) {
  const data = await api("/api/sessions/" + encodeURIComponent(sid));
  const s = data.session;
  refreshTopbar();
  const u = s.usage;
  const totalTok = u.input_tokens + u.cache_read_tokens +
    u.cache_write_tokens + u.output_tokens;

  const ca = s.current_action;
  const pending = s.pending_tools && s.pending_tools.length;

  let html = "<a class='back' href='#/'>← all sessions</a>";

  html += "<div class='card current " +
    (s.status === "stalled" ? "stalled" : "") + "'>" +
    "<div class='label'>current action · " +
    "<span class='pill " + s.status + "'>" + s.status + "</span></div>" +
    (ca ? "<div class='what'>" + esc(ca.summary) + "</div>" +
      "<div class='since'>since " + esc(ca.ts) + " (" +
      esc(since(ca.ts)) + ")</div>" : "") +
    (pending ? "<div class='since'>⚠ " + pending +
      " tool call(s) awaiting result</div>" : "") +
    (s.status === "stalled"
      ? "<div class='since'>No transcript activity for a while — " +
        "this agent looks stuck.</div>" : "") +
    "</div>";

  html += "<div class='card'><div class='kv'>" +
    "<span><b>" + esc(s.title) + "</b></span>" +
    "<span>cwd: <b class='mono'>" + esc(s.cwd || s.project_dir) +
    "</b></span>" +
    "<span>branch: <b>" + esc(s.git_branch || "—") + "</b></span>" +
    "<span>model: <b>" + esc(Object.keys(u.models || {}).join(", ") ||
      "—") + "</b></span>" +
    "<span>tokens: <b>" + fmtTokens(totalTok) + "</b></span>" +
    "<span>est. cost: <b>" + fmtCost(s.cost_usd) + "</b></span>" +
    "<span>tools: <b>" + (s.counts.tools || 0) + "</b>" +
    (s.counts.errors ? " · errors: <b>" + s.counts.errors + "</b>"
      : "") + "</span>" +
    "<span>started: <b>" + esc(s.started_at || "—") + "</b></span>" +
    "<span>last: <b>" + ago(s.last_activity_at) + "</b></span>" +
    "</div>";

  if (s.subagents && s.subagents.length) {
    html += "<h2 class='project'>subagents</h2><table class='rows'>" +
      "<tbody>";
    for (const a of s.subagents) {
      html += "<tr><td class='mono'>" + esc(a.agent_type || "?") + "</td>" +
        "<td>" + esc(a.description || "") + "</td>" +
        "<td class='action'>" + esc(a.last_action || "") + "</td>" +
        "<td class='nowrap muted'>" + ago(a.last_ts) + "</td></tr>";
    }
    html += "</tbody></table>";
  }
  html += "</div>";

  html += "<div class='card'><h2 class='project'>timeline</h2>" +
    "<ul class='timeline'>" + timelineHtml(data.activities) + "</ul>" +
    (data.activities.length >= 200
      ? "<div class='muted'>…showing the newest 200 events</div>" : "") +
    "</div>";

  $("view-session").innerHTML = html;
  $("last-refresh").textContent = "updated " +
    new Date().toTimeString().slice(0, 8);
}

/* ---------------------------------------------------------------- stats */
async function renderStats() {
  const d = await api("/api/stats");
  refreshTopbar();
  const root = $("view-stats");

  let html = "<div class='card'><div class='kv'>" +
    "<span>sessions: <b>" + d.session_count + "</b></span>" +
    "<span>active: <b>" + d.sessions_by_status.active + "</b></span>" +
    "<span>idle: <b>" + d.sessions_by_status.idle + "</b></span>" +
    "<span>stalled: <b>" + d.sessions_by_status.stalled + "</b></span>" +
    "<span>archived: <b>" + d.sessions_by_status.archived + "</b></span>" +
    "</div></div>";

  html += "<div class='card'><h2 class='project'>tokens by model " +
    "(last 24h: " + fmtTokens(d.last_24h.input_tokens +
      d.last_24h.cache_read_tokens + d.last_24h.output_tokens) +
    ")</h2>";
  const models = d.by_model;
  const maxTok = Math.max(1, ...models.map((m) =>
    m.input_tokens + m.cache_read_tokens + m.output_tokens));
  const palette = ["b1", "b2", "b3", "b4"];
  models.forEach((m, i) => {
    const tok = m.input_tokens + m.cache_read_tokens + m.output_tokens;
    const w = Math.max(2, Math.round(tok / maxTok * 100));
    html += "<div class='bar-row'>" +
      "<span class='bar-label' title='" + esc(m.model) + "'>" +
      esc(m.model) + "</span>" +
      "<span class='bar-track'><span class='bar-fill " +
      palette[i % palette.length] + "' style='width:" + w + "%'></span></span>" +
      "<span class='bar-val'>" + fmtTokens(tok) + " · " +
      fmtUsd(m.cost_usd) + "</span></div>";
  });
  if (!models.length) html += "<div class='muted'>no usage recorded</div>";
  html += "</div>";

  if (d.priciest_sessions.length) {
    html += "<div class='card'><h2 class='project'>priciest sessions" +
      "</h2><table class='rows'><tbody>";
    for (const p of d.priciest_sessions) {
      html += "<tr class='rowlink' data-sid='" + esc(p.session_id) + "'>" +
        "<td class='num'>" + fmtUsd(p.cost_usd) + "</td>" +
        "<td class='title-cell'>" + esc(p.title) + "</td>" +
        "<td class='muted'>" + esc(p.project) + "</td>" +
        "<td class='num'>" + fmtTokens(p.total_tokens) + " tok</td>" +
        "</tr>";
    }
    html += "</tbody></table></div>";
  }
  root.innerHTML = html;
  for (const tr of root.querySelectorAll("tr.rowlink")) {
    tr.addEventListener("click", () => {
      location.hash = "#/session/" + tr.dataset.sid;
    });
  }
  $("last-refresh").textContent = "updated " +
    new Date().toTimeString().slice(0, 8);
}

/* ---------------------------------------------------------------- start */
route();
