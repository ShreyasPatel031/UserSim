const studySelect = document.getElementById("study-select");
const personaSelect = document.getElementById("persona-select");
const journeySelect = document.getElementById("journey-select");
const seedSelect = document.getElementById("seed-select");
const goalSelect = document.getElementById("goal-select");
const platformGrid = document.getElementById("platform-grid");
const compareBanner = document.getElementById("compare-banner");
const goalPrompt = document.getElementById("goal-prompt");
const analyticsRoot = document.getElementById("analytics-root");
const studyHeadline = document.getElementById("study-headline");
const overviewPanel = document.getElementById("overview-panel");
const tracesPanel = document.getElementById("traces-panel");
const personaFilterWrap = document.getElementById("persona-filter-wrap");
const journeyFilterWrap = document.getElementById("journey-filter-wrap");
const seedFilterWrap = document.getElementById("seed-filter-wrap");
const goalFilterWrap = document.getElementById("goal-filter-wrap");

const PLATFORMS = ["bland", "vapi", "retell"];
const PLAT_LABEL = { bland: "Bland AI", vapi: "Vapi", retell: "Retell AI" };
const PLAT_CLASS = { bland: "bland", vapi: "vapi", retell: "retell" };

let _study = null;
let _currentGoal = null;
let _currentBlock = null;
let _activeView = "overview";
const _activeIdx = { bland: 0, vapi: 0, retell: 0 };

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function pct(n) {
  return `${Math.round((n || 0) * 100)}%`;
}

function heatColor(rate) {
  const r = Math.round(40 + (rate || 0) * 180);
  const g = Math.round(50 + (rate || 0) * 140);
  return `rgba(${r}, ${g}, 80, 0.85)`;
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

function renderColumn(r, { isWinner, isPreferred }) {
  const platLabel = PLAT_LABEL[r.platform] || r.platform;
  const likes = (r.likes || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  const dislikes = (r.dislikes || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  let extraClass = "";
  if (isWinner) extraClass += " winner";
  if (isPreferred) extraClass += " preferred";
  return `
  <article class="platform-card${extraClass}" data-platform="${escapeHtml(r.platform)}">
    <div class="col-header">
      <h3>
        ${escapeHtml(platLabel)}
        ${isWinner ? '<span class="tag">success</span>' : ""}
        ${isPreferred ? '<span class="tag">preferred</span>' : ""}
      </h3>
      <span class="tag status-${r.success ? "complete" : "error"}">${r.success ? "SUCCESS" : escapeHtml(r.judge_status || "FAIL")}</span>
      ${r.difficulty ? `<span class="tag">${escapeHtml(r.difficulty)}</span>` : ""}
      ${r.num_actions != null ? `<span class="tag">${escapeHtml(r.num_actions)} steps</span>` : ""}
    </div>
    ${renderStepViewer(r)}
    <details class="feedback-details">
      <summary>Likes / dislikes · judge</summary>
      <div class="likes-dislikes">
        ${likes ? `<div><strong>Liked</strong><ul>${likes}</ul></div>` : ""}
        ${dislikes ? `<div><strong>Disliked</strong><ul>${dislikes}</ul></div>` : ""}
        ${r.judge_reason ? `<div><strong>Judge</strong><p>${escapeHtml(r.judge_reason.slice(0, 400))}</p></div>` : ""}
        ${!likes && !dislikes && !r.judge_reason ? `<p class="trace-empty">No feedback recorded.</p>` : ""}
      </div>
    </details>
  </article>`;
}

function goStep(platform, idx) {
  const key = _currentBlock || _currentGoal;
  const results = (_study?.agent_results || []).filter(
    (r) => (r.comparative_group === key || r.goal_key === key || r.task_id === key) && r.platform === platform
  );
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
  const key = _currentBlock || _currentGoal;
  const r = (_study.agent_results || []).find(
    (x) => (x.comparative_group === key || x.goal_key === key || x.task_id === key) && x.platform === platform
  );
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

function renderBarChart(title, dataByPlatform, { valueKey = "rate", labelKey = "success", suffix = "" } = {}) {
  const rows = PLATFORMS.filter((p) => dataByPlatform[p]).map((p) => {
    const d = dataByPlatform[p];
    const val = typeof d === "number" ? d : d[valueKey] ?? 0;
    const label = typeof d === "object" ? `${d[labelKey] ?? 0}/${d.eligible ?? d.total ?? "?"}` : val;
    return { p, val, label };
  });
  const max = Math.max(...rows.map((r) => r.val), 0.01);
  return `
    <div class="analytics-card">
      <h4>${escapeHtml(title)}</h4>
      <div class="bar-chart">
        ${rows
          .map(
            (r) => `
          <div class="bar-row">
            <span>${escapeHtml(PLAT_LABEL[r.p] || r.p)}</span>
            <div class="bar-track"><div class="bar-fill ${PLAT_CLASS[r.p] || "success"}" style="width:${Math.round((r.val / max) * 100)}%"></div></div>
            <span>${typeof r.val === "number" && r.val <= 1 ? pct(r.val) : r.label}${suffix}</span>
          </div>`
          )
          .join("")}
      </div>
    </div>`;
}

function renderCountBars(title, counts) {
  const max = Math.max(...PLATFORMS.map((p) => counts[p] || 0), 1);
  return `
    <div class="analytics-card">
      <h4>${escapeHtml(title)}</h4>
      <div class="bar-chart">
        ${PLATFORMS.map(
          (p) => `
          <div class="bar-row">
            <span>${escapeHtml(PLAT_LABEL[p])}</span>
            <div class="bar-track"><div class="bar-fill pref" style="width:${Math.round(((counts[p] || 0) / max) * 100)}%"></div></div>
            <span>${counts[p] || 0}</span>
          </div>`
        ).join("")}
      </div>
    </div>`;
}

function renderHeatmap(title, matrix, personaNames) {
  const rows = Object.keys(matrix);
  if (!rows.length) return "";
  return `
    <div class="analytics-card" style="grid-column: 1 / -1;">
      <h4>${escapeHtml(title)}</h4>
      <div class="heatmap-wrap">
        <table class="heatmap">
          <thead><tr><th></th>${PLATFORMS.map((p) => `<th>${escapeHtml(PLAT_LABEL[p])}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows
              .map((pid) => {
                const name = personaNames[pid] || pid;
                return `<tr>
                  <td class="row-label" title="${escapeHtml(name)}">${escapeHtml(name.split(" ")[0] || pid)}</td>
                  ${PLATFORMS.map((p) => {
                    const cell = matrix[pid]?.[p];
                    const rate = cell?.rate ?? 0;
                    const txt = cell ? `${cell.success}/${cell.eligible}` : "—";
                    return `<td class="heat-cell" style="background:${heatColor(rate)}">${escapeHtml(txt)}</td>`;
                  }).join("")}
                </tr>`;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    </div>`;
}

function renderAnalytics() {
  const a = _study?.analytics;
  if (!a) {
    analyticsRoot.innerHTML = `<p class="trace-empty">No analytics for this study.</p>`;
    return;
  }
  const personaNames = Object.fromEntries((_study.personas || []).map((p) => [p.id, p.name]));

  const journeyHtml = (a.by_journey || [])
    .map((j) => {
      const pills = PLATFORMS.map((p) => {
        const st = j.platforms?.[p];
        const pref = j.preference_counts?.[p] || 0;
        if (!st) return "";
        return `<span class="mini-pill">${PLAT_LABEL[p]} ${st.success}/${st.eligible} · pref ${pref}</span>`;
      }).join("");
      return `<div class="journey-row drill-link" data-drill-journey="${escapeHtml(j.goal_key)}" style="cursor:pointer" title="Open traces for this journey">
        <span><strong>${escapeHtml(j.category || j.title)}</strong><br/><span style="opacity:0.7;font-size:0.75rem">${escapeHtml(j.title)}</span></span>
        <div class="mini-pills">${pills}</div>
      </div>`;
    })
    .join("");

  const personaRows = (a.by_persona || [])
    .map((p) => {
      const top = p.top_preference ? PLAT_LABEL[p.top_preference] : "—";
      const succ = PLATFORMS.map((plat) => {
        const st = p.platforms?.[plat];
        return st ? `${PLAT_LABEL[plat][0]}:${st.success}/${st.eligible}` : "";
      })
        .filter(Boolean)
        .join(" · ");
      return `<div class="journey-row drill-link" data-drill-persona="${escapeHtml(p.persona_id)}" style="cursor:pointer" title="Open traces for this persona">
        <span><strong>${escapeHtml(p.persona_name)}</strong><br/><span style="opacity:0.7;font-size:0.75rem">prefers ${escapeHtml(top)}</span></span>
        <div class="mini-pills"><span class="mini-pill">${escapeHtml(succ)}</span></div>
      </div>`;
    })
    .join("");

  analyticsRoot.innerHTML = `
    <div class="analytics-grid">
      <div class="analytics-card">
        <h4>Overall</h4>
        <div class="stat-row"><span class="label">Success (raw)</span><span class="value">${a.successes}/${a.n} (${pct(a.success_rate_raw)})</span></div>
        <div class="stat-row"><span class="label">Scored (excl blocked)</span><span class="value">${pct(a.success_rate_scored)}</span></div>
        <div class="stat-row"><span class="label">Cost</span><span class="value">$${escapeHtml((a.total_cost_usd || 0).toFixed(2))}</span></div>
        ${_study.model ? `<div class="stat-row"><span class="label">Model</span><span class="value">${escapeHtml(_study.model)}</span></div>` : ""}
      </div>
      ${renderBarChart("Success rate by platform", a.success_by_platform || {})}
      ${renderCountBars("Avg preference (matched triplets)", a.preference_by_platform || {})}
      ${renderCountBars("Sole success wins (only platform that succeeded)", a.success_wins_by_platform || {})}
    </div>
    ${renderHeatmap("Persona × platform success rate", a.persona_success_matrix || {}, personaNames)}
    <div class="analytics-grid">
      <div class="analytics-card">
        <h4>By journey / task type</h4>
        <div class="journey-list">${journeyHtml || "<p class='trace-empty'>—</p>"}</div>
      </div>
      <div class="analytics-card">
        <h4>By persona (preference + success)</h4>
        <div class="journey-list">${personaRows || "<p class='trace-empty'>—</p>"}</div>
      </div>
    </div>
    <p class="section-sub" style="margin-top:0.5rem;opacity:0.75;font-size:0.8rem">
      Preference = explicit comparative pick when available, else sole SUCCESS in a matched triplet, else furthest progress (non-blocked).
      Click a journey or persona row to jump to traces. Use <strong>Trace drill-down</strong> for step screenshots.
    </p>`;

  analyticsRoot.querySelectorAll("[data-drill-persona]").forEach((el) => {
    el.addEventListener("click", () => {
      if (!_study?.is_full270) return;
      personaSelect.value = el.dataset.drillPersona;
      populateJourneyOptions(personaSelect.value);
      populateSeedOptions(personaSelect.value, journeySelect.value);
      setView("traces");
      applyDrillDown();
    });
  });
  analyticsRoot.querySelectorAll("[data-drill-journey]").forEach((el) => {
    el.addEventListener("click", () => {
      if (!_study?.is_full270) return;
      const pid = el.dataset.drillPersona || personaSelect.value;
      personaSelect.value = pid;
      populateJourneyOptions(pid);
      journeySelect.value = el.dataset.drillJourney;
      populateSeedOptions(pid, journeySelect.value);
      setView("traces");
      applyDrillDown();
    });
  });
}

function setView(view) {
  _activeView = view;
  document.querySelectorAll(".view-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.view === view);
  });
  overviewPanel.classList.toggle("hidden", view !== "overview");
  tracesPanel.classList.toggle("hidden", view !== "traces");
}

function blockForFilters(personaId, journeyKey, seed) {
  if (!_study?.is_full270) return null;
  const blocks = _study.matched_blocks || [];
  return blocks.find(
    (b) =>
      b.persona_id === personaId &&
      b.goal_key === journeyKey &&
      (seed == null || b.seed === seed)
  );
}

function syncFiltersFromBlock(blockId) {
  const block = (_study.matched_blocks || []).find((b) => b.id === blockId);
  if (!block) return;
  if (personaSelect.value !== block.persona_id) personaSelect.value = block.persona_id;
  populateJourneyOptions(block.persona_id);
  if (journeySelect.value !== block.goal_key) journeySelect.value = block.goal_key;
  populateSeedOptions(block.persona_id, block.goal_key);
  if (block.seed != null) seedSelect.value = String(block.seed);
}

function populatePersonaOptions() {
  personaSelect.innerHTML = "";
  for (const p of _study.personas || []) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    personaSelect.appendChild(opt);
  }
}

function populateJourneyOptions(personaId) {
  journeySelect.innerHTML = "";
  const types = _study.journey_types || [];
  const seen = new Set();
  for (const t of types) {
    if (seen.has(t.key)) continue;
    seen.add(t.key);
    const hasBlock = (_study.matched_blocks || []).some(
      (b) => b.persona_id === personaId && b.goal_key === t.key
    );
    if (!hasBlock && _study.is_full270) continue;
    const opt = document.createElement("option");
    opt.value = t.key;
    opt.textContent = `${t.category} — ${t.title}`;
    journeySelect.appendChild(opt);
  }
}

function populateSeedOptions(personaId, journeyKey) {
  seedSelect.innerHTML = "";
  const seeds = [
    ...new Set(
      (_study.matched_blocks || [])
        .filter((b) => b.persona_id === personaId && b.goal_key === journeyKey)
        .map((b) => b.seed)
        .filter((s) => s != null)
    ),
  ].sort();
  for (const s of seeds) {
    const opt = document.createElement("option");
    opt.value = String(s);
    opt.textContent = `Seed ${s}`;
    seedSelect.appendChild(opt);
  }
}

function populateGoalOptionsLegacy() {
  goalSelect.innerHTML = "";
  const byJourney = {};
  for (const t of _study.tasks || []) {
    const gk = t.goal_key || t.id;
    if (!byJourney[gk]) byJourney[gk] = t;
  }
  const groups = _study.journey_types?.length
    ? _study.journey_types
    : Object.values(byJourney).map((t) => ({ key: t.goal_key || t.id, title: t.title, category: "Tasks" }));
  for (const jt of groups) {
    const tasksInGroup = (_study.tasks || []).filter((t) => (t.goal_key || t.id) === jt.key);
    if (!tasksInGroup.length && !byJourney[jt.key]) continue;
    const og = document.createElement("optgroup");
    og.label = jt.category || jt.title;
    for (const t of tasksInGroup.length ? tasksInGroup : [byJourney[jt.key]].filter(Boolean)) {
      const opt = document.createElement("option");
      opt.value = t.comparative_group || t.id;
      const seedLabel = t.seed ? ` · seed ${t.seed}` : "";
      opt.textContent = `${t.title || jt.title}${seedLabel}`;
      og.appendChild(opt);
    }
    if (og.children.length) goalSelect.appendChild(og);
  }
  if (!goalSelect.options.length) {
    const goals = [...new Set((_study.agent_results || []).map((r) => r.goal_key))];
    for (const g of goals) {
      const sample = _study.agent_results.find((r) => r.goal_key === g);
      const opt = document.createElement("option");
      opt.value = g;
      opt.textContent = sample?.task_title?.split(" — ")[0] || g;
      goalSelect.appendChild(opt);
    }
  }
}

function renderBlock(blockId) {
  _currentBlock = blockId;
  _currentGoal = blockId;
  const block = (_study.matched_blocks || []).find((b) => b.id === blockId);
  const results = (_study.agent_results || []).filter((r) => r.comparative_group === blockId);
  const byPlatform = Object.fromEntries(results.map((r) => [r.platform, r]));

  const pref = (_study.analytics?.block_preferences || []).find((b) => b.block_id === blockId)?.preferred;
  const successPlats = results.filter((r) => r.success).map((r) => r.platform);

  const sample = results[0];
  goalPrompt.textContent = sample?.task_prompt || "";
  if (sample?.persona_name) {
    goalPrompt.textContent = `${sample.persona_name} · ${goalPrompt.textContent}`;
  }

  const comp = (_study.comparative?.reviews || []).find(
    (r) => r.goal_key === block?.goal_key && r.persona_id === block?.persona_id
  );
  if (comp?.most_likely_to_use) {
    compareBanner.hidden = false;
    compareBanner.innerHTML = `<strong>Persona pick:</strong> ${escapeHtml(comp.most_likely_to_use)} · runner-up ${escapeHtml(comp.runner_up || "—")} — ${escapeHtml(comp.why_winner || "")}`;
  } else if (pref) {
    compareBanner.hidden = false;
    compareBanner.innerHTML = `<strong>Derived preference:</strong> ${escapeHtml(PLAT_LABEL[pref] || pref)}${successPlats.length ? ` · SUCCESS on: ${successPlats.map((p) => PLAT_LABEL[p]).join(", ")}` : ""}`;
  } else {
    compareBanner.hidden = true;
  }

  platformGrid.innerHTML = PLATFORMS.map((plat) => {
    const r = byPlatform[plat];
    if (!r) {
      return `<article class="platform-card"><div class="col-header"><h3>${escapeHtml(PLAT_LABEL[plat])}</h3></div><p class="trace-empty">No run.</p></article>`;
    }
    return renderColumn(r, {
      isWinner: r.success,
      isPreferred: pref === plat,
    });
  }).join("");
  wireStepControls();
}

function renderGoalLegacy(goalKey) {
  _currentBlock = null;
  _currentGoal = goalKey;
  const byPlatform = Object.fromEntries(
    (_study.agent_results || []).filter((r) => r.goal_key === goalKey || r.task_id === goalKey).map((r) => [r.platform, r])
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
      return `<article class="platform-card"><div class="col-header"><h3>${escapeHtml(PLAT_LABEL[plat])}</h3></div><p class="trace-empty">No run.</p></article>`;
    }
    return renderColumn(r, { isWinner: comp?.most_likely_to_use === plat, isPreferred: false });
  }).join("");
  wireStepControls();
}

function applyDrillDown() {
  PLATFORMS.forEach((p) => {
    _activeIdx[p] = 0;
  });
  if (_study?.is_full270) {
    const block = blockForFilters(
      personaSelect.value,
      journeySelect.value,
      Number(seedSelect.value)
    );
    if (block) {
      goalSelect.value = block.id;
      renderBlock(block.id);
    }
  } else {
    renderGoalLegacy(goalSelect.value);
  }
}

async function loadStudies() {
  const res = await fetch("/api/bakeoff/studies");
  const data = await res.json();
  studySelect.innerHTML = "";
  for (const s of data.studies || []) {
    const opt = document.createElement("option");
    opt.value = s.id;
    const label = s.is_full270
      ? s.persona_name
      : `${s.persona_name} (${s.successes}/${s.n_runs})`;
    opt.textContent = label;
    studySelect.appendChild(opt);
  }
  if (studySelect.options.length) await loadStudy(studySelect.value);
}

async function loadStudy(studyId) {
  const res = await fetch(`/api/bakeoff/studies/${encodeURIComponent(studyId)}`);
  _study = await res.json();
  studyHeadline.textContent = _study.headline || "";

  const isF270 = _study.is_full270;
  personaFilterWrap.classList.toggle("hidden", !isF270);
  journeyFilterWrap.classList.toggle("hidden", !isF270);
  seedFilterWrap.classList.toggle("hidden", !isF270);
  goalFilterWrap.classList.toggle("hidden", isF270);

  if (isF270) {
    populatePersonaOptions();
    const pid = personaSelect.value || _study.personas?.[0]?.id;
    populateJourneyOptions(pid);
    populateSeedOptions(pid, journeySelect.value);
    applyDrillDown();
  } else {
    populateGoalOptionsLegacy();
    if (goalSelect.options.length) renderGoalLegacy(goalSelect.value);
  }

  renderAnalytics();
  PLATFORMS.forEach((p) => {
    _activeIdx[p] = 0;
  });
}

document.querySelectorAll(".view-tab").forEach((btn) => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});

studySelect.addEventListener("change", () => loadStudy(studySelect.value));

personaSelect.addEventListener("change", () => {
  populateJourneyOptions(personaSelect.value);
  populateSeedOptions(personaSelect.value, journeySelect.value);
  applyDrillDown();
});

journeySelect.addEventListener("change", () => {
  populateSeedOptions(personaSelect.value, journeySelect.value);
  applyDrillDown();
});

seedSelect.addEventListener("change", applyDrillDown);

goalSelect.addEventListener("change", () => {
  if (_study?.is_full270) {
    syncFiltersFromBlock(goalSelect.value);
    renderBlock(goalSelect.value);
  } else {
    PLATFORMS.forEach((p) => {
      _activeIdx[p] = 0;
    });
    renderGoalLegacy(goalSelect.value);
  }
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
  analyticsRoot.innerHTML = `<p class="trace-empty">Failed to load: ${escapeHtml(err.message)}</p>`;
});
