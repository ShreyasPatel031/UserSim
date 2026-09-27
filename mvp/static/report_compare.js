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

function cmpScoreCell(v, isPick, level, comp, notRun, sel) {
  // An empty cell was never run (or the run was excluded), it is not a 0.
  if (v == null) return `<td class="num muted small">${notRun ? "not run" : "—"}</td>`;
  const shade = Math.max(0, Math.min(10, Number(v))) / 10;
  const bg = `rgba(15,122,76,${(0.08 + shade * 0.32).toFixed(2)})`;
  // sel makes the cell open this row and site in Task comparison.
  const open = sel
    ? ` data-tc-kind="${cmpEsc(sel.kind)}" data-tc-key="${cmpEsc(sel.key)}" data-tc-site="${cmpEsc(sel.site)}" data-tc-cell="${cmpEsc(`${sel.kind}|${sel.key}|${sel.site}`)}" title="Compare in Task comparison"`
    : "";
  return `<td class="num${isPick ? " pick" : ""}${sel ? " tc-cell" : ""}"${open} style="background:${bg}">${Number(v).toFixed(1)}${isPick ? ' <span class="pick-mark">★ pick</span>' : ""}${level ? `<div>${cmpLevel(level, comp)}</div>` : ""}</td>`;
}

// Task comparison state. filter narrows the matchups ("" = all); cell is the
// grid cell that set it, so that cell stays outlined.
const CMP = { comp: null, filter: { task: "", pid: "", rival: "" }, cell: "", layer: null, layerState: "" };
const CMP_LEVEL_RANK = { wall_or_nothing: 0, vague_marketing: 1, clear_evidence: 2, in_product: 3 };

function cmpBaseTask(run) {
  // Mirrors comparison._base_task: the planner's task without the "(vs https://…)" wrapper.
  return String(run.task_title || run.task_prompt || "").replace(/\s*\(vs https?:\/\/\S+\)\s*$/, "").trim();
}

function cmpScoreOf(run) {
  const s = run && run.comparison_score;
  return s && s.score != null ? Number(s.score) : null;
}

function cmpBest(task, pid, site) {
  // Same ordering as comparison.best: score, then level, then less friction.
  const rank = (r) => {
    const sc = r.comparison_score || {};
    return [Number(sc.score), CMP_LEVEL_RANK[sc.level] ?? 0, -Number(sc.friction || 0)];
  };
  let best = null;
  for (const r of runs()) {
    if ((r.site_key || "product") !== site || String(r.persona_id) !== String(pid) || cmpBaseTask(r) !== task) continue;
    if (cmpScoreOf(r) == null || cmpInfraStop(r)) continue;
    if (!best) { best = r; continue; }
    const a = rank(r), b = rank(best);
    if (a[0] > b[0] || (a[0] === b[0] && (a[1] > b[1] || (a[1] === b[1] && a[2] > b[2])))) best = r;
  }
  return best;
}

const CMP_INFRA_STOPS = new Set(["session ended", "study budget", "browser lost", "no browser", "model returned no action"]);

function cmpInfraStop(run) {
  // Mirrors comparison.infra_stop: the harness, not the site, ended this run.
  const stop = String(run.stop_reason || "").trim().toLowerCase();
  const steps = Number(run.num_steps || 0);
  return CMP_INFRA_STOPS.has(stop) || (steps <= 0 && !!String(run.browser_error || "").trim());
}

function cmpPersona(comp, pid) {
  return (comp.by_persona || []).find((p) => String(p.persona_id) === String(pid)) || {};
}

function cmpPairOf(comp, task, pid, rival) {
  const pr = cmpBest(task, pid, "product");
  const cr = cmpBest(task, pid, rival);
  if (!pr || !cr) return null;
  return { task, persona_id: pid, competitor: rival, product_run: pr, competitor_run: cr, gap: cmpScoreOf(pr) - cmpScoreOf(cr) };
}

function cmpStartIdx(run) {
  // Open each trace on the step the judge cited; if that step has no screenshot
  // (older studies saved only final.png), jump to the nearest one that does.
  if (_activeIdx[run.agent_id] != null) return;
  const shots = shotsOf(run);
  if (!shots.length) return;
  const cited = Number(run.comparison_score?.evidence_step);
  let idx = shots.findIndex((s) => Number(s.step) === cited);
  if (idx < 0 || !shots[idx].screenshot_url) {
    const from = idx < 0 ? shots.length - 1 : idx;
    let bestIdx = -1;
    shots.forEach((s, i) => {
      if (s.screenshot_url && (bestIdx < 0 || Math.abs(i - from) < Math.abs(bestIdx - from))) bestIdx = i;
    });
    if (bestIdx >= 0) idx = bestIdx;
  }
  _activeIdx[run.agent_id] = Math.max(0, idx);
}

function cmpSideCol(run, label, key, comp) {
  const sc = run.comparison_score || {};
  cmpStartIdx(run);
  return `<div class="tc-col">
    <div class="tc-col-head"><span class="swatch ${cmpCss(key)}"></span><strong>${cmpEsc(label)}</strong>
      ${cmpCite(run.agent_id, sc.evidence_step, "open in traces")}</div>
    ${sc.reason ? `<p class="wl-reason">${cmpEsc(sc.reason)}</p>` : ""}
    ${sc.quote ? `<blockquote>“${cmpEsc(sc.quote)}”</blockquote>` : ""}
    ${renderStepViewer(run)}
  </div>`;
}

function cmpPairCard(pair, comp) {
  const kind = pair.gap > 0 ? "win" : pair.gap < 0 ? "loss" : "tie";
  const buyer = cmpPersona(comp, pair.persona_id);
  const rivalLabel = cmpLabel(comp, pair.competitor);
  const side = (label, key, run, won) => {
    const sc = run.comparison_score || {};
    return `<div class="wl-side${won ? " won" : ""}">
      <span class="wl-site"><span class="swatch ${cmpCss(key)}"></span>${cmpEsc(label)}</span>
      <span class="wl-num">${Number(sc.score).toFixed(1)}</span>
      ${sc.level ? cmpLevel(sc.level, comp) : ""}
    </div>`;
  };
  return `<article class="wl-card ${kind}">
    <div class="wl-tags">
      <span class="wl-tag"><span class="wl-k">Buyer</span> <strong>${cmpEsc(buyer.name || pair.persona_id)}</strong>${buyer.role ? ` <span class="muted">${cmpEsc(buyer.role)}</span>` : ""}</span>
      <span class="wl-tag"><span class="wl-k">Task</span> <strong>${cmpEsc(pair.task)}</strong></span>
    </div>
    <div class="wl-scoreboard">
      ${side(comp.product_label, "product", pair.product_run, pair.gap > 0)}
      <span class="wl-gap ${kind}">${pair.gap > 0 ? "+" : ""}${pair.gap.toFixed(1)}</span>
      ${side(rivalLabel, pair.competitor, pair.competitor_run, pair.gap < 0)}
    </div>
    <div class="tc-cols">
      ${cmpSideCol(pair.product_run, comp.product_label, "product", comp)}
      ${cmpSideCol(pair.competitor_run, rivalLabel, pair.competitor, comp)}
    </div>
  </article>`;
}

function cmpDefaultPair(x) {
  // Backend wins/losses carry the exact two runs that were compared.
  const pr = x && cmpRun(x.product_evidence?.agent_id);
  const cr = x && cmpRun(x.competitor_evidence?.agent_id);
  if (!pr || !cr) return null;
  return { task: x.task, persona_id: x.persona_id, competitor: x.competitor, product_run: pr, competitor_run: cr, gap: Number(x.product_score) - Number(x.competitor_score) };
}

function cmpLevelGap(pair) {
  return (CMP_LEVEL_RANK[pair.product_run.comparison_score?.level] ?? 0) - (CMP_LEVEL_RANK[pair.competitor_run.comparison_score?.level] ?? 0);
}

function cmpFilteredPairs(comp, f) {
  const rivals = (comp.sites || []).map((s) => s.key).filter((k) => k !== "product");
  const tasks = (comp.by_task || []).map((t) => t.task);
  const pids = (comp.by_persona || []).map((p) => String(p.persona_id));
  const out = [];
  for (const rival of f.rival ? [f.rival] : rivals) {
    for (const task of f.task ? [f.task] : tasks) {
      for (const pid of f.pid ? [f.pid] : pids) {
        const pair = cmpPairOf(comp, task, pid, rival);
        if (pair) out.push(pair);
      }
    }
  }
  return out;
}

function cmpWinLoss(comp) {
  // One biggest win and one biggest loss inside the filter; a fully pinned
  // filter is a single matchup, shown even when it is a tie.
  const f = CMP.filter;
  if (!f.task && !f.pid && !f.rival) {
    return { win: cmpDefaultPair((comp.wins || [])[0]), loss: cmpDefaultPair((comp.losses || [])[0]), n: null };
  }
  const pairs = cmpFilteredPairs(comp, f);
  if (f.task && f.pid && f.rival) return { single: pairs[0] || null, n: pairs.length };
  const signed = (p) => p.gap || cmpLevelGap(p) * 0.001;
  const wins = pairs.filter((p) => signed(p) > 0).sort((a, b) => signed(b) - signed(a));
  const losses = pairs.filter((p) => signed(p) < 0).sort((a, b) => signed(a) - signed(b));
  // A tied score is still a matchup. Dropping it left the pane saying neither side won.
  const ties = pairs.filter((p) => signed(p) === 0);
  return { win: wins[0] || null, loss: losses[0] || null, ties, n: pairs.length, nWins: wins.length, nLosses: losses.length };
}

function cmpFilterBar(comp) {
  const f = CMP.filter;
  const opt = (value, label, current) => `<option value="${cmpEsc(value)}"${value === current ? " selected" : ""}>${cmpEsc(label)}</option>`;
  const select = (name, label, allLabel, items, current) => `<label class="tc-filter"><span class="wl-k">${label}</span>
      <select data-tc-filter="${name}">${opt("", allLabel, current)}${items.map((i) => opt(i.value, i.label, current)).join("")}</select></label>`;
  const any = f.task || f.pid || f.rival;
  return `<div class="tc-filters">
      ${select("task", "Task", "All tasks", (comp.by_task || []).map((t) => ({ value: t.task, label: t.task })), f.task)}
      ${select("pid", "Buyer", "All buyers", (comp.by_persona || []).map((p) => ({ value: String(p.persona_id), label: p.name })), f.pid)}
      ${select("rival", "Versus", "All competitors", (comp.sites || []).filter((s) => s.key !== "product").map((s) => ({ value: s.key, label: s.label })), f.rival)}
      ${any ? `<button type="button" class="tc-reset">Clear filters</button>` : ""}
    </div>`;
}

function cmpTaskCompareBody(comp) {
  const label = cmpEsc(comp.product_label);
  const r = cmpWinLoss(comp);
  if ("single" in r) {
    return `${cmpFilterBar(comp)}${r.single ? cmpPairCard(r.single, comp) : `<p class="empty-claim">No scored run pair for this buyer, task and competitor.</p>`}`;
  }
  const ties = r.ties || [];
  if (!r.win && !r.loss && ties.length) {
    return `${cmpFilterBar(comp)}
      <h4 class="tc-sub">Tied with ${label}</h4>
      <p class="muted small">Same score on ${ties.length === 1 ? "this matchup" : `these ${ties.length} matchups`}, so neither side won.</p>
      <div class="wl-stack">${ties.map((p) => cmpPairCard(p, comp)).join("")}</div>`;
  }
  const count = (n, one, many) => (n ? ` <span class="muted small">(top of ${n} ${n === 1 ? one : many})</span>` : "");
  return `${cmpFilterBar(comp)}
    <h4 class="tc-sub">Biggest win for ${label}${count(r.nWins, "win", "wins")}</h4>
    <div class="wl-stack">${r.win ? cmpPairCard(r.win, comp) : `<p class="empty-claim">No matchup here where ${label} beat the competitor.</p>`}</div>
    <h4 class="tc-sub warn">Biggest loss for ${label}${count(r.nLosses, "loss", "losses")}</h4>
    <div class="wl-stack">${r.loss ? cmpPairCard(r.loss, comp) : `<p class="empty-claim">No matchup here where a competitor beat ${label}.</p>`}</div>`;
}

function cmpRenderBody(comp) {
  const body = document.getElementById("tc-body");
  if (!body) return;
  body.innerHTML = cmpTaskCompareBody(comp);
  cmpWireBody(body, comp, true);
  document.querySelectorAll(".tc-cell").forEach((td) => {
    td.classList.toggle("tc-selected", !!CMP.cell && td.dataset.tcCell === CMP.cell);
  });
}

function cmpWireBody(body, comp, cites) {
  wireStepControls(body);
  if (cites) {
    body.querySelectorAll("button[data-agent][data-step]").forEach((node) => {
      node.addEventListener("click", () => openTrace(node.dataset.agent, Number(node.dataset.step)));
    });
  }
  body.querySelector(".tc-reset")?.addEventListener("click", () => {
    CMP.filter = { task: "", pid: "", rival: "" };
    CMP.cell = "";
    cmpRenderBody(comp);
  });
  body.querySelectorAll("select[data-tc-filter]").forEach((sel) => sel.addEventListener("change", () => {
    CMP.filter = { ...CMP.filter, [sel.dataset.tcFilter]: sel.value };
    CMP.cell = "";
    cmpRenderBody(comp);
  }));
}

function wireCompare(root, comp) {
  // Called by renderAnalytics after it wired the trace links in root.
  const body = root.querySelector("#tc-body");
  if (body) cmpWireBody(body, comp, false);
  root.querySelectorAll(".ins-link").forEach((b) => b.addEventListener("click", () => {
    CMP.filter = { task: b.dataset.insTask, pid: b.dataset.insPid, rival: b.dataset.insRival };
    CMP.cell = "";
    cmpRenderBody(comp);
    document.getElementById("task-compare")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  root.querySelectorAll(".tc-cell").forEach((td) => {
    td.classList.toggle("tc-selected", !!CMP.cell && td.dataset.tcCell === CMP.cell);
    td.addEventListener("click", () => {
      // A task row pins the task, a buyer row pins the buyer; a competitor
      // column pins that competitor, our own column compares against all.
      const rival = td.dataset.tcSite === "product" ? "" : td.dataset.tcSite;
      CMP.filter = td.dataset.tcKind === "task"
        ? { task: td.dataset.tcKey, pid: "", rival }
        : { task: "", pid: td.dataset.tcKey, rival };
      CMP.cell = td.dataset.tcCell;
      cmpRenderBody(comp);
      document.getElementById("task-compare")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function cmpLink(text, f) {
  // An insight link sets the Task comparison filters to the matchups behind it.
  return `<button type="button" class="ins-link" data-ins-task="${cmpEsc(f.task || "")}" data-ins-pid="${cmpEsc(f.pid || "")}" data-ins-rival="${cmpEsc(f.rival || "")}">${cmpEsc(text)}</button>`;
}

function cmpLoadLayer() {
  // Buyer/task groups, 3-line summary and 3 recommendations come from
  // /insight-layer (Gemini, cached per study); the page re-renders when it lands.
  if (CMP.layerState || !_study?.id) return;
  CMP.layerState = "loading";
  fetch(`/api/studies/${encodeURIComponent(_study.id)}/insight-layer`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((layer) => { CMP.layer = layer; CMP.layerState = "ready"; })
    .catch((err) => { console.warn("insight layer", err); CMP.layerState = "error"; })
    .finally(() => { if (typeof renderAnalytics === "function") renderAnalytics(); });
}

function cmpGroupedRows(groups, rowsByKey, colspan, verb, comp) {
  // One header row per product, then the buyers or tasks that score best there.
  return groups
    .map((g) => {
      const rows = g.members.map((m) => rowsByKey[m]).filter(Boolean).join("");
      if (!rows) return "";
      return `<tr class="grp-row"><td colspan="${colspan}">
          <span class="swatch ${cmpCss(g.site)}"></span><strong>${cmpEsc(g.site_label)}</strong> ${verb}${g.label ? ` · <strong>${cmpEsc(g.label)}</strong>` : ""}
          ${g.why ? `<div class="muted small">${cmpEsc(g.why)}</div>` : ""}
        </td></tr>${rows}`;
    })
    .join("");
}

function cmpPendingNote(what) {
  if (CMP.layerState === "loading") return `<p class="muted small">Grouping ${what}…</p>`;
  if (CMP.layerState === "error") return `<p class="muted small">Could not group ${what}; showing the flat list.</p>`;
  return "";
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

  CMP.comp = comp;
  const siteHead = sites.map((s) => `<th class="num">${cmpEsc(s.label)}</th>`).join("");
  cmpLoadLayer();
  const layer = CMP.layer;
  const personaRowOf = {};
  (comp.by_persona || [])
    .forEach((p) => {
      const cells = sites.map((s) => cmpScoreCell(p.scores?.[s.key], p.pick === s.key, null, comp, (p.not_run || []).includes(s.key), { kind: "persona", key: String(p.persona_id), site: s.key })).join("");
      const exp = p.expected_favorite ? cmpLabel(comp, p.expected_favorite) : "—";
      const hit = p.expected_favorite && p.pick ? (p.expected_favorite === p.pick ? "as expected" : "against expectation") : "";
      personaRowOf[String(p.persona_id)] = `<tr><td><strong>${cmpEsc(p.name)}</strong><div class="muted small">${cmpEsc(p.role)}</div></td>${cells}
        <td>${cmpEsc(exp)}${p.expected_why ? `<div class="muted small">${cmpEsc(p.expected_why)}</div>` : ""}${hit ? `<div class="small ${hit === "as expected" ? "ok" : "warn"}">${hit}</div>` : ""}</td></tr>`;
    });
  const personaRows = layer?.buyers?.length
    ? cmpGroupedRows(layer.buyers, personaRowOf, sites.length + 2, "is preferred by", comp)
    : Object.values(personaRowOf).join("");

  const taskRowOf = {};
  (comp.by_task || [])
    .forEach((t) => {
      const cells = sites.map((s) => cmpScoreCell(t.scores?.[s.key], t.winner === s.key, t.levels?.[s.key], comp, (t.not_run || []).includes(s.key), { kind: "task", key: t.task, site: s.key })).join("");
      const ev = t.winner_evidence;
      const row = `<tr><td><strong>${cmpEsc(t.task)}</strong>
          <div class="muted small">Winner: ${cmpEsc(t.winner_label)} · ${cmpEsc(comp.product_label)} rank ${t.product_rank ?? "—"} of ${t.n_sites}</div>
          ${t.expected_favorite ? `<div class="muted small">Expected: ${cmpEsc(cmpLabel(comp, t.expected_favorite))}</div>` : ""}
          ${ev ? cmpCite(ev.agent_id, ev.step, "why") : ""}</td>${cells}</tr>`;
      taskRowOf[t.task] = row;
    });
  const taskRows = layer?.tasks?.length
    ? cmpGroupedRows(layer.tasks, taskRowOf, sites.length + 1, "wins", comp)
    : Object.values(taskRowOf).join("");

  const personaName = (pid) => ((comp.by_persona || []).find((p) => String(p.persona_id) === String(pid)) || {}).name || pid;
  const recs = (layer?.recommendations || [])
    .map((r, i) => {
      const buyers = (r.buyers || []).map((pid) => cmpLink(personaName(pid), { pid })).join(", ");
      const tasks = (r.tasks || []).map((t) => cmpLink(t, { task: t })).join(", ");
      return `<li class="rec">
        <div><strong>${i + 1}. ${cmpEsc(r.title)}</strong></div>
        ${r.detail ? `<div class="small">${cmpEsc(r.detail)}</div>` : ""}
        ${buyers ? `<div class="small rec-ex"><span class="wl-k">Buyers</span> ${buyers}</div>` : ""}
        ${tasks ? `<div class="small rec-ex"><span class="wl-k">Tasks</span> ${tasks}</div>` : ""}
      </li>`;
    })
    .join("");
  const summaryLines = (layer?.summary || []).slice(0, 3);

  const signupNote = comp.signup_note && comp.signup_note.text
    ? `<p class="small muted signup-note">Signup note: ${cmpEsc(comp.signup_note.text)}</p>` : "";
  return `
    <section class="cmp-hero">
      <p class="eyebrow">Which product would each buyer pick?</p>
      <h2 class="pick-line">${cmpEsc(comp.headline_metric)}</h2>
      <div class="pick-chips">${pickChips}</div>
      ${summaryLines.length ? `<ul class="hl-lines">${summaryLines.map((l) => `<li>${cmpEsc(l)}</li>`).join("")}</ul>` : cmpPendingNote("the results")}
      <details class="pickers"><summary>Each buyer's pick and why</summary><ul>${pickers}</ul></details>
    </section>
    <div class="chart-card">
      <h3>Buyers × products</h3>
      <p class="sub">Each buyer is listed under the product they picked after trying them. They are not told which product they were expected to favor. Scores are the average over the tasks they ran; ★ marks that pick.</p>
      ${layer?.buyers?.length ? "" : cmpPendingNote("buyers")}
      <div style="overflow-x:auto"><table class="cmp-grid"><thead><tr><th>Buyer</th>${siteHead}<th>Expected favorite</th></tr></thead><tbody>${personaRows}</tbody></table></div>
    </div>
    <div class="chart-card">
      <h3>Tasks × products</h3>
      <p class="sub">Tasks grouped under the product that won them. Average score and how far buyers usually got: done in product › clear on website › vague marketing › wall.</p>
      ${layer?.tasks?.length ? "" : cmpPendingNote("tasks")}
      <div style="overflow-x:auto"><table class="cmp-grid"><thead><tr><th>Task</th>${siteHead}</tr></thead><tbody>${taskRows}</tbody></table></div>
    </div>
    <div class="chart-card" id="task-compare">
      <h3>Task comparison</h3>
      <p class="sub">One buyer on one task: ${cmpEsc(comp.product_label)}'s run beside a competitor's run, step by step. Scores are 0–10 from the Gemini judge reading each trace, final page and screenshot. Filter by task, buyer or competitor, or click any score above.</p>
      <div id="tc-body">${cmpTaskCompareBody(comp)}</div>
    </div>
    <div class="chart-card">
      <h3>Recommendations for ${cmpEsc(comp.product_label)}</h3>
      <p class="sub">Three changes drawn from the buyer and task groups ${cmpEsc(comp.product_label)} loses, with the buyers and tasks they would win back.</p>
      ${recs ? `<ol class="rec-list">${recs}</ol>` : cmpPendingNote("recommendations") || `<p class="empty-claim">No recommendation.</p>`}
      ${signupNote}
    </div>
    <div class="chart-card">
      <h3>Trace drill-down</h3>
      <p class="sub">Every step, screenshot and page for each buyer, task and product.</p>
      <button type="button" class="tab-jump" data-tab-jump="traces">Open the traces</button>
    </div>`;
}
