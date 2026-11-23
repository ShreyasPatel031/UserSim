# simharness: social simulation harness (v0)

Open-source code for calibrating simulated people against real behaviour in any domain. A domain plugs in its own
data as four tables; the harness turns them into time-split benchmark tasks, runs any model behind one interface, and
scores every model on the same days against the same baselines. See docs/SOCIAL_SIM_PLAN.md (sections 2 and 3).

**This package holds code only.** Data, benchmark files, calibrated traces and trained weights are private and never
live in this repository. Person ids reaching the harness must already be salted by the domain adapter.

## The plug-in tables (`schema.py`)

| table | one row per | key columns |
|---|---|---|
| items | thing people act on (a launch) | item_id, day, title, summary, description, tags |
| events (people histories) | dated action of a person | person_id, kind (endorse / comment / review / make / follow), item_id, day, ts, text |
| people | person | person_id, complete, observed_until |
| outcomes | item | item_id, final_score, final_rank (never a model input) |
| structural | item per day | item_id, day, score, model_version, frozen_at (the domain model, frozen before the day) |

`observed_until` matters: a person whose actions were last read before day D cannot show an action on D, so they are
not a valid negative for D and the builder leaves them out of D's pool.

## Benchmark v0 (`bench.py`)

- **Task V (vote)**: for launch day D and item L, the candidates are the active pool of D (held-whole people with at
  least one endorsement on an item of the 60 days before D, observed after D closed). Label: endorsed L. History:
  events on items with day < D only (and before D starts when an exact time is known).
- **Task C (comment)**: (person, item, real comment text) rows, same history rule.
- **Splits** by item day: train <= 2026-10-31, validation Nov 1-10, test Nov 11-22. The first scored day is the first
  item day plus 60 (full look-back window).
- Stored compactly: pool per day and positives per item. `Benchmark.training_sample(days, k)` gives all positives
  plus k negatives per item with weights that undo the sampling; `score.evaluate_full` ranks the whole pool.

## Models (`models/`)

```python
class VoteModel:
    def prepare(self, bench, day): ...          # optional: walk-forward fit on days < day
    def score(self, histories, item) -> np.ndarray   # p_vote per person in the HistoryBatch
    def comment(self, histories, j, item) -> str
```

- `baselines.most_active()`: 60-day endorsement count (made a probability by a 1-feature walk-forward logistic).
- `baselines.backer_logistic()`: ln(1 + recency-weighted endorsements, 7-day half-life), topic match with past
  endorsed topics, their interaction; walk-forward logistic. No follow edges (undated, would leak).
- `llm.PromptVote(backend)`: renders the history as text (`HistoryBatch.render`) and the item, asks for
  `{"p_vote", "comment"}` JSON. Backends: `GeminiBackend` (Vertex) implemented; `ClaudeBackend`, `OpenAIBackend`,
  `LocalOpenModelBackend` are marked stubs.

To add a model: subclass `VoteModel` (or write a `Backend` with `call(prompt) -> str` and wrap it in `PromptVote`),
then score it with `score.evaluate_full` (full pool) or `score.evaluate_sample` (a fixed sample shared with the
baselines) and add it with `score.write_leaderboard`. Language models have read about past launches: score their
rank tests forward or on days after their training cutoff.

## Scoring (`score.py`)

recall@N per item (N = held endorsers in the pool; pooled and mean), AUC per item, expected calibration error, each
with a day-clustered bootstrap 95% interval; `paired_diff` compares two models on the same items.

## Running

```bash
python -m simharness.run_v0 build --store STORE_DIR --items ITEMS.parquet --comment-texts TEXTS.parquet --out BENCH
python -m simharness.run_v0 baselines --bench BENCH --split test --out RESULTS
# LLM adapters need the repo's src/ on the path and a GCP project:
PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python your_script.py
```

`domains/producthunt.py` is the first adapter; its module docstring lists its dating and leak choices.
