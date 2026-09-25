/** Report page — evidence-backed insights for a finished study. */

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

let _study = null;
let _traceAgent = null;
let _traceStep = 0;

function shotsOf(run) {
  return (run?.trace || []).filter((s) => s && s.screenshot_url);
}

function renderClaims(el, claims, kind) {
  if (!el) return;
  if (!claims?.length) {
    el.innerHTML = `<p class="empty-claim">None. The traces do not support a specific ${kind === "strength" ? "strength" : "weakness"}.</p>`;
    return;
  }
  el.innerHTML = claims
    .map((claim) => {
      const cites = (claim.evidence || [])
        .map((ev) => {
          const shot = ev.screenshot_url
            ? `<button type="button" class="shot" data-agent="${escapeHtml(ev.agent_id)}" data-step="${Number(ev.step)}"><img src="${escapeHtml(ev.screenshot_url)}" alt="Step ${Number(ev.step)} screenshot" /></button>`
            : "";
          const finalUrl = ev.final_url
            ? `<a href="${escapeHtml(ev.final_url)}" target="_blank" rel="noopener">final URL</a>`
            : "";
          return `<div class="cite">
            ${shot}
            <div>
              <p class="who">${escapeHtml(ev.persona_name || "Agent")} · ${escapeHtml(ev.task_title || "")}</p>
              <p class="detail">${escapeHtml(ev.detail || ev.action || "")}</p>
              <p class="links">
                <button type="button" data-agent="${escapeHtml(ev.agent_id)}" data-step="${Number(ev.step)}">Open trace · step ${Number(ev.step)}</button>
                ${finalUrl}
              </p>
            </div>
          </div>`;
        })
        .join("");
      return `<article class="claim-card ${kind}"><p>${escapeHtml(claim.claim)}</p>${cites}</article>`;
    })
    .join("");
  el.querySelectorAll("[data-agent]").forEach((node) => {
    node.addEventListener("click", () => {
      openTrace(node.dataset.agent, Number(node.dataset.step));
    });
  });
}

function renderCompare(insights) {
  const note = document.getElementById("tie-note");
  const table = document.getElementById("compare-table");
  const rows = insights?.comparisons || [];
  if (note) {
    if (insights?.tie_note) {
      note.hidden = false;
      note.textContent = insights.tie_note;
    } else {
      note.hidden = false;
      note.textContent = rows.length
        ? "Success rates differ, so steps, time, and friction are shown beside the rates and are not used to break a tie."
        : "No site comparison — the study has no finished runs.";
    }
  }
  if (!table) return;
  if (!rows.length) {
    table.innerHTML = "";
    return;
  }
  const body = rows
    .map((r) => {
      const time = r.median_time_s == null ? "—" : `${r.median_time_s}s`;
      const steps = r.median_steps == null ? "—" : Number(r.median_steps).toFixed(1);
      const pct = Math.round((r.success_rate || 0) * 100);
      return `<tr>
        <td>${escapeHtml(r.site_label || r.site_key)}</td>
        <td>${r.ok}/${r.n} (${pct}%)</td>
        <td>${r.left_start_pct ?? 0}%</td>
        <td>${steps}</td>
        <td>${time}</td>
        <td>${r.friction_n ?? 0}</td>
      </tr>`;
    })
    .join("");
  table.innerHTML = `<thead><tr><th>Site</th><th>Task success</th><th>Left start</th><th>Median steps</th><th>Median time</th><th>Friction notes</th></tr></thead><tbody>${body}</tbody>`;
}

function renderTrace() {
  const panel = document.getElementById("trace-panel");
  const viewer = document.getElementById("trace-viewer");
  const meta = document.getElementById("trace-meta");
  const run = (_study?.agent_results || []).find((r) => r.agent_id === _traceAgent);
  if (!panel || !viewer || !run) return;
  const shots = shotsOf(run);
  if (!shots.length) {
    panel.hidden = false;
    viewer.innerHTML = "<p class='empty-claim'>This run has no step screenshots.</p>";
    return;
  }
  let idx = shots.findIndex((s) => s.step === _traceStep);
  if (idx < 0) idx = shots.length - 1;
  const step = shots[idx];
  panel.hidden = false;
  if (meta) {
    const final = run.final_url
      ? ` · <a href="${escapeHtml(run.final_url)}" target="_blank" rel="noopener">${escapeHtml(run.final_url)}</a>`
      : "";
    meta.innerHTML = `${escapeHtml(run.persona_name || "")} — ${escapeHtml(run.task_title || "")}${final}`;
  }
  viewer.innerHTML = `
    <div class="step-nav">
      ${shots
        .map(
          (s, i) =>
            `<button type="button" class="${i === idx ? "active" : ""}" data-idx="${i}">${s.step}</button>`
        )
        .join("")}
    </div>
    <figure class="trace-shot"><img src="${escapeHtml(step.screenshot_url)}" alt="Step ${step.step}" /></figure>
    <p class="trace-action"><strong>Step ${step.step}.</strong> ${escapeHtml(step.action || "")}</p>
  `;
  viewer.querySelectorAll("[data-idx]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const shot = shots[Number(btn.dataset.idx)];
      if (shot) {
        _traceStep = shot.step;
        renderTrace();
      }
    });
  });
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function openTrace(agentId, step) {
  _traceAgent = agentId;
  _traceStep = Number.isFinite(step) ? step : 0;
  renderTrace();
}

function showReport(data) {
  const empty = document.getElementById("report-empty");
  const results = document.getElementById("results");
  const summary = data?.summary;
  const insights = summary?.insights;
  if (!summary || !insights) {
    empty.hidden = false;
    empty.textContent = "This study has no evidence-backed report yet.";
    results.hidden = true;
    return;
  }
  _study = data;
  empty.hidden = true;
  results.hidden = false;
  const title = document.getElementById("report-title");
  if (title && data.url) title.textContent = data.url;
  document.getElementById("headline").textContent = insights.headline || summary.headline || "";
  const note = document.getElementById("evidence-note");
  if (insights.evidence_note) {
    note.hidden = false;
    note.textContent = insights.evidence_note;
  } else {
    note.hidden = true;
  }
  const infoEl = document.getElementById("access-info");
  const backend = data.access_backend || summary.access_backend;
  if (backend && infoEl) {
    infoEl.hidden = false;
    infoEl.textContent = `Page loaded via ${backend}.`;
  }
  renderClaims(document.getElementById("strength-cards"), insights.strengths, "strength");
  renderClaims(document.getElementById("weakness-cards"), insights.weaknesses, "weakness");
  renderCompare(insights);
}

async function loadReport() {
  const params = new URLSearchParams(location.search);
  const studyId = params.get("study") || "";
  const empty = document.getElementById("report-empty");
  const results = document.getElementById("results");
  if (!studyId) {
    empty.hidden = false;
    results.hidden = true;
    return;
  }
  empty.hidden = false;
  empty.textContent = "Loading report…";
  results.hidden = true;
  try {
    const res = await fetch(`/api/studies/${encodeURIComponent(studyId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showReport(await res.json());
  } catch (err) {
    empty.hidden = false;
    empty.textContent = `Couldn’t load study ${studyId}: ${err.message || err}`;
    results.hidden = true;
  }
}

loadReport();
