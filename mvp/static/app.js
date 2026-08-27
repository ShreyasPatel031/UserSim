const form = document.getElementById("study-form");
const submitBtn = document.getElementById("submit-btn");
const btnLabel = submitBtn.querySelector(".btn-label");
const btnSpinner = submitBtn.querySelector(".btn-spinner");
const progressPanel = document.getElementById("progress");
const livePanel = document.getElementById("live-panel");
const resultsSection = document.getElementById("results");
const phaseLabel = document.getElementById("phase-label");
const progressFill = document.getElementById("progress-fill");
const progressElapsed = document.getElementById("progress-elapsed");
const progressAgents = document.getElementById("progress-agents");
const progressHint = document.getElementById("progress-hint");
const errorPanel = document.getElementById("error-panel");
const errorMessage = document.getElementById("error-message");

const PHASE_PROGRESS = {
  Starting: 5,
  "Fetching site": 12,
  "Generating personas & tasks": 22,
  "Writing executive summary": 92,
  Complete: 100,
  "Site blocked": 100,
  Failed: 100,
};

function studyProgress(phase) {
  if (PHASE_PROGRESS[phase] != null) return PHASE_PROGRESS[phase];
  let prep = phase && phase.match(/^Preparing browser sessions — (\d+)\/(\d+) ready/);
  if (prep) {
    const i = Number(prep[1]);
    const n = Number(prep[2]);
    return 22 + Math.round((i / Math.max(n, 1)) * 4);
  }
  let m = phase && phase.match(/^Live browser agents — (\d+)\/(\d+) done/);
  if (m) {
    const i = Number(m[1]);
    const n = Number(m[2]);
    const base = 26;
    const span = 58;
    if (i === 0) {
      const stepsMatch = phase.match(/(\d+) steps$/);
      const steps = stepsMatch ? Number(stepsMatch[1]) : 0;
      return base + Math.min(12, steps * 2 + span / (n * 2));
    }
    return base + Math.round((i / n) * span);
  }
  return 10;
}

let _traceResults = [];
let _activeTraceIdx = 0;
let _userPickedTrace = false;
let _activityRendered = 0;
let _lastStudyData = null;

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")} elapsed`;
}

function formatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

function mergeSessions(data) {
  const tasks = data.tasks || [];
  const personas = data.personas || [];
  const personaById = Object.fromEntries(personas.map((p) => [p.id, p]));
  const live = data.live_sessions || [];
  const completed = data.agent_results || [];
  const byId = {};

  for (const s of live) {
    if (s?.agent_id) byId[s.agent_id] = { ...s };
  }
  for (const r of completed) {
    const id = r.agent_id || r.task_id;
    byId[id] = { ...byId[id], ...r, status: "complete" };
  }

  return tasks.map((t) => {
    const id = t.id;
    const persona = personaById[t.persona_id];
    const base = byId[id] || {
      agent_id: id,
      task_id: id,
      task_title: t.title,
      task_prompt: t.prompt,
      persona_id: t.persona_id,
      persona_name: persona?.name,
      persona_bio: persona?.bio,
      status: "pending",
      trace: [],
    };
    if (!base.persona_name && persona) base.persona_name = persona.name;
    return base;
  });
}

function statusLabel(status) {
  switch (status) {
    case "running":
      return "Browsing";
    case "summarizing":
      return "Summarizing";
    case "complete":
      return "Done";
    case "error":
      return "Fallback";
    case "pending":
    default:
      return "Queued";
  }
}

function setLoading(loading) {
  submitBtn.disabled = loading;
  btnSpinner.hidden = !loading;
  btnLabel.textContent = loading ? "Running study…" : "Run study";
}

function showError(msg) {
  errorPanel.hidden = false;
  errorMessage.textContent = msg;
}

function hideError() {
  errorPanel.hidden = true;
}

function resetLiveUI() {
  _traceResults = [];
  _activeTraceIdx = 0;
  _userPickedTrace = false;
  _activityRendered = 0;
  _lastStudyData = null;
  document.getElementById("activity-log").innerHTML = "";
  document.getElementById("personas-grid").innerHTML = "";
  document.getElementById("personas-section").hidden = true;
}

function updateProgressUI(data, startedAt) {
  const phase = data.phase || data.status || "Starting";
  phaseLabel.textContent = phase;
  progressFill.style.width = `${studyProgress(phase)}%`;

  const totalAgents = (data.tasks || []).length || 4;
  const finished = (data.agent_results || []).length;
  const liveMatch = phase.match(
    /(\d+)\/(\d+) done · (\d+) active(?: · (\d+) queued)? · (\d+) steps/
  );
  if (liveMatch) {
    const [, done, total, active, queued, steps] = liveMatch;
    progressAgents.textContent = `${done} / ${total} done · ${active} browsing · ${steps} steps`;
    if (Number(queued) > 0) {
      progressHint.textContent = `${active} agents browsing in parallel (${queued} waiting for a browser slot — free tier allows 3 at once). First step takes ~1–2 min.`;
    } else if (Number(active) > 0) {
      progressHint.textContent = `${active} agents browsing in parallel. Steps stream below as they act.`;
    } else if (Number(done) > 0) {
      progressHint.textContent = "Sessions are finishing — select a persona below to watch their trace.";
    } else {
      progressHint.textContent = "Agents starting — first browser step can take 1–2 minutes.";
    }
  } else if (phase.startsWith("Preparing browser sessions")) {
    progressAgents.textContent = `Warming browser pool (${phase.split("—")[1]?.trim() || ""})`;
    progressHint.textContent =
      "Creating Browserbase sessions so the first 3 agents can browse in parallel…";
  } else {
    progressAgents.textContent = `${finished} / ${totalAgents} agents finished`;
    if (finished > 0) {
      progressHint.textContent = "Sessions are finishing — select a persona below to watch their trace.";
    } else if (phase.includes("Live browser agents")) {
      progressHint.textContent =
        "Live browser sessions running (2–4 min each). Steps stream in below as agents browse.";
    } else if (phase === "Generating personas & tasks") {
      progressHint.textContent = "Planner is reading your site and creating personas & tasks…";
    } else if (phase === "Fetching site") {
      progressHint.textContent = "Fetching the page (HTTP → Playwright → Browserbase if needed)…";
    }
  }
  progressElapsed.textContent = formatElapsed(Math.floor((Date.now() - startedAt) / 1000));
}

function renderActivityLog(log) {
  const el = document.getElementById("activity-log");
  const items = log || [];
  if (items.length <= _activityRendered) return;

  for (let i = _activityRendered; i < items.length; i++) {
    const item = items[i];
    const li = document.createElement("li");
    li.className = `activity-item activity-${item.kind || "info"}`;
    li.innerHTML = `
      <span class="activity-time">${escapeHtml(formatTime(item.at))}</span>
      <span class="activity-kind">${escapeHtml(item.kind || "info")}</span>
      <span class="activity-msg">${escapeHtml(item.message || "")}</span>
    `;
    el.appendChild(li);
  }
  _activityRendered = items.length;
  el.scrollTop = el.scrollHeight;
}

const THOUGHT_LABELS = {
  next_goal: "Next goal",
  evaluation_previous_goal: "Previous step",
  thinking: "Reasoning",
  memory: "Memory",
};

function formatThoughtText(text) {
  if (!text) return "";
  return String(text)
    .replace(/<\/?redacted_thinking>/gi, "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/(\d+\.\s)/g, "\n$1")
    .replace(/^\n+/, "")
    .trim();
}

function parseThoughtDetail(step) {
  const detail = step?.thought_detail;
  if (detail && typeof detail === "object" && Object.keys(detail).length) {
    return detail;
  }
  const raw = formatThoughtText(step?.thought);
  return raw ? { note: raw } : {};
}

function summarizeThought(detail) {
  const pick =
    detail.next_goal ||
    detail.evaluation_previous_goal ||
    detail.thinking ||
    detail.memory ||
    detail.note ||
    "";
  const text = formatThoughtText(pick).replace(/\n/g, " ");
  if (!text) return "Agent reasoning";
  return text.length > 140 ? `${text.slice(0, 137)}…` : text;
}

function renderThoughtHtml(step) {
  const detail = parseThoughtDetail(step);
  const order = ["next_goal", "evaluation_previous_goal", "thinking", "memory", "note"];
  const entries = order
    .filter((key) => detail[key] && formatThoughtText(detail[key]))
    .map((key) => [key, formatThoughtText(detail[key])]);

  if (!entries.length) return "";

  const body = entries
    .map(
      ([key, value]) => `
      <div class="thought-section">
        <h5>${escapeHtml(THOUGHT_LABELS[key] || key)}</h5>
        <pre class="thought-text">${escapeHtml(value)}</pre>
      </div>`
    )
    .join("");

  return `
    <details class="thought-details">
      <summary><span class="thought-summary-label">Reasoning</span> ${escapeHtml(summarizeThought(detail))}</summary>
      <div class="thought-body">${body}</div>
    </details>`;
}

function renderTraceStepsHtml(trace, status) {
  if (!trace?.length) {
    const msg =
      status === "running"
        ? "Browsing — steps will stream in here…"
        : status === "pending"
          ? "Waiting to start…"
          : "No steps recorded yet.";
    return `<p class="trace-empty">${msg}</p>`;
  }

  return trace
    .map(
      (step) => `
    <article class="trace-step outcome-${escapeHtml(step.outcome || "neutral")}">
      <div class="trace-step-num">${escapeHtml(step.step ?? "")}</div>
      <div class="trace-step-body">
        <h4>${escapeHtml(step.action || "Action")}</h4>
        ${step.url ? `<p><strong>URL:</strong> ${escapeHtml(step.url)}</p>` : ""}
        <p><strong>Sees:</strong> ${escapeHtml(step.observation || "")}</p>
        ${renderThoughtHtml(step)}
        ${
          step.screenshot_url
            ? `<figure class="trace-step-figure">
            <img class="trace-step-screenshot" src="${escapeHtml(step.screenshot_url)}" alt="Step ${escapeHtml(step.step)} screenshot" loading="lazy" />
            <figcaption class="trace-step-screenshot-caption">Boxes = clickable elements in view</figcaption>
          </figure>`
            : ""
        }
      </div>
    </article>`
    )
    .join("");
}

function renderPersonas(personas, sessions) {
  const section = document.getElementById("personas-section");
  const grid = document.getElementById("personas-grid");
  _traceResults = sessions || [];

  if (!personas?.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  grid.innerHTML = "";

  if (!_userPickedTrace) {
    const firstWithTrace = sessions.findIndex((s) => (s.trace || []).length > 0);
    if (firstWithTrace >= 0) _activeTraceIdx = firstWithTrace;
  } else if (_activeTraceIdx >= sessions.length) {
    _activeTraceIdx = Math.max(0, sessions.length - 1);
  }

  personas.forEach((p) => {
    const sessionIdx = sessions.findIndex((s) => s.persona_id === p.id);
    const session = sessionIdx >= 0 ? sessions[sessionIdx] : null;
    const expanded = sessionIdx >= 0 && sessionIdx === _activeTraceIdx;
    const taskText = session?.task_prompt || session?.task_title || "";
    const trace = session?.trace || [];
    const lastAction = session?.last_action || trace[trace.length - 1]?.action || "";
    const liveHint =
      !expanded && session?.status === "pending"
        ? "Waiting for browser slot…"
        : !expanded && session?.status === "running" && !lastAction
          ? "Browser session starting (first step ~1–2 min)…"
          : !expanded && lastAction
            ? lastAction
            : "";

    const card = document.createElement("article");
    card.className = `persona-session-card${expanded ? " expanded active" : ""}`;
    if (sessionIdx >= 0) card.dataset.sessionIdx = String(sessionIdx);

    const feedbackBlock =
      expanded && session?.product_feedback
        ? `
      <div class="persona-feedback">
        <p>${escapeHtml(session.product_feedback)}</p>
        ${session.quote ? `<blockquote class="quote">"${escapeHtml(session.quote)}"</blockquote>` : ""}
      </div>`
        : "";

    card.innerHTML = `
      <button type="button" class="persona-session-header" aria-expanded="${expanded ? "true" : "false"}">
        <div class="persona-session-title">
          <h3>${escapeHtml(p.name || "Persona")}</h3>
          ${
            session
              ? `<div class="meta">
            <span class="tag status-${session.status || "pending"}">${escapeHtml(statusLabel(session.status))}</span>
            <span class="tag">${trace.length} steps</span>
            ${session.difficulty ? `<span class="tag difficulty-${session.difficulty}">${escapeHtml(session.difficulty)}</span>` : ""}
            ${session.would_convert ? `<span class="tag">convert: ${escapeHtml(session.would_convert)}</span>` : ""}
          </div>`
              : ""
          }
        </div>
        <span class="persona-chevron" aria-hidden="true">${expanded ? "▾" : "▸"}</span>
      </button>
      <div class="persona-session-body">
        ${p.bio ? `<p class="persona-bio">${escapeHtml(p.bio)}</p>` : ""}
        ${taskText ? `<p class="persona-task"><strong>Task:</strong> ${escapeHtml(taskText)}</p>` : ""}
        ${liveHint ? `<p class="persona-live-hint">${escapeHtml(liveHint)}</p>` : ""}
        ${
          expanded
            ? `<div class="persona-trace trace-timeline">${renderTraceStepsHtml(trace, session?.status)}</div>${feedbackBlock}`
            : ""
        }
      </div>
    `;

    card.querySelector(".persona-session-header")?.addEventListener("click", () => {
      if (sessionIdx >= 0) selectTrace(sessionIdx, true);
    });
    grid.appendChild(card);
  });
}

function selectTrace(idx, userInitiated = false) {
  if (userInitiated) {
    _userPickedTrace = true;
    if (_activeTraceIdx === idx) {
      _activeTraceIdx = -1;
    } else {
      _activeTraceIdx = idx;
    }
  } else {
    _activeTraceIdx = idx;
  }
  if (_lastStudyData) {
    renderPersonas(_lastStudyData.personas, mergeSessions(_lastStudyData));
    if (_activeTraceIdx >= 0) {
      const card = document.querySelector(`.persona-session-card[data-session-idx="${_activeTraceIdx}"]`);
      card?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

function renderAgents(results) {
  const grid = document.getElementById("agents-grid");
  const section = document.getElementById("agents-section-final");
  if (!grid) return;
  if (!results?.length) {
    if (section) section.hidden = true;
    return;
  }
  if (section) section.hidden = false;
  grid.innerHTML = "";

  results.forEach((r, idx) => {
    const card = document.createElement("article");
    card.className = "agent-card";
    card.style.cursor = "pointer";
    const friction = (r.friction_points || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
    const easy = (r.what_was_easy || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
    card.innerHTML = `
      <h3>${escapeHtml(r.persona_name || "Agent")} — ${escapeHtml(r.task_title || "Task")}</h3>
      <div class="meta">
        <span class="tag difficulty-${r.difficulty || "medium"}">${escapeHtml(r.difficulty || "medium")}</span>
        <span class="tag">would convert: ${escapeHtml(r.would_convert || "?")}</span>
        <span class="tag">${(r.trace || []).length} steps</span>
      </div>
      <p style="margin-top:0.75rem">${escapeHtml(r.product_feedback || "")}</p>
      <blockquote class="quote">"${escapeHtml(r.quote || "")}"</blockquote>
      <div class="agent-lists">
        <div><h4>Friction</h4><ul>${friction || "<li>—</li>"}</ul></div>
        <div><h4>Easy</h4><ul>${easy || "<li>—</li>"}</ul></div>
      </div>
    `;
    card.addEventListener("click", () => {
      livePanel.hidden = false;
      selectTrace(idx, true);
    });
    grid.appendChild(card);
  });
}

function renderList(el, items) {
  el.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    el.appendChild(li);
  });
}

function renderSummary(summary, accessBackend, browserbaseSessionUrl) {
  if (!summary) return;
  const infoEl = document.getElementById("access-info");
  const backend = accessBackend || summary.access_backend;
  const sessionUrl = browserbaseSessionUrl || summary.browserbase_session_url;
  if (backend) {
    infoEl.hidden = false;
    const msg = `Page loaded via ${backend}.`;
    infoEl.innerHTML = sessionUrl
      ? `${msg} <a href="${escapeHtml(sessionUrl)}" target="_blank" rel="noopener">View Browserbase session</a>`
      : msg;
  } else {
    infoEl.hidden = true;
  }

  document.getElementById("headline").textContent = summary.headline || "";
  renderList(document.getElementById("top-friction"), summary.top_friction);
  renderList(document.getElementById("top-strengths"), summary.top_strengths);
  document.getElementById("fit-score").textContent = summary.segment_fit_score ?? "—";
  document.getElementById("fit-rationale").textContent = summary.segment_fit_rationale || "";
  document.getElementById("conversion-outlook").textContent = summary.conversion_outlook || "";

  const recEl = document.getElementById("recommendations");
  recEl.innerHTML = "";
  (summary.recommendations || []).forEach((rec) => {
    const div = document.createElement("div");
    div.className = "rec-card";
    div.innerHTML = `
      <span class="priority ${escapeHtml(rec.priority || "medium")}">${escapeHtml(rec.priority || "medium")}</span>
      <div>
        <strong>${escapeHtml(rec.action || "")}</strong>
        <p style="margin:0.25rem 0 0;color:var(--text-muted);font-size:0.9rem">${escapeHtml(rec.rationale || "")}</p>
      </div>
    `;
    recEl.appendChild(div);
  });
}

function renderLiveStudy(data) {
  _lastStudyData = data;
  const sessions = mergeSessions(data);
  renderActivityLog(data.activity_log);
  renderPersonas(data.personas, sessions);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function pollStudy(studyId) {
  const res = await fetch(`/api/studies/${studyId}`);
  if (!res.ok) throw new Error("Failed to fetch study status");
  return res.json();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideError();
  resetLiveUI();
  resultsSection.hidden = true;
  livePanel.hidden = false;
  progressPanel.hidden = false;
  setLoading(true);

  const url = form.url.value.trim();
  const segment = form.segment.value.trim();

  try {
    const startRes = await fetch("/api/studies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, segment }),
    });
    const raw = await startRes.text();
    if (!startRes.ok) {
      let detail = "Could not start study";
      try {
        const err = JSON.parse(raw);
        detail = err.detail || err.error || detail;
        if (typeof detail !== "string") detail = JSON.stringify(detail);
      } catch {
        if (raw) detail = raw.slice(0, 300);
      }
      throw new Error(detail);
    }

    const payload = JSON.parse(raw);
    const studyId = payload.study_id || payload.id;
    const startedAt = Date.now();
    livePanel.scrollIntoView({ behavior: "smooth" });

    let data = payload;
    // Vercel runs the full study synchronously in POST — response is already complete.
    if (!data?.personas && studyId) {
      data = await pollStudy(studyId);
    }

    if (data.status === "complete" || data.summary || data.agent_results?.length) {
      updateProgressUI({ ...data, phase: "Complete", status: "complete" }, startedAt);
      renderLiveStudy(data);
      if (!data.summary && (!data.agent_results || !data.agent_results.length)) {
        throw new Error("Study finished but returned no results.");
      }
      progressFill.style.width = "100%";
      phaseLabel.textContent = "Complete";
      renderSummary(data.summary, data.access_backend, data.browserbase_session_url);
      renderAgents(data.agent_results);
      resultsSection.hidden = false;
      await new Promise((r) => setTimeout(r, 600));
      progressPanel.hidden = true;
      setLoading(false);
      return;
    }

    let pollData;
    while (true) {
      pollData = await pollStudy(studyId);
      data = pollData;
      updateProgressUI(data, startedAt);
      renderLiveStudy(data);

      if (data.status === "complete") break;
      if (data.status === "error") throw new Error(data.error || "Study failed");
      await new Promise((r) => setTimeout(r, 1500));
    }

    if (!data.summary && (!data.agent_results || !data.agent_results.length)) {
      throw new Error("Study finished but returned no results. Check server logs.");
    }

    progressFill.style.width = "100%";
    phaseLabel.textContent = "Complete";
    renderLiveStudy(data);
    renderSummary(data.summary, data.access_backend, data.browserbase_session_url);
    renderAgents(data.agent_results);
    resultsSection.hidden = false;

    await new Promise((r) => setTimeout(r, 600));
    progressPanel.hidden = true;
  } catch (err) {
    progressPanel.hidden = true;
    showError(err.message || String(err));
  } finally {
    setLoading(false);
  }
});
