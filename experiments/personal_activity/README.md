# Personal activity simulator

Predicts one person's key computer behaviour from their screenpipe
**activity-only** export (focused app/domain, UI event types, speech yes/no),
and measures how well it does against simple baselines on later, unseen days.

No window titles, URLs, screen text, typed text or audio content are used.

> This repo is public. Real exports (`*.jsonl.gz`) and everything under `out/`
> are git-ignored. Commit only synthetic data. Don't paste real-data results
> into PRs or issues.

## Run it on real data (on your Mac)

```bash
gcloud auth login
```

```bash
gcloud config set project <your-gcp-project>
```

```bash
python -m experiments.personal_activity.run --input gs://<bucket>/ --tz America/Los_Angeles
```

- `--input` can be a `gs://` prefix (every `activity_*.jsonl.gz` under it), a
  local folder, or a single file. `gs://` is read with `gcloud storage` under
  your own login. Nothing is downloaded to disk.
- Use every weekly file you have. Files overlap by a day and are de-duplicated.
  At least 4 observed days are required. Three or more weeks give usable
  confidence intervals.
- `--tz` is the timezone for days and clock times. The default is this machine's
  timezone. A day runs from 04:00 to 04:00 local time (`--day-start-hour`).
- Output goes to `experiments/personal_activity/out/<timestamp>/` (git-ignored):
  - `report.md`
  - `results.json`
  - `llm_prompts/`, which holds exactly what was sent to the LLM.

### The LLM simulator

`--llm auto` is the default. When `gcloud` is logged in and a project is
set, it calls **Gemini 2.5 Flash on Vertex in your gcloud project** under
your account. Otherwise it falls back to `dry-run`, which writes the prompts and
a cost estimate without making any calls.

| Mode | What it does |
|---|---|
| `--llm auto` | Default. Uses `vertex` when gcloud is ready, otherwise `dry-run`. |
| `--llm vertex` | Forces real calls and fails if gcloud isn't ready. |
| `--llm dry-run` | Writes prompts and a cost estimate, makes no calls. |
| `--llm off` | Skips the LLM entirely. |

Other LLM options:
- `--llm-project`, `--llm-location`, `--llm-model` choose where it runs.
- `--llm-budget-usd` (default 1.0) is a hard cap, checked before every call.
- `--llm-points` (default 200) and `--llm-batch` (default 20) control how many
  test switches it sees.

On the 25-day synthetic fixture the estimate is about **$0.05**. With
`--llm-points 200` the switch part stays the same size on real data. The
day-level part grows by about $0.002 per test day.

**What gets sent to Vertex:** context labels (app names and domains), local
clock times, durations, and the profile built from train days (shares, top
transitions, idle rates, call slots). No raw events are sent. You can read
`out/*/llm_prompts/` to see it exactly. The project and account in use are
printed at the start of the run.

## What it does

```
loader.py    JSONL(.gz) / gs:// → de-duplicated events → focused segments, idle gaps, sessions, calls
tasks.py     prediction points + time-ordered split (train | test, last ~20% of train = validation)
models.py    baselines, the classical simulator (PersonalSimulator, DayRollout, CallModel)
llm_sim.py   LLM simulator (profile + batched queries, budget, parsing, gcloud Vertex caller)
evaluate.py  runs every model on every task, day-clustered paired bootstrap vs the best baseline
report.py    report.md
synth.py     synthetic fixture generator (exact production schema)
run.py       entry point
```

**Timeline:**
- **Activity:** any `ui` event, any `screen` event except `trigger=idle`, or a mic
  chunk with speech.
- **Idle:** more than 5 minutes with no activity (`--idle-gap-min`). An idle gap
  ends a **session**.
- **Segment:** the focused context is `app`, or `app | domain` when there is a
  domain (`--label-mode`). A focused screen event or a UI event naming another
  context starts a new segment. Segments under 2 s (alt-tab flicker) are
  absorbed.
- **Call:** a 5-minute window with at least 2 mic chunks with speech *and* at
  least 2 system chunks with speech. Speech on only one side, such as a video or
  talking in the room, doesn't count.
- **Labels:** the 30 most common contexts in train are kept; the rest become
  `other`.

### Tasks, baselines, metrics

| Task | Unit | Metric | Baselines |
|---|---|---|---|
| Next app/domain after the current one (same session) | switch | top-1 / top-3 accuracy | most-frequent, last-value (go back to the previous context), Markov 1st order, time-of-day prior |
| Time until the next switch (dwell) | switch | MAE s, log-MAE | global median, previous dwell, per-context median, time-of-day median |
| Goes idle within 10 min (`--idle-horizon-min`) | switch | Brier, AUC | base rate, per-context rate, time-of-day rate |
| First-active time, total active time, share of time per context | day (day-ahead) | MAE min, total-variation distance | median day, yesterday, same day-type (weekday/weekend) prior |
| When calls happen | 30-min slot (day-ahead) | Brier, AUC, slots/day error | base rate, yesterday, same day-type slot rate |

"Time-of-day" buckets are 3 hours, kept separately for weekdays and weekends.

**Classical simulator:**
- **Next context:** a mixture of global, 1st-order, 2nd-order, time-of-day,
  time-of-day × current-context, and a recency kernel over today's earlier
  contexts. The weights are tuned on the validation days.
- **Dwell:** a log-linear model.
- **Idle:** a logistic model over smoothed rates.
- **Whole day:** Monte-Carlo rollouts (`--rollouts`). Each rollout takes the
  session schedule of a past day of the same type and fills it with switches
  sampled from the model. This gives point predictions *and* 80% intervals.
- **Calls:** a logistic model on slot rates (same day-type, same weekday,
  neighbouring slots, yesterday, the last 5 days).

**LLM simulator:** Gemini sees the train-day profile plus, for each query, the
clock time, the current context and today's last 6 contexts with their dwells.
It returns the top-3 next contexts, the dwell and P(idle) per switch. For each
test day it also returns first-active time, active minutes, time shares and
call-slot probabilities. It is scored on the same sampled switches as every
other model (a separate table in the report).

**No leakage:**
- The test days are the last ~30% of observed days, so every test day comes
  after every train day.
- Switch-level models are fit on train days only. At prediction time they see
  only what happened earlier that same day.
- Day-level models are day-ahead: for test day *d* they use only days before
  *d*.

## Which metrics show it "predicts key behaviour"

The report opens with a **scorecard**. For each key metric it compares the
simulator with the **best baseline for that metric**. That baseline is picked
on the test set, which favours the baselines. Each comparison has a 90%
day-clustered paired bootstrap CI.

The simulator predicts this person's key behaviour if:

1. **Next context top-3** beats the best baseline with the CI excluding 0. This
   is the core claim: it knows where you go next better than habit counts do.
2. **At least one of dwell log-MAE or idle Brier** beats the best baseline. It
   knows *when* you switch or stop.
3. **Call AUC ≥ 0.75**, and call Brier is no worse than the time-of-day slot
   prior. It knows when you're on calls.
4. **Daily shape:** active-time MAE and share TV are no worse than the
   same-day-type prior. The rollout 80% intervals cover 65–95% of test days,
   so the simulated days are realistic rather than just averages.

Absolute numbers depend on the person. The lift over the best baseline and
the CI are what carry the claim. With fewer than about 10 test days, expect
wide CIs on the day-level metrics.

## Synthetic fixture

`fixtures/synthetic/` holds 4 weekly files: 25 observed days of a fictional
person, in the exact production schema, with the 8-day overlap.
`synth.py` regenerates them byte for byte:

```bash
python -m experiments.personal_activity.synth
```

```bash
python -m experiments.personal_activity.run --input experiments/personal_activity/fixtures/synthetic
```

```bash
python -m pytest experiments/personal_activity/tests -q
```

[`SYNTHETIC_REPORT.md`](SYNTHETIC_REPORT.md) is the report on that fixture.
The LLM was in dry-run because the cloud session that built this has no
gcloud login. Results, 17 train days and 8 test days:
- Next-context top-3 is **0.75**, against 0.70 for Markov and 0.45 for
  most-frequent. The CI excludes 0.
- Idle Brier, active time and call Brier are slightly better than the best
  baseline, within noise.
- Dwell, first-active time and time shares are tied with or slightly worse than
  the best baseline.

These numbers only show the pipeline works. They say nothing about a real
person.

## Data requests

These are fields not in the current export, ranked by expected value for this
simulator. The gains are **estimates** from how much of each target the field
explains. They are not measured, because no data with these fields exists yet.
Each one can be exported in a privacy-reduced form.

| # | Field (privacy-reduced form) | Helps | Expected gain |
|---|---|---|---|
| 1 | **Calendar events**: start/end, attendee count, has video link. No titles or attendees. | calls, first-active time, idle | Call AUC from ~0.75 to **0.9+**, call Brier roughly halved. Meetings are scheduled, and today the model can only learn them from past slots. Biggest single win for calls. |
| 2 | **Window title**, as a local category (`code-review`, `email-compose`, `doc-edit`, `dm`, …) or a salted hash per title | next context, dwell | **+5–10 pts top-1** at the current label granularity. The title tells the task (e.g. a PR review means GitHub/terminal next). Dwell log-MAE −10–15%. Also allows finer labels (which repo/doc/channel). |
| 3 | **Screen lock / sleep / wake / display-off events** | idle, first-active time, active time | Separates "stepped away" from "reading". Idle Brier **−15–25%**. First-active and active-time errors drop because lock/unlock gives exact edges. |
| 4 | **Notification posted** (app only, no content) | next context, dwell | Many switches answer a ping. **+3–8 pts top-1** on switches into chat/mail, dwell log-MAE −5–10%. |
| 5 | **App producing system audio / mic in use by app** (e.g. `zoom.us`, `Google Chrome`) | calls | Call detection precision near 100%. Videos with speech stop looking like half-calls. Fixes label noise rather than adding prediction lift. |
| 6 | **URL path template** (first path segment, e.g. `github.com/<org>/<repo>/pull`) | next context | **+2–5 pts top-1** inside the browser (review vs browse vs issues). Cheaper and less sensitive than full URLs. |
| 7 | **Visible (unfocused) windows per snapshot** (app + domain) | next context | The next context is often already on screen. **+3–5 pts top-3**. The export has `focused=false` snapshots, but they are sparse. |
| 8 | **Longer history** (keep or upload more than 8 days, or backfill) | everything day-level, calls | No new field, so the cheapest change. Per-weekday call patterns need about 4+ weeks. Day-level CIs shrink roughly as 1/√(test days). |
| 9 | **Machine timezone / UTC offset per event** | daily shape | Prevents broken day boundaries when travelling. Small but free. |

Suggested order: 8 (free), then 1, then 3. Those three cover the call and
idle tasks almost entirely. Then add 2 in its category form for the
next-context task. Re-run the same command after each export change and
compare the scorecards. The split and metrics stay fixed, so the deltas are
comparable.

## Known limitations

- The switch-level models don't update online during the test days. The
  day-level models do (day-ahead).
- Labels are app or app+domain only. A context outside the train vocabulary
  becomes `other`, so a newly adopted app shows up as `other` until retraining.
- The day rollout reuses past session schedules rather than generating new
  ones, so its active-time prediction is close to the same-day-type prior by
  design. Its value is the time shares and the intervals.
