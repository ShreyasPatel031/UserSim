/** Developer live dashboard — lists studies and polls frames by study id. */

const listEl = document.getElementById("study-list");
const emptyEl = document.getElementById("live-empty");
const watchEl = document.getElementById("live-watch");
const agentGrid = document.getElementById("agent-grid");
const watchId = document.getElementById("watch-id");
const watchUrl = document.getElementById("watch-url");
const watchPhase = document.getElementById("watch-phase");
const watchMeta = document.getElementById("watch-meta");
const runtimeEl = document.getElementById("runtime-status");

const params = new URLSearchParams(location.search);
let selectedId = params.get("study") || localStorage.getItem("usersim_last_study") || "";
let listTimer = null;
let watchTimer = null;
let runtimeTimer = null;
let bootDone = false;
let killing = false;

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusClass(status) {
  const s = String(status || "").toLowerCase();
  if (s === "complete") return "ok";
  if (s === "error" || s === "abandoned" || s === "killed") return "err";
  if (s === "running" || s === "pending") return "run";
  return "";
}

async function fetchList() {
  const res = await fetch("/api/studies?limit=40");
  if (!res.ok) throw new Error("Failed to list studies");
  const data = await res.json();
  return data.studies || [];
}

async function fetchStudy(id) {
  const res = await fetch(`/api/studies/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error("Study not found");
  return res.json();
}

async function fetchRuntime() {
  const res = await fetch("/api/runtime/status");
  if (!res.ok) throw new Error("runtime status failed");
  return res.json();
}

function renderRuntime(data) {
  if (!runtimeEl) return;
  const bb = data.browserbase_running ?? 0;
  const studies = data.local_studies_running ?? 0;
  const vms = data.vms || [];
  const fleet = vms.filter((v) => v.kind === "fleet").length;
  const seeds = vms.filter((v) => v.kind === "seed").length;
  runtimeEl.textContent = `${bb} Browserbase · ${studies} local studies · ${fleet} fleet VMs · ${seeds} seed VMs`;
}

async function refreshRuntime() {
  try {
    renderRuntime(await fetchRuntime());
  } catch (err) {
    if (runtimeEl) runtimeEl.textContent = err.message || "runtime check failed";
  }
}

async function killNow({ agents = true, vms = false, seeds = false } = {}) {
  if (killing) return;
  killing = true;
  const buttons = ["kill-agents", "kill-agents-vms", "kill-everything"]
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  buttons.forEach((b) => {
    b.disabled = true;
  });
  if (runtimeEl) runtimeEl.textContent = "Killing…";
  try {
    const res = await fetch("/api/runtime/kill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agents, vms, seeds }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Kill failed");
    if (data.status) renderRuntime(data.status);
    else await refreshRuntime();
    await refreshList();
    if (selectedId) await refreshWatch();
  } catch (err) {
    if (runtimeEl) runtimeEl.textContent = err.message || "Kill failed";
  } finally {
    killing = false;
    buttons.forEach((b) => {
      b.disabled = false;
    });
  }
}

function dedupeStudiesOnePerUrl(studies) {
  const rank = { running: 0, pending: 1, queued: 2, complete: 3, error: 4, abandoned: 5 };
  const best = new Map();
  for (const s of studies) {
    let key = s.url || s.id || "";
    try {
      const u = new URL(key.startsWith("http") ? key : `https://${key}`);
      const host = u.hostname.replace(/^www\./, "");
      const path = (u.pathname || "/").replace(/\/$/, "") || "/";
      key = `${host}${path}`;
    } catch {
      key = String(s.id || key);
    }
    const cur = best.get(key);
    if (!cur) {
      best.set(key, s);
      continue;
    }
    const rn = rank[String(s.status || "")] ?? 9;
    const ro = rank[String(cur.status || "")] ?? 9;
    if (rn < ro || (rn === ro && String(s.updated_at || "") >= String(cur.updated_at || ""))) {
      best.set(key, s);
    }
  }
  return [...best.values()].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
}

function renderList(studies) {
  listEl.innerHTML = "";
  studies = dedupeStudiesOnePerUrl(studies);
  if (!studies.length) {
    listEl.innerHTML = `<li class="live-study-empty">No studies yet — start one from New run.</li>`;
    return;
  }
  for (const s of studies) {
    const li = document.createElement("li");
    const active = s.id === selectedId ? " active" : "";
    const cls = statusClass(s.status);
    li.innerHTML = `
      <button type="button" class="live-study-item${active}" data-id="${escapeHtml(s.id)}">
        <span class="live-study-status ${cls}">${escapeHtml(s.status || "?")}</span>
        <span class="live-study-url">${escapeHtml(s.url || s.id)}</span>
        <span class="live-study-stats">${escapeHtml(String(s.steps ?? 0))} steps · ${escapeHtml(String(s.agents ?? 0))} agents</span>
        <span class="live-study-phase">${escapeHtml((s.phase || "").slice(0, 80))}</span>
      </button>`;
    listEl.appendChild(li);
  }
  listEl.querySelectorAll("[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => selectStudy(btn.getAttribute("data-id")));
  });
}

function latestShot(session) {
  const trace = session?.trace || [];
  for (let i = trace.length - 1; i >= 0; i--) {
    if (trace[i]?.screenshot_url) return trace[i];
  }
  return null;
}

function renderWatch(data) {
  emptyEl.hidden = true;
  watchEl.hidden = false;
  watchId.textContent = data.id || selectedId;
  watchUrl.textContent = data.url || "Study";
  watchPhase.textContent = `${data.status || "?"} · ${data.phase || ""}`;
  const reportLink = document.getElementById("open-report-link");
  const studyId = data.id || selectedId || "";
  const reportReady = data.status === "complete" && Boolean(data.summary);
  if (reportLink) {
    if (reportReady && studyId) {
      reportLink.href = `/report?study=${encodeURIComponent(studyId)}`;
      reportLink.hidden = false;
    } else {
      reportLink.hidden = true;
    }
  }
  const live = data.live_sessions || [];
  const items = Array.isArray(live) ? live : Object.values(live);
  const steps = items.reduce((n, s) => n + (s.trace?.length || 0), 0);
  const withShots = items.filter((s) => latestShot(s)).length;
  watchMeta.innerHTML = `
    <span>${items.length} agents</span>
    <span>${withShots} with screenshots</span>
    <span>${steps} frames</span>
    <span>${(data.personas || []).length} users</span>
    <span>${(data.tasks || []).length} tasks</span>`;

  agentGrid.innerHTML = "";
  const sorted = [...items].sort((a, b) => {
    const as = latestShot(a) ? 0 : 1;
    const bs = latestShot(b) ? 0 : 1;
    if (as !== bs) return as - bs;
    const ar = a.status === "running" ? 0 : a.status === "starting" ? 1 : 2;
    const br = b.status === "running" ? 0 : b.status === "starting" ? 1 : 2;
    if (ar !== br) return ar - br;
    return (b.trace?.length || 0) - (a.trace?.length || 0);
  });
  for (const sess of sorted) {
    const shot = latestShot(sess);
    const card = document.createElement("article");
    card.className = "live-agent-card";
    const site = sess.site_label || sess.site_key || "";
    const browsing = ["starting", "pending", "running"].includes(String(sess.status || ""));
    let frame;
    if (shot?.screenshot_url) {
      frame = `<img src="${escapeHtml(shot.screenshot_url)}?t=${Date.now()}" alt="" loading="eager" />`;
    } else if (browsing && sess.live_view_url) {
      frame = `<iframe class="live-agent-iframe" src="${escapeHtml(sess.live_view_url)}" title="live" sandbox="allow-same-origin allow-scripts" referrerpolicy="no-referrer"></iframe>`;
    } else {
      frame = `<div class="live-agent-waiting">${escapeHtml(sess.last_action || sess.status || "waiting for first frame…")}</div>`;
    }
    card.innerHTML = `
      <header>
        <strong>${escapeHtml(sess.persona_name || sess.agent_id || "agent")}</strong>
        <span class="live-study-status ${statusClass(sess.status)}">${escapeHtml(sess.status || "")}</span>
      </header>
      <p class="live-agent-task">${escapeHtml(sess.task_title || "")}${
        site ? ` · <em>${escapeHtml(site)}</em>` : ""
      }</p>
      <div class="live-agent-frame">${frame}</div>
      <p class="live-agent-step">${
        shot
          ? `step ${escapeHtml(shot.step)} · ${escapeHtml(shot.action || "")}`
          : browsing && sess.live_view_url
            ? "live view — waiting for screenshot"
            : "no frame yet"
      }</p>`;
    agentGrid.appendChild(card);
  }
}

function rememberStudy(id) {
  selectedId = id;
  localStorage.setItem("usersim_last_study", id);
  const url = new URL(location.href);
  url.searchParams.set("study", id);
  history.replaceState({}, "", url);
}

function startWatchPolling() {
  if (watchTimer) clearInterval(watchTimer);
  watchTimer = setInterval(refreshWatch, 3000);
}

async function selectStudy(id) {
  if (!id) return;
  rememberStudy(id);
  // Load frames immediately — do NOT wait on the slow study list.
  await refreshWatch();
  startWatchPolling();
  refreshList().catch(() => {});
}

async function refreshList() {
  try {
    if (!listEl.querySelector(".live-study-item") && !listEl.querySelector(".live-study-empty")) {
      listEl.innerHTML = `<li class="live-study-empty">Loading studies…</li>`;
    }
    const studies = await fetchList();
    const newestRunning = studies.find((s) => s.status === "running" || s.status === "pending");
    if (selectedId) {
      const stillThere = studies.some((s) => s.id === selectedId);
      if (!stillThere && newestRunning) selectedId = newestRunning.id;
    }
    if (!selectedId && studies.length) {
      selectedId = (newestRunning || studies[0]).id;
    }
    renderList(studies);
    if (selectedId) {
      rememberStudy(selectedId);
      if (!bootDone || watchEl.hidden) {
        await refreshWatch();
        startWatchPolling();
      }
    }
  } catch (err) {
    listEl.innerHTML = `<li class="live-study-empty">${escapeHtml(err.message)}</li>`;
  }
}

async function refreshWatch() {
  if (!selectedId) return;
  try {
    const data = await fetchStudy(selectedId);
    renderWatch(data);
  } catch (err) {
    emptyEl.hidden = true;
    watchEl.hidden = false;
    watchPhase.textContent = err.message;
  }
}

document.getElementById("refresh-list").addEventListener("click", () => {
  refreshList();
  refreshRuntime();
});

document.getElementById("kill-agents")?.addEventListener("click", () => {
  killNow({ agents: true, vms: false, seeds: false });
});
document.getElementById("kill-agents-vms")?.addEventListener("click", () => {
  killNow({ agents: true, vms: true, seeds: false });
});
document.getElementById("kill-everything")?.addEventListener("click", () => {
  killNow({ agents: true, vms: true, seeds: true });
});

listEl.innerHTML = `<li class="live-study-empty">Loading studies…</li>`;

(async function boot() {
  // If we already know the study id, show frames first (list can lag on GCS).
  if (selectedId) {
    await refreshWatch();
    startWatchPolling();
  }
  await Promise.all([refreshList(), refreshRuntime()]);
  bootDone = true;
  listTimer = setInterval(refreshList, 12000);
  runtimeTimer = setInterval(refreshRuntime, 8000);
})();
