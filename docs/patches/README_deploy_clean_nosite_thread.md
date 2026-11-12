# Deploy candidate: clean_nosite_thread (DRAFT, not applied)

What it is: the 00:05 launch model trained and served without any input that needs a named maker (maker profiles, ID set)
and without llm_site, then re-ranked by a within-day z ridge on [clean score, th_has_first, th_hunter_first, th_n_pre]
(coefficients results/thread_live_model_z_nosite.json; th_n_pre = distinct non-hunter commenters incl. replies created
<= 00:05 PT; hunter by post.user.id; unknown -> day mean).

Evidence (thread_feats_perday*.csv, 207 days month-forward; tw_nosite.parquet 214 days):
| line | top 3 | top 5 | top 10 | #1 in top 3 | exact |
|---|---|---|---|---|---|
| clean_nosite | 56.2 | 67.6 | 75.0 | 72.5 | 38.2 |
| clean_thread_z (keeps llm_site) | 61.8 | 69.0 | 75.1 | 75.8 | 40.6 |
| clean_nosite_thread | 60.9 | 68.5 | 75.2 | 77.3 | 40.1 |
vs clean_nosite: top 3 +4.7 [+2.3, +7.1]; vs clean_thread_z: -1.0 [-2.6, +0.5]. As-live replay, 15 live days (counts):
deployed 27/45 top-3 hits, #1 in top 3 8/15; clean_nosite 29, 14; clean_nosite_thread 27, 13 (3 of the 15 days had no
comment read <= 00:05, so their thread features are empty).

What a deploy changes (`deploy_clean_nosite_thread.patch`, forecast.py only; model.py unchanged):
1. The 00:05 model's columns: M.cols(live sources) minus maker-profile prefixes, the ID set and llm_site; explicit LightGBM
   settings (= the shadow's clean line), 5 seeds.
2. The published order: the thread ridge score when data/today_comments/<day>.jsonl exists, else the clean score alone.
3. NEW DATA DEPENDENCY (not in the patch): a 00:05 PT read of every comment and reply of today's posts
   (created_at, parent_id, commenter_user_id, launch_id) into data/today_comments/<day>.jsonl, before forecast.py runs. The live
   capture's comment feed starts ~01:30 PT, so without this read the deploy publishes the clean score alone.
4. forecast_<day>.parquet keeps `pred` (the clean log-vote prediction) so early_shock / shadows keep their offset.
Apply after approval: git apply docs/patches/deploy_clean_nosite_thread.patch; deploy by merging to main.
