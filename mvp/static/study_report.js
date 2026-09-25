/** Study Report — analytics + trace drill-down for any product study */

const insightsRoot = document.getElementById("insights-root");
const personaSelect = document.getElementById("persona-select");
const taskSelect = document.getElementById("task-select");
const traceContainer = document.getElementById("trace-container");
const taskPrompt = document.getElementById("task-prompt");

let _study = null;
let _currentTask = null;
let _activeIdx = 0;

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function getStudyId() {
  const params = new URLSearchParams(location.search);
  return params.get("id") || params.get("study") || "";
}

function getStudySlug() {
  const path = location.pathname;
  // Handle /study/<slug> paths
  const match = path.match(/^\/study\/([^/]+)/);
  if (match) return match[1];
  // Handle direct product slugs like /retell, /blandai
  const directMatch = path.match(/^\/([a-z][a-z0-9-]+)$/i);
  if (directMatch && !["live", "report", "health", "bakeoff", "recurse"].includes(directMatch[1])) {
    return directMatch[1];
  }
  return "";
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
function successPill(success) {
  if (success === true) return '<span class="pill success">SUCCESS</span>';
  if (success === false) return '<span class="pill fail">FAIL</span>';
  return '<span class="pill partial">PARTIAL</span>';
}

function barRow(label, value, max, colorClass = "") {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const fillClass = colorClass || (pct >= 70 ? "success" : pct >= 40 ? "warning" : "error");
  return `<div class="bar-row">
    <span class="bar-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span>
    <div class="bar-track"><div class="bar-fill ${fillClass}" style="width:${pct}%"></div></div>
    <span class="bar-val">${typeof value === "number" ? (Number.isInteger(value) ? value : value.toFixed(1)) : value}</span>
  </div>`;
}

function renderInsightCard(title, items, type, onEvidenceClick) {
  if (!items || !items.length) return "";
  const listItems = items.map((item, i) => {
    const evidence = item.evidence ? 
      `<span class="evidence-link" data-task="${escapeHtml(item.task_id || "")}" data-persona="${escapeHtml(item.persona_id || "")}">→ see trace</span>` : "";
    return `<li>${escapeHtml(item.text || item)} ${evidence}</li>`;
  }).join("");
  return `<div class="insight-card ${type}">
    <h3>${type === "strengths" ? "✓" : "✗"} ${escapeHtml(title)}</h3>
    <ul>${listItems}</ul>
  </div>`;
}

function computeAnalytics(study) {
  const results = study.agent_results || [];
  const personas = study.personas || [];
  const tasks = study.tasks || [];
  
  const totalRuns = results.length;
  const successRuns = results.filter(r => r.success).length;
  const successRate = totalRuns ? Math.round(100 * successRuns / totalRuns) : 0;
  
  const stepsArr = results.filter(r => r.success && r.num_actions).map(r => r.num_actions);
  const avgSteps = stepsArr.length ? (stepsArr.reduce((a, b) => a + b, 0) / stepsArr.length) : 0;
  
  const byPersona = {};
  personas.forEach(p => {
    byPersona[p.id] = { id: p.id, name: p.name, ok: 0, n: 0, steps: [] };
  });
  results.forEach(r => {
    const pid = r.persona_id;
    if (!byPersona[pid]) byPersona[pid] = { id: pid, name: r.persona_name || pid, ok: 0, n: 0, steps: [] };
    byPersona[pid].n++;
    if (r.success) {
      byPersona[pid].ok++;
      if (r.num_actions) byPersona[pid].steps.push(r.num_actions);
    }
  });
  
  const byTask = {};
  tasks.forEach(t => {
    byTask[t.id] = { id: t.id, title: t.title || t.id, ok: 0, n: 0, steps: [] };
  });
  results.forEach(r => {
    const tid = r.task_id || r.goal_key;
    if (!byTask[tid]) byTask[tid] = { id: tid, title: r.task_title || tid, ok: 0, n: 0, steps: [] };
    byTask[tid].n++;
    if (r.success) {
      byTask[tid].ok++;
      if (r.num_actions) byTask[tid].steps.push(r.num_actions);
    }
  });
  
  const strengths = [];
  const weaknesses = [];
  
  results.forEach(r => {
    (r.likes || []).forEach(like => {
      strengths.push({ text: like, task_id: r.task_id || r.goal_key, persona_id: r.persona_id, evidence: true });
    });
    (r.dislikes || []).forEach(dislike => {
      weaknesses.push({ text: dislike, task_id: r.task_id || r.goal_key, persona_id: r.persona_id, evidence: true });
    });
    (r.friction_points || []).forEach(fp => {
      weaknesses.push({ text: fp, task_id: r.task_id || r.goal_key, persona_id: r.persona_id, evidence: true });
    });
  });
  
  const uniqueStrengths = [];
  const seenStrengths = new Set();
  strengths.forEach(s => {
    const key = s.text.toLowerCase().slice(0, 50);
    if (!seenStrengths.has(key)) {
      seenStrengths.add(key);
      uniqueStrengths.push(s);
    }
  });
  
  const uniqueWeaknesses = [];
  const seenWeaknesses = new Set();
  weaknesses.forEach(w => {
    const key = w.text.toLowerCase().slice(0, 50);
    if (!seenWeaknesses.has(key)) {
      seenWeaknesses.add(key);
      uniqueWeaknesses.push(w);
    }
  });
  
  return {
    totalRuns,
    successRuns,
    successRate,
    avgSteps,
    byPersona: Object.values(byPersona),
    byTask: Object.values(byTask),
    strengths: uniqueStrengths.slice(0, 8),
    weaknesses: uniqueWeaknesses.slice(0, 8),
  };
}

function renderAnalytics(study, analytics) {
  const productName = study.product_name || (study.url ? new URL(study.url).hostname.replace("www.", "") : "Product");
  const comparisonNote = study.comparison_note || "";
  
  const personaBars = analytics.byPersona.map(p => {
    const rate = p.n ? Math.round(100 * p.ok / p.n) : 0;
    return barRow(p.name, `${p.ok}/${p.n}`, 1, rate >= 80 ? "success" : rate >= 50 ? "warning" : "error");
  }).join("");
  
  const taskBars = analytics.byTask.map(t => {
    const rate = t.n ? Math.round(100 * t.ok / t.n) : 0;
    return barRow(t.title.slice(0, 25), `${t.ok}/${t.n}`, 1, rate >= 80 ? "success" : rate >= 50 ? "warning" : "error");
  }).join("");
  
  const taskStepBars = analytics.byTask.filter(t => t.steps.length).map(t => {
    const avg = t.steps.reduce((a, b) => a + b, 0) / t.steps.length;
    return barRow(t.title.slice(0, 25), avg.toFixed(1), 20);
  }).join("");
  
  const strengthsCard = renderInsightCard(`${productName} strengths`, analytics.strengths, "strengths");
  const weaknessesCard = renderInsightCard(`${productName} weaknesses`, analytics.weaknesses, "weaknesses");
  
  insightsRoot.innerHTML = `
    <div class="stat-strip">
      <span><strong>${analytics.totalRuns}</strong> agent runs</span>
      <span><strong>${analytics.successRate}%</strong> task success</span>
      <span><strong>${analytics.avgSteps.toFixed(1)}</strong> avg steps (successful)</span>
    </div>
    
    ${comparisonNote ? `<p class="metric-note">${escapeHtml(comparisonNote)}</p>` : ""}
    
    <div class="insight-cards">
      ${strengthsCard}
      ${weaknessesCard}
    </div>
    
    <div class="analytics-grid">
      <div class="chart-card">
        <h3>Success by persona</h3>
        <p class="sub">Did each persona complete their assigned tasks?</p>
        ${personaBars || '<p class="sub">No persona data</p>'}
      </div>
      <div class="chart-card">
        <h3>Success by task</h3>
        <p class="sub">Which tasks were completed across all personas?</p>
        ${taskBars || '<p class="sub">No task data</p>'}
      </div>
      <div class="chart-card">
        <h3>Avg steps by task</h3>
        <p class="sub">How many actions to complete each task? (lower is better)</p>
        ${taskStepBars || '<p class="sub">No step data</p>'}
      </div>
    </div>
    
    <div class="chart-card">
      <h3>Persona breakdown</h3>
      <p class="sub">Click a task to see its trace</p>
      ${renderPersonaBlocks(study, analytics)}
    </div>
  `;
  
  insightsRoot.querySelectorAll(".evidence-link, .task-row").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const taskId = el.dataset.task;
      const personaId = el.dataset.persona;
      if (taskId) {
        document.querySelector('.tab-btn[data-tab="traces"]').click();
        if (personaId && [...personaSelect.options].some(o => o.value === personaId)) {
          personaSelect.value = personaId;
          populateTaskSelect(personaId);
        }
        if ([...taskSelect.options].some(o => o.value === taskId)) {
          taskSelect.value = taskId;
          _activeIdx = 0;
          renderTrace(taskId);
        }
      }
    });
  });
}

function renderPersonaBlocks(study, analytics) {
  return analytics.byPersona.map(p => {
    const persona = (study.personas || []).find(x => x.id === p.id) || { bio: "" };
    const tasks = (study.agent_results || []).filter(r => r.persona_id === p.id);
    const taskRows = tasks.map(t => `
      <tr class="task-row" data-task="${escapeHtml(t.task_id || t.goal_key)}" data-persona="${escapeHtml(p.id)}">
        <td>${escapeHtml((t.task_title || t.goal_key || "").slice(0, 40))}</td>
        <td>${successPill(t.success)}</td>
        <td>${t.num_actions || "—"}</td>
        <td>${escapeHtml(t.difficulty || "—")}</td>
      </tr>
    `).join("");
    
    const rate = p.n ? Math.round(100 * p.ok / p.n) : 0;
    return `<div class="persona-block">
      <div class="persona-header">
        <span class="persona-summary-title">${escapeHtml(p.name)} <span class="pill ${rate >= 70 ? "success" : rate >= 40 ? "partial" : "fail"}">${p.ok}/${p.n}</span></span>
        <span class="persona-summary-meta">${rate}% success</span>
      </div>
      <div class="persona-body">
        <p class="bio">${escapeHtml(persona.bio || "")}</p>
        <table>
          <thead><tr><th>Task</th><th>Status</th><th>Steps</th><th>Difficulty</th></tr></thead>
          <tbody>${taskRows}</tbody>
        </table>
      </div>
    </div>`;
  }).join("");
}

/* ---------- trace viewer ---------- */
function stepsWithScreenshots(trace) {
  return (trace || []).filter(s => s.screenshot_url);
}

function renderStepViewer(result) {
  const shots = stepsWithScreenshots(result.trace || []);
  if (!shots.length) {
    return `<div class="step-viewer">
      <div class="step-shot" style="min-height:200px;align-items:center;justify-content:center;">
        <p style="color:#888">No step screenshots available.<br/>Final URL: ${escapeHtml(result.final_url || "—")}</p>
      </div>
    </div>`;
  }
  
  let idx = _activeIdx;
  if (idx < 0 || idx >= shots.length) idx = 0;
  _activeIdx = idx;
  const step = shots[idx];
  
  return `<div class="step-viewer">
    <div class="step-nav">
      <button type="button" class="step-arrow" data-dir="-1" ${idx <= 0 ? "disabled" : ""}>←</button>
      <div class="step-nums">
        ${shots.map((s, i) => `
          <button type="button" class="step-num${i === idx ? " active" : ""}" data-idx="${i}">${s.step}</button>
        `).join("")}
      </div>
      <button type="button" class="step-arrow" data-dir="1" ${idx >= shots.length - 1 ? "disabled" : ""}>→</button>
    </div>
    <figure class="step-shot">
      <img class="trace-screenshot" src="${escapeHtml(step.screenshot_url)}" alt="Step ${step.step}" />
    </figure>
    <div class="step-detail">
      <p class="step-action"><strong>${escapeHtml(step.step)}.</strong> ${escapeHtml(step.action || "Action")}</p>
      ${step.target ? `<p class="step-meta"><span>Clicked</span> ${escapeHtml(step.target)}</p>` : ""}
      ${step.url ? `<p class="step-meta"><span>URL</span> ${escapeHtml(step.url)}</p>` : ""}
    </div>
  </div>`;
}

function renderTrace(taskId) {
  _currentTask = taskId;
  const personaId = personaSelect.value;
  const result = (_study.agent_results || []).find(r => 
    (r.task_id === taskId || r.goal_key === taskId) && 
    (!personaId || r.persona_id === personaId)
  );
  
  if (!result) {
    traceContainer.innerHTML = '<p class="error-msg">No trace found for this task/persona combination.</p>';
    return;
  }
  
  taskPrompt.textContent = result.task_prompt || "";
  
  const likesHtml = (result.likes || []).map(x => `<li>${escapeHtml(x)}</li>`).join("");
  const dislikesHtml = (result.dislikes || []).map(x => `<li>${escapeHtml(x)}</li>`).join("");
  
  traceContainer.innerHTML = `
    <div class="trace-card">
      <div class="col-header">
        <h3>
          ${escapeHtml(result.persona_name || "Agent")} — ${escapeHtml((result.task_title || taskId).slice(0, 50))}
          <span class="tag status-${result.success ? "complete" : "error"}">${result.success ? "SUCCESS" : "FAIL"}</span>
        </h3>
        <p style="margin:0.25rem 0 0;font-size:0.85rem;color:var(--text-muted)">
          ${result.num_actions || "?"} steps · ${escapeHtml(result.difficulty || "—")} difficulty
          ${result.final_url ? ` · <a href="${escapeHtml(result.final_url)}" target="_blank" rel="noopener">final URL</a>` : ""}
        </p>
      </div>
      ${renderStepViewer(result)}
      ${(likesHtml || dislikesHtml) ? `
        <div class="feedback-section">
          ${likesHtml ? `<h4>👍 Liked</h4><ul>${likesHtml}</ul>` : ""}
          ${dislikesHtml ? `<h4>👎 Disliked</h4><ul>${dislikesHtml}</ul>` : ""}
        </div>
      ` : ""}
    </div>
  `;
  
  wireStepControls();
}

function wireStepControls() {
  traceContainer.querySelectorAll(".step-num").forEach(el => {
    el.addEventListener("click", () => {
      const idx = Number(el.dataset.idx);
      if (!Number.isNaN(idx)) {
        _activeIdx = idx;
        renderTrace(_currentTask);
      }
    });
  });
  traceContainer.querySelectorAll(".step-arrow:not([disabled])").forEach(el => {
    el.addEventListener("click", () => {
      const dir = Number(el.dataset.dir);
      if (dir) {
        _activeIdx += dir;
        renderTrace(_currentTask);
      }
    });
  });
}

function populateTaskSelect(personaId) {
  const tasks = (_study.agent_results || [])
    .filter(r => !personaId || r.persona_id === personaId)
    .map(r => ({ id: r.task_id || r.goal_key, title: r.task_title || r.goal_key }));
  
  const uniqueTasks = [];
  const seen = new Set();
  tasks.forEach(t => {
    if (!seen.has(t.id)) {
      seen.add(t.id);
      uniqueTasks.push(t);
    }
  });
  
  taskSelect.innerHTML = uniqueTasks.map(t => 
    `<option value="${escapeHtml(t.id)}">${escapeHtml((t.title || t.id).slice(0, 50))}</option>`
  ).join("");
  
  if (uniqueTasks.length) {
    _activeIdx = 0;
    renderTrace(uniqueTasks[0].id);
  }
}

function populateSelects() {
  const personas = _study.personas || [];
  const defaultPersonas = [...new Set((_study.agent_results || []).map(r => r.persona_id))];
  
  personaSelect.innerHTML = '<option value="">All personas</option>' + 
    (personas.length ? personas : defaultPersonas.map(id => ({ id, name: id }))).map(p => 
      `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name || p.id)}</option>`
    ).join("");
  
  populateTaskSelect("");
}

personaSelect.addEventListener("change", () => {
  populateTaskSelect(personaSelect.value);
});

taskSelect.addEventListener("change", () => {
  _activeIdx = 0;
  renderTrace(taskSelect.value);
});

/* ---------- load study ---------- */
async function loadStudy() {
  const slug = getStudySlug();
  const studyId = getStudyId();
  
  let apiUrl = "";
  if (slug) {
    apiUrl = `/api/experiment/${encodeURIComponent(slug)}`;
  } else if (studyId) {
    apiUrl = `/api/studies/${encodeURIComponent(studyId)}`;
  } else {
    insightsRoot.innerHTML = '<p class="error-msg">No study ID specified. Use ?id=STUDY_ID or /study/SLUG</p>';
    return;
  }
  
  try {
    const res = await fetch(apiUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _study = await res.json();
    
    const productName = _study.product_name || (_study.url ? new URL(_study.url).hostname.replace("www.", "").replace(".com", "") : "Study");
    document.getElementById("study-title").innerHTML = `${escapeHtml(productName)} study<br /><em>analytics + traces</em>`;
    document.getElementById("study-lede").textContent = _study.lede || _study.segment || `Simulated user study of ${productName}`;
    document.getElementById("study-badge").textContent = productName;
    document.getElementById("study-badge").classList.add(slug || "study");
    document.title = `UserSim — ${productName} study`;
    
    const analytics = computeAnalytics(_study);
    renderAnalytics(_study, analytics);
    populateSelects();
  } catch (err) {
    insightsRoot.innerHTML = `<p class="error-msg">Failed to load study: ${escapeHtml(err.message)}</p>`;
    console.error(err);
  }
}

loadStudy();
