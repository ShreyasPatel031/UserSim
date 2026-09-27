/** Comparison study sections (summary.comparison): where the product wins and loses. */

function cmpEsc(s) { return escapeHtml(s); }

function cmpLabel(comp, key) {
  const s = (comp.sites || []).find((x) => x.key === key);
  return s ? s.label : key || "";
}

function cmpCss(key) {
  // Stable colors: the product is site-0, competitor_N is site-N.
  if (key === "product") return "site-0";
  const m = String(key || "").match(/competitor_(\d+)/);
  return m ? `site-${Math.min(3, Number(m[1]))}` : "site-0";
}

function cmpRun(agentId) {
  return runs().find((r) => r.agent_id === agentId) || null;
}

function cmpCite(agentId, step, text) {
  if (!agentId) return "";
  const s = Number.isFinite(Number(step)) ? Number(step) : 0;
  return `<button type="button" class="cite-link" data-agent="${cmpEsc(agentId)}" data-step="${s}">${cmpEsc(text || "evidence")}</button>`;
}

function cmpLevel(level, comp) {
  if (!level) return "";
  const label = (comp.level_labels || {})[level] || level;
  return `<span class="lvl lvl-${cmpEsc(level)}">${cmpEsc(label)}</span>`;
}

function cmpScoreCell(v, isPick, level, comp, notRun) {
  // A rival runs only its 2 x 2 slice: an empty cell was never run, it is not a 0.
  if (v == null) return `<td class="num muted small">${notRun ? "not run" : "—"}</td>`;
  const shade = Math.max(0, Math.min(10, Number(v))) / 10;
  const bg = `rgba(15,122,76,${(0.08 + shade * 0.32).toFixed(2)})`;
  return `<td class="num${isPick ? " pick" : ""}" style="background:${bg}">${Number(v).toFixed(1)}${isPick ? ' <span class="pick-mark">★ pick</span>' : ""}${level ? `<div>${cmpLevel(level, comp)}</div>` : ""}</td>`;
}

function cmpShot(ev) {
  if (!ev || !ev.screenshot) return "";
  return `<a class="shot mini" href="${cmpEsc(ev.screenshot)}" target="_blank" rel="noopener"><img loading="lazy" src="${cmpEsc(ev.screenshot)}" alt="final page" /></a>`;
}

function cmpPairCard(x, kind, comp) {
  const ev = kind === "win" ? x.product_evidence : x.competitor_evidence;
  const other = kind === "win" ? x.competitor_evidence : x.product_evidence;
  return `<article class="wl-card ${kind}">
    <div class="wl-head">
      <span class="wl-scores"><strong>${cmpEsc(comp.product_label)} ${Number(x.product_score).toFixed(1)}</strong> vs ${cmpEsc(x.competitor_label)} ${Number(x.competitor_score).toFixed(1)}</span>
      <span class="wl-meta">${cmpEsc(x.task)} · ${cmpEsc(x.persona)}</span>
    </div>
    <div class="wl-body">
      ${cmpShot(ev)}
      <div>
        <p class="wl-reason">${cmpEsc(x.reason)}</p>
        ${ev && ev.quote ? `<blockquote>“${cmpEsc(ev.quote)}”</blockquote>` : ""}
        <p class="links">${cmpCite(ev && ev.agent_id, ev && ev.step, `Open ${kind === "win" ? comp.product_label : x.competitor_label} trace · step ${ev && ev.step != null ? ev.step : 0}`)}
        ${cmpCite(other && other.agent_id, other && other.step, `vs ${kind === "win" ? x.competitor_label : comp.product_label}`)}</p>
      </div>
    </div>
  </article>`;
}

function renderCompareHtml(comp) {
  const sites = comp.sites || [];
  const counts = comp.pick_counts || {};
  const order = [...sites].sort((a, b) => (counts[b.key] || 0) - (counts[a.key] || 0) || (a.key === "product" ? -1 : 1));
  const pickChips = order
    .map((s) => `<span class="pick-chip ${cmpCss(s.key)}"><strong>${counts[s.key] || 0}</strong> ${cmpEsc(s.label)}</span>`)
    .join("") + (comp.pick_ties ? `<span class="pick-chip tie"><strong>${comp.pick_ties}</strong> tie</span>` : "");

  const pickers = (comp.by_persona || [])
    .map((p) => {
      const cite = (p.pick_cites || [])[0] || "";
      const run = cite ? cmpRun(cite) : null;
      const step = run?.comparison_score?.evidence_step ?? 0;
      return `<li><strong>${cmpEsc(p.name)}</strong> <span class="muted">${cmpEsc(p.role)}</span> → ${p.pick ? `<span class="pill ${cmpCss(p.pick)}">${cmpEsc(p.pick_label)}</span>` : `<span class="pill mixed">${cmpEsc(p.pick_label)}</span>`}
        ${p.against_scores ? `<span class="muted small"> · picked against its own averages (${(comp.sites || []).map((s) => `${cmpEsc(s.label)} ${p.scores?.[s.key] ?? "–"}`).join(", ")})</span>` : ""}
        ${p.pick_why ? `<div class="muted small">“${cmpEsc(p.pick_why)}”</div>` : ""}
        ${(p.pick_cites || []).map((c, i) => cmpCite(c, cmpRun(c)?.comparison_score?.evidence_step, `evidence ${i + 1}`)).join(" ")}</li>`;
    })
    .join("");

  const headline = (comp.headline || [])
    .map((h) => {
      const run = cmpRun(h.cite);
      return `<span class="hl-sentence">${cmpEsc(h.text)} ${h.cite ? cmpCite(h.cite, run?.comparison_score?.evidence_step, "↗") : ""}</span>`;
    })
    .join(" ");

  const wins = (comp.wins || []).map((x) => cmpPairCard(x, "win", comp)).join("") || `<p class="empty-claim">No task where ${cmpEsc(comp.product_label)} beat a competitor.</p>`;
  const losses = (comp.losses || []).map((x) => cmpPairCard(x, "loss", comp)).join("") || `<p class="empty-claim">No task where a competitor beat ${cmpEsc(comp.product_label)}.</p>`;

  const siteHead = sites.map((s) => `<th class="num">${cmpEsc(s.label)}</th>`).join("");
  const personaRows = (comp.by_persona || [])
    .map((p) => {
      const cells = sites.map((s) => cmpScoreCell(p.scores?.[s.key], p.pick === s.key, null, comp, (p.not_run || []).includes(s.key))).join("");
      const exp = p.expected_favorite ? cmpLabel(comp, p.expected_favorite) : "—";
      const hit = p.expected_favorite && p.pick ? (p.expected_favorite === p.pick ? "as expected" : "against expectation") : "";
      return `<tr><td><strong>${cmpEsc(p.name)}</strong><div class="muted small">${cmpEsc(p.role)}</div></td>${cells}
        <td>${cmpEsc(exp)}${p.expected_why ? `<div class="muted small">${cmpEsc(p.expected_why)}</div>` : ""}${hit ? `<div class="small ${hit === "as expected" ? "ok" : "warn"}">${hit}</div>` : ""}</td></tr>`;
    })
    .join("");

  const taskRows = (comp.by_task || [])
    .map((t) => {
      const cells = sites.map((s) => cmpScoreCell(t.scores?.[s.key], t.winner === s.key, t.levels?.[s.key], comp, (t.not_run || []).includes(s.key))).join("");
      const ev = t.winner_evidence;
      return `<tr><td><strong>${cmpEsc(t.task)}</strong>
          <div class="muted small">Winner: ${cmpEsc(t.winner_label)} · ${cmpEsc(comp.product_label)} rank ${t.product_rank ?? "—"} of ${t.n_sites}</div>
          ${t.expected_favorite ? `<div class="muted small">Expected: ${cmpEsc(cmpLabel(comp, t.expected_favorite))}</div>` : ""}
          ${ev ? cmpCite(ev.agent_id, ev.step, "why") : ""}</td>${cells}</tr>`;
    })
    .join("");

  const impressions = (comp.first_impressions || [])
    .map((f) => `<div class="fi-card">
        <h4><span class="pill ${cmpCss(f.site)}">${cmpEsc(f.label)}</span> ${f.clarity != null ? `<span class="muted small">clarity ${Number(f.clarity).toFixed(0)}/10</span>` : ""}</h4>
        <dl>
          <dt>What it is</dt><dd>${cmpEsc(f.what_it_is)}</dd>
          <dt>Who it's for</dt><dd>${cmpEsc(f.who_for)}</dd>
          <dt>Price</dt><dd>${cmpEsc(f.price)}</dd>
          <dt>Proof</dt><dd>${cmpEsc(f.proof)}</dd>
          <dt>Fastest way to try</dt><dd>${cmpEsc(f.fastest_path)} <span class="muted small">(${f.signups_ok}/${f.runs} self-serve signups worked)</span></dd>
        </dl>
        ${(f.cites || []).slice(0, 2).map((c, i) => cmpCite(c, cmpRun(c)?.comparison_score?.evidence_step, `evidence ${i + 1}`)).join(" ")}
      </div>`)
    .join("");

  const personaName = (pid) => ((comp.by_persona || []).find((p) => p.persona_id === pid) || {}).name || pid;
  const fixes = (comp.fixes || [])
    .map((f, i) => `<li class="fix">
        <div><strong>${i + 1}. ${cmpEsc(f.issue)}</strong> <span class="muted small">hurts ${(f.personas || []).length} of ${comp.n_personas} buyers${(f.personas || []).length ? ": " + f.personas.map(personaName).map(cmpEsc).join(", ") : ""}</span></div>
        ${f.fix ? `<div class="small">Fix: ${cmpEsc(f.fix)}</div>` : ""}
        ${(f.moments || []).map((m) => `<div class="small muted">${cmpCite(m.agent_id, m.step, `step ${m.step ?? 0}`)} ${cmpEsc(m.what)}</div>`).join("")}
      </li>`)
    .join("");

  const signupNote = comp.signup_note && comp.signup_note.text
    ? `<p class="small muted signup-note">Signup note: ${cmpEsc(comp.signup_note.text)}</p>` : "";
  return `
    <section class="cmp-hero">
      <p class="eyebrow">Which product would each buyer pick?</p>
      ${headline ? `<p class="hl">${headline}</p>` : ""}
      <h2 class="pick-line">${cmpEsc(comp.headline_metric)}</h2>
      <div class="pick-chips">${pickChips}</div>
      <details class="pickers"><summary>Each buyer's pick and why</summary><ul>${pickers}</ul></details>
    </section>
    <div class="chart-card">
      <h3>Where ${cmpEsc(comp.product_label)} wins</h3>
      <p class="sub">One buyer on one task, ${cmpEsc(comp.product_label)} against one competitor. Scores are 0–10 from the Gemini judge reading the trace, the final page and its screenshot.</p>
      <div class="wl-stack">${wins}</div>
      <h3 class="warn">Where ${cmpEsc(comp.product_label)} loses</h3>
      <div class="wl-stack">${losses}</div>
    </div>
    <div class="chart-card">
      <h3>Buyers × products</h3>
      <p class="sub">Average score over the tasks each buyer ran. ★ marks the product each buyer picked; "not run" means that buyer did not try that site (each competitor runs 2 buyers × 2 tasks).</p>
      ${comp.persona_summary ? `<p class="cmp-summary">${cmpEsc(comp.persona_summary)}</p>` : ""}
      <div style="overflow-x:auto"><table class="cmp-grid"><thead><tr><th>Buyer</th>${siteHead}<th>Expected favorite</th></tr></thead><tbody>${personaRows}</tbody></table></div>
    </div>
    <div class="chart-card">
      <h3>Tasks × products</h3>
      <p class="sub">Average score and how far buyers usually got: done in product › clear on website › vague marketing › wall.</p>
      ${comp.task_summary ? `<p class="cmp-summary">${cmpEsc(comp.task_summary)}</p>` : ""}
      <div style="overflow-x:auto"><table class="cmp-grid"><thead><tr><th>Task</th>${siteHead}</tr></thead><tbody>${taskRows}</tbody></table></div>
    </div>
    <div class="chart-card">
      <h3>First impression (about 30 seconds on the website)</h3>
      <div class="fi-grid">${impressions || `<p class="empty-claim">Not recorded.</p>`}</div>
    </div>
    <div class="chart-card">
      <h3>Fixes to make in ${cmpEsc(comp.product_label)}</h3>
      <p class="sub">${comp.fixes_source === "losses" ? `Drawn from the tasks ${cmpEsc(comp.product_label)} lost: what the competitor did that ${cmpEsc(comp.product_label)} did not.` : "Product problems from the weak runs"}, ranked by how many buyers they hurt.</p>
      ${fixes ? `<ol class="fix-list">${fixes}</ol>` : `<p class="empty-claim">No product problem found.</p>`}
      ${signupNote}
    </div>
    <div class="chart-card">
      <h3>Trace drill-down</h3>
      <p class="sub">Every step, screenshot and page for each buyer, task and product.</p>
      <button type="button" class="tab-jump" data-tab-jump="traces">Open the traces</button>
    </div>`;
}
