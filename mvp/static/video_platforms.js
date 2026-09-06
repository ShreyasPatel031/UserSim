const PLATFORMS = ["youtube", "vimeo", "dailymotion"];
const PLAT_LABEL = { youtube: "YouTube", vimeo: "Vimeo", dailymotion: "Dailymotion" };

const studySelect = document.getElementById("study-select");
const goalSelect = document.getElementById("goal-select");
const platformGrid = document.getElementById("platform-grid");
const compareBanner = document.getElementById("compare-banner");
const goalPrompt = document.getElementById("goal-prompt");
const analyticsRoot = document.getElementById("analytics-root");

let _study = null;
let _currentGoal = null;
const _activeIdx = { youtube: 0, vimeo: 0, dailymotion: 0 };

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- tabs ---------- */
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.hidden = p.id !== `tab-${btn.dataset.tab}`;
    });
  });
});

/* ---------- analytics ---------- */
function barRows(rates, max = 100) {
  return PLATFORMS.map((p) => {
    const v = rates[p] ?? 0;
    const pct = max ? Math.max(0, Math.min(100, (v / max) * 100)) : 0;
    return `<div class="bar-row">
      <span class="bar-label">${escapeHtml(PLAT_LABEL[p])}</span>
      <div class="bar-track"><div class="bar-fill ${p}" style="width:${pct}%"></div></div>
      <span class="bar-val">${v == null ? "—" : `${v}%`}</span>
    </div>`;
  }).join("");
}

function countBars(counts) {
  const max = Math.max(1, ...PLATFORMS.map((p) => counts[p] || 0));
  return PLATFORMS.map((p) => {
    const v = counts[p] || 0;
    const pct = (v / max) * 100;
    return `<div class="bar-row">
      <span class="bar-label">${escapeHtml(PLAT_LABEL[p])}</span>
      <div class="bar-track"><div class="bar-fill ${p}" style="width:${pct}%"></div></div>
      <span class="bar-val">${v}</span>
    </div>`;
  }).join("");
}

function legend() {
  return `<div class="legend">
    <span class="youtube">YouTube</span>
    <span class="vimeo">Vimeo</span>
    <span class="dailymotion">Dailymotion</span>
  </div>`;
}

function pill(plat) {
  if (!plat) return "—";
  return `<span class="pill ${escapeHtml(plat)}">${escapeHtml(plat)}</span>`;
}

function renderAnalytics(data) {
  const prefShare = data.preference_share || {};
  const prefs = data.preference_counts || {};
  const avgActions = data.avg_actions || {};
  const successRates = Object.fromEntries(
    PLATFORMS.map((p) => [p, data.success_by_platform?.[p]?.rate ?? 0])
  );
  const maxActions = Math.max(1, ...PLATFORMS.map((p) => avgActions[p] || 0));

  const journeyRows = (data.by_journey || [])
    .map((j) => {
      const prefTotal = PLATFORMS.reduce((s, p) => s + (j.preferences?.[p] || 0), 0) || 1;
      const prefBars = PLATFORMS.map((p) => {
        const n = j.preferences?.[p] || 0;
        const pct = Math.round((100 * n) / prefTotal);
        return `<div class="bar-row journey-pref-bar">
          <span class="bar-label">${escapeHtml(PLAT_LABEL[p])}</span>
          <div class="bar-track"><div class="bar-fill ${p}" style="width:${pct}%"></div></div>
          <span class="bar-val">${n} · ${pct}%</span>
        </div>`;
      }).join("");
      return `<tr>
        <td class="journey-name"><strong>${escapeHtml(j.id)}</strong><br/><span class="journey-label">${escapeHtml(j.label)}</span></td>
        <td class="journey-prefs">${prefBars}</td>
      </tr>`;
    })
    .join("");

  const matrix = data.matrix || {};
  const journeys = matrix.journeys || [];
  const matrixHead = journeys
    .map((j) => `<th title="${escapeHtml(matrix.journey_labels?.[j] || j)}">${escapeHtml(j)}</th>`)
    .join("");
  const personaBlocks = (data.by_persona || [])
    .map((persona) => {
      const matrixRow = journeys
        .map((j) => {
          const cell = matrix.cells?.[persona.persona_id]?.[j];
          return `<td>${pill(cell)}</td>`;
        })
        .join("");
      const goalRows = (persona.goals || [])
        .map(
          (g) => `<tr class="goal-row" data-persona-study="${escapeHtml(_studyIdForPersona(persona.persona_id))}" data-goal="${escapeHtml(g.goal_key)}">
          <td>${escapeHtml(g.journey)} · ${escapeHtml(g.title || g.goal_key)}</td>
          ${PLATFORMS.map((p) => `<td>${g.success?.[p] ? "✓" : g.success?.[p] === false ? "✗" : "—"}</td>`).join("")}
          <td>${pill(g.winner)}</td>
        </tr>`
        )
        .join("");
      const prefLine = PLATFORMS.map((p) => `${PLAT_LABEL[p]} ${persona.preferences?.[p] || 0}`).join(" · ");
      const nGoals = (persona.goals || []).length;
      return `<div class="persona-block" id="persona-${escapeHtml(persona.persona_id)}">
        <div class="persona-header">
          <span class="persona-summary-title">${escapeHtml(persona.persona_name)} ${pill(persona.top_preference)}</span>
          <span class="persona-summary-meta">${escapeHtml(prefLine)}</span>
        </div>
        <div class="persona-body">
          <p class="bio">${escapeHtml(persona.bio)} · Preference wins: ${escapeHtml(prefLine)}</p>
          <table class="matrix-table"><thead><tr><th>Journey prefs</th>${matrixHead}</tr></thead>
          <tbody><tr><td>${escapeHtml(persona.persona_name)}</td>${matrixRow}</tr></tbody></table>
          <details class="persona-goals">
            <summary>Goal breakdown (${nGoals})</summary>
            <table class="persona-table" style="margin-top:.5rem">
              <thead><tr><th>Goal</th><th>YouTube</th><th>Vimeo</th><th>Dailymotion</th><th>Pick</th></tr></thead>
              <tbody>${goalRows}</tbody>
            </table>
          </details>
        </div>
      </div>`;
    })
    .join("");

  analyticsRoot.innerHTML = `
    <div class="stat-strip">
      <span><strong>${data.n_runs ?? "—"}</strong> agent runs</span>
      <span><strong>${data.n_goals ?? "—"}</strong> head-to-head goals</span>
      <span>6 personas × 5 goals × 3 platforms</span>
    </div>
    <p class="metric-note">${escapeHtml(data.metric_note || "")}</p>
    <div class="analytics-grid">
      <div class="chart-card">
        <h3>Preference win share</h3>
        <p class="sub">Which platform personas would actually pick (comparative winners)</p>
        ${legend()}
        ${barRows(prefShare)}
        <p class="sub" style="margin-top:.75rem;margin-bottom:0">Counts: YouTube ${prefs.youtube || 0} · Vimeo ${prefs.vimeo || 0} · Dailymotion ${prefs.dailymotion || 0}</p>
      </div>
      <div class="chart-card">
        <h3>Avg seconds to result</h3>
        <p class="sub">Lower is faster — elapsed time across runs</p>
        ${legend()}
        ${PLATFORMS.map((p) => {
          const v = avgActions[p];
          const pct = v == null ? 0 : (v / maxActions) * 100;
          return `<div class="bar-row">
            <span class="bar-label">${escapeHtml(PLAT_LABEL[p])}</span>
            <div class="bar-track"><div class="bar-fill ${p}" style="width:${pct}%"></div></div>
            <span class="bar-val">${v == null ? "—" : v}</span>
          </div>`;
        }).join("")}
      </div>
      <div class="chart-card">
        <h3>Likely task completion</h3>
        <p class="sub">Did the agent report completing the requested task?</p>
        ${legend()}
        ${barRows(successRates)}
      </div>
    </div>

    <div class="chart-card" style="margin-bottom:1.25rem">
      <h3>By journey / task type (J1–J5)</h3>
      <p class="sub">Preference wins by journey bucket</p>
      <div style="overflow-x:auto">
        <table class="journey-table">
          <thead>
            <tr>
              <th>Journey</th>
              <th>Preference wins</th>
            </tr>
          </thead>
          <tbody>${journeyRows}</tbody>
        </table>
      </div>
    </div>

    <div class="chart-card">
      <h3>By persona → goals</h3>
      <p class="sub">Click a goal row to open the trace drill-down</p>
      ${personaBlocks}
    </div>
  `;

  analyticsRoot.querySelectorAll(".goal-row").forEach((row) => {
    row.addEventListener("click", async () => {
      const studyId = row.dataset.personaStudy;
      const goal = row.dataset.goal;
      if (!studyId) return;
      document.querySelector('.tab-btn[data-tab="traces"]').click();
      if (studySelect.value !== studyId) {
        studySelect.value = studyId;
        await loadStudy(studyId);
      }
      if (goal && [...goalSelect.options].some((o) => o.value === goal)) {
        goalSelect.value = goal;
        PLATFORMS.forEach((p) => {
          _activeIdx[p] = 0;
        });
        renderGoal(goal);
      }
    });
  });
}

const _personaStudyMap = {};
function _studyIdForPersona(personaId) {
  return _personaStudyMap[personaId] || "";
}

async function loadAnalytics() {
  const res = await fetch("/api/video-study/analytics");
  if (!res.ok) throw new Error(`analytics ${res.status}`);
  const data = await res.json();
  renderAnalytics(data);
}

/* ---------- traces ---------- */
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
  const shots = stepsWithScreenshots(r.trace || []);
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
          <button type="button" class="step-num${i === idx ? " active" : ""}" data-platform="${escapeHtml(platform)}" data-idx="${i}">
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
    <details class="feedback-details" open>
      <summary>Agent report</summary>
      <p style="white-space:pre-wrap">${escapeHtml(r.product_feedback || "No report recorded.")}</p>
    </details>
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
  const r = (_study?.agent_results || []).find((x) => x.goal_key === _currentGoal && x.platform === platform);
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
  const res = await fetch("/api/video-study/studies");
  const data = await res.json();
  studySelect.innerHTML = "";
  for (const s of data.studies || []) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = `${s.persona_name} (${s.successes}/${s.n_runs})`;
    studySelect.appendChild(opt);
    if (s.persona_id) _personaStudyMap[s.persona_id] = s.id;
  }
  if (studySelect.options.length) await loadStudy(studySelect.value);
}

async function loadStudy(studyId) {
  const res = await fetch(`/api/video-study/studies/${encodeURIComponent(studyId)}`);
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
  const sample = byPlatform.youtube || byPlatform.vimeo || byPlatform.dailymotion;
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

Promise.all([loadAnalytics(), loadStudies()]).catch((err) => {
  analyticsRoot.innerHTML = `<p class="trace-empty">Failed to load: ${escapeHtml(err.message)}</p>`;
});
