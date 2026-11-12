# Honest-backtest leak audit (E5, Nov 12 2026)

These scripts were run on usersim-exp-2 in experiments/ph_honest, which holds honest.py with data/ symlinked to ph_predict.

- `leak_audit.py`: share of launches whose site text contains outcome words, by final rank group.
- `colcheck*.py`: for each honest column, how often its top launch of the day is the winner, and how often it finishes top 3.
- `refit*.py`: honest.py's folds, 5 seeds and ctrl.fit, with sources removed.
- `score.py`: daily top 3/5/10, #1/#2/#3 pick hit rates and exact-winner rate, each with a day-bootstrap CI.
- `makers.py`, `raw.py`, `fc.py`: maker-record completeness and first-comment presence, by final rank.

**Finding:** the redaction of maker/user records in the day files re-read on Oct 25 depends on the final rank. Only 2.5% of winners have a redacted maker, against 70% of launches ranked #2–3. Maker-record fields, maker-id history and first-comment inputs therefore label the winner. The llm/page source does not.
