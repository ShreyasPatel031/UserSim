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

const PHASE_PROGRESS = {
  Starting: 5,
  "Understanding context of product": 14,
  "Fetching site": 14,
  "Finding competitors": 22,
  "Building simulated users": 28,
  "Building simulated users & tasks": 30,
  "Writing tasks": 32,
  "Inventing simulated users & tasks": 30,
  "Finding competitors & simulated users": 26,
  "Generating personas & tasks": 30,
  "Brief ready": 34,
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
let _shotIdx = {};
let _shotFollowLatest = {};
let _activeTraceIdx = 0;
let _userPickedTrace = false;
let _activityRendered = 0;
let _lastStudyData = null;
let _notifyEmail = "";
let _emailCaptureSubmitted = false;
let _briefScrollStep = "";
const BRIEF_SCROLL_ORDER = ["products", "users", "tasks", "live"];
const IS_LOCAL_HOST = /^(localhost|127\.0\.0\.1)$/i.test(location.hostname);

function scrollBriefTo(elOrId, step) {
  const order = BRIEF_SCROLL_ORDER;
  const next = order.indexOf(step);
  const cur = order.indexOf(_briefScrollStep);
  if (next < 0 || (cur >= 0 && next <= cur)) return;
  _briefScrollStep = step;
  const el = typeof elOrId === "string" ? document.getElementById(elOrId) : elOrId;
  if (!el || el.hidden) return;
  requestAnimationFrame(() => {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

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
  const liveRaw = data.live_sessions || [];
  const live = Array.isArray(liveRaw)
    ? liveRaw
    : Object.values(liveRaw || {});
  const completed = data.agent_results || [];
  const byId = {};

  for (const s of live) {
    if (!s?.agent_id) continue;
    const copy = { ...s };
    // Keep live_view_url — UI mounts it only after live_active.
    delete copy.debugger_url;
    byId[s.agent_id] = copy;
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
      status: "pending",
      trace: [],
    };
    const merged = {
      ...base,
      agent_id: base.agent_id || id,
      task_id: base.task_id || id,
      task_title: base.task_title || t.title,
      task_prompt: base.task_prompt || t.prompt,
      persona_id: base.persona_id || t.persona_id,
      persona_name: base.persona_name || persona?.name,
      persona_bio: base.persona_bio || persona?.bio,
      site_key: base.site_key || t.site_key || "product",
      site_url: base.site_url || t.site_url || data.url || "",
      site_label: base.site_label || t.site_label || "Product",
      _persona: persona || null,
    };
    return merged;
  });
}

function statusLabel(status) {
  switch (status) {
    case "running":
      return "Browsing";
    case "starting":
      return "Starting";
    case "summarizing":
      return "Summarizing";
    case "complete":
      return "Done";
    case "error":
      return "Fallback";
    case "pending":
      return "Queued";
    default:
      return status || "…";
  }
}

function setLoading(loading) {
  submitBtn.disabled = loading;
  btnSpinner.hidden = !loading;
  btnLabel.textContent = loading ? "…" : "Run";
}

function showError(msg) {
  const text = String(msg || "Couldn’t finish this run. Try again in a moment.");
  if (progressHint) progressHint.textContent = text;
  if (phaseLabel) phaseLabel.textContent = "Paused";
}

function hideError() {
  /* public UI has no error panel */
}

function resetLiveUI() {
  _traceResults = [];
  _activeTraceIdx = 0;
  _userPickedTrace = false;
  _activityRendered = 0;
  _lastStudyData = null;
  _shotIdx = {};
  _shotFollowLatest = {};
  _notifyEmail = "";
  _emailCaptureSubmitted = false;
  _briefScrollStep = "";
  document.getElementById("brief-section").hidden = true;
  document.getElementById("stage-section").hidden = true;
  const reportLink = document.getElementById("view-report-link");
  if (reportLink) reportLink.hidden = true;
  const emailPrompt = document.getElementById("report-email-prompt");
  if (emailPrompt) emailPrompt.hidden = true;
  const emailSaved = document.getElementById("report-email-saved");
  if (emailSaved) {
    emailSaved.hidden = true;
    emailSaved.textContent = "";
  }
  const emailForm = document.getElementById("report-email-form");
  if (emailForm) emailForm.hidden = false;
  document.getElementById("products-list").innerHTML = "";
  document.getElementById("tasks-list").innerHTML = "";
  const usersRail = document.getElementById("users-rail");
  if (usersRail) usersRail.innerHTML = "";
  const usersPanel = document.getElementById("users-panel");
  const tasksPanel = document.getElementById("tasks-panel");
  if (usersPanel) usersPanel.hidden = true;
  if (tasksPanel) tasksPanel.hidden = true;
  const usersSpin = document.getElementById("users-searching");
  const tasksSpin = document.getElementById("tasks-searching");
  if (usersSpin) usersSpin.hidden = true;
  if (tasksSpin) tasksSpin.hidden = true;
  document.getElementById("stage-body").innerHTML = "";
  const siteSwitch = document.getElementById("stage-site-switch");
  if (siteSwitch) siteSwitch.innerHTML = "";
  const taskSelect = document.getElementById("stage-task-select");
  if (taskSelect) taskSelect.innerHTML = "";
  const userSelect = document.getElementById("stage-user-select");
  if (userSelect) userSelect.innerHTML = "";
  const legacySwitch = document.getElementById("stage-user-switch");
  if (legacySwitch) legacySwitch.innerHTML = "";
  const emailStatus = document.getElementById("email-status");
  if (emailStatus) {
    emailStatus.hidden = true;
    emailStatus.textContent = "";
  }
}

function updateProgressUI(data, startedAt) {
  const phase = data.phase || data.status || "Starting";
  phaseLabel.textContent = phase;
  progressFill.style.width = `${studyProgress(phase)}%`;

  const totalAgents = (data.tasks || []).length;
  const finished = (data.agent_results || []).length;
  const liveMatch = phase.match(
    /(\d+)\/(\d+) done · (\d+) active(?: · (\d+) queued)? · (\d+) steps/
  );
  if (liveMatch) {
    const [, done, total, active, queued, steps] = liveMatch;
    progressAgents.textContent = `${done} / ${total} done · ${active} browsing · ${steps} steps`;
    if (Number(queued) > 0) {
      progressHint.textContent = `${active} simulated users browsing (${queued} waiting). Watch the stage below.`;
    } else if (Number(active) > 0) {
      progressHint.textContent = `Watching one simulated user click through — step screenshots update below.`;
    } else if (Number(done) > 0) {
      progressHint.textContent = "Sessions finishing — report coming next.";
    } else {
      progressHint.textContent = "Browser starting — first screenshot in ~1–2 min.";
    }
  } else if (phase.startsWith("Preparing browser sessions")) {
    progressAgents.textContent = `Warming browser pool (${phase.split("—")[1]?.trim() || ""})`;
    progressHint.textContent = "Opening live Browserbase windows — they appear in the stage as soon as each is ready…";
  } else {
    if (!totalAgents) {
      progressAgents.textContent = "Planning sessions…";
    } else {
      progressAgents.textContent = `${finished} / ${totalAgents} sessions finished`;
    }
    if (phase === "Understanding context of product" || phase === "Fetching site") {
      progressHint.textContent = "Understanding context of the product…";
    } else if (phase === "Finding competitors") {
      progressHint.textContent = "Searching the web for competitors…";
    } else if (
      phase === "Building simulated users" ||
      phase === "Building simulated users & tasks" ||
      phase === "Inventing simulated users & tasks" ||
      phase === "Generating personas & tasks" ||
      phase === "Finding competitors & simulated users"
    ) {
      progressHint.textContent = "Building simulated users…";
    } else if (phase === "Writing tasks") {
      progressHint.textContent = "Writing tasks…";
    } else if (phase === "Brief ready") {
      progressHint.textContent = "Brief ready — launching browsers…";
    } else if (phase === "Writing executive summary") {
      progressHint.textContent = "All sessions done — writing the report…";
    } else if (phase.includes("Live browser") || phase.includes("Simulating")) {
      progressHint.textContent = "Watch the stage — screenshots update as each persona browses.";
    } else if (finished > 0) {
      progressHint.textContent = "Wrapping up sessions…";
    } else if (!totalAgents) {
      progressHint.textContent = "Building the brief — personas and tasks appear first.";
    }
  }
  progressElapsed.textContent = formatElapsed(Math.floor((Date.now() - startedAt) / 1000));
}

function renderActivityLog(log) {
  const el = document.getElementById("activity-log");
  if (!el) return;
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

function demographicLine(p) {
  if (!p) return "";
  const bits = [
    p.age_range || p.age,
    p.occupation || p.role,
    p.location,
    p.tech_comfort ? `tech: ${p.tech_comfort}` : "",
  ].filter(Boolean);
  if (bits.length) return bits.join(" · ");
  return p.demographics || "";
}

function stepShotSrc(step) {
  const inline = step?.screenshot_data_url || "";
  if (typeof inline === "string" && inline.startsWith("data:image/")) return inline;
  return step?.screenshot_url || "";
}

function stepsWithScreenshots(trace) {
  return (trace || []).filter((s) => stepShotSrc(s));
}

/** Prefer the newest frame that is still on the assigned site (agents sometimes wander). */
function preferredShots(session) {
  const shots = stepsWithScreenshots(session?.trace);
  if (!shots.length) return shots;
  const host = siteHostname(session?.site_url);
  if (!host) return shots;
  const onSite = shots.filter((s) => {
    const h = siteHostname(s.url);
    return h && (h === host || h.endsWith(`.${host}`) || host.endsWith(`.${h}`));
  });
  return onSite.length ? onSite : shots;
}

function renderFocusStage(session, sessionIdx) {
  const persona = session?._persona;
  const demos = demographicLine(persona);
  const taskText = session?.task_prompt || session?.task_title || "";
  const trace = session?.trace || [];
  const shots = preferredShots(session);
  const key = String(sessionIdx ?? 0);
  // Follow newest frame (0 → 1 → …) unless user scrubbed away.
  if (_shotFollowLatest[key] !== false) {
    _shotIdx[key] = Math.max(0, shots.length - 1);
  } else if (_shotIdx[key] == null || _shotIdx[key] >= shots.length) {
    _shotIdx[key] = Math.max(0, shots.length - 1);
  }
  const idx = shots.length ? _shotIdx[key] : 0;
  const step = shots[idx];
  const lastAction = session?.last_action || trace[trace.length - 1]?.action || "";
  const lastObs = trace[trace.length - 1]?.observation || "";
  const siteName = prettySiteName(session?.site_url, session?.site_label);

  let visual = "";
  const browsing = ["starting", "pending", "running"].includes(String(session?.status || ""));
  const liveView = session?.live_view_url;
  // XOR: live iframe when agent is up; otherwise screenshot; never both.
  const showLive = Boolean(liveView && session?.live_active && browsing);
  const shotSrc = !showLive && step ? stepShotSrc(step) : "";
  if (showLive) {
    visual = `
      <div class="stage-visuals">
        <div class="stage-live-wrap" data-live-src="${escapeHtml(liveView)}">
          <iframe
            class="stage-live-frame"
            src="${escapeHtml(liveView)}"
            title="Live browser — ${escapeHtml(siteName)}"
            sandbox="allow-same-origin allow-scripts"
            allow="clipboard-read; clipboard-write"
            referrerpolicy="no-referrer"
          ></iframe>
          <p class="stage-live-caption">Live browser · ${escapeHtml(siteName)} · agent acting</p>
        </div>
      </div>`;
  } else if (shotSrc) {
    const boxes = step?.boxes || [];
    const boxLegend = boxes.length
      ? `<details class="stage-box-details"><summary><span class="box-swatch box-red"></span> ${boxes.length} click targets${
          step.highlight_index != null ? ` · green = #${escapeHtml(step.highlight_index)}` : ""
        }</summary>
         <ol class="stage-box-list">${boxes
           .slice(0, 12)
           .map(
             (b) =>
               `<li${step.highlight_index === b.index ? ' class="hl"' : ""}><strong>${escapeHtml(b.index)}</strong> ${escapeHtml(b.label || b.tag || "element")}</li>`
           )
           .join("")}${boxes.length > 12 ? `<li>… +${boxes.length - 12} more</li>` : ""}</ol></details>`
      : "";
    visual = `
      <div class="stage-visuals">
        <figure class="stage-shot">
          <img class="trace-screenshot" data-shot-src="${escapeHtml(shotSrc)}" src="${escapeHtml(shotSrc)}" alt="Step ${escapeHtml(step?.step ?? 0)} screenshot" loading="eager" />
          <figcaption><strong>Step ${escapeHtml(step?.step ?? 0)}</strong> — ${escapeHtml(step?.action || "Opened page")}${
            browsing ? " · waiting for agent…" : ""
          }</figcaption>
        </figure>
      </div>
      ${boxLegend}
      ${
        shots.length
          ? `<div class="stage-shot-nav">
        <button type="button" class="step-nav" data-shot-key="${escapeHtml(key)}" data-shot-delta="-1" ${idx <= 0 ? "disabled" : ""}>← Prev</button>
        <div class="trace-step-pills">
          ${shots
            .map(
              (s, i) =>
                `<button type="button" class="step-pill${i === idx ? " active" : ""}" data-shot-key="${escapeHtml(key)}" data-shot-idx="${i}">${escapeHtml(s.step)}</button>`
            )
            .join("")}
        </div>
        <button type="button" class="step-nav" data-shot-key="${escapeHtml(key)}" data-shot-delta="1" ${idx >= shots.length - 1 ? "disabled" : ""}>Next →</button>
      </div>`
          : ""
      }`;
  } else {
    const waitingMsg =
      session?.status === "summarizing"
        ? "Page captured — writing feedback…"
        : browsing
          ? session?.last_action ||
            (Array.isArray(session?.live_thoughts) && session.live_thoughts.length
              ? session.live_thoughts[session.live_thoughts.length - 1].text
              : null) ||
            "Opening the page…"
          : "Waiting for the first browser frame…";
    visual = `
      <div class="stage-waiting">
        <div class="stage-waiting-chrome"><span></span><span></span><span></span><strong>${escapeHtml(statusLabel(session?.status))}</strong></div>
        <p>${escapeHtml(waitingMsg)}</p>
      </div>`;
  }

  const thoughts = Array.isArray(session?.live_thoughts) ? session.live_thoughts : [];
  const thoughtPanel = thoughts.length
    ? `<div class="stage-thoughts" aria-live="polite">
        <p class="stage-label">Live thoughts</p>
        <ul class="stage-thought-list">
          ${thoughts
            .slice(-8)
            .map(
              (t) =>
                `<li class="stage-thought stage-thought-${escapeHtml(t.kind || "status")}">${escapeHtml(
                  t.text || ""
                )}</li>`
            )
            .join("")}
        </ul>
      </div>`
    : "";

  const latestThought =
    thoughts.length ? thoughts[thoughts.length - 1]?.text : step?.thought || "";

  return `
    <div class="stage-card">
      <div class="stage-identity">
        <div>
          <p class="stage-label">Simulated user</p>
          <h3>${escapeHtml(session?.persona_name || persona?.name || "Simulated user")}</h3>
          ${demos ? `<p class="stage-demos">${escapeHtml(demos)}</p>` : ""}
          ${persona?.bio ? `<p class="persona-bio">${escapeHtml(persona.bio)}</p>` : ""}
        </div>
        <div>
          <p class="stage-label">Task</p>
          <p class="persona-task stage-task">${escapeHtml(taskText || "Task pending…")}</p>
          <div class="meta">
            <span class="tag status-${session?.status || "pending"}">${escapeHtml(statusLabel(session?.status))}</span>
            ${session?.site_url || session?.site_label ? `<span class="tag site">${escapeHtml(prettySiteName(session.site_url, session.site_label))}</span>` : ""}
            <span class="tag">${trace.length} steps</span>
          </div>
        </div>
      </div>
      ${visual}
      ${thoughtPanel}
      ${
        step || latestThought
          ? `<p class="step-shot-action"><strong>Now doing:</strong> ${escapeHtml(
              step?.action || session?.last_action || "Browsing"
            )}</p>
             ${
               latestThought
                 ? `<p class="trace-step-observation"><strong>Thinking:</strong> ${escapeHtml(latestThought)}</p>`
                 : step?.observation
                   ? `<p class="trace-step-observation"><strong>They see:</strong> ${escapeHtml(step.observation)}</p>`
                   : ""
             }`
          : ""
      }
      ${
        session?.product_feedback
          ? `<div class="persona-feedback"><p>${escapeHtml(session.product_feedback)}</p>
             ${session.quote ? `<blockquote class="quote">"${escapeHtml(session.quote)}"</blockquote>` : ""}</div>`
          : ""
      }
    </div>`;
}

function baseTaskId(id) {
  return String(id || "").split("__")[0];
}

function cleanTaskTitle(title) {
  return String(title || "")
    .replace(/\s*\(vs\s+[^)]+\)\s*$/i, "")
    .trim();
}

function uniqueBriefTasks(tasks) {
  const seen = new Set();
  const out = [];
  for (const t of tasks || []) {
    const key = baseTaskId(t.id) || cleanTaskTitle(t.title) || t.prompt;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push({
      ...t,
      id: key,
      title: cleanTaskTitle(t.title) || t.title,
    });
  }
  return out;
}

function siteHostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return String(url || "")
      .replace(/^https?:\/\//i, "")
      .replace(/^www\./i, "")
      .split("/")[0];
  }
}

function prettySiteName(url, fallback) {
  const host = siteHostname(url);
  if (!host) return fallback || "Site";
  const known = {
    "youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "vimeo.com": "Vimeo",
    "netflix.com": "Netflix",
    "twitch.tv": "Twitch",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
    "reddit.com": "Reddit",
    "spotify.com": "Spotify",
    "apple.com": "Apple",
    "music.apple.com": "Apple Music",
    "amazon.com": "Amazon",
    "primevideo.com": "Prime Video",
    "disneyplus.com": "Disney+",
    "hulu.com": "Hulu",
    "useagency.dev": "Agency",
    "langchain.com": "LangChain",
    "langgraph.dev": "LangGraph",
  };
  if (known[host]) return known[host];
  const base = host.split(".").slice(0, -1).join(".") || host;
  const brand = base.split(".").pop() || base;
  return brand.charAt(0).toUpperCase() + brand.slice(1);
}

function faviconUrl(url) {
  const host = siteHostname(url);
  if (!host) return "";
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`;
}

function productSites(data) {
  const sites = [];
  const seen = new Set();
  const add = (url, label, kind) => {
    const href = String(url || "").trim();
    if (!href) return;
    const key = href.replace(/\/$/, "").toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    const pretty = prettySiteName(href, label);
    const rawLabel = String(label || "").trim();
    const looksLikeUrl = /^https?:\/\//i.test(rawLabel) || rawLabel === href;
    sites.push({
      url: href,
      label: looksLikeUrl || !rawLabel || rawLabel === "Your product" || rawLabel === "Product"
        ? pretty
        : rawLabel,
      host: siteHostname(href),
      kind,
      site_key: kind === "product" ? "product" : undefined,
    });
  };
  add(data?.url, "Your product", "product");
  (data?.competitors || []).forEach((c, i) => {
    if (typeof c === "string") add(c, c, "competitor");
    else add(c?.url, c?.name || c?.url, "competitor");
    const last = sites[sites.length - 1];
    if (last && last.kind === "competitor" && !last.site_key) {
      last.site_key = `competitor_${i + 1}`;
    }
  });
  return sites;
}

function isSearchingCompetitors(data) {
  // Product-only runs (empty competitors box) never invent rivals — don't spin.
  if (data?.skip_competitors) return false;
  const phase = String(data?.phase || "");
  const hasComps = (data?.competitors || []).length > 0;
  if (hasComps) return false;
  if (!phase) return true;
  return (
    /understanding context|fetching site|finding competitors|starting/i.test(phase) ||
    phase === "Finding competitors & simulated users"
  );
}

function isBuildingUsersPhase(phase) {
  return /building simulated users|inventing simulated users|generating personas|finding competitors & simulated users/i.test(
    String(phase || "")
  );
}

function isWritingTasksPhase(phase) {
  return /^writing tasks$/i.test(String(phase || "").trim());
}

function isSearchingUsers(data) {
  const personas = data?.personas || [];
  if (personas.length) return false;
  const phase = String(data?.phase || "");
  if (isBuildingUsersPhase(phase)) return true;
  // Competitors landed — next step is users.
  return (data?.competitors || []).length > 0 && !isWritingTasksPhase(phase);
}

function isSearchingTasks(data) {
  const tasks = uniqueBriefTasks(data?.tasks || []);
  if (tasks.length) return false;
  const personas = data?.personas || [];
  if (!personas.length) return false;
  // Only after users exist and we've entered the tasks phase.
  return isWritingTasksPhase(String(data?.phase || ""));
}

function renderBrief(data, sessions) {
  const brief = document.getElementById("brief-section");
  const tasks = uniqueBriefTasks(data.tasks || []);
  const personas = data.personas || [];
  const products = productSites(data);
  const searching = isSearchingCompetitors(data);
  const searchingUsers = isSearchingUsers(data);
  const searchingTasks = isSearchingTasks(data);
  brief.hidden = false;

  const pEl = document.getElementById("products-list");
  if (!products.length) {
    pEl.innerHTML = `<p class="brief-empty">Resolving product…</p>`;
  } else {
    pEl.innerHTML = products
      .map((p) => {
        const role = p.kind === "product" ? "Your product" : "Competitor";
        const icon = faviconUrl(p.url);
        const spin =
          p.kind === "product" && searching
            ? `<span class="product-search-spin" title="Searching for competitors" aria-label="Searching"></span>`
            : "";
        const status =
          p.kind === "product" && searching
            ? `<span class="product-search-label">Searching rivals…</span>`
            : `<span>${escapeHtml(role)}</span>`;
        return `
          <a class="product-tile${p.kind === "product" ? " is-product" : ""}${
            p.kind === "product" && searching ? " is-searching" : ""
          }" href="${escapeHtml(p.url)}" target="_blank" rel="noopener">
            ${
              icon
                ? `<img class="product-favicon" src="${escapeHtml(icon)}" alt="" width="20" height="20" loading="lazy" />`
                : `<span class="product-favicon product-favicon-fallback">${escapeHtml((p.label || "?").slice(0, 1))}</span>`
            }
            <span class="product-tile-text">
              <strong>${escapeHtml(p.label)}</strong>
              ${status}
            </span>
            ${spin}
          </a>`;
      })
      .join("");
  }
  if (products.length) scrollBriefTo("products-panel", "products");

  const usersPanel = document.getElementById("users-panel");
  const rail = document.getElementById("users-rail");
  const usersSpin = document.getElementById("users-searching");
  const showUsers = searchingUsers || personas.length > 0;
  if (!showUsers) {
    usersPanel.hidden = true;
    if (usersSpin) usersSpin.hidden = true;
  } else {
    usersPanel.hidden = false;
    if (usersSpin) usersSpin.hidden = !searchingUsers;
    if (searchingUsers && !personas.length) {
      rail.innerHTML = `<p class="brief-empty brief-loading-row"><span class="product-search-spin" aria-hidden="true"></span> Building simulated users…</p>`;
    } else {
      const activePersonaId =
        sessions[_activeTraceIdx]?.persona_id ||
        sessions.find((s) => (s.trace || []).length)?.persona_id ||
        "";
      rail.innerHTML = personas
        .map((p) => {
          const demos = demographicLine(p);
          const sessionIdx = sessions.findIndex((s) => s.persona_id === p.id);
          const selected = Boolean(p.id && p.id === activePersonaId);
          const goals = (p.goals || []).filter(Boolean);
          const meta = [p.age_range, p.occupation, p.location].filter(Boolean);
          return `
          <button type="button" class="user-card${selected ? " is-selected" : ""}" data-persona-id="${escapeHtml(p.id || "")}" data-session-idx="${sessionIdx}" aria-pressed="${selected ? "true" : "false"}">
            <span class="user-card-top">
              <span class="user-card-identity">
                <strong>${escapeHtml(p.name || "Simulated user")}</strong>
                ${
                  meta.length
                    ? `<span class="user-card-meta">${escapeHtml(meta.join(" · "))}</span>`
                    : demos
                      ? `<span class="user-card-meta">${escapeHtml(demos)}</span>`
                      : ""
                }
              </span>
              <span class="user-card-chevron" aria-hidden="true"></span>
            </span>
            <span class="user-card-expand">
              <span class="user-card-expand-inner">
                ${p.bio ? `<span class="user-card-bio">${escapeHtml(p.bio)}</span>` : ""}
                ${
                  goals.length
                    ? `<span class="user-card-goals">${goals
                        .map((g) => `<span>${escapeHtml(g)}</span>`)
                        .join("")}</span>`
                    : ""
                }
              </span>
            </span>
          </button>`;
        })
        .join("");
    }
    if (searchingUsers || personas.length) scrollBriefTo("users-panel", "users");
  }

  const tasksPanel = document.getElementById("tasks-panel");
  const tEl = document.getElementById("tasks-list");
  const tasksSpin = document.getElementById("tasks-searching");
  const showTasks = searchingTasks || tasks.length > 0;
  if (!showTasks) {
    tasksPanel.hidden = true;
    if (tasksSpin) tasksSpin.hidden = true;
  } else {
    tasksPanel.hidden = false;
    if (tasksSpin) tasksSpin.hidden = !searchingTasks;
    if (searchingTasks && !tasks.length) {
      tEl.innerHTML = `<li class="brief-empty brief-loading-row"><span class="product-search-spin" aria-hidden="true"></span> Writing tasks…</li>`;
    } else {
      tEl.innerHTML = tasks
        .map(
          (t, i) =>
            `<li class="task-row"><span class="brief-num">T${i + 1}</span><div><strong>${escapeHtml(t.title || "Task")}</strong><span class="brief-detail">${escapeHtml(t.prompt || "")}</span></div></li>`
        )
        .join("");
    }
    if (searchingTasks || tasks.length) scrollBriefTo("tasks-panel", "tasks");
  }
}

function renderStage(sessions) {
  const section = document.getElementById("stage-section");
  const body = document.getElementById("stage-body");
  const siteSwitch = document.getElementById("stage-site-switch");
  const taskSelect = document.getElementById("stage-task-select");
  const userSelect = document.getElementById("stage-user-select");
  _traceResults = sessions || [];

  const hasPixels = (s) =>
    (s?.trace || []).some((t) => t && stepShotSrc(t));

  // Never show an empty "watching/capturing" browser pane — only open the
  // stage once at least one real screenshot exists.
  if (!sessions?.length || !sessions.some(hasPixels)) {
    section.hidden = true;
    document.querySelector("main")?.classList.remove("live-wide");
    return;
  }
  section.hidden = false;
  document.querySelector("main")?.classList.add("live-wide");
  scrollBriefTo("stage-section", "live");

  if (!_userPickedTrace) {
    const firstWithShot = sessions.findIndex(hasPixels);
    const firstWithTrace = sessions.findIndex((s) => (s.trace || []).length > 0);
    if (firstWithShot >= 0) _activeTraceIdx = firstWithShot;
    else if (firstWithTrace >= 0) _activeTraceIdx = firstWithTrace;
    else _activeTraceIdx = 0;
  } else if (_activeTraceIdx >= sessions.length) {
    _activeTraceIdx = Math.max(0, sessions.length - 1);
  }

  const idx = Math.max(0, _activeTraceIdx);
  const session = sessions[idx];
  const activeBase = baseTaskId(session?.task_id || session?.agent_id);
  const activeSite =
    session?.site_key ||
    (session?.site_label === "Product" ? "product" : session?.site_url || "product");
  const activePersona = session?.persona_id || "";

  document.getElementById("stage-title").textContent =
    session?.persona_name || session?._persona?.name || "Simulated user";
  document.getElementById("stage-meta").textContent = [
    prettySiteName(session?.site_url, session?.site_label),
    cleanTaskTitle(session?.task_title),
    statusLabel(session?.status),
  ]
    .filter(Boolean)
    .join(" · ");

  const products = productSites(_lastStudyData || {});
  if (!products.length) {
    const seen = new Set();
    for (const s of sessions) {
      const url = s.site_url || "";
      const key = String(url || s.site_label || "")
        .replace(/\/$/, "")
        .toLowerCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      products.push({
        url: s.site_url || "",
        label: prettySiteName(s.site_url, s.site_label),
        kind: s.site_key === "product" || s.site_label === "Product" ? "product" : "competitor",
        site_key: s.site_key,
      });
    }
  }

  const taskOpts = uniqueBriefTasks(
    sessions.map((s) => ({
      id: s.task_id || s.agent_id,
      title: s.task_title,
      prompt: s.task_prompt,
      persona_id: s.persona_id,
    }))
  );

  const personas = Array.from(
    new Map(
      sessions
        .filter((s) => s.persona_id || s.persona_name)
        .map((s) => [
          s.persona_id || s.persona_name,
          {
            id: s.persona_id,
            name: s.persona_name || s._persona?.name || "Simulated user",
          },
        ])
    ).values()
  );

  if (siteSwitch) {
    siteSwitch.innerHTML = products
      .map((p, i) => {
        const siteKey =
          p.site_key || (p.kind === "product" ? "product" : `competitor_${i}`);
        const matchUrl = String(p.url || "")
          .replace(/\/$/, "")
          .toLowerCase();
        const isActive =
          activeSite === siteKey ||
          String(session?.site_url || "")
            .replace(/\/$/, "")
            .toLowerCase() === matchUrl ||
          (p.kind === "product" &&
            (activeSite === "product" || session?.site_label === "Product"));
        const name = p.label || prettySiteName(p.url, "Site");
        return `<button type="button" class="stage-chip${isActive ? " active" : ""}${
          p.kind === "product" ? " is-product" : ""
        }" data-stage-site-url="${escapeHtml(p.url)}" data-stage-site-key="${escapeHtml(siteKey)}">${escapeHtml(name)}</button>`;
      })
      .join("");
  }

  setSelectOptions(
    taskSelect,
    taskOpts.map((t) => ({ value: t.id, label: t.title || "Task" })),
    activeBase
  );
  setSelectOptions(
    userSelect,
    personas.map((p) => ({
      value: p.id || p.name || "",
      label: p.name || "Simulated user",
    })),
    activePersona
  );

  paintStageBody(body, session, idx);
}

function paintStageBody(body, session, idx) {
  const nextHtml = renderFocusStage(session, idx);
  const nextShots = preferredShots(session);
  const nextSrc = nextShots.length
    ? stepShotSrc(
        nextShots[
          Math.max(
            0,
            _shotFollowLatest[String(idx)] !== false
              ? nextShots.length - 1
              : Math.min(_shotIdx[String(idx)] ?? 0, nextShots.length - 1)
          )
        ]
      )
    : "";
  const liveImg = body.querySelector("img.trace-screenshot");
  const liveFrame = body.querySelector("iframe.stage-live-frame");
  const liveWrap = body.querySelector(".stage-live-wrap");
  const sameAgent = body.dataset.agentId === String(session?.agent_id || idx);
  const wantLive =
    Boolean(session?.live_view_url && session?.live_active) &&
    ["starting", "pending", "running"].includes(String(session?.status || ""));
  const liveSrc = session?.live_view_url || "";

  const patchMeta = () => {
    const actionEl = body.querySelector(".step-shot-action");
    const obsEl = body.querySelector(".trace-step-observation");
    const cap = body.querySelector(".stage-shot figcaption");
    const step =
      (session?.trace || []).find((t) => stepShotSrc(t) === nextSrc) ||
      preferredShots(session).at(-1);
    const thoughts = Array.isArray(session?.live_thoughts) ? session.live_thoughts : [];
    const latestThought = thoughts.length
      ? thoughts[thoughts.length - 1]?.text
      : step?.thought || "";
    if (cap && step) {
      cap.innerHTML = `<strong>Step ${escapeHtml(step.step)}</strong> — ${escapeHtml(
        step.action || "Action"
      )}`;
    }
    if (actionEl) {
      actionEl.innerHTML = `<strong>Now doing:</strong> ${escapeHtml(
        step?.action || session?.last_action || "Browsing"
      )}`;
    }
    if (obsEl && latestThought) {
      obsEl.innerHTML = `<strong>Thinking:</strong> ${escapeHtml(latestThought)}`;
    }
    const list = body.querySelector(".stage-thought-list");
    if (list && thoughts.length) {
      list.innerHTML = thoughts
        .slice(-8)
        .map(
          (t) =>
            `<li class="stage-thought stage-thought-${escapeHtml(t.kind || "status")}">${escapeHtml(
              t.text || ""
            )}</li>`
        )
        .join("");
    }
  };

  // Mode switch shot ↔ live requires a full repaint (never side-by-side).
  const haveShot = Boolean(liveImg);
  const haveLive = Boolean(liveFrame);
  if (
    sameAgent &&
    ((wantLive && haveShot && !haveLive) || (!wantLive && haveLive && Boolean(nextSrc)))
  ) {
    body.innerHTML = nextHtml;
    body.dataset.agentId = String(session?.agent_id || idx);
    return;
  }
  if (sameAgent && (liveImg || liveFrame)) {
    // Keep iframe mounted — remounting blanks the live view.
    if (wantLive && liveSrc && liveFrame) {
      const cur = liveWrap?.dataset.liveSrc || liveFrame.getAttribute("src") || "";
      if (cur !== liveSrc) {
        liveFrame.src = liveSrc;
        if (liveWrap) liveWrap.dataset.liveSrc = liveSrc;
      }
    }
    if (liveImg && nextSrc && !wantLive) {
      const shown = liveImg.dataset.shotSrc || liveImg.getAttribute("src") || "";
      if (shown.split("?")[0] !== nextSrc && !String(nextSrc).startsWith("data:")) {
        const pre = new Image();
        pre.onload = () => {
          if (!liveImg.isConnected) return;
          liveImg.src = nextSrc;
          liveImg.dataset.shotSrc = nextSrc;
        };
        pre.src = nextSrc;
      } else if (String(nextSrc).startsWith("data:") && shown !== nextSrc) {
        liveImg.src = nextSrc;
        liveImg.dataset.shotSrc = nextSrc;
      }
    }
    patchMeta();
    return;
  }

  body.dataset.agentId = String(session?.agent_id || idx);
  body.innerHTML = nextHtml;
}

function siteMatches(session, siteKey, siteUrl) {
  const wantUrl = String(siteUrl || "")
    .replace(/\/$/, "")
    .toLowerCase();
  const sUrl = String(session?.site_url || "")
    .replace(/\/$/, "")
    .toLowerCase();
  const keyOk =
    !siteKey ||
    session?.site_key === siteKey ||
    (siteKey === "product" &&
      (session?.site_key === "product" || session?.site_label === "Product"));
  const urlOk = !wantUrl || sUrl === wantUrl;
  return { keyOk, urlOk, ok: keyOk && urlOk };
}

function findSessionIdx(sessions, { taskBase, siteKey, siteUrl, personaId, prefer } = {}) {
  // Tasks are usually 1:1 with a persona. Prefer the control the user just changed
  // so Task/User dropdowns don't snap back when the exact combo doesn't exist.
  const ranked = [];
  for (let i = 0; i < sessions.length; i++) {
    const s = sessions[i];
    const base = baseTaskId(s.task_id || s.agent_id);
    const taskOk = !taskBase || base === taskBase;
    const personaOk = !personaId || !s.persona_id || s.persona_id === personaId;
    const site = siteMatches(s, siteKey, siteUrl);
    let score = -1;
    if (taskOk && personaOk && site.ok) score = 100;
    else if (prefer === "site" && site.ok && (taskOk || personaOk)) score = 95;
    else if (prefer === "site" && site.ok) score = 88;
    else if (prefer === "persona" && personaOk && site.ok) score = 90;
    else if (prefer === "task" && taskOk && site.ok) score = 90;
    else if (prefer === "persona" && personaOk) score = 80;
    else if (prefer === "task" && taskOk) score = 80;
    else if (taskOk && personaOk && (site.keyOk || site.urlOk)) score = 70;
    else if (taskOk && site.ok) score = 60;
    else if (personaOk && site.ok) score = 55;
    else if (taskOk) score = 40;
    else if (personaOk) score = 35;
    if (score >= 0) ranked.push({ i, score });
  }
  ranked.sort((a, b) => b.score - a.score);
  if (ranked.length) return ranked[0].i;
  return -1;
}

function setSelectOptions(select, options, selectedValue) {
  if (!select) return;
  const next = options || [];
  const same =
    select.options.length === next.length &&
    next.every((o, i) => select.options[i]?.value === String(o.value));
  if (!same) {
    select.innerHTML = next
      .map(
        (o) =>
          `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`
      )
      .join("");
  }
  const values = next.map((o) => String(o.value));
  if (values.includes(String(selectedValue ?? ""))) {
    select.value = String(selectedValue);
  } else if (values.length) {
    select.value = values[0];
  }
}

function selectTrace(idx, userInitiated = false) {
  if (userInitiated) {
    _userPickedTrace = true;
    _activeTraceIdx = idx;
  } else {
    _activeTraceIdx = idx;
  }
  if (_lastStudyData) {
    const sessions = mergeSessions(_lastStudyData);
    renderBrief(_lastStudyData, sessions);
    renderStage(sessions);
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
      <h3>${escapeHtml(r.persona_name || "Simulated user")} — ${escapeHtml(r.task_title || "Task")}</h3>
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
      document.getElementById("stage-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
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

function saveReportAndOfferLink(data) {
  const studyId = data.id || data.study_id || "";
  try {
    sessionStorage.setItem(
      "usersim_report",
      JSON.stringify({
        summary: data.summary,
        agent_results: data.agent_results || [],
        access_backend: data.access_backend,
        browserbase_session_url: data.browserbase_session_url,
        notify_email: _notifyEmail || "",
        study_id: studyId,
        url: data.url || "",
        status: data.status || "",
      })
    );
  } catch {
    /* ignore quota */
  }
  updateReportCta(data);
}

function updateReportCta(data) {
  const fullyDone = data?.status === "complete" && Boolean(data?.summary);
  const link = document.getElementById("view-report-link");
  const emailPrompt = document.getElementById("report-email-prompt");
  const stageVisible = !document.getElementById("stage-section")?.hidden;
  if (fullyDone) {
    if (link) {
      const studyId = data.id || data.study_id || "";
      link.href = studyId ? `/report?study=${encodeURIComponent(studyId)}` : "/report";
      link.hidden = false;
      link.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    if (emailPrompt) emailPrompt.hidden = true;
    return;
  }
  if (link) link.hidden = true;
  if (emailPrompt) {
    emailPrompt.hidden = !stageVisible;
    const saved = document.getElementById("report-email-saved");
    const formEl = document.getElementById("report-email-form");
    if (_emailCaptureSubmitted && _notifyEmail) {
      if (formEl) formEl.hidden = true;
      if (saved) {
        saved.hidden = false;
        saved.textContent = `We’ll email the report to ${_notifyEmail} when it’s ready.`;
      }
    } else {
      if (formEl) formEl.hidden = false;
      if (saved) saved.hidden = true;
    }
  }
}

function renderSummary(summary, accessBackend, browserbaseSessionUrl) {
  // Full report lives on /report — only fill inline nodes if present/visible.
  if (!document.getElementById("headline")) return;
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

  const note = document.getElementById("report-email-note");
  if (_notifyEmail) {
    note.hidden = false;
    note.textContent = `Feedback ready — we’ll send a copy to ${_notifyEmail}.`;
  } else {
    note.hidden = true;
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

function maybeShowEmailCapture(sessions) {
  // Email prompt lives in #report-cta via updateReportCta.
  updateReportCta(_lastStudyData || {});
}

function renderLiveStudy(data) {
  _lastStudyData = data;
  const sessions = mergeSessions(data);
  renderActivityLog(data.activity_log);
  renderBrief(data, sessions);
  renderStage(sessions);
  updateReportCta(data);
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

function lines(value) {
  return String(value || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function normalizeUrl(raw) {
  const url = String(raw || "").trim();
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  return `https://${url}`;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideError();
  resetLiveUI();
  resultsSection.hidden = true;
  livePanel.hidden = false;
  progressPanel.hidden = false;
  setLoading(true);

  const url = normalizeUrl(form.url.value.trim());
  if (!url) {
    showError("Paste a product URL to run.");
    setLoading(false);
    return;
  }
  const customers = form.customers?.value?.trim() || "";
  const competitors = lines(form.competitors?.value);
  const tasks = lines(form.tasks?.value);
  const testMode = Boolean(form.test_mode?.checked);
  _notifyEmail = "";
  const segment =
    customers ||
    "Auto-research target customers from the product URL and invent a mixed panel of directed simulated users with realistic demographics.";

  // Show products immediately; users/tasks appear as they stream in.
  renderBrief(
    {
      url,
      competitors,
      tasks: [],
      personas: [],
      test_mode: testMode,
      phase: "Understanding context of product",
    },
    []
  );
  livePanel.scrollIntoView({ behavior: "smooth" });
  scrollBriefTo("products-panel", "products");
  const startedAt = Date.now();
  updateProgressUI({ phase: "Understanding context of product", status: "running" }, startedAt);

  try {
    const startRes = await fetch("/api/studies", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
        "X-UserSim-Stream": "1",
      },
      body: JSON.stringify({
        url,
        email: null,
        segment,
        customers: customers || null,
        competitors,
        tasks,
        test_mode: testMode,
        backend: "default",
      }),
    });

    const contentType = startRes.headers.get("content-type") || "";
    if (!startRes.ok) {
      const raw = await startRes.text();
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

    let data = null;

    if (contentType.includes("ndjson") || contentType.includes("stream")) {
      const reader = startRes.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (!line) continue;
          let chunk;
          try {
            chunk = JSON.parse(line);
          } catch {
            continue;
          }
          data = chunk;
          updateProgressUI(data, startedAt);
          renderLiveStudy(data);
          if (chunk.stream_event === "error" || data.status === "error") {
            throw new Error(data.error || "Study failed");
          }
        }
      }
      if (!data) throw new Error("Study stream ended with no data");
    } else {
      const raw = await startRes.text();
      const payload = JSON.parse(raw);
      const studyId = payload.study_id || payload.id;
      data = payload;
      if (!data?.personas && studyId) {
        data = await pollStudy(studyId);
      }
      if (!(data.status === "complete" || data.summary || data.agent_results?.length)) {
        while (true) {
          data = await pollStudy(studyId);
          updateProgressUI(data, startedAt);
          renderLiveStudy(data);
          if (data.status === "complete") break;
          if (data.status === "error") throw new Error(data.error || "Study failed");
          await new Promise((r) => setTimeout(r, 1500));
        }
      } else {
        updateProgressUI({ ...data, phase: "Complete", status: "complete" }, startedAt);
        renderLiveStudy(data);
      }
    }

    if (!data.summary && (!data.agent_results || !data.agent_results.length)) {
      throw new Error("Study finished but returned no results.");
    }

    progressFill.style.width = "100%";
    phaseLabel.textContent = "Complete";
    renderLiveStudy(data);
    saveReportAndOfferLink(data);
    if (resultsSection) resultsSection.hidden = true;

    await new Promise((r) => setTimeout(r, 600));
    progressPanel.hidden = true;
  } catch (err) {
    progressPanel.hidden = false;
    const raw = err.message || String(err);
    const soft =
      /network|failed to fetch|load failed|aborted/i.test(raw)
        ? "Connection interrupted — refresh and try again."
        : raw;
    showError(soft);
  } finally {
    setLoading(false);
  }
});

document.addEventListener("click", (ev) => {
  const siteBtn = ev.target.closest("[data-stage-site-key], [data-stage-site-url]");
  if (siteBtn) {
    const sessions = _traceResults || [];
    const cur = sessions[_activeTraceIdx] || sessions[0] || {};
    const taskBase = baseTaskId(cur.task_id || cur.agent_id);
    const siteKey = siteBtn.getAttribute("data-stage-site-key") || cur.site_key || "product";
    const siteUrl = siteBtn.getAttribute("data-stage-site-url") || cur.site_url || "";
    const idx = findSessionIdx(sessions, {
      taskBase,
      siteKey,
      siteUrl,
      personaId: cur.persona_id,
      prefer: "site",
    });
    if (idx >= 0) selectTrace(idx, true);
    return;
  }

  const chip = ev.target.closest(".user-card[data-persona-id], .user-card[data-session-idx]");
  if (chip) {
    const sessions = _traceResults || [];
    const personaId = chip.getAttribute("data-persona-id") || "";
    let idx = Number(chip.getAttribute("data-session-idx"));
    if (Number.isNaN(idx) || idx < 0) {
      idx = sessions.findIndex((s) => s.persona_id === personaId);
    }
    if (idx < 0 && personaId) {
      const cur = sessions[_activeTraceIdx] || sessions[0] || {};
      idx = findSessionIdx(sessions, {
        taskBase: baseTaskId(cur.task_id || cur.agent_id),
        siteKey: cur.site_key || "product",
        siteUrl: cur.site_url || "",
        personaId,
      });
    }
    if (idx >= 0) selectTrace(idx, true);
    else if (personaId && _lastStudyData) {
      // No live session yet — still mark card selected in the brief.
      _userPickedTrace = true;
      document.querySelectorAll(".user-card").forEach((el) => {
        const on = el.getAttribute("data-persona-id") === personaId;
        el.classList.toggle("is-selected", on);
        el.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
    return;
  }

  const nav = ev.target.closest(".step-nav[data-shot-key]");
  if (nav) {
    const key = nav.getAttribute("data-shot-key");
    const delta = Number(nav.getAttribute("data-shot-delta") || 0);
    const sessions = _traceResults || [];
    const session = sessions[Number(key)] || sessions[_activeTraceIdx];
    const shots = preferredShots(session);
    if (!shots.length) return;
    const cur = _shotIdx[key] ?? 0;
    _shotIdx[key] = Math.max(0, Math.min(shots.length - 1, cur + delta));
    _shotFollowLatest[key] = _shotIdx[key] >= shots.length - 1;
    if (_lastStudyData) renderStage(mergeSessions(_lastStudyData));
    return;
  }

  const btn = ev.target.closest(".step-pill[data-shot-key]");
  if (!btn) return;
  const key = btn.getAttribute("data-shot-key");
  const idx = Number(btn.getAttribute("data-shot-idx"));
  if (!key || Number.isNaN(idx)) return;
  _shotIdx[key] = idx;
  const sessions2 = _traceResults || [];
  const session2 = sessions2[Number(key)] || sessions2[_activeTraceIdx];
  const shots2 = preferredShots(session2);
  _shotFollowLatest[key] = idx >= Math.max(shots2.length - 1, 0);
  if (_lastStudyData) {
    renderStage(mergeSessions(_lastStudyData));
  }
});

document.getElementById("report-email-form")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("report-email-input");
  const email = input?.value?.trim() || "";
  if (!email) return;
  _notifyEmail = email;
  _emailCaptureSubmitted = true;
  const formEl = document.getElementById("report-email-form");
  const done = document.getElementById("report-email-saved");
  if (formEl) formEl.hidden = true;
  if (done) {
    done.hidden = false;
    done.textContent = `We’ll email the report to ${email} when it’s ready.`;
  }
  const progressNote = document.getElementById("email-status");
  if (progressNote) {
    progressNote.hidden = false;
    progressNote.textContent = `Report will be emailed to ${email} when ready.`;
  }
});

function syncStageFromControls(ev) {
  const sessions = _traceResults || [];
  if (!sessions.length) return;
  const cur = sessions[_activeTraceIdx] || sessions[0] || {};
  const taskSelect = document.getElementById("stage-task-select");
  const userSelect = document.getElementById("stage-user-select");
  const prefer =
    ev?.target?.id === "stage-user-select"
      ? "persona"
      : ev?.target?.id === "stage-task-select"
        ? "task"
        : null;
  // When switching user/task, don't require the other dimension — sessions are
  // usually one persona per task.
  const taskBase =
    prefer === "persona"
      ? ""
      : taskSelect?.value || baseTaskId(cur.task_id || cur.agent_id);
  const personaId =
    prefer === "task" ? "" : userSelect?.value || cur.persona_id || "";
  const activeBtn = document.querySelector("#stage-site-switch .stage-chip.active");
  const siteKey =
    activeBtn?.getAttribute("data-stage-site-key") || cur.site_key || "product";
  const siteUrl =
    activeBtn?.getAttribute("data-stage-site-url") || cur.site_url || "";
  const idx = findSessionIdx(sessions, {
    taskBase,
    siteKey,
    siteUrl,
    personaId,
    prefer,
  });
  if (idx >= 0) selectTrace(idx, true);
}

document.getElementById("stage-task-select")?.addEventListener("change", syncStageFromControls);
document.getElementById("stage-user-select")?.addEventListener("change", syncStageFromControls);

if (typeof IS_LOCAL_HOST !== "undefined" && IS_LOCAL_HOST) {
  const smokeRow = document.getElementById("local-smoke-row");
  const smokeBtn = document.getElementById("smoke-btn");
  const smokeInput = document.getElementById("test-mode-input");
  const localNav = document.getElementById("local-nav");
  if (smokeRow) smokeRow.hidden = false;
  if (localNav) localNav.hidden = false;
  if (smokeBtn) {
    smokeBtn.hidden = false;
    smokeBtn.addEventListener("click", () => {
      if (smokeInput) smokeInput.checked = true;
      const urlInput = form?.url;
      if (urlInput && !String(urlInput.value || "").trim()) {
        urlInput.value = "https://useagency.dev/";
      }
      if (typeof form?.requestSubmit === "function") form.requestSubmit();
      else form?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    });
  }
}
