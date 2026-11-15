# Pre-registration: spectrum panel (one voice per subgroup), Nov 15 19:40Z

Request: orchestrator 19:08Z Nov 15 (from the website agent, on Shreyas's ask "show the full spectrum of groups").

## Arms
- **SPECTRUM.** One persona per leaf unit of the segments: every subgroup, plus each group that has no subgroups.
  - The harness uses the 2026-08-01 segments cut (12 units). Live uses the current cut (20 units).
  - Voices are sorted by lift. Each card gives:
    - share of the launch's likely-voter pool, base share (the unit's share of held upvotes in the 30 days before) and lift;
    - interest derived from lift: ≥ 1.5 high, ≥ 0.67 medium, otherwise low;
    - the unit's profile: who, says (paraphrased from its own past comments), votes for;
    - topics and products from the unit's pool members, or from a 400-member sample when fewer than 20 members are in the pool.
  - Same prompt (`persona_prompt.py`) and the same Gemini settings as the comparator.
- **Comparator: HYBRID_V3_K24.** The current live 24-persona, people-specific panel.

## Data and scoring
- The same 276 launches of the `reactions_v2` harness, scored with the same blinded judge.
- Metrics: recall, recall_w, precision, and complaint recall (CTRUTH).
- Paired by launch, with a 95% launch bootstrap.

## Decision rule
- SPECTRUM **replaces** the "what they say" panel only if:
  - the paired recall lower bound is > 0, and
  - the paired precision and complaint-recall upper bounds are both ≥ 0, i.e. neither is clearly worse.
- Otherwise we **keep both**: the spectrum for "who and how likely" (counts, share, lift, interest), and the 24-persona panel for "what they say". The spectrum's reaction text is then labelled lower-accuracy.
- Spend stops at $10.
