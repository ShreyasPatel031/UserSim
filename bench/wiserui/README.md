# WiserUI-Bench harness (UserSim model stack)

Benchmark: https://github.com/jeochris/wiserui-bench (paper arXiv 2505.05026, ACL 2026). CC BY-NC-SA 4.0,
internal research only. **No dataset images or metadata are committed here**; everything lives in
`/workspace/bench/wiserui/` (repo clone, `images/`, `images_clean/`, `results/`).

## Data
`WiserUI_Bench.json`: 300 items with `index, win_url, lose_url, source, company, page_type, industry_domain,
web_mobile, ui_change, rationale`.
- `ui_change` = what changed, as `{element: [attributes]}`, e.g. `{"Tile": ["Count", "Size"]}`,
  `{"Button": ["Presence"]}`, `{"Card": ["Presence", "Hover State", "Color", "Text Content"]}`.
- `rationale` = 1-3 `{reason, law: {name, type}}` (UX laws such as Fitts's Law or Von Restorff); reasons often say
  "the right version ...", so they reveal the answer. Never shown to a model.
- 72 items have `win_url == lose_url`: a single composite image with both variants, often with the result
  printed on it. With the public scripts win and lose come out identical, so `run_bench.py` is run on the other
  225 (`clean_indices.txt`).

## Steps
```bash
unset MVP_STUDY_BUDGET_S; source /workspace/usersim-env.sh; unset MVP_STUDY_BUDGET_S
export PYTHONPATH=$PWD:$PWD/src:/workspace/pydeps-gcs      # run from the worktree root
git clone https://github.com/jeochris/wiserui-bench /workspace/bench/wiserui/repo
uv pip install --target /workspace/bench/wiserui/pydeps opencv-python-headless numpy
python bench/wiserui/prepare.py              # repo download_image + process_image (marker inpainting)
python bench/wiserui/run_bench.py --indices @/workspace/bench/wiserui/clean_indices.txt \
    --out /workspace/bench/wiserui/results/full
python bench/wiserui/score.py /workspace/bench/wiserui/results/full
```

## Conditions (all gemini-2.5-flash through UserSim's Vertex client, thinking_budget=0)
- `baseline`: the paper's `prompts_task1/zero_shot.txt` verbatim, with the two screenshots (temp 0.2, as the paper used with GPT-4o).
- `baseline_ctx`: the same, with one line of page context (company, page type, industry, platform).
- `usersim`: a planner call (same shape as `_CMP_PERSONAS` in `mvp/fast_plan.py`) invents 6 visitors for the page
  from context only; each persona sees both screenshots and says which version it would act on (JSON, temp 0.4);
  majority vote; a tie goes to summed confidence, and one still tied counts as wrong. Personas are shared across both orders.

Input modes:
- default: two separate images per call (the paper's format). On Vertex, gemini-2.5-flash shrinks each image to
  about 258 tokens when a request has 2+ images (HIGH media resolution is refused for multi-image requests).
- `WISERUI_STITCH=1`: one side-by-side image labelled First/Second. This is tiled at full detail (about 2.3k image
  tokens vs 0.5k) and is otherwise the same prompt.

`report.py label=run_dir ...` writes the markdown tables and example misses. `paired.py run_dir condA condB` gives the
paired bootstrap difference.

Metrics: consistent accuracy (right in both orders; chance 25%), plain accuracy (chance 50%, pair bootstrap CI),
first-position pick rate, by source and platform. For `usersim`, also a 12-vote pooled pick per pair.

## G-FOCUS arms (GFOCUS_REPORT.md)
`--stream gfocus`: the full G-FOCUS (arXiv 2505.05026v1 Appendix E prompts: goal, goal-conditioned diffs, argue both sides, Evaluator),
per order (strict), one neutral judge, temperature 1. `--stream gfocus_personas`: the same, with each persona arguing and evaluating.
`cost_per_pair.py` (tokens/cost per pair from ledgers) and `cost_project.py` (per-study and fine-tuning projections).
