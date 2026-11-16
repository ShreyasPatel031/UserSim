# Ordered deploy list for Shreyas (Nov 14, ~22:20Z). Every line runs ON usersim-pipeline as user agent; every file is staged there now.
Each line needs Shreyas's direct word. None may run between 23:30 and 01:00 PT. Steps 1-2 are tonight's candidates; 3-7 come after.

1. TODAY-ROWS FIX: `bash ~/w/today_rows.new/deploy_today_rows.sh deploy` (script cc69181a)
   Changes: ph_predict/features.py 981c5ded -> 033d7bd7 (the line-up build reads only the target day's file; unlabelled rows never enter history).
   It writes the fix-date marker ~/w/today_rows_fix.json (+ bucket copy).
   Prerequisite: none. Refuses 23:30-01:00 PT. Rehearsal (`check`) passed at this md5.
   Rollback: `bash ~/w/today_rows.new/deploy_today_rows.sh rollback` (restores 981c5ded, removes the marker). A killed deploy resumes on rerun.
2. TWO PUBLISHED PREDICTIONS (12a.2): `bash ~/w/stage/b12a2/deploy_b12a.sh ~/w/stage/b12a2` (deploy_b12a.sh 3d87bfb4)
   Changes: adds the 1-minute tick cron block; writes predictions/<d>_0005.json at 00:25 PT and <d>_prereveal.json at 03:50 PT from the VM.
   Labels: live-prior hybrid. ~/w/tw12a becomes a symlink to a versioned tree.
   Prerequisite: none (step 1 first is the safe order).
   Rollback: `bash ~/w/stage/b12a2/deploy_b12a.sh rollback` (flips to the previous tree; on a first deploy it refuses: use `... remove` to take 12a off).
3. FIXED-PRIOR HYBRID WEIGHTS + TABLE LABELS (12a.5): `bash ~/w/stage/b12a5/install_fixedprior_weights.sh ~/w/stage/b12a5` (installer 73911b63; deploy_b12a.sh cab1bd88)
   Changes: weights 16912cd6 -> b8a59cdd (pinned, no silent revert); two_predictions ccb316f9 reads every label from north_star_table.json;
   arm-3 label and named arm-3 failure.
   Prerequisite: step 1's marker (refuses without it) and step 2.
   Rollback: `bash ~/w/stage/b12a5/deploy_b12a.sh rollback` (back to the 12a.2 tree; the weights pin follows the restored tree).
4. ARM-3 FILES, SHADOW ONLY: `bash ~/w/stage/arm3/deploy_arm3.sh install` (4731fe2e)
   Changes: creates ~/w/arm3_live (E5 modules, bge-small offline cache). No PUBLISH file, so nothing published changes.
   Prerequisite: none. Run BEFORE step 5, because live-code 2 then replaces its arm3_live.py with e62eae24.
   Rollback: `bash ~/w/stage/arm3/deploy_arm3.sh rollback`.
5. LIVE-CODE 2: `bash ~/w/livecode2.new/deploy_livecode2.sh deploy` (e49fdba6)
   Changes: forecast.py 61538501 -> 3c7da1b5, arm2_live/h25_live.py e3af37b4 -> ff40d796, pipeline/daily.py 27f0578d -> 54456921, new input_guard.py
   01547d5b, arm3_live.py -> e62eae24 (if step 4 ran). Brings in input guards, reproducible fits, explicit-day build, known launches kept,
   ids from the parquet, one published-model name, and the arm-3 switch (inert without PUBLISH).
   Prerequisite: step 1 (refuses unless features.py is 033d7bd7).
   Rollback: `bash ~/w/livecode2.new/deploy_livecode2.sh rollback`.
6. TIMED WRITES + E5 WRITERS (bundle 12.8): `cd ~/w/stage/b12_8 && bash deploy_b12.sh a6626fcf ee976fde` (985c6ef8)
   Changes: the tw.sh scheduler (shadows, P points, why files and drivers, website files, E5's writers 79abe5d5 incl. the nightly truth job).
   It exports the fix marker and WHY_LABEL_FROM_TABLE=1.
   Prerequisite: steps 1 and 5 (its scripts expect live-code 2's parquet columns).
   Rollback: `bash ~/w/stage/b12_8/deploy_b12.sh rollback` (restores the crontab backup; the tree is moved to backup_b12/).
7. PUBLISH ARM 3 (only after E5's arm-3 night audit, passed at 5183b614, and Shreyas's separate word): `bash ~/w/stage/arm3/deploy_arm3.sh publish`
   Changes: creates ~/w/arm3_live/PUBLISH, so from the next 00:05 run the published order is arm 3 and arm 2 stays as a shadow.
   Evidence: pre-registered top 5 +1.5 [+0.2, +2.8] (2026) / +1.8 [+0.4, +3.1] (2025); top 3 not established.
   Prerequisite: steps 3, 4 and 5.
   Rollback: `bash ~/w/stage/arm3/deploy_arm3.sh unpublish` (arm 2 publishes again at the next 00:05).

NEXT BUNDLE MANIFEST ADDITIONS (not deployed; to be built as a new named bundle):
- ~/w/arm2_live/ctrl.py, md5 b47fc28f (= ~/w/mk/ctrl.py). It is imported by training_window.py through history_retrain. Its absence
  caused the Nov 14 00:05 arm-2 fallback. It was added by hand at 09:02Z Nov 14, and no manifest tracks it yet. The bundle's
  deploy check should md5-verify it and import-gate h25_live.
- ph_n_makers drop: CLOSED, NOT ADOPTED (orchestrator 23:34Z Nov 14: worse beyond noise on 4 of 6 cells; the deployed input set is kept).
- NEXT BUNDLE BUILT, NOT DEPLOYED (now also the llm-link fix for arm 2: `deploy_nb.sh deploy_h25` installs only that, before 23:30 PT; see ph_predict/audit_nullinputs/README.md): pipeline_patches/20261115_next_bundle, staged on the VM at ~/w/stage/20261115_next_bundle
  (deploy_nb.sh d47b7218; check passed against 12.8's own tarball; deploy_h25 + rollback simulated). It carries ctrl.py b47fc28f -> ~/w/arm2_live and readable_shadow.py 2851a666 -> ~/w/tw/h25
  (per-launch "values" = raw X10 inputs for the site's "why"; ph_n_makers == 0 treated as missing), and arm2_shap.py 92f9e80d -> ~/w/tw/experiments/ph_predict (arm 2 TreeSHAP, groups and per-input centred, + raw input values; run nightly by 12.8's why_drivers job). Run it after step 6: `bash ~/w/stage/20261115_next_bundle/deploy_nb.sh deploy`;
  rollback with `… rollback`. Deploys only on Shreyas's word.
- Before-reveal writer 12a.6 (orchestrator 02:37Z Nov 15): 20261115_next_bundle/b12a6 replaces step 3's 12a.5 folder when deployed (label and top-10 edge from the table). A 03:45 replay line (hybrid_lodo READ_H=3.75) is scored nightly by the PH ops session; it stays empty until 03:45 reads exist.
- Stale-input audit (orchestrator 01:37Z Nov 15): the next bundle also carries the shared root builder rootlink.py (arm 2, arm 3, the tw 2025 shadows), comment_forecast cache refresh and tw.sh sync_wh alerting. See 20261115_next_bundle/README.md. Tonight only `deploy_h25` (with step 1) matters; the rest rides with step 6.

DEPLOYED Nov 15 ~19:50 PT (03:52Z Nov 16), under Shreyas's standing rule (chat, Nov 16: rehearsed deploy-list fixes go in without asking):
- Step 1 today-rows fix: features.py 033d7bd7, marker ~/w/today_rows_fix.json (fixed_from 2026-11-16). Check and dry run passed; the post-deploy run had 0 hunters with history and a null hist_hunter_rel.
- deploy_nb.sh deploy_h25: ~/w/arm2_live/h25_live.py 364b3b2a (over e3af37b4) + rootlink.py 38e37fba. Bundle check passed. A live arm-2 run for Nov 15
  afterwards gave llm_pitch / llm_brand null 0% (was 100%) and hist_hunter_rel|has_history 0% (was 25%).
  Rollback: bash ~/w/stage/20261115_next_bundle/deploy_nb.sh rollback (backup map ~/w/nb_backup/map.txt).
- NOTE step 5 (live-code 2) expects h25_live e3af37b4 and will now refuse. To run it: deploy_nb.sh rollback, then step 5, then deploy_nb.sh deploy_h25 (it picks the ff40d796 variant).

## Rehearsal standard (orchestrator 09:54Z Nov 16; applies to every deploy from now on)
"Rehearsed" means: each CHANGED job ran end to end on the latest real day, with DRY output to scratch, before install. An import gate or a bash -n alone is NOT a rehearsal (Nov 16: readable_shadow 2851a666 passed its import gate and failed its first nightly run).
- Next bundle: `bash ~/w/stage/20261116_next_bundle_r5/run_chain.sh deploy|deploy_h25` runs check -> `rehearse.sh <day>` -> deploy and stops at the first failure. rehearse.sh runs arm2_live (full predict), readable_shadow, h25_shadow, arm2_shap, comment_forecast P030, arm3_shadow (and tw.sh syntax) for every file that differs from the installed one, from scratch code trees (results/ is a copy, data/ read-only), with a gsutil stub that refuses every upload / rm. `REHEARSE_ALL=1` runs all jobs; `REHEARSE_DAY` picks the day. First full run: Nov 16, 7/7 jobs passed.
- Every other deploy script (12a, 12.8, live-code, arm 3): its entry in this file must name the end-to-end DRY command run on the latest real day and its result before the deploy line. Template:
  `N. <name>: <deploy command> (<md5>)`
  `   Rehearsal: <end-to-end DRY command on <day>, outputs to scratch> -> <result>`
  `   Post-deploy check: <command> -> <expected>`
  `   Rollback: <command>`
