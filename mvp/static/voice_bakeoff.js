/** Voice AI Bakeoff — Retell vs Bland vs Vapi comparison */

const PLATFORMS = ["retell", "bland", "vapi"];
const PLAT_LABEL = { retell: "Retell AI", bland: "Bland AI", vapi: "Vapi" };

const personaSelect = document.getElementById("persona-select");
const taskSelect = document.getElementById("task-select");
const platformGrid = document.getElementById("platform-grid");
const taskPrompt = document.getElementById("task-prompt");
const analyticsRoot = document.getElementById("analytics-root");
const statusContent = document.getElementById("status-content");

let _study = null;
let _currentTask = null;
const _activeIdx = { retell: 0, bland: 0, vapi: 0 };

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.hidden = p.id !== `tab-${btn.dataset.tab}`;
    });
  });
});

function legend() {
  return `<div class="legend">
    <span class="retell">Retell</span>
    <span class="bland">Bland</span>
    <span class="vapi">Vapi</span>
  </div>`;
}

function pill(plat) {
  if (!plat) return "—";
  return `<span class="pill ${escapeHtml(plat)}">${escapeHtml(PLAT_LABEL[plat] || plat)}</span>`;
}

function statusPill(result) {
  if (result.success) return '<span class="pill success">SUCCESS</span>';
  if (result.harness_timeout) return '<span class="pill timeout">TIMEOUT</span>';
  return '<span class="pill fail">FAIL</span>';
}

function renderStatus(summary) {
  const byProduct = summary.by_product || {};
  const totalRuns = summary.total_runs || 0;
  
  let totalSuccess = 0, totalHarness = 0, totalBotWall = 0, totalProductFail = 0;
  for (const p of PLATFORMS) {
    const prod = byProduct[p] || {};
    totalSuccess += prod.success || 0;
    totalHarness += prod.harness_failure || prod.harness || prod.harness_timeout || 0;
    totalBotWall += prod.bot_wall || 0;
    totalProductFail += prod.product_failure || prod.failure || 0;
  }

  const items = [
    { label: "Total runs", value: totalRuns },
    { label: "Successes", value: totalSuccess },
    { label: "Harness failures", value: totalHarness },
    { label: "Bot walls", value: totalBotWall },
    { label: "Product failures", value: totalProductFail },
    { label: "Page", value: '<a href="/retell">/retell</a>' },
  ];

  let blockerHtml = "";
  if (totalHarness > 0 || totalBotWall > 0) {
    blockerHtml = `
    <div class="blocker">
      ⚠️ <strong>Note:</strong> Harness failures and bot walls are NOT product issues.
      Only product failures indicate actual UX problems with the platform.
    </div>`;
  }

  statusContent.innerHTML = items.map(item =>
    `<div class="status-item">
      <span class="status-label">${escapeHtml(item.label)}</span>
      <span class="status-value">${item.value}</span>
    </div>`
  ).join("") + blockerHtml;
}

function renderAnalytics(study) {
  const summary = study.summary || {};
  const results = study.agent_results || [];
  const byProduct = summary.by_product || {};
  const taskWinners = summary.task_winners || {};

  renderStatus(summary);

  const successRates = {};
  const timeoutRates = {};
  const failRates = {};
  for (const p of PLATFORMS) {
    const prod = byProduct[p] || {};
    const total = (prod.success || 0) + (prod.harness_timeout || 0) + (prod.failure || 0);
    successRates[p] = total ? Math.round(100 * (prod.success || 0) / total) : 0;
    timeoutRates[p] = total ? Math.round(100 * (prod.harness_timeout || 0) / total) : 0;
    failRates[p] = total ? Math.round(100 * (prod.failure || 0) / total) : 0;
  }

  const successBars = PLATFORMS.map(p => {
    const pct = successRates[p];
    return `<div class="bar-row">
      <span class="bar-label">${escapeHtml(PLAT_LABEL[p])}</span>
      <div class="bar-track"><div class="bar-fill ${p}" style="width:${pct}%"></div></div>
      <span class="bar-val">${pct}%</span>
    </div>`;
  }).join("");

  const tasksByProduct = {};
  const taskList = [...new Set(results.map(r => r.task_title))];
  
  for (const task of taskList) {
    tasksByProduct[task] = {};
    for (const p of PLATFORMS) {
      const runs = results.filter(r => r.task_title === task && r.product === p);
      tasksByProduct[task][p] = {
        success: runs.filter(r => r.success).length,
        timeout: runs.filter(r => r.harness_timeout).length,
        fail: runs.filter(r => !r.success && !r.harness_timeout).length,
        total: runs.length,
        avgSteps: runs.filter(r => r.success).reduce((s, r) => s + (r.num_steps || 0), 0) / 
                  (runs.filter(r => r.success).length || 1)
      };
    }
  }

  const taskRows = taskList.map(task => {
    const winner = taskWinners[task] || "";
    const cells = PLATFORMS.map(p => {
      const d = tasksByProduct[task][p];
      const rate = d.total ? Math.round(100 * d.success / d.total) : 0;
      let note = "";
      if (d.timeout > 0) note = ` (${d.timeout} timeout)`;
      return `<td>${d.success}/${d.total}${note}</td>`;
    }).join("");
    
    let winnerDisplay;
    if (winner.startsWith("tie:")) {
      const tiedPlatforms = winner.replace("tie:", "").split(",");
      winnerDisplay = `<span class="pill" style="background:#f6f6f6;color:#6b6b6b">TIE: ${tiedPlatforms.map(p => PLAT_LABEL[p] || p).join(", ")}</span>`;
    } else if (winner === "none") {
      winnerDisplay = `<span style="color:#6b6b6b">—</span>`;
    } else {
      winnerDisplay = pill(winner);
    }
    
    return `<tr>
      <td>${escapeHtml(task.slice(0, 35))}</td>
      ${cells}
      <td>${winnerDisplay}</td>
    </tr>`;
  }).join("");

  const retellStrengths = (summary.retell_strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");
  const retellWeaknesses = (summary.retell_weaknesses || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");
  const blandStrengths = (summary.bland_strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");
  const blandWeaknesses = (summary.bland_weaknesses || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");
  const vapiStrengths = (summary.vapi_strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");
  const vapiWeaknesses = (summary.vapi_weaknesses || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");

  analyticsRoot.innerHTML = `
    <div class="stat-strip">
      <span><strong>${summary.total_runs || results.length}</strong> agent runs</span>
      <span><strong>3</strong> platforms compared</span>
      <span><strong>3</strong> personas × <strong>5</strong> tasks</span>
    </div>
    <p class="metric-note">
      Harness timeouts (8 min wall clock) are counted separately from product failures. 
      A timeout means the test harness hit its limit, not necessarily a product issue.
    </p>

    <div class="analytics-grid">
      <div class="chart-card">
        <h3>Task success rate</h3>
        <p class="sub">Percentage of runs that completed successfully</p>
        ${legend()}
        ${successBars}
      </div>
      <div class="chart-card">
        <h3>Breakdown by product</h3>
        <p class="sub">Success vs timeout vs failure counts</p>
        ${PLATFORMS.map(p => {
          const prod = byProduct[p] || {};
          return `<div style="margin-bottom:0.75rem">
            <strong>${escapeHtml(PLAT_LABEL[p])}</strong>
            <div style="font-size:0.85rem;color:var(--text-muted)">
              ✓ ${prod.success || 0} success · ⏱ ${prod.harness_timeout || 0} timeout · ✗ ${prod.failure || 0} fail
            </div>
          </div>`;
        }).join("")}
      </div>
    </div>

    <div class="chart-card" style="margin-bottom:1.25rem">
      <h3>Results by task</h3>
      <p class="sub">Success rates and winner per task across all personas</p>
      <table>
        <thead>
          <tr>
            <th>Task</th>
            <th>Retell</th>
            <th>Bland</th>
            <th>Vapi</th>
            <th>Winner</th>
          </tr>
        </thead>
        <tbody>${taskRows}</tbody>
      </table>
    </div>

    <div class="insight-cards">
      <div class="insight-card strengths">
        <h3>✓ Retell AI Strengths</h3>
        <ul>${retellStrengths || "<li>—</li>"}</ul>
      </div>
      <div class="insight-card weaknesses">
        <h3>✗ Retell AI Weaknesses</h3>
        <ul>${retellWeaknesses || "<li>—</li>"}</ul>
      </div>
    </div>

    <div class="insight-cards">
      <div class="insight-card strengths">
        <h3>✓ Bland AI Strengths</h3>
        <ul>${blandStrengths || "<li>—</li>"}</ul>
      </div>
      <div class="insight-card weaknesses">
        <h3>✗ Bland AI Weaknesses</h3>
        <ul>${blandWeaknesses || "<li>—</li>"}</ul>
      </div>
    </div>

    <div class="insight-cards">
      <div class="insight-card strengths">
        <h3>✓ Vapi Strengths</h3>
        <ul>${vapiStrengths || "<li>—</li>"}</ul>
      </div>
      <div class="insight-card weaknesses">
        <h3>✗ Vapi Weaknesses</h3>
        <ul>${vapiWeaknesses || "<li>—</li>"}</ul>
      </div>
    </div>
  `;
}

function stepsWithScreenshots(trace) {
  return (trace || []).filter(s => s.screenshot_url);
}

function renderStepViewer(r) {
  const platform = r.product;
  const shots = stepsWithScreenshots(r.trace || []);
  if (!shots.length) {
    return `<div class="step-viewer step-viewer-empty">
      <div style="color:#888;text-align:center">No screenshots available.<br/>Final URL: ${escapeHtml(r.final_url || "—")}</div>
    </div>`;
  }

  let idx = _activeIdx[platform] ?? 0;
  if (idx < 0 || idx >= shots.length) idx = 0;
  _activeIdx[platform] = idx;
  const step = shots[idx];

  return `<div class="step-viewer" data-platform="${escapeHtml(platform)}">
    <div class="step-nav">
      <button type="button" class="step-arrow" data-platform="${escapeHtml(platform)}" data-dir="-1"${idx <= 0 ? " disabled" : ""}>←</button>
      <div class="step-nums">
        ${shots.map((s, i) => `
          <button type="button" class="step-num${i === idx ? " active" : ""}" data-platform="${escapeHtml(platform)}" data-idx="${i}">${s.step}</button>
        `).join("")}
      </div>
      <button type="button" class="step-arrow" data-platform="${escapeHtml(platform)}" data-dir="1"${idx >= shots.length - 1 ? " disabled" : ""}>→</button>
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

function renderColumn(r, isWinner) {
  const platLabel = PLAT_LABEL[r.product] || r.product;
  let statusClass = "status-error";
  let statusText = "FAIL";
  if (r.success) {
    statusClass = "status-complete";
    statusText = "SUCCESS";
  } else if (r.harness_timeout) {
    statusClass = "status-timeout";
    statusText = "TIMEOUT";
  }

  return `
  <article class="platform-card${isWinner ? " winner" : ""}" data-platform="${escapeHtml(r.product)}">
    <div class="col-header">
      <h3>
        ${escapeHtml(platLabel)}
        ${isWinner ? '<span class="tag">winner</span>' : ""}
      </h3>
      <span class="tag ${statusClass}">${statusText}</span>
      <span class="tag">${r.num_steps || "?"} steps</span>
    </div>
    ${renderStepViewer(r)}
  </article>`;
}

function goStep(platform, idx) {
  const r = (_study?.agent_results || []).find(x => 
    x.task_id === _currentTask && x.product === platform && x.persona_id === personaSelect.value
  );
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
  const r = (_study.agent_results || []).find(x => 
    x.task_id === _currentTask && x.product === platform && x.persona_id === personaSelect.value
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
  root.querySelectorAll(".step-num").forEach(el => {
    el.addEventListener("click", () => {
      const plat = el.dataset.platform;
      const idx = Number(el.dataset.idx);
      if (plat && !Number.isNaN(idx)) goStep(plat, idx);
    });
  });
  root.querySelectorAll(".step-arrow:not([disabled])").forEach(el => {
    el.addEventListener("click", () => {
      const plat = el.dataset.platform;
      const dir = Number(el.dataset.dir);
      if (plat && dir) nudgeStep(plat, dir);
    });
  });
}

function renderTask(taskId) {
  _currentTask = taskId;
  const personaId = personaSelect.value;
  
  const byPlatform = {};
  for (const p of PLATFORMS) {
    byPlatform[p] = (_study.agent_results || []).find(r => 
      r.task_id === taskId && r.product === p && r.persona_id === personaId
    );
  }

  const sample = byPlatform.retell || byPlatform.bland || byPlatform.vapi;
  taskPrompt.textContent = sample?.task_prompt || sample?.task_title || "";

  let winner = null;
  const successPlatforms = PLATFORMS.filter(p => byPlatform[p]?.success);
  if (successPlatforms.length === 1) {
    winner = successPlatforms[0];
  } else if (successPlatforms.length > 1) {
    const minSteps = Math.min(...successPlatforms.map(p => byPlatform[p].num_steps || 999));
    winner = successPlatforms.find(p => (byPlatform[p].num_steps || 999) === minSteps);
  }

  platformGrid.innerHTML = PLATFORMS.map(plat => {
    const r = byPlatform[plat];
    if (!r) {
      return `<article class="platform-card"><div class="col-header"><h3>${escapeHtml(PLAT_LABEL[plat])}</h3></div><p style="color:#888;padding:1rem">No run for this combination.</p></article>`;
    }
    return renderColumn(r, winner === plat);
  }).join("");
  wireStepControls();
}

function populateTaskSelect(personaId) {
  const tasks = (_study.agent_results || [])
    .filter(r => r.persona_id === personaId)
    .map(r => ({ id: r.task_id, title: r.task_title }));

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
    PLATFORMS.forEach(p => { _activeIdx[p] = 0; });
    renderTask(uniqueTasks[0].id);
  }
}

function populateSelects() {
  const personas = _study.personas || [];
  const defaultPersonas = [...new Set((_study.agent_results || []).map(r => r.persona_id))];

  personaSelect.innerHTML = (personas.length ? personas : defaultPersonas.map(id => ({ id, name: id }))).map(p =>
    `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name || p.id)}</option>`
  ).join("");

  if (personaSelect.options.length) {
    populateTaskSelect(personaSelect.value);
  }
}

personaSelect.addEventListener("change", () => {
  populateTaskSelect(personaSelect.value);
});

taskSelect.addEventListener("change", () => {
  PLATFORMS.forEach(p => { _activeIdx[p] = 0; });
  renderTask(taskSelect.value);
});

let _dashboardData = null;

async function loadDashboardData() {
  try {
    const res = await fetch("/api/experiment/voice-dashboard");
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error("Dashboard data not available:", err);
    return null;
  }
}

function renderDashboardSection(data) {
  const section = document.getElementById("dashboard-section");
  const content = document.getElementById("dashboard-content");
  
  if (!data || !data.runs || data.runs.length === 0) {
    section.style.display = "none";
    return;
  }
  
  section.style.display = "block";
  _dashboardData = data;
  
  const signup = data.signup_outcomes || {};
  const byPlatform = {};
  
  for (const r of data.runs) {
    const plat = r.website || "unknown";
    if (!byPlatform[plat]) {
      byPlatform[plat] = { success: 0, product: 0, harness: 0, total: 0, hadAuth: false };
    }
    byPlatform[plat].total++;
    if (r.had_auth) byPlatform[plat].hadAuth = true;
    
    if (r.success) {
      byPlatform[plat].success++;
    } else if (r.failure_category === "PRODUCT") {
      byPlatform[plat].product++;
    } else {
      byPlatform[plat].harness++;
    }
  }
  
  const signupRows = PLATFORMS.map(p => {
    const info = signup[p] || {};
    const ok = info.ok;
    const reason = info.reason || "";
    const friction = info.captcha_friction ? "reCAPTCHA" : info.phone_required ? "Phone required" : "";
    
    let statusHtml;
    if (ok) {
      statusHtml = '<span class="pill success">Signed up</span>';
    } else if (reason === "captcha_unsolved") {
      statusHtml = '<span class="pill timeout">Blocked: reCAPTCHA</span>';
    } else if (reason === "phone_required") {
      statusHtml = '<span class="pill timeout">Blocked: Phone required</span>';
    } else {
      statusHtml = '<span class="pill fail">Blocked</span>';
    }
    
    return `<tr>
      <td>${escapeHtml(PLAT_LABEL[p] || p)}</td>
      <td>${statusHtml}</td>
      <td>${friction ? escapeHtml(friction) : "—"}</td>
    </tr>`;
  }).join("");
  
  const taskRows = PLATFORMS.map(p => {
    const stats = byPlatform[p] || { success: 0, product: 0, harness: 0, total: 0, hadAuth: false };
    
    if (!stats.hadAuth && stats.total > 0) {
      return `<tr>
        <td>${escapeHtml(PLAT_LABEL[p] || p)}</td>
        <td colspan="3" style="color:var(--text-muted);font-style:italic">Not reached: signup blocked</td>
      </tr>`;
    }
    
    return `<tr>
      <td>${escapeHtml(PLAT_LABEL[p] || p)}</td>
      <td><strong>${stats.success}/${stats.total}</strong></td>
      <td>${stats.product}</td>
      <td>${stats.harness}</td>
    </tr>`;
  }).join("");
  
  content.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:0.75rem">
      <div class="chart-card" style="margin:0">
        <h3>Signup Outcomes</h3>
        <p class="sub">Can users create accounts?</p>
        <table>
          <thead><tr><th>Platform</th><th>Status</th><th>Friction</th></tr></thead>
          <tbody>${signupRows}</tbody>
        </table>
      </div>
      <div class="chart-card" style="margin:0">
        <h3>Dashboard Tasks</h3>
        <p class="sub">Logged-in product exploration</p>
        <table>
          <thead><tr><th>Platform</th><th>Success</th><th>Product Fail</th><th>No Auth</th></tr></thead>
          <tbody>${taskRows}</tbody>
        </table>
      </div>
    </div>
    <p class="sub" style="margin-top:0.75rem">
      <strong>Key findings:</strong> Vapi signup succeeded; 11/15 dashboard tasks passed. 
      Retell blocked by reCAPTCHA, Bland requires phone verification. 
      Retell/Bland dashboard failures are "no auth" (not product issues).
    </p>
  `;
}

async function loadStudy() {
  try {
    const [publicRes, dashboardData] = await Promise.all([
      fetch("/api/experiment/voice-bakeoff"),
      loadDashboardData()
    ]);
    
    if (!publicRes.ok) throw new Error(`HTTP ${publicRes.status}`);
    _study = await publicRes.json();

    renderAnalytics(_study);
    populateSelects();
    
    if (dashboardData) {
      renderDashboardSection(dashboardData);
    }
  } catch (err) {
    analyticsRoot.innerHTML = `<p class="error-msg">Failed to load study: ${escapeHtml(err.message)}</p>`;
    statusContent.innerHTML = `<p class="error-msg">Failed to load study</p>`;
    console.error(err);
  }
}

loadStudy();
