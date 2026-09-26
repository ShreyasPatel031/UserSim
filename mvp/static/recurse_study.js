let D = null;
const SITES = ["product", "competitor_1", "competitor_2", "competitor_3"];
const idx = {};                      // per-site active step index
let curPersona = null, curGoal = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pctOf = (n, d) => (d ? Math.round((n / d) * 100) : 0);

function bar(s) {
  const t = (s.yes || 0) + (s.maybe || 0) + (s.no || 0) || 1;
  return `<div class="bar" title="yes ${s.yes} · maybe ${s.maybe} · no ${s.no}">
    <span style="width:${((s.yes || 0) / t) * 100}%;background:#0f7a4c"></span>
    <span style="width:${((s.maybe || 0) / t) * 100}%;background:#b4530a"></span>
    <span style="width:${((s.no || 0) / t) * 100}%;background:#b02a2a"></span></div>`;
}

function runFor(siteKey) {
  return D.rows.find((r) => r.site_key === siteKey && r.persona_id === curPersona && r.task === curGoal);
}

function stepViewer(siteKey, r) {
  if (!r) return `<div class="step-viewer step-viewer-empty"><div class="screenshot-missing">No agent ran this combination.</div></div>`;
  const shots = r.trace || [];
  if (!shots.length) {
    return `<div class="step-viewer step-viewer-empty"><div class="screenshot-missing">
      No step screenshots.<br/>Final URL: ${esc(r.final_url || "—")}</div></div>`;
  }
  let i = idx[siteKey] ?? 0;
  if (i < 0 || i >= shots.length) i = idx[siteKey] = 0;
  const s = shots[i];
  const nums = shots.map((x, n) =>
    `<button type="button" class="step-num${n === i ? " active" : ""}" data-site="${esc(siteKey)}" data-idx="${n}">${esc(x.step)}</button>`).join("");
  return `<div class="step-viewer">
    <div class="step-nav">
      <button type="button" class="step-arrow" data-site="${esc(siteKey)}" data-dir="-1"${i === 0 ? " disabled" : ""}>←</button>
      <div class="step-nums">${nums}</div>
      <button type="button" class="step-arrow" data-site="${esc(siteKey)}" data-dir="1"${i >= shots.length - 1 ? " disabled" : ""}>→</button>
    </div>
    <figure class="step-shot"><img class="trace-screenshot" loading="lazy" src="${esc(s.shot)}" alt="Step ${esc(s.step)}" /></figure>
    <div class="step-detail">
      <p class="step-action"><strong>${esc(s.step)}.</strong> ${esc(s.action || "—")}</p>
      ${s.url ? `<p class="step-meta"><span>URL</span> ${esc(s.url)}</p>` : ""}
      ${s.observation ? `<p class="step-meta"><span>Saw</span> ${esc(s.observation)}</p>` : ""}
      ${s.thought ? `<div class="thought-details"><p class="thought-text">${esc(s.thought)}</p></div>` : ""}
    </div></div>`;
}

function renderGrid() {
  document.getElementById("goal-prompt").innerHTML = curGoal
    ? `<strong>Task:</strong> ${esc(curGoal)}` : "";
  document.getElementById("platform-grid").innerHTML = SITES.map((k) => {
    const site = D.sites.find((x) => x.key === k) || {};
    const r = runFor(k);
    const v = r ? r.would_convert : "";
    return `<div class="platform-card${k === "product" ? " winner" : ""}">
      <div class="col-header">
        <h3>${esc(site.label)} ${v ? `<span class="pill ${esc(v)}">${esc(v)}</span>` : ""}</h3>
        <p class="section-sub" style="margin:0">
          ${r ? `${r.steps_n} steps${r.difficulty ? " · " + esc(r.difficulty) : ""}${r.completed ? "" : " · incomplete"}` : "—"}
          ${r && r.session ? ` · <a href="${esc(r.session)}" target="_blank" rel="noopener">replay ↗</a>` : ""}
        </p>
      </div>
      ${stepViewer(k, r)}
      ${r && r.quote ? `<p class="quote" style="margin:.5rem 0 0;font-size:.82rem">“${esc(r.quote)}”</p>` : ""}
      ${r && (r.friction || []).length ? `<div class="section-sub" style="margin-top:.4rem;font-size:.8rem"><strong>Friction:</strong>
        <ul class="tight">${r.friction.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : ""}
    </div>`;
  }).join("");

  document.querySelectorAll(".step-arrow").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.site, r = runFor(k); if (!r) return;
    const n = (r.trace || []).length;
    idx[k] = Math.min(Math.max((idx[k] ?? 0) + Number(b.dataset.dir), 0), n - 1);
    renderGrid();
  }));
  document.querySelectorAll(".step-num").forEach((b) => b.addEventListener("click", () => {
    idx[b.dataset.site] = Number(b.dataset.idx); renderGrid();
  }));
}

function renderAnalytics() {
  const s = D.summary || {};
  const li = (a) => (a || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>";
  const rows = D.sites.map((x) => `<tr>
      <td><strong>${esc(x.label)}</strong><div class="section-sub"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)}</a></div></td>
      <td>${x.runs}</td><td>${x.completed} <span class="section-sub">(${pctOf(x.completed, x.runs)}%)</span></td>
      <td>${bar(x)}<div class="section-sub">${x.yes} yes · ${x.maybe} maybe · ${x.no} no</div></td>
      <td>${x.steps}</td><td>${x.shots}</td></tr>`).join("");
  const recs = (s.recommendations || []).map((r) => {
    const p = String(r.priority || "low").toLowerCase();
    return `<div class="rec ${p}"><div><span class="pill ${p === "high" ? "no" : p === "medium" ? "maybe" : ""}">${esc(p)}</span>
      <strong>${esc(r.action)}</strong></div><div class="section-sub">${esc(r.rationale)}</div></div>`;
  }).join("");
  document.getElementById("analytics-root").innerHTML = `
    <div class="compare-banner"><strong>${esc(s.headline || "—")}</strong></div>
    <div class="metric-note">Segment fit <strong>${esc(s.segment_fit_score ?? "—")}/10</strong> — ${esc(s.segment_fit_rationale || "")}</div>
    <table class="ht"><thead><tr><th>Site</th><th>Runs</th><th>Completed</th><th>Would convert</th><th>Steps</th><th>Screenshots</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <div style="display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));margin:1.25rem 0">
      <div><h3 style="font-size:.95rem;margin:0 0 .3rem">Top friction</h3><ul class="tight">${li(s.top_friction)}</ul></div>
      <div><h3 style="font-size:.95rem;margin:0 0 .3rem">Top strengths</h3><ul class="tight">${li(s.top_strengths)}</ul></div>
    </div>
    <div class="metric-note"><strong>Conversion outlook.</strong> ${esc(s.conversion_outlook || "—")}</div>
    <h3 style="font-size:1rem;margin:0 0 .6rem">Recommendations</h3>${recs}`;
}

function renderSessions() {
  const rows = D.rows.map((r) => `<tr>
      <td><strong>${esc(r.persona_name || r.persona_id)}</strong><div class="section-sub">${esc(r.agent_id)}</div></td>
      <td>${esc(r.site)}</td><td>${esc(r.task)}</td>
      <td><span class="pill ${esc(r.would_convert)}">${esc(r.would_convert || "—")}</span></td>
      <td>${(r.trace || []).length} shots · ${r.steps_n} steps</td>
      <td>${r.quote ? `<span class="quote">“${esc(r.quote)}”</span>` : ""}</td></tr>`).join("");
  document.getElementById("sessions-root").innerHTML =
    `<table class="ht"><thead><tr><th>Agent</th><th>Site</th><th>Task</th><th>Verdict</th><th>Trace</th><th>Quote</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function boot() {
  const t = D.totals, s = D.summary || {};
  document.getElementById("hdr-badge").textContent = D.status || "study";
  document.getElementById("lede").textContent = s.headline || "";
  document.getElementById("stats").innerHTML = `
    <span><strong>${t.agents}</strong> agents</span>
    <span><strong>${D.personas.length}</strong> personas</span>
    <span><strong>${D.tasks.length}</strong> tasks</span>
    <span><strong>${D.sites.length}</strong> sites</span>
    <span><strong>${t.steps}</strong> steps</span>
    <span><strong>${t.shots}</strong> screenshots</span>`;
  document.getElementById("foot").innerHTML =
    `Study <code>${esc(D.study_id)}</code> · ${esc(D.updated_at || "")} · ${t.agents}/${t.planned} agents.
     Browserbase agents, gemini-2.5-flash-lite. <a href="/report?study=${esc(D.study_id)}">Raw report →</a>`;

  const ps = document.getElementById("persona-select");
  ps.innerHTML = D.personas.map((p) => `<option value="${esc(p.id)}">${esc(p.name || p.id)}</option>`).join("");
  const gs = document.getElementById("goal-select");
  gs.innerHTML = D.tasks.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  curPersona = D.personas[0] && D.personas[0].id;
  curGoal = D.tasks[0];
  const reset = () => { SITES.forEach((k) => (idx[k] = 0)); renderGrid(); };
  ps.addEventListener("change", () => { curPersona = ps.value; reset(); });
  gs.addEventListener("change", () => { curGoal = gs.value; reset(); });

  renderGrid(); renderAnalytics(); renderSessions();
  document.querySelectorAll(".tab-btn").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".tab-panel").forEach((p) => { p.hidden = p.dataset.panel !== b.dataset.tab; });
  }));
}

fetch("/static/recurse_study_data.json").then((r) => r.json()).then((d) => { D = d; boot(); })
  .catch((e) => { document.getElementById("lede").textContent = "Failed to load: " + e.message; });
