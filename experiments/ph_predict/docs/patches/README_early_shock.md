# early_shock.py hidden-votes fix (ready to apply, NOT applied)

From the PR #143 session (commit 8452809e on claude/tender-albattani-txg77t), received Nov 12.
Problem: Product Hunt hides vote counts for about the first 4 hours (every launch reads 0 votes at hours 0-3 on all
5 clean days); the deployed early_shock.py scores hours 1-3 on those zeros, so its vote arms equal the prior and would be
written to `backtests` as fake "no gain" rows when the backtest first runs (~Nov 20, at 14 clean days).
Fix: vote arms only where >= 50% of the line-up shows votes; comment-count arms (public from hour 0); optional hour 5;
deltas on shared days. Status line, output paths, backtests columns unchanged. Reviewed: one file, no new writes or
network calls.
Apply (deploy = merge to main, a decision for the orchestrator / Shreyas): `git am docs/patches/early_shock_hidden_votes.patch`
from the repo root, before Nov 20.
