# Audit of every number in claims.json (claude/ph-website e5a99ca3, read Nov 13 06:10Z)

**Rules.**
- clean: every test launch, and its comments, is outside the model's training data and outside any retrieval bank used to score it.
- in-sample: at least one is inside.
- cannot tell: the evidence does not settle it.

LLM generation and judging use gemini-2.5-flash / pro on 2026 launches, which are after the models' 2025 training cutoff.

| claim | number(s) | model / recipe | training window / bank | test launches | verdict |
|---|---|---|---|---|---|
| reactions_eval | desc point precision 0.23 (generic 0.20), topic recall / precision 0.78; page 0.15 (generic 0.27), topic 0.63 / 0.65 | BEST reactions (flash, k = 10 retrieved neighbours' comment themes); strict pro same-point judge | Bank: reactions_retrieval v1, Jan 1 – Oct 24. S300 lists use only neighbours dated strictly before the target, excluding the same stem / name / team (reactions_v2.py l.124). Fresh lists use the site code; the bank ends Oct 24, before every fresh target. | 60 S300 (Aug – Oct) + 36 fresh page reads (Oct 27 – Nov 10) | **clean** |
| similar_tools_auc | AUC 0.692 | person_bundle_gemini (Gemini-256 + trees) | Uses lists are November snapshots, undated | held-out uses (random split), not launches | **cannot tell** in time: a held-out-item test, not a forward test. Fine as worded ("held-out uses") |
| rank_band_coverage | 0.797 on 5,351 launches | landing_retrieval: product-only ridge + band, month-forward | bands built only from earlier months | Mar – Nov 10, each month scored by a model fit on earlier months | **clean** (as a recipe claim; the served launch_band.json itself is trained to Nov 10) |
| matches_vs_voting | top-100 match upvote rate 0.98% vs activity-matched 1.04% | website person-bundle scorer, unchanged | person tools = undated Nov snapshots; activity controls use only upvotes before the day | 114 launches, Aug – Oct | **cannot tell** (a stack may list a tool adopted after the launch; near-identical items are dropped). Any leak would favour the matches, and they still do not beat the control, so the claim is conservative. Keep it |
| exp_votes_error | median abs error 20–29% (30–56% top 10) | PH ops growth model | PH ops | PH ops | **cannot tell from E5**: ask the PH agent (fit window vs the 3–4 test days) |
| reactions_vs_humans | recall ratio 1.27, precision ratio 1.40 (vs a real half-sample) | BEST reactions (as reactions_eval) vs split-half real comments | neighbours strictly earlier (reactions_v2) | 158 launches, Aug – Oct | **clean** |
| person_sim | same point 0.22 own history vs 0.12 generic; forced choice 0.29 / 0.27 (chance 0.25) | flash with the person's earlier comments | history = comments dated before the launch day | 275 comments by 88 members, Aug – Oct | **clean** |
| launch_model_backtest | top 3 / 5 / 10: 56.1 / 67.5 / 74.4, 255 days | PH ops honest_preds_v2 | PH ops (00:05-visible inputs) | Mar 1 – Nov 10 | **clean per PH ops**, one flag below |
| try_e2e | Spearman 0.42 [0.27, 0.56] on 130; 0.353 [0.29, 0.41] on 856; coverage 0.76; fetch-fail 0.27 / 0.20 | PH ridge retrained month-forward (corrected Nov 13) | earlier months only | 130 page reads Oct 27 – Nov 10; 856 Sep – Nov | **clean** (corrected); label fix below |
| page_band | Spearman 0.279 on 856 | launch_band_page_v1 (d_both) | trained to Aug 31 | 856 held-out, Sep 1 – Nov 10 | **clean** (726 held page reads were fetched Oct 25, after launch; outcome phrases stripped) |
| try_stability | reaction agreement 0.56, concern overlap 0.47, question overlap 0.59, 60 launches | reruns of the site code | no training involved | 60 fresh launches | **clean** (reproducibility, not accuracy) |
| top_items | top question from a description 1 in 2 (0.49–0.50), from a page 2 in 5 (0.41), generic 1 in 5; top concern 2 in 5 vs 1 in 5; ceiling 1 in 3 | ranked() (retrieval + flash) | bank neighbours dated strictly before the launch day | 70 launches (44 fresh Oct 27 – Nov 10 + 26 Sep – Oct) | **clean** (earlier relaunches of the same product can be neighbours: no future leak) |

**Result.** None of the published numbers is in-sample now; the 0.59 band was the only one, and it is already corrected. Three cannot be fully settled from E5's side: similar_tools_auc, matches_vs_voting and exp_votes_error.

**Recommended changes.**
1. **try_e2e label.** It says "130 page reads" next to coverage 0.76, but 0.76 is the cross-fit on the 856. Suggested wording: "rank correlation 0.42 on the 130 most recent launches and 0.35 on 856 Sep – Nov launches; the real rank fell inside the band about 3 times in 4 (856 launches)".
2. **launch_model_backtest.** No change to the number. E5 found that the 00:05 read's hunter followersCount still has a partial correlation of +0.15 / +0.29 beyond clean on Nov 10 / 11, although clean already contains ph_hunter_followers. The PH agent should confirm which read the backtest's value comes from: a later read would be a leak, and an older one only a missed gain.
3. **exp_votes_error.** The PH agent should state the growth model's fit window against its test days.
4. **similar_tools_auc.** Wording is fine. Optionally add "tools are a November snapshot".

The scope is claims.json only. Numbers hard-coded in page templates were not audited.

## Hardcoded numbers in templates and page copy (claude/ph-website e5a99ca3: mvp/static/ph.html, try.html, mvp/ph_site/live.py, try_sim.py)

| where | text | source | verdict |
|---|---|---|---|
| ph.html l.26; live.py l.27–34 | "first 4 hours … PH's own order + 00:05 forecast; after the 04:00 PT reveal, it uses votes" | pipeline timing | **matches** (reveal 04:00 PT) |
| live.py l.135 / l.147 | "daily rank … only stable from 03:00 PT the next day" | operational rule | ok |
| ph.html l.148 / l.164 | "Pick figures are an in-sample replay on N past days … optimistic" | prereveal_confidence.json (n from data) | **ok**, honest label. Tonight's pre-reveal replay covers 7 days; N comes from the file, so check the file says 7 |
| live.py l.563–564 | lock reliability: "tested right about 93% of the time after noon PT" / "only 67–81% before noon PT" | hardcoded; no source in code | **stale / unsourced**. Tonight's evidence is 92 / 94 / 96 (top 3 / 5 / 10) by 08:00 PT. If the lock backtest is now that, "only 67–81% before noon" understates it. The PH agent should give the lock-label backtest by hour, and the text should be generated from that file |
| try_sim._full_model_ref (via claims launch_model_backtest) | 00:05 model 56.1 / 67.5 / 74.4, 255 days | claims.json | **stale**: current clean backtest is 56.4 / 67.8 / 75.0 |
| try_sim._honesty | description-only model "29% / 40% / 60% of the real top 3 / 5 / 10", 222 days month-forward | launch_band.json heldout_accuracy (computed) | **clean** |
| try_sim._honesty | "deployed 00:05 model … scores X / Y / Z live over N days" | live track record (computed) | ok |
| try_sim l.769 | "on launches with 10 or more comments, generic concerns hit about as often" | not found in E5 reports | **cannot tell**: source needed, or drop |
| try_sim l.772 | "under 40 words … no better than generic (40 to 100 words did clearly better)" | E5 page_path/paste_length | **matches** |
| try.html l.81 | "3 simulations per hour, 10 per day per visitor" | try_sim CAPS defaults (TRY_PER_IP_HOUR 3, TRY_PER_IP_DAY 10) | matches the code defaults; production env overrides cannot be checked |
| try.html l.62–66, l.133 | "Who it resonates with … Most over-represented interest segment" | similar-tools scorer + interest segments | **mismatch with evidence**: segment over-representation did not beat the best constant (who_fix; retrieval who_mix, Nov 13: top-2 hit 14–17% vs constant 44%). The withdrawn segment claim is still displayed. Remove the "most over-represented interest segment" card, or relabel it "segment with the most similar-tool members (not validated as a predictor of voters)" |
| try.html l.65 / try_sim l.404 | "description shared by 20+ real members" / "20 or more people" | display rule | ok |
| try_sim l.429 / l.516 / l.584 | 13.6k profiles, 5,096 people, AUC 0.69, 10 neighbours | docstrings (not shown) | ok |
| weekly (live.py l.611 on) | weekly call, computed from results/web/weekly_*.json | data | no hardcoded number. If a weekly accuracy is shown, the source is the close backtest 82 / 88 / 90 (data, not template) |
