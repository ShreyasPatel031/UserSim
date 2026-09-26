/** Generic study report in the /blandai layout. Data is one study payload. */

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const HARNESS_NOTE = /wrong site|wrong website|captcha|turnstile|hcaptcha|recaptcha|timed?\s*out|\btimeout\b|about:blank|infrastructure error|browser session ended/i;

let _study = null;
let _insights = null;
let _sites = [];
let _currentPersona = "";
let _currentGoal = "";
const _activeIdx = {};
let _pollTimer = null;

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => selectTab(btn.dataset.tab));
});

function selectTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.hidden = p.id !== `tab-${name}`;
  });
}

function siteOf(key) {
  return _sites.find((s) => s.site_key === key) || { site_key: key, site_label: key, css: "site-0" };
}

function runs() {
  return (_study?.agent_results || []).filter((r) => r && typeof r === "object");
}

function issueFor(agentId) {
  return (_insights?.run_issues || []).find((row) => row.agent_id === agentId) || null;
}

function shotsOf(run) {
  return (run?.trace || []).filter((s) => s && s.screenshot_url && Number.isFinite(Number(s.step)));
}

function productNotes(list) {
  return (list || []).map((x) => String(x || "").trim()).filter((x) => x && !HARNESS_NOTE.test(x));
}

function legend() {
  if (!_sites.length) return "";
  return `<div class="legend">${_sites
    .map((s) => `<span class="${escapeHtml(s.css)}">${escapeHtml(s.site_label)}</span>`)
    .join("")}</div>`;
}

function barRows(valueOf, format, fixedMax) {
  if (!_sites.length) {
    return `<p class="empty-claim">No included runs yet.</p>`;
  }
  const vals = _sites.map((s) => Number(valueOf(s)) || 0);
  const max = fixedMax || Math.max(1, ...vals);
  return _sites
    .map((s) => {
      const raw = valueOf(s);
      const missing = raw == null || raw === "";
      const v = missing ? 0 : Number(raw);
      const pct = missing ? 0 : Math.max(0, Math.min(100, (v / max) * 100));
      return `<div class="bar-row">
        <span class="bar-label">${escapeHtml(s.site_label)}</span>
        <div class="bar-track"><div class="bar-fill ${escapeHtml(s.css)}" style="width:${pct}%"></div></div>
        <span class="bar-val">${missing ? "—" : format(raw, s)}</span>
      </div>`;
    })
    .join("");
}

function pill(key) {
  if (!key) return `<span class="pill mixed">mixed</span>`;
  const site = siteOf(key);
  return `<span class="pill ${escapeHtml(site.css)}">${escapeHtml(site.site_label)}</span>`;
}

function claimCards(claims, kind) {
  if (!claims?.length) {
    const word = kind === "strength" ? "strength" : "weakness";
    return `<p class="empty-claim">None. The traces do not support a specific ${word}.</p>`;
  }
  return claims
    .map((claim) => {
      const cites = (claim.evidence || [])
        .map((ev) => {
          const shot = ev.screenshot_url
            ? `<a class="shot" href="${escapeHtml(ev.screenshot_url)}" target="_blank" rel="noopener" data-agent="${escapeHtml(ev.agent_id)}" data-step="${Number(ev.step)}"><img src="${escapeHtml(ev.screenshot_url)}" alt="Step ${Number(ev.step)} screenshot" /></a>`
            : "";
          return `<div class="cite">
            ${shot}
            <div>
              <p class="who">${escapeHtml(ev.persona_name || "Agent")} · ${escapeHtml(ev.task_title || "")}</p>
              <p class="detail">${escapeHtml(ev.detail || ev.action || "")}</p>
              <p class="links">
                <button type="button" data-agent="${escapeHtml(ev.agent_id)}" data-step="${Number(ev.step)}">Open trace · step ${Number(ev.step)}</button>
              </p>
            </div>
          </div>`;
        })
        .join("");
      return `<article class="claim-card ${kind}"><p>${escapeHtml(claim.claim)}</p>${cites}</article>`;
    })
    .join("");
}

// Step labels a reader understands: no drag coordinates, no DOM ids
// (same rules as report_insights.human_action).
function humanAction(action) {
  const text = String(action || "").split(/\s+/).join(" ").trim();
  if (/^drag\b/i.test(text)) return "drag on the canvas";
  const m = text.match(/^(click|type .* into) ([a-z0-9]+(?:[-_][a-z0-9]+)+)$/);
  if (m) {
    const words = m[2].split(/[-_]/);
    while (words.length > 1 && ["trigger", "button", "btn", "icon", "toggle"].includes(words[words.length - 1])) words.pop();
    return `${m[1]} ${words.join(" ")}`;
  }
  return text;
}

function renderAnalytics() {
  const root = document.getElementById("analytics-root");
  const insights = _insights || {};
  const sites = _sites;
  const taskRows = (insights.by_task || [])
    .map((task) => {
      const bars = sites
        .map((s) => {
          const cell = task.sites?.[s.site_key] || { n: 0, ok: 0 };
          const pct = cell.n ? Math.round((100 * cell.ok) / cell.n) : 0;
          const steps = cell.median_all_steps != null ? cell.median_all_steps : cell.median_steps;
          const time = cell.median_time_s;
          const extra = [
            steps != null ? `${Number(steps).toFixed(0)} step${Number(steps).toFixed(0) === "1" ? "" : "s"}` : "",
            time != null ? `${Number(time).toFixed(0)}s` : "",
          ]
            .filter(Boolean)
            .join(" · ");
          return `<div class="bar-stack">
            <div class="bar-row">
              <span class="bar-label">${escapeHtml(s.site_label)}</span>
              <div class="bar-track"><div class="bar-fill ${escapeHtml(s.css)}" style="width:${pct}%"></div></div>
              <span class="bar-val">${cell.ok}/${cell.n}${extra ? ` · ${extra}` : ""}</span>
            </div>
          </div>`;
        })
        .join("");
      return `<tr>
        <td><strong>${escapeHtml(task.title || task.task_id)}</strong></td>
        <td>${bars}</td>
      </tr>`;
    })
    .join("");

  const personaBlocks = (insights.by_persona || [])
    .map((persona) => {
      const goalRows = (persona.goals || [])
        .map((g) => {
          const cells = sites
            .map((s) => {
              const ok = g.success?.[s.site_key];
              return `<td>${ok ? "✓" : ok === false ? "✗" : "—"}</td>`;
            })
            .join("");
          return `<tr class="goal-row" data-persona="${escapeHtml(persona.persona_id)}" data-goal="${escapeHtml(g.task_id)}">
            <td>${escapeHtml(g.title || g.task_id)}</td>
            ${cells}
            <td>${g.pick ? pill(g.pick) : `<span class="pill mixed">no single pick</span>`}</td>
          </tr>`;
        })
        .join("");
      const head = sites.map((s) => `<th>${escapeHtml(s.site_label)}</th>`).join("");
      const pref = sites.map((s) => `${escapeHtml(s.site_label)} ${persona.completed?.[s.site_key] || 0}`).join(" · ");
      return `<div class="persona-block" id="persona-${escapeHtml(persona.persona_id)}">
        <div class="persona-header">
          <span class="persona-summary-title">${escapeHtml(persona.persona_name)} ${persona.top_site ? pill(persona.top_site) : ""}</span>
          <span class="persona-summary-meta">${pref}</span>
        </div>
        <div class="persona-body">
          ${persona.bio ? `<p class="bio">${escapeHtml(persona.bio)}</p>` : ""}
          <details class="persona-goals" open>
            <summary>Goal breakdown (${(persona.goals || []).length})</summary>
            <table>
              <thead><tr><th>Goal</th>${head}<th>Pick</th></tr></thead>
              <tbody>${goalRows}</tbody>
            </table>
          </details>
        </div>
      </div>`;
    })
    .join("");

  const issues = insights.run_issues || [];
  const issueHtml = issues.length
    ? `<div class="chart-card">
        <h3>Run issues</h3>
        <p class="sub">Navigation, captcha, timeout, and infrastructure failures. These are not product friction.</p>
        ${issues
          .map((issue) => {
            const shot = issue.screenshot_url
              ? `<a href="${escapeHtml(issue.screenshot_url)}" target="_blank" rel="noopener">screenshot</a>`
              : "";
            const open = issue.agent_id
              ? `<button type="button" data-agent="${escapeHtml(issue.agent_id)}" data-step="${Number(issue.step || 0)}">Open trace</button>`
              : "";
            return `<div class="issue-row">
              <strong>${escapeHtml(issue.kind || "run issue")}</strong>
              · ${escapeHtml(issue.persona_name || "Agent")} · ${escapeHtml(issue.task_title || "")}
              <div>${escapeHtml(issue.reason || "")} ${open} ${shot}</div>
            </div>`;
          })
          .join("")}
      </div>`
    : "";

  const matrix = insights.n_personas && insights.n_tasks && insights.n_sites
    ? `${insights.n_personas} personas × ${insights.n_tasks} tasks × ${insights.n_sites} sites`
    : "";

  root.innerHTML = `
    <div class="stat-strip">
      <span><strong>${insights.n_runs ?? 0}</strong> included runs</span>
      <span><strong>${insights.n_goals ?? 0}</strong> head-to-head goals</span>
      ${matrix ? `<span>${escapeHtml(matrix)}</span>` : ""}
      ${issues.length ? `<span><strong>${issues.length}</strong> run issues excluded</span>` : ""}
    </div>
    ${insights.headline ? `<p class="headline-line">${escapeHtml(insights.headline)}</p>` : ""}
    <p class="metric-note">${escapeHtml(insights.metric_note || insights.evidence_note || "")}</p>
    <div class="analytics-grid">
      <div class="chart-card">
        <h3>Task completion</h3>
        <p class="sub">Included runs that finished the task, per site. 0% is a real rate, not a missing chart.</p>
        ${legend()}
        ${barRows(
          (s) => (s.n ? s.success_pct : null),
          (v, s) => (s && s.n ? `${s.ok ?? 0}/${s.n} · ${v}%` : "—"),
          100
        )}
      </div>
      <div class="chart-card">
        <h3>Median steps</h3>
        <p class="sub">Steps on every included run, finished or not. Lower is a shorter trace.</p>
        ${legend()}
        ${barRows(
          (s) => s.median_steps,
          (v) => (v == null ? "—" : Number(v).toFixed(0))
        )}
      </div>
      <div class="chart-card">
        <h3>Median time</h3>
        <p class="sub">Seconds from agent start to agent done, per site.</p>
        ${legend()}
        ${barRows(
          (s) => s.median_time_s,
          (v) => (v == null ? "—" : `${Number(v).toFixed(0)}s`)
        )}
      </div>
    </div>
    ${verdictHtml(insights)}
    <div class="chart-card">
      <h3>What the traces support</h3>
      <p class="sub">Each claim cites a real agent step and screenshot. Open the trace to see that step.</p>
      <div class="split">
        <div><h3>Strengths</h3>${claimCards(insights.strengths, "strength")}</div>
        <div><h3>Weaknesses</h3>${claimCards(insights.weaknesses, "weakness")}</div>
      </div>
    </div>
    ${issueHtml}
    <div class="chart-card">
      <h3>By task</h3>
      <p class="sub">Completed runs / included runs on each site</p>
      <div style="overflow-x:auto">
        <table>
          <thead><tr><th>Task</th><th>Completion</th></tr></thead>
          <tbody>${taskRows || `<tr><td colspan="2">No included runs.</td></tr>`}</tbody>
        </table>
      </div>
    </div>
    <div class="chart-card">
      <h3>By persona → goals</h3>
      <p class="sub">Click a goal row to open the trace drill-down</p>
      ${personaBlocks || `<p class="empty-claim">No persona breakdown — the included traces do not cover a goal.</p>`}
    </div>
  `;

  root.querySelectorAll("button[data-agent]").forEach((node) => {
    node.addEventListener("click", () => {
      openTrace(node.dataset.agent, Number(node.dataset.step));
    });
  });
  root.querySelectorAll(".goal-row").forEach((row) => {
    row.addEventListener("click", () => openGoal(row.dataset.persona, row.dataset.goal));
  });
}

function thoughtHtml(step) {
  const detail = step.thought_detail || {};
  const order = ["next_goal", "evaluation_previous_goal", "thinking", "memory"];
  const labels = {
    next_goal: "Next goal",
    evaluation_previous_goal: "Previous step",
    thinking: "Reasoning",
    memory: "Memory",
  };
  const entries = order.filter((k) => detail[k]);
  if (!entries.length && step.thought) {
    return `<details class="thought-details"><summary>Reasoning</summary><pre class="thought-text">${escapeHtml(step.thought)}</pre></details>`;
  }
  if (!entries.length) return "";
  const body = entries
    .map(
      (key) => `<div><strong>${escapeHtml(labels[key] || key)}</strong><pre class="thought-text">${escapeHtml(detail[key])}</pre></div>`
    )
    .join("");
  return `<details class="thought-details"><summary>Reasoning</summary>${body}</details>`;
}

function renderStepViewer(run) {
  const key = run.site_key || "product";
  const shots = shotsOf(run);
  if (!shots.length) {
    const finalUrl = run.final_url
      ? `<a href="${escapeHtml(run.final_url)}" target="_blank" rel="noopener">${escapeHtml(run.final_url)}</a>`
      : "—";
    return `<div class="step-viewer step-viewer-empty"><div class="screenshot-missing">No step screenshots yet.<br/>Final URL: ${finalUrl}</div></div>`;
  }
  let idx = _activeIdx[run.agent_id] ?? 0;
  if (idx < 0 || idx >= shots.length) idx = 0;
  _activeIdx[run.agent_id] = idx;
  const step = shots[idx];
  return `<div class="step-viewer" data-agent="${escapeHtml(run.agent_id)}">
    <div class="step-nav">
      <button type="button" class="step-arrow" data-agent="${escapeHtml(run.agent_id)}" data-dir="-1"${idx <= 0 ? " disabled" : ""} aria-label="Previous step">←</button>
      <div class="step-nums">
        ${shots
          .map(
            (s, i) =>
              `<button type="button" class="step-num${i === idx ? " active" : ""}" data-agent="${escapeHtml(run.agent_id)}" data-idx="${i}">${escapeHtml(s.step)}</button>`
          )
          .join("")}
      </div>
      <button type="button" class="step-arrow" data-agent="${escapeHtml(run.agent_id)}" data-dir="1"${idx >= shots.length - 1 ? " disabled" : ""} aria-label="Next step">→</button>
    </div>
    <figure class="step-shot">
      <a href="${escapeHtml(step.screenshot_url)}" target="_blank" rel="noopener">
        <img class="trace-screenshot" src="${escapeHtml(step.screenshot_url)}" alt="Step ${escapeHtml(step.step)}" />
      </a>
    </figure>
    <div class="step-detail">
      <p class="step-action"><strong>${escapeHtml(step.step)}.</strong> ${escapeHtml(humanAction(step.action) || "Action")}</p>
      ${step.url ? `<p class="step-meta"><span>URL</span> <a href="${escapeHtml(step.url)}" target="_blank" rel="noopener">${escapeHtml(step.url)}</a></p>` : ""}
      ${thoughtHtml(step)}
    </div>
    <p class="step-caption">${idx + 1} / ${shots.length} · <a href="${escapeHtml(step.screenshot_url)}" target="_blank" rel="noopener">open screenshot</a></p>
  </div>`;
}

function renderColumn(run, isWinner) {
  const site = siteOf(run.site_key || "product");
  const issue = issueFor(run.agent_id);
  const likes = productNotes(run.what_was_easy).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  const dislikes = productNotes(run.friction_points).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  const status = issue
    ? `<span class="tag status-issue">RUN ISSUE</span>`
    : `<span class="tag status-${run.completed || run.would_convert === "yes" ? "complete" : "error"}">${issue ? "RUN ISSUE" : "TRACE"}</span>`;
  return `<article class="platform-card${isWinner ? " winner" : ""}" data-agent="${escapeHtml(run.agent_id)}" data-site="${escapeHtml(site.site_key)}">
    <div class="col-header">
      <h3>${escapeHtml(site.site_label)} ${isWinner ? '<span class="tag">pick</span>' : ""}</h3>
      ${status}
    </div>
    ${issue ? `<p class="run-issue-flag">${escapeHtml(issue.reason || "Run issue — excluded from product insights.")}</p>` : ""}
    ${renderStepViewer(run)}
    <details class="feedback-details">
      <summary>Likes / dislikes</summary>
      ${likes ? `<div><strong>Liked</strong><ul>${likes}</ul></div>` : ""}
      ${dislikes ? `<div><strong>Disliked</strong><ul>${dislikes}</ul></div>` : ""}
      ${!likes && !dislikes ? `<p class="trace-empty">No product feedback in this trace.</p>` : ""}
    </details>
  </article>`;
}

function goalMeta(personaId, taskId) {
  const persona = (_insights?.by_persona || []).find((p) => p.persona_id === personaId);
  return (persona?.goals || []).find((g) => g.task_id === taskId) || null;
}

function taskKeyOf(run) {
  const title = String(run.task_title || "")
    .replace(/\s*\(vs\s+https?:\/\/[^)]+\)\s*$/i, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  if (title) return title.slice(0, 120);
  return String(run.task_id || "task").split("__")[0];
}

function runsFor(personaId, taskId) {
  return runs().filter((r) => {
    const pk = String(r.persona_id || r.persona_name || "persona");
    return pk === personaId && taskKeyOf(r) === taskId;
  });
}

function renderGoal(personaId, taskId) {
  _currentPersona = personaId;
  _currentGoal = taskId;
  const grid = document.getElementById("platform-grid");
  const banner = document.getElementById("compare-banner");
  const prompt = document.getElementById("goal-prompt");
  const matched = runsFor(personaId, taskId);
  const meta = goalMeta(personaId, taskId);
  const sample = matched[0];
  prompt.textContent = meta?.prompt || sample?.task_prompt || "";
  if (meta?.pick_reason) {
    banner.hidden = false;
    const who = meta.pick ? `Pick: ${siteOf(meta.pick).site_label}. ` : "";
    banner.textContent = `${who}${meta.pick_reason}`;
  } else if (!matched.length) {
    banner.hidden = false;
    banner.textContent = "No runs for this persona and task.";
  } else {
    banner.hidden = true;
  }
  const order = _sites.map((s) => s.site_key);
  const ordered = [...matched].sort((a, b) => {
    const ia = order.indexOf(a.site_key || "product");
    const ib = order.indexOf(b.site_key || "product");
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  grid.style.gridTemplateColumns = ordered.length <= 1 ? "1fr" : ordered.length === 2 ? "1fr 1fr" : "repeat(3, minmax(0, 1fr))";
  if (!ordered.length) {
    grid.innerHTML = `<p class="trace-empty">No traces for this goal.</p>`;
    return;
  }
  grid.innerHTML = ordered.map((run) => renderColumn(run, meta?.pick && meta.pick === (run.site_key || "product"))).join("");
  wireStepControls(grid);
}

function wireStepControls(root) {
  root.querySelectorAll(".step-num").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = Number(el.dataset.idx);
      if (!Number.isNaN(idx)) goStep(el.dataset.agent, idx);
    });
  });
  root.querySelectorAll(".step-arrow:not([disabled])").forEach((el) => {
    el.addEventListener("click", () => {
      const dir = Number(el.dataset.dir);
      const run = runs().find((r) => r.agent_id === el.dataset.agent);
      const current = _activeIdx[el.dataset.agent] ?? 0;
      if (dir) goStep(el.dataset.agent, current + dir);
      else if (run) goStep(el.dataset.agent, current);
    });
  });
}

function goStep(agentId, idx) {
  const run = runs().find((r) => r.agent_id === agentId);
  if (!run) return;
  const shots = shotsOf(run);
  if (!shots.length) return;
  _activeIdx[agentId] = Math.max(0, Math.min(shots.length - 1, idx));
  const card = document.querySelector(`.platform-card[data-agent="${CSS.escape(agentId)}"]`);
  if (!card) return;
  const viewer = card.querySelector(".step-viewer");
  if (!viewer) return;
  const tmp = document.createElement("div");
  tmp.innerHTML = renderStepViewer(run);
  viewer.replaceWith(tmp.firstElementChild);
  wireStepControls(card);
}

function fillSelectors() {
  const personaSelect = document.getElementById("persona-select");
  const goalSelect = document.getElementById("goal-select");
  const personas = _insights?.by_persona || [];
  const seen = new Set();
  const options = [];
  for (const persona of personas) {
    options.push(persona);
    seen.add(persona.persona_id);
  }
  for (const run of runs()) {
    const id = String(run.persona_id || run.persona_name || "persona");
    if (seen.has(id)) continue;
    seen.add(id);
    options.push({ persona_id: id, persona_name: run.persona_name || id, goals: [] });
  }
  personaSelect.innerHTML = options
    .map((p) => `<option value="${escapeHtml(p.persona_id)}">${escapeHtml(p.persona_name)}</option>`)
    .join("");
  const personaId = options[0]?.persona_id || "";
  if (personaId) fillGoals(personaId);
  else goalSelect.innerHTML = "";
}

function fillGoals(personaId, preferTask) {
  const goalSelect = document.getElementById("goal-select");
  const persona = (_insights?.by_persona || []).find((p) => p.persona_id === personaId);
  const map = new Map();
  for (const goal of persona?.goals || []) map.set(goal.task_id, goal);
  for (const run of runs()) {
    if (String(run.persona_id || run.persona_name || "persona") !== personaId) continue;
    const id = taskKeyOf(run);
    if (!map.has(id)) map.set(id, { task_id: id, title: run.task_title || id });
  }
  const goals = [...map.values()];
  goalSelect.innerHTML = goals
    .map((g) => `<option value="${escapeHtml(g.task_id)}">${escapeHtml(g.title || g.task_id)}</option>`)
    .join("");
  const chosen = goals.find((g) => g.task_id === preferTask) || goals[0];
  if (chosen) renderGoal(personaId, chosen.task_id);
}

function openGoal(personaId, taskId) {
  selectTab("traces");
  const personaSelect = document.getElementById("persona-select");
  if ([...personaSelect.options].some((o) => o.value === personaId)) {
    personaSelect.value = personaId;
    fillGoals(personaId, taskId);
  }
}

function openTrace(agentId, step) {
  const run = runs().find((r) => r.agent_id === agentId);
  if (!run) return;
  const shots = shotsOf(run);
  const idx = shots.findIndex((s) => Number(s.step) === Number(step));
  _activeIdx[agentId] = idx >= 0 ? idx : 0;
  const personaId = String(run.persona_id || run.persona_name || "persona");
  const taskId = taskKeyOf(run);
  openGoal(personaId, taskId);
  goStep(agentId, _activeIdx[agentId]);
  const card = document.querySelector(`.platform-card[data-agent="${CSS.escape(agentId)}"]`);
  card?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showReport(data) {
  _study = data;
  _insights = data?.summary?.insights || null;
  const name = _insights?.product_name || "Study";
  document.title = `UserSim — ${name} study`;
  document.getElementById("product-badge").textContent = name;
  document.getElementById("report-title").innerHTML = `${escapeHtml(name)} study<br /><em>analytics + traces</em>`;
  const lede = document.getElementById("report-lede");
  if (!_insights) {
    const status = data?.status || "unknown";
    const waiting =
      status === "complete"
        ? "This study finished without per-run traces. The charts below stay in the report."
        : `This study is ${status}. Charts fill as runs land.`;
    _insights = {
      product_name: name,
      headline: waiting,
      lede: waiting,
      metric_note: `${waiting} Open the live view if a run is still going.`,
      sites: [],
      by_task: [],
      by_persona: [],
      strengths: [],
      weaknesses: [],
      run_issues: [],
      n_runs: 0,
    };
  }
  _sites = _insights.sites || [];
  lede.textContent = _insights.lede || _insights.headline || "";
  renderAnalytics();
  fillSelectors();
}

document.getElementById("persona-select").addEventListener("change", (event) => {
  fillGoals(event.target.value);
});
document.getElementById("goal-select").addEventListener("change", (event) => {
  const personaId = document.getElementById("persona-select").value;
  _sites.forEach(() => {});
  renderGoal(personaId, event.target.value);
});

document.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  const card = document.activeElement?.closest?.(".platform-card[data-agent]");
  const agentId = card?.dataset?.agent;
  if (!agentId) return;
  event.preventDefault();
  const current = _activeIdx[agentId] ?? 0;
  goStep(agentId, current + (event.key === "ArrowRight" ? 1 : -1));
});

async function loadReport() {
  const params = new URLSearchParams(location.search);
  const studyId = params.get("study") || "";
  const lede = document.getElementById("report-lede");
  const root = document.getElementById("analytics-root");
  if (!studyId) {
    lede.textContent = "No study selected. Run a simulation, then open its report.";
    root.innerHTML = `<p class="section-sub"><a href="/">Run a simulation</a></p>`;
    return;
  }
  try {
    const res = await fetch(`/api/studies/${encodeURIComponent(studyId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    showReport(data);
    if (data.status && data.status !== "complete" && data.status !== "error" && data.status !== "abandoned") {
      if (_pollTimer) clearTimeout(_pollTimer);
      _pollTimer = setTimeout(loadReport, 4000);
    }
  } catch (err) {
    lede.textContent = `Couldn’t load study ${studyId}.`;
    root.innerHTML = `<p class="trace-empty">${escapeHtml(err.message || err)}</p>`;
  }
}

loadReport();

function verdictHtml(insights) {
  const v = (insights && insights.verdict) || {};
  const good = v.good_for || [];
  const trails = v.trails || [];
  const unfinished = v.unfinished || [];
  if (!good.length && !trails.length && !unfinished.length && !v.summary) return "";
  const list = (items, empty) =>
    items.length
      ? `<ul class="verdict-list">${items.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`
      : `<p class="sub">${escapeHtml(empty)}</p>`;
  return `<div class="chart-card verdict-card">
      <h3>Verdict</h3>
      <p class="sub">Per-task results against the competitors. Finished runs count first, then steps, then time.</p>
      ${v.summary ? `<p class="verdict-summary">${escapeHtml(v.summary)}</p>` : ""}
      ${signupLine(insights.signups)}
      <div class="split">
        <div><h3>Good for</h3>${list(good, "No task where it led or matched the competitors.")}</div>
        <div><h3>Trails competitors on</h3>${list(trails, "No task where a competitor did better.")}</div>
      </div>
      ${unfinished.length ? `<div><h3>No site finished</h3>${list(unfinished, "")}</div>` : ""}
    </div>`;
}

function signupLine(signups) {
  const sites = (signups && signups.sites) || [];
  if (!sites.length) return "";
  const bits = sites.map((r) => {
    const why = Object.entries(r.reasons || {}).map(([k, n]) => `${k} ×${n}`).join(", ");
    return `${escapeHtml(r.site)}: ${r.ok}/${r.tried} signed up live` +
      (r.median_s != null ? ` (median ${Math.round(r.median_s)}s)` : "") +
      (why ? ` (UserSim could not finish: ${escapeHtml(why)})` : "");
  });
  return `<p class="sub"><strong>Account walls:</strong> agents created real accounts mid-task when a step needed one. ${bits.join(" · ")}</p>`;
}
