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
- `taste.TasteVote` (taste-v1): LightGBM / logistic on `features.TASTE_NAMES` (activity, topic shares, a local
  bge-small text embedding of the item vs the person's backed items, comment rate), trained on train days only.
- `llm.PromptVote(backend, prompt_version=2)`: renders the history as text (`HistoryBatch.render`: activity over the
  last 7 / 30 / 60 days, comments, top topics, last ~30 backed items, recent comments with @handles removed) and the
  item as listed at the start of its day, asks for `{"p_vote", "comment"}` JSON. Version 3 is the same prompt
  answered yes/no (the supervised-tuning format; `VertexGemini(..., yes_no=True)` turns the logprobs into P(yes)).

Backends (all `call(prompt) -> str`, real token usage, cost, latency, and a shared `Budget` dollar cap):
`VertexGemini` (also a tuned endpoint via `endpoint=`), `VertexClaude` (Vertex publisher anthropic, rawPredict),
`VertexOpenAICompat` (Model Garden MaaS: gpt-oss-120b, Llama 4 Maverick), `OpenAICompat` (any OpenAI-compatible
server, e.g. vLLM on our own GPU VM), `GeminiBackend` (v0, via the repo helper), `OpenAIBackend` (stub, no key).
To add a backend: subclass `Backend`, implement `_call(prompt) -> (text, input_tokens, output_tokens)`, add its
prices to `PRICES`.

To add a model: subclass `VoteModel` (or write a `Backend` with `call(prompt) -> str` and wrap it in `PromptVote`),
then score it with `score.evaluate_full` (full pool) or `score.evaluate_sample` (a fixed sample shared with the
baselines) and add it with `score.write_leaderboard`. Language models have read about past launches: score their
rank tests forward or on days after their training cutoff.

## Scoring (`score.py`)

recall@N per item (N = held endorsers in the pool; pooled and mean), AUC per item, expected calibration error, each
with a day-clustered bootstrap 95% interval; `paired_diff` compares two models on the same items.

## Evaluation sets (round 1)

- **HARD**: every held voter of every test launch plus one non-voter of that launch from the same day pool, matched on
  the nearest `rw30` (recency-weighted upvotes in the 30 days before the day) — `features.build_hard_set`. It
  separates "who is active" from "who picks this launch": most-active scores about 0.50 AUC on it by construction.
- **HARD-LLM**: a fixed subsample of HARD shared by every prompt model (size set by the budget).
- **VAL-HARD** / VAL-HARD-LLM: the same on validation days, for choosing learners and fitting stack weights.
- **EASY**: random pool non-voters (activity dominates). **FULL**: full-pool ranking (non-LLM models).
- `score.stack_fit` / `stack_apply`: a logistic stack on member logits, fit on validation only.
  `score.summarize(..., cluster="item")` and `paired_diff(..., cluster="item")` bootstrap by launch.

## Task C: what they say (`task_c.py`)

Rows are (person, item, the person's real comment), kept only when the comment was written on the item's own day and
the person is not a maker of the item. A model writes one comment per row; sentence embeddings (a small local model by
default) compare it with the real one.

- `match`: similarity at or above a threshold fixed on training comments, so that a real comment taken from a
  different item matches 5% of the time. The chance level is known by construction.
- `own_vs_other`: is the simulated comment closer to this person's real comment than to another person's real comment
  on the same item? 0.5 means no person-specific signal.
- References scored on the same rows with no model call: a real comment from another item (floor), the person's own
  latest earlier comment, and another person's real comment on the same item (the human yardstick).
- `PlainComment` (item only) is the baseline; `PromptComment` (history + item) has to beat it on the same rows
  (`paired_diff`, day-clustered interval). Both take any `Backend`.

```python
T = TaskC(Benchmark(BENCH))                 # fits the threshold on the training split
rows = T.rows("test")
scores = T.score(rows, T.generate(PromptComment(backend), rows))
summarize(scores); paired_diff(scores, plain_scores, "match")
```

## Fine-tuning (`finetune/`)

Fine-tune an open chat model on a benchmark's training rows and score it on the same rows as every other model.

1. `python -m simharness.finetune.export --bench BENCH --out DATA` writes `train.jsonl` (chat rows: the person's
   history and the item as the prompt, the real comment as the answer; most recent training rows, capped per person)
   and `eval.jsonl` (the Task C scorer's validation and test rows).
2. `finetune/lora.py` (one standalone file: torch, transformers, peft) trains a LoRA adapter with the loss on the
   answer only (`train`) and writes comments for the eval rows with or without the adapter (`generate`).
3. `finetune/gcp/launch.sh TAG MODEL MACHINE ZONE MAX_HOURS ...` runs both on a GPU VM that uploads its log, outputs
   and adapter to `FT_PREFIX/runs/TAG/`, then deletes itself; the run-time cap deletes it if anything hangs.
4. `python -m simharness.finetune.score_taskc --bench BENCH --gen tuned=... base=... --pairs tuned-base` scores any
   generation files next to the references, paired on the same rows.

Training rows, generations and adapters are private (real text and trained weights): they live under `FT_PREFIX` in a
private bucket, never in this repository.

## Running

```bash
python -m simharness.run_v0 build --store STORE_DIR --items ITEMS.parquet --comment-texts TEXTS.parquet --out BENCH
python -m simharness.run_v0 baselines --bench BENCH --split test --out RESULTS
# LLM adapters need the repo's src/ on the path and a GCP project:
PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python your_script.py
```

Round 1 (activity-matched HARD rows, taste-v1, prompt models, stacks; results in `bench_v0/round1/`):

```bash
R="python -m simharness.run_round1"; A="--bench BENCH --out OUT --sync gs://PRIVATE/prefix"
$R sets $A && $R leak $A && $R taste $A && $R ablate $A && $R nonllm $A --easy EASY.parquet
PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... $R llm $A --models gemini-2.5-flash,gpt-oss-120b --split test --cap 2.0
$R agg --bench BENCH --out OUT --results-dir simharness/bench_v0/round1
```

Every stage writes its files to OUT and copies them to the `--sync` prefix; prompt-model calls are cached in
append-only part files (`llm.JsonlCache`) so a restart never repeats a paid call, and `--cap` is a hard dollar limit.

`domains/producthunt.py` is the first adapter; its module docstring lists its dating and leak choices.
