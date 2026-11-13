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
