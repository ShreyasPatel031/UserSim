const studySelect = document.getElementById("study-select");
const goalSelect = document.getElementById("goal-select");
const platformGrid = document.getElementById("platform-grid");
const compareBanner = document.getElementById("compare-banner");
const goalPrompt = document.getElementById("goal-prompt");

const PLATFORMS = ["bland", "vapi", "retell"];
const PLAT_LABEL = { bland: "Bland AI", vapi: "Vapi", retell: "Retell AI" };

let _study = null;
let _currentGoal = null;
const _activeIdx = { bland: 0, vapi: 0, retell: 0 };

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const THOUGHT_LABELS = {
  next_goal: "Next goal",
  evaluation_previous_goal: "Previous step",
  thinking: "Reasoning",
  memory: "Memory",
};

function formatThoughtText(text) {
  if (!text) return "";
  return String(text).replace(/\r\n/g, "\n").trim();
}

function renderThoughtHtml(step) {
  const detail = step.thought_detail || {};
  const order = ["next_goal", "evaluation_previous_goal", "thinking", "memory"];
  const entries = order.filter((k) => detail[k]).map((k) => [k, formatThoughtText(detail[k])]);
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
  return `<details class="thought-details">
    <summary><span class="thought-summary-label">Reasoning</span></summary>
    <div class="thought-body">${body}</div>
  </details>`;
}

function stepsWithScreenshots(trace) {
  return (trace || []).filter((s) => s.screenshot_url);
}

function renderStepViewer(r) {
  const platform = r.platform;
  const trace = r.trace || [];
  const shots = stepsWithScreenshots(trace);
  if (!shots.length) {
    return `<div class="step-viewer step-viewer-empty">
      <div class="screenshot-missing">No step screenshots yet.<br/>Final URL: ${escapeHtml(r.final_url || "—")}</div>
    </div>`;
  }

  let idx = _activeIdx[platform] ?? 0;
  if (idx < 0 || idx >= shots.length) idx = 0;
  _activeIdx[platform] = idx;

  const step = shots[idx];
  const prevDisabled = idx <= 0 ? " disabled" : "";
  const nextDisabled = idx >= shots.length - 1 ? " disabled" : "";

  return `<div class="step-viewer" data-platform="${escapeHtml(platform)}">
    <div class="step-nav">
      <button type="button" class="step-arrow" data-platform="${escapeHtml(platform)}" data-dir="-1"${prevDisabled} aria-label="Previous step">←</button>
      <div class="step-nums">
        ${shots
          .map(
            (s, i) => `
          <button type="button" class="step-num${i === idx ? " active" : ""}" data-platform="${escapeHtml(platform)}" data-idx="${i}" aria-label="Step ${escapeHtml(s.step)}">
            ${escapeHtml(s.step)}
          </button>`
          )
          .join("")}
      </div>
      <button type="button" class="step-arrow" data-platform="${escapeHtml(platform)}" data-dir="1"${nextDisabled} aria-label="Next step">→</button>
    </div>
    <figure class="step-shot">
      <img class="trace-screenshot" src="${escapeHtml(step.screenshot_url)}" alt="Step ${escapeHtml(step.step)}" />
    </figure>
    <div class="step-detail">
      <p class="step-action"><strong>${escapeHtml(step.step)}.</strong> ${escapeHtml(step.action || "Action")}</p>
      ${step.target ? `<p class="step-meta"><span>Clicked</span> ${escapeHtml(step.target)}</p>` : ""}
      ${step.url ? `<p class="step-meta"><span>URL</span> ${escapeHtml(step.url)}</p>` : ""}
      ${renderThoughtHtml(step)}
    </div>
    <p class="step-caption">${idx + 1} / ${shots.length} · boxes = clickable · red = click target</p>
  </div>`;
}

function renderColumn(r, isWinner) {
  const platLabel = PLAT_LABEL[r.platform] || r.platform;
  const likes = (r.likes || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  const dislikes = (r.dislikes || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  return `
  <article class="platform-card${isWinner ? " winner" : ""}" data-platform="${escapeHtml(r.platform)}">
    <div class="col-header">
      <h3>
        ${escapeHtml(platLabel)}
        ${isWinner ? '<span class="tag">pick</span>' : ""}
      </h3>
      <span class="tag status-${r.success ? "complete" : "error"}">${r.success ? "SUCCESS" : escapeHtml(r.judge_status || "FAIL")}</span>
      ${r.difficulty ? `<span class="tag">${escapeHtml(r.difficulty)}</span>` : ""}
    </div>
    ${renderStepViewer(r)}
    <details class="feedback-details">
      <summary>Likes / dislikes</summary>
      <div class="likes-dislikes">
        ${likes ? `<div><strong>Liked</strong><ul>${likes}</ul></div>` : ""}
        ${dislikes ? `<div><strong>Disliked</strong><ul>${dislikes}</ul></div>` : ""}
        ${!likes && !dislikes ? `<p class="trace-empty">No feedback recorded.</p>` : ""}
      </div>
    </details>
  </article>`;
}

function goStep(platform, idx) {
  const results = (_study?.agent_results || []).filter((r) => r.goal_key === _currentGoal && r.platform === platform);
  const r = results[0];
  if (!r) return;
  const shots = stepsWithScreenshots(r.trace);
  if (!shots.length) return;
  _activeIdx[platform] = Math.max(0, Math.min(shots.length - 1, idx));
  updateColumn(platform);
}

function nudgeStep(platform, delta) {
  goStep(platform, (_activeIdx[platform] ?? 0) + delta);
}

function updateColumn(platform) {
  const card = platformGrid.querySelector(`.platform-card[data-platform="${platform}"]`);
  if (!card) return;
  const r = (_study.agent_results || []).find((x) => x.goal_key === _currentGoal && x.platform === platform);
  if (!r) return;
  const comp = (_study.comparative?.reviews || []).find((rev) => rev.goal_key === _currentGoal);
  const viewer = card.querySelector(".step-viewer");
  if (viewer) {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderStepViewer(r);
    viewer.replaceWith(tmp.firstElementChild);
  }
  wireStepControls(card);
}

function wireStepControls(root = platformGrid) {
  root.querySelectorAll(".step-num").forEach((el) => {
    el.addEventListener("click", () => {
      const plat = el.dataset.platform;
      const idx = Number(el.dataset.idx);
      if (plat && !Number.isNaN(idx)) goStep(plat, idx);
    });
  });
  root.querySelectorAll(".step-arrow:not([disabled])").forEach((el) => {
    el.addEventListener("click", () => {
      const plat = el.dataset.platform;
      const dir = Number(el.dataset.dir);
      if (plat && dir) nudgeStep(plat, dir);
    });
  });
}

async function loadStudies() {
  const res = await fetch("/api/bakeoff/studies");
  const data = await res.json();
  studySelect.innerHTML = "";
  for (const s of data.studies || []) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = `${s.persona_name} (${s.successes}/${s.n_runs})`;
    studySelect.appendChild(opt);
  }
  if (studySelect.options.length) await loadStudy(studySelect.value);
}

async function loadStudy(studyId) {
  const res = await fetch(`/api/bakeoff/studies/${encodeURIComponent(studyId)}`);
  _study = await res.json();
  const goals = [...new Set((_study.agent_results || []).map((r) => r.goal_key))];
  goalSelect.innerHTML = "";
  for (const g of goals) {
    const sample = _study.agent_results.find((r) => r.goal_key === g);
    const opt = document.createElement("option");
    opt.value = g;
    opt.textContent = sample?.task_title?.split(" — ")[0] || g;
    goalSelect.appendChild(opt);
  }
  PLATFORMS.forEach((p) => {
    _activeIdx[p] = 0;
  });
  if (goals.length) renderGoal(goals[0]);
}

function renderGoal(goalKey) {
  _currentGoal = goalKey;
  const byPlatform = Object.fromEntries(
    (_study.agent_results || []).filter((r) => r.goal_key === goalKey).map((r) => [r.platform, r])
  );
  const comp = (_study.comparative?.reviews || []).find((r) => r.goal_key === goalKey);
  const sample = byPlatform.bland || byPlatform.vapi || byPlatform.retell;
  goalPrompt.textContent = sample?.task_prompt || "";

  if (comp?.most_likely_to_use) {
    compareBanner.hidden = false;
    compareBanner.innerHTML = `<strong>Persona pick:</strong> ${escapeHtml(comp.most_likely_to_use)} · runner-up ${escapeHtml(comp.runner_up || "—")} — ${escapeHtml(comp.why_winner || "")}`;
  } else {
    compareBanner.hidden = true;
  }

  platformGrid.innerHTML = PLATFORMS.map((plat) => {
    const r = byPlatform[plat];
    if (!r) {
      return `<article class="platform-card"><div class="col-header"><h3>${escapeHtml(PLAT_LABEL[plat])}</h3></div><p class="trace-empty">No run for this platform.</p></article>`;
    }
    return renderColumn(r, comp?.most_likely_to_use === plat);
  }).join("");
  wireStepControls();
}

studySelect.addEventListener("change", () => loadStudy(studySelect.value));
goalSelect.addEventListener("change", () => {
  PLATFORMS.forEach((p) => {
    _activeIdx[p] = 0;
  });
  renderGoal(goalSelect.value);
});

document.addEventListener("keydown", (e) => {
  if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
  const card = document.activeElement?.closest?.(".platform-card[data-platform]");
  const plat = card?.dataset?.platform;
  if (!plat) return;
  e.preventDefault();
  nudgeStep(plat, e.key === "ArrowRight" ? 1 : -1);
});

loadStudies().catch((err) => {
  platformGrid.innerHTML = `<p class="trace-empty">Failed to load: ${escapeHtml(err.message)}</p>`;
});
