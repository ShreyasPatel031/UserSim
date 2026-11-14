# E5 website writers for the VM cron (bundle 12; not deployed until Shreyas says)

No LLM calls, no git at run time; each run is idempotent and logs one line "<UTC time> <job> rc=<code> inputs ... | last output line".
Exit codes: 0 ok; 2 asset sync failed; 3 inputs missing (named in the log); 64 unknown job; otherwise the script's own error.

| job | cron (UTC) | writes (gs://.../usersim_sim/) | reads |
|---|---|---|---|
| prob_0005 | 08:20 daily (after the 00:05 publish) | tmp/e5/website/probabilities/<today>_0005.json | results/web/predictions/<d>_0005.json, else raw/daily/<d>/forecast_<d>.parquet pred_arm2, else results/web/forecast_0005 ranks |
| prob_prereveal | 12:07 daily (after the 03:45 publish) | ..._prereveal.json | results/web/predictions/<d>_prereveal.json, else results/early_forecast/<d>_P345.json pred_rank_hybrid |
| period | 09:20 daily | <yesterday>_weekly.json, _monthly.json | warehouse launches (synced from the bucket by pipeline/warehouse.py) |
| track_record | 09:25 daily | tmp/e5/website/track_record_v1.json | assets a2x/X.parquet (arm-2 backtest), tmp/ph_ops/hybrid_vmonly_days.json, published files, warehouse daily_rank |
| held_team_score | 09:30 daily | appends simlab/reports/held_team_shadow/forward.jsonl (local) | tmp/e5/held_team_shadow/<yesterday>.json, warehouse |
| held_team_predict | 08:20 daily | tmp/e5/held_team_shadow/<today>.json (cp -n) | raw/daily/<d>/today_0005.json, forecast pred_arm2, raw/population/store_v3 persons+events (~300 MB), warehouse, 2025 lists, salt |

Frozen tables travel inside the tarball (simlab/reports/...): prob_model (00:05 logistic + 03:45 rank table), period_prob (position tables),
held_strict/frozen_weight.json, prereveal_345.json (launch counts only). Pinned asset in the bucket: tmp/e5/vm_writers/assets/a2x/X.parquet
(PH ops' arm-2 walk-forward dump). Python deps: pandas, numpy, pyarrow, duckdb (warehouse), gsutil on PATH.

Still in E5's session (needs Gemini): the forward /try record (forward_band.py + forward_sim.py: page reads through the site's safe_fetch,
the try_sim simulator from the claude/ph-website code, gemini-2.5-pro judge). To move it the VM needs: a Gemini key (Vertex service
account or API key) in the VM secret store, a checkout of claude/ph-website at a pinned commit (try_sim, person_e5, safe_fetch), the
frozen band pickles (tmp/e5/forward_assets/), and about $0.15-0.30 of Gemini per night.

## Build 12.2 (Nov 14, after the bug sweep)
Build with `bash vm_writers/build.sh [--sync] <out.tgz>`. The build fails if any vm_writers/simlab/*.py, frozen report JSON or pipeline/warehouse.py differs from its source, or if a writer imports a module the tarball lacks. MANIFEST.md5 travels inside; builds are deterministic.
Built: gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/vm_writers/e5_vm_writers_12_2.tgz, md5 427f222b2d6ea723bdda5e4f90f54b9f (18 files). Bundles 12 and 12.1 (tarball f9abf3e0) are withdrawn.
Checked on the BUILT tarball: manifest verifies; all .py compile; repro_B3 / B6 / B7 pass; every run.sh job (prob_0005 and prob_prereveal Nov 14, period Nov 13, track_record, period_score Nov 8) rc 0 with bucket writes stubbed.
