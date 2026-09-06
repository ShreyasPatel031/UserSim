# Experiment: YouTube competitive preference study (Bland-style, CUA agents)

**What the Bland study actually answered** ([/blandai](https://usersim.vercel.app/blandai)):

> For voice-AI dashboards (Bland vs Vapi vs Retell), **which platform do synthetic users prefer**, broken down by **persona** and **task type** — with step traces to explain why.

That is the experiment. Fleet auth was only plumbing so agents could *be* signed-in users.

**What we are proving here**

1. The **same study shape** works for an arbitrary product URL (YouTube first).
2. Agents are **CUA / Browser Use**, not Bland’s pre-baked signed-in sessions.
3. Sign-in is handled by our auth stack (TOTP + profile clone / seed egress), then forgotten — the deliverable is preference analytics + traces.

---

## Research questions (same as Bland)

| # | Question |
|---|---|
| Q1 | Overall, which site do personas prefer: **YouTube vs competitor A vs competitor B**? |
| Q2 | Does preference **change by persona**? |
| Q3 | Does preference **change by task type**? |
| Q4 | Where do losers fail (friction themes), with screenshots? |

**Success for this experiment** = we can answer Q1–Q4 with the same artifact shape as `/blandai` (overview + per-persona comparative + trace drill-down), produced by a live CUA run — not a prebaked JSON dump.

---

## Product loop we are testing (generalize later)

```
URL  ──►  invent 2 competitors
     ──►  invent personas (segment)
     ──►  invent tasks (typed)
     ──►  expand: every (persona × task × site)
     ──►  CUA agent per cell (signed-in when the site needs it)
     ──►  judge: success / ease / likes / dislikes / most_likely_to_use
     ──►  rollup: preference × persona × task_type + traces
```

YouTube is the **first URL** through that loop. The claim we want afterward:

> Anyone pastes a URL → UserSim finds 2 competitors, builds personas/tasks, runs CUA agents, ships a Bland-style preference report.

---

## Fixed study design (YouTube pilot)

### Sites (3)

| Role | URL | Auth |
|---|---|---|
| Product | `https://www.youtube.com/` | **Signed-in** (CUA uses cloned Google profile / seed auth) |
| Competitor 1 | invent or pin `https://www.tiktok.com/` | Signed-out OK unless task requires login |
| Competitor 2 | invent or pin `https://www.twitch.tv/` | Signed-out OK unless task requires login |

Pin competitors for the pilot so runs are comparable. Later, `invent_competitors(url)` fills this automatically.

### Personas (3–4) — invent from segment

**Segment prompt (pilot):**

> Gen-Z / millennial viewers who use short-form and long-form video daily for entertainment and learning.

Planner invents personas e.g.:

| ID | Sketch |
|---|---|
| p_shorts | Short-form snackable scroller |
| p_learn | Learner hunting tutorials / deep docs |
| p_create | Aspiring creator checking discoverability & Studio-adjacent UX |
| p_live | Live / community watcher |

(Exact names/bios come from the planner; keep ≥3.)

### Task types (the Bland axis)

Each persona gets tasks labeled with a **type** so we can slice preference like Bland:

| `task_type` | YouTube-shaped example |
|---|---|
| `discover` | Find something new on Home / For You without a query |
| `search` | Search a concrete topic and open a relevant result |
| `navigate` | Reach Subscriptions / Following / a channel page |
| `consume` | Play something and confirm it actually starts |
| `account` | Use a signed-in-only surface (history, liked, library) — **YouTube only if signed-in** |

Pilot size (cheap but Bland-complete):

- **3 personas × 3 task_types × 3 sites = 27 CUA runs**
- Gemini **2.5 Flash Lite**, max ~12–15 steps/run
- Parallelism: as many as auth allows (local profile clones or 1–2 seed VMs)

That is enough to fill:

- overall win rate / preference share
- preference × persona
- preference × task_type
- traces for drill-down

Scale up to 6 personas × 5 tasks later; do **not** start at 104 workers.

---

## Agent contract (CUA, not Bland session)

For each cell `(persona, task, site)`:

1. **Boot browser** with site-appropriate auth  
   - YouTube → signed-in profile clone (or seed egress). Abort cell if avatar missing.  
   - Competitors → fresh context unless the task is `account`.
2. **CUA** (Browser Use + Gemini 2.5 Flash Lite) executes the task as the persona.
3. Capture: step screenshots (+ bbox if available), actions, final URL, success flag.
4. **Judge** (same schema as Bland comparative reviews):

```json
{
  "persona_id": "p_shorts",
  "task_type": "discover",
  "goal": "...",
  "per_platform": {
    "youtube": { "liked": [], "disliked": [], "ease": "easy|medium|hard", "would_complete_again": true, "success": true },
    "tiktok": { "...": "..." },
    "twitch": { "...": "..." }
  },
  "most_likely_to_use": "youtube|tiktok|twitch",
  "runner_up": "...",
  "why_winner": "...",
  "confidence": "high|medium|low"
}
```

Preference is **judged from the three traces for the same (persona, task)**, not from a single site in isolation — identical to Bland.

---

## What “done” looks like (pass/fail)

| Gate | Pass bar |
|---|---|
| Pipeline | One command/URL submit produces competitors + personas + tasks + 27 runs without hand-writing them |
| Auth | ≥ 90% of YouTube cells start with avatar visible |
| CUA | ≥ 80% of cells finish (success or honest fail) with ≥1 screenshot |
| Bland parity | Rollup answers Q1–Q3; UI can show overview + persona slice + task_type slice + open a trace |
| No Bland dependency | Zero use of Bland/Vapi/Retell prebaked sessions — only CUA + our auth |
| Cost | Pilot ≤ ~$10 compute+LLM |

**Fail examples:** YouTube cells all signed-out; competitors invented are wrong vertical; judge picks winners without reading traces; only aggregate score, no persona/task_type breakdown.

---

## How this differs from the fleet-auth writeup

| | Fleet auth doc (wrong frame) | This experiment |
|---|---|---|
| Question | Can 104 browsers stay signed in? | Which video platform do personas prefer, by task type? |
| Unit of value | Concurrent sessions | Preference × persona × task_type + traces |
| Auth | The product | Prerequisite so YouTube `account`/`discover` tasks are real |
| Scale | 13×8 VMs | 27 judged cells first; scale only if the report is useful |

Auth scaling (seed VMs, egress, clones) stays a **supporting runbook**. It is not the experiment.

---

## Runbook (YouTube pilot)

```text
1. Ensure YouTube auth healthy
   PYTHONPATH=src .venv/bin/python -m mvp.session_health https://www.youtube.com/

2. Start study (same path as product UI)
   POST /api/studies
   {
     "url": "https://www.youtube.com/",
     "segment": "Gen-Z and millennial viewers who watch short-form and long-form daily",
     "competitors": ["https://www.tiktok.com/", "https://www.twitch.tv/"],
     "test_mode": false
   }

3. Agents: MVP_FORCE_LOCAL_BROWSER=1 (or seed VMs), Gemini 2.5 Flash Lite,
   signed-in profile clones for youtube.com cells

4. After runs: build Bland-shaped artifacts
   - persona_*_comparative.json  (most_likely_to_use per goal)
   - overview rollup (win share by site, by persona, by task_type)
   - traces under runs/<study_id>/…

5. View like /blandai: overview → persona → task → step screenshots
```

Optional cheap gate before full 27: **1 persona × 1 task_type × 3 sites = 3 runs** and confirm the comparative judge + avatar on YouTube.

---

## Generalization (after YouTube passes)

Replace the pinned YouTube block with:

```text
input:  { url, segment? }
auto:   competitors[2] = invent_competitors(url)
auto:   personas, tasks(+task_type) = plan(url, segment, page)
auto:   auth = ensure_site_auth(url) if vault match else signed_out
run:    CUA ∀ persona × task × {product|comp1|comp2}
out:    /study/:id  ≈ /blandai analytics
```

**YouTube is the proving ground** because signed-out YouTube is a fake product (empty Home). If CUA preference studies work here with real auth, the URL→competitors→personas→tasks→CUA loop is credible for other products.

---

## Decision rule

| Outcome | Meaning |
|---|---|
| Pilot answers Q1–Q4 with traces | **Bland-style CUA study works** for a URL; ship as default study mode |
| Preferential winners are nonsense / unsigned YouTube | Fix auth or judge before any fleet talk |
| Works on YouTube, fails on random SaaS URL | Competitor invent + task typing need work — still a product bug, not an auth bug |
