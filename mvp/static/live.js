/** Developer live dashboard — lists GCS studies and polls frames by study id. */

const listEl = document.getElementById("study-list");
const emptyEl = document.getElementById("live-empty");
const watchEl = document.getElementById("live-watch");
const agentGrid = document.getElementById("agent-grid");
const watchId = document.getElementById("watch-id");
const watchUrl = document.getElementById("watch-url");
const watchPhase = document.getElementById("watch-phase");
const watchMeta = document.getElementById("watch-meta");

const params = new URLSearchParams(location.search);
let selectedId = params.get("study") || localStorage.getItem("usersim_last_study") || "";
let listTimer = null;
let watchTimer = null;

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
  if (s === "error" || s === "abandoned") return "err";
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

function renderList(studies) {
  listEl.innerHTML = "";
  if (!studies.length) {
    listEl.innerHTML = `<li class="live-study-empty">No studies in GCS yet.</li>`;
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
  const live = data.live_sessions || [];
  const items = Array.isArray(live) ? live : Object.values(live);
  const steps = items.reduce((n, s) => n + (s.trace?.length || 0), 0);
  watchMeta.innerHTML = `
    <span>${items.length} agents</span>
    <span>${steps} frames</span>
    <span>${(data.personas || []).length} users</span>
    <span>${(data.tasks || []).length} tasks</span>`;

  agentGrid.innerHTML = "";
  const sorted = [...items].sort((a, b) => {
    const ar = a.status === "running" ? 0 : a.status === "starting" ? 1 : 2;
    const br = b.status === "running" ? 0 : b.status === "starting" ? 1 : 2;
    if (ar !== br) return ar - br;
    return (b.trace?.length || 0) - (a.trace?.length || 0);
  });
  for (const sess of sorted) {
    const shot = latestShot(sess);
    const card = document.createElement("article");
    card.className = "live-agent-card";
    const img = shot?.screenshot_url
      ? `<img src="${escapeHtml(shot.screenshot_url)}?t=${Date.now()}" alt="" loading="lazy" />`
      : `<div class="live-agent-waiting">${escapeHtml(sess.last_action || sess.status || "waiting")}</div>`;
    card.innerHTML = `
      <header>
        <strong>${escapeHtml(sess.persona_name || sess.agent_id || "agent")}</strong>
        <span class="live-study-status ${statusClass(sess.status)}">${escapeHtml(sess.status || "")}</span>
      </header>
      <p class="live-agent-task">${escapeHtml(sess.task_title || sess.site_label || "")}</p>
      <div class="live-agent-frame">${img}</div>
      <p class="live-agent-step">${shot ? `step ${escapeHtml(shot.step)} · ${escapeHtml(shot.action || "")}` : "no frame yet"}</p>`;
    agentGrid.appendChild(card);
  }
}

async function selectStudy(id) {
  if (!id) return;
  selectedId = id;
  localStorage.setItem("usersim_last_study", id);
  const url = new URL(location.href);
  url.searchParams.set("study", id);
  history.replaceState({}, "", url);
  await refreshList();
  await refreshWatch();
  if (watchTimer) clearInterval(watchTimer);
  watchTimer = setInterval(refreshWatch, 4000);
}

async function refreshList() {
  try {
    const studies = await fetchList();
    renderList(studies);
    if (!selectedId && studies.length) {
      const running = studies.find((s) => s.status === "running");
      await selectStudy((running || studies[0]).id);
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
    watchPhase.textContent = err.message;
  }
}

document.getElementById("refresh-list").addEventListener("click", refreshList);

refreshList();
listTimer = setInterval(refreshList, 12000);
if (selectedId) {
  selectStudy(selectedId);
}
