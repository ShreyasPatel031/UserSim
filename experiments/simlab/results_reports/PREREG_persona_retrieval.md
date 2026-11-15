# Pre-registration: does the persona panel add to BEST's retrieval ingredient? (orchestrator, 01:28Z Nov 15)

Written before any PERSONA12R output exists.

- **Sample:** the 279 of the 300 reactions_v2 launches that have persona cards (Aug–Oct 2026).
- **Truth and judge:** reactions_v2 truth themes and its blinded judge, unchanged.
- **Arms:**
  - PERSONA12: the live panel.
  - PERSONA12R: the same panel prompt, plus the themes condensed from the real comments on the 10 most similar launches dated before the target. The neighbours and exclusions are exactly those of R10/BEST.
  - BEST: the cached output (flash, temperature 0.3, k = 10), re-judged on the same 279 launches.
- **Pairs:** by launch, launch bootstrap 4000, 95%.
  - Primary: PERSONA12R − PERSONA12.
  - Also: PERSONA12 − BEST and PERSONA12R − BEST.
- **Adoption rule for PERSONA12R (replacing the live panel):** adopt if the recall difference vs PERSONA12 has a lower bound > 0 AND the precision difference has a point estimate ≥ −3.0.
- **Also reported:** complaint recall, using complaints_eval Part B's critical-only truth and complaint judge (BEST's earlier value was 18.2 [15.8, 20.7]). It is reported only and does not enter the decision.
