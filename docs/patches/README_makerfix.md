# makerfix_forecast.patch: ready to apply, NOT applied (orchestrator 23:35Z Nov 11)

**What it does.** In the live 00:05 forecast (experiments/ph_predict/forecast.py), for today's launches whose maker
ids are placeholders ("0" or empty), it sets every maker-derived input to missing. Without it, those inputs are joined
on the placeholder id. Training rows are untouched.

**Evidence.**
- parity_live.md: swapping the re-read maker values gives +2.4 top 3 over 14 days (not significant).
- 4–12 launches per day carry placeholders at 00:05 (12 of 16 on Nov 11).
- Shadow: makerfix_shadow.py, scored forward in results/shadow_makerfix_forward.jsonl and in scoreboard.json (0005 makerfix_shadow).

**Apply only after the shadow beats the published line over at least 7 live days, and never 00:05–01:00 PT:**
`git apply docs/patches/makerfix_forecast.patch`, then deploy as a pipeline bundle.

The patch sets the columns to missing after M.add_fold_feats and before live_sources(), the same place as the shadow.
