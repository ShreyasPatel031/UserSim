# simlab — test theories about how real users react, against real outcomes

The MVP of the UserSim prediction platform (plan: "UserSim prediction platform: plan" doc). First domain: Product Hunt.

| Part | File | What it does |
|---|---|---|
| Data store | `store.py` | `data/people.parquet` (20.7k real people), `items.parquet` (6.5k launches + outcomes in `out_` columns), `events.parquet` (127k dated comments / upvotes) |
| Test harness | `harness.py` | Scores an experiment against the baseline on launches the model never trained on: day top 3 / 5 / 10 with 95% intervals, a leave-one-week-out blend, and a residual test. Logs every run to `registry.jsonl`. ~10 s |
| Baseline | `harness.baseline()` | Best pre-launch model (LightGBM, all sources), monthly rolling, cached |
| Persona engine | `persona.py` | Real people as of launch day (taste-matched + random), Gemini Flash reactions in words, SSR 1–5 score |
| Crowd step | `crowd.py` | Expected votes = P(sees it) x P(upvotes); follows raise P(sees); optional herding |

## Use

```bash
cd experiments
python -m simlab.store                                   # rebuild the store (seconds)
python -m simlab.persona react 2026-09-01 2026-10-24     # persona reactions (resumable)
python -m simlab.persona score                           # per-launch and per-person scores
python -m simlab.run simlab/experiments/persona_appeal.py
```

An experiment is one file in `experiments/` with `NAME`, `UNDATED` (inputs that could include the future),
`NOTES`, and `scores()` returning `id` + score columns (higher = more likely to rank high).

## Rules

- Every input must be known before launch day. Inputs read "now" (follows, segments, LinkedIn) go in `UNDATED`.
- Compare against the baseline on the same launches; a gain counts only if its interval clears the baseline's.
- Person-level data is research-only; ongoing pipelines use segment counts.

## Person-level results (Oct holdout)
- Start here: [reports/overnight_summary.md](reports/overnight_summary.md) (scores, spend, what to pay for) and [reports/path_to_90.md](reports/path_to_90.md) (what it takes to reach 90% top-3 hit).
- Scripts: `choice.py` (person rows and metrics), `path90.py` (miss buckets and oracle), `phase2.py` (collaborative filtering), `rel.py` (new relationship signals), `screen.py` (screening sample), `best_now.py` (full-holdout winners).
