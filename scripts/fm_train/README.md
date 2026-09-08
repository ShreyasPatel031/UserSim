# Qwen3-8B-Base BehaviorBench SFT kill-test

Scripts in this directory implement the plan in
`/opt/cursor/artifacts/plans/8b-base_sft_pilot_39d897c3.plan.md`.

## Pipeline

```bash
# 1. Leakage registry
python scripts/fm_train/build_leakage_registry.py

# 2. Corpus (20–50k chat JSONL)
python scripts/fm_train/build_befm_pilot_corpus.py --target 40000

# 3. Train on a GPU box (GCP L4 / Colab)
#    sync data/fm_train/pilot_corpus.jsonl + these scripts to $ROOT
python scripts/fm_train/boot_pilot_sft.py

# 4. Eval kill tasks then gate
python scripts/fm_train/eval_pilot_kill_tasks.py --dry-run   # wiring check
python scripts/fm_train/apply_pilot_kill_gate.py \
  --beauty-win 0.18 --game-w 10.2 --survey-acc 0.30
```

## GO / STOP

| Metric | Floor | GO | STOP |
|---|---:|---:|---:|
| Beauty Contest win | 4.8% | ≥ 15% | < 8% |
| Single-round game avg W | 15.4 | ≤ 11.0 | > 14.0 |

Survey Acc must not fall more than 5 pp below floor (~27%).

## Notes

- Beauty Contest is **not** in the train mix (no public individual guessing
  rows). Lift there is transfer from other game CE.
- Raw sources live under `data/fm_train/raw/` (BIG5 + Mei ChatGPT-Behavioral CSVs).
- Adapter out: `/opt/usersim_fm/adapters/qwen3_8b_base_pilot/`.
