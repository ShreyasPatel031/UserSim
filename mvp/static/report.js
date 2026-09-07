/** Report page — reads the last completed study from sessionStorage. */

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderList(el, items) {
  el.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    el.appendChild(li);
  });
}

function renderSummary(summary, accessBackend, browserbaseSessionUrl, notifyEmail) {
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
  if (notifyEmail) {
    note.hidden = false;
    note.textContent = `Feedback ready — we’ll send a copy to ${notifyEmail}.`;
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
  results.forEach((r) => {
    const card = document.createElement("article");
    card.className = "agent-card";
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
    grid.appendChild(card);
  });
}

function showReport(data) {
  const empty = document.getElementById("report-empty");
  const results = document.getElementById("results");
  if (!data?.summary) {
    empty.hidden = false;
    results.hidden = true;
    return;
  }
  empty.hidden = true;
  results.hidden = false;
  const title = document.querySelector(".summary-panel h2");
  if (title && data.url) {
    title.textContent = `Executive summary — ${data.url}`;
  }
  renderSummary(
    data.summary,
    data.access_backend,
    data.browserbase_session_url,
    data.notify_email || ""
  );
  renderAgents(data.agent_results || []);
}

async function loadReport() {
  const params = new URLSearchParams(location.search);
  const studyId = params.get("study") || "";
  const empty = document.getElementById("report-empty");
  const results = document.getElementById("results");

  if (studyId) {
    empty.hidden = false;
    empty.textContent = "Loading report…";
    results.hidden = true;
    try {
      const res = await fetch(`/api/studies/${encodeURIComponent(studyId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      showReport(data);
      if (!data?.summary) {
        empty.hidden = false;
        empty.innerHTML = `No summary on this study yet. <a href="/live?study=${encodeURIComponent(studyId)}">Open live view</a>`;
        results.hidden = true;
      }
      return;
    } catch (err) {
      empty.hidden = false;
      empty.textContent = `Couldn’t load study ${studyId}: ${err.message || err}`;
      results.hidden = true;
      return;
    }
  }

  try {
    const raw = sessionStorage.getItem("usersim_report");
    const data = raw ? JSON.parse(raw) : null;
    showReport(data);
  } catch {
    empty.hidden = false;
    results.hidden = true;
  }
}

loadReport();

