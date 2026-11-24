# Arm-3 live top-3 miss anatomy

- days 4: {'2026-11-16': {'source': 'shadow_arm3', 'launches': 38, 'a3_top3_hits': 0, 'p345': True}, '2026-11-17': {'source': 'published pred_arm3', 'launches': 43, 'a3_top3_hits': 1, 'p345': True}, '2026-11-18': {'source': 'published pred_arm3', 'launches': 44, 'a3_top3_hits': 1, 'p345': True}, '2026-11-19': {'source': 'published pred_arm3', 'launches': 33, 'a3_top3_hits': 1, 'p345': True}}
- misses 9; buckets {'a': 8, 'b': 1}; shares {'a': 0.889, 'b': 0.111}
- bucket (a) features (00:05 input at/above arm-3's top-3 minimum): {'promo_posts': 7, 'ph_hunter_followers': 6, 'promo_reactions': 5, 'x_maker_sum_followers': 2, 'x_company_followers': 1}
- bucket (b) 03:45 signals (top 3 by): {'api_rank': 1, 'n_c': 1, 'u_out': 1}

- 2026-11-16 id 1306136 true #1 arm3 #4 bucket a a=['ph_hunter_followers'] b=['api_rank', 'n_c', 'u_out']
- 2026-11-16 id 1302625 true #2 arm3 #5 bucket a a=['ph_hunter_followers', 'promo_posts'] b=['n_c', 'u_out']
- 2026-11-16 id 1309589 true #3 arm3 #6 bucket a a=['ph_hunter_followers', 'x_maker_sum_followers', 'promo_reactions', 'promo_posts'] b=['api_rank']
- 2026-11-17 id 1316291 true #2 arm3 #7 bucket a a=['x_company_followers', 'promo_reactions', 'promo_posts'] b=['api_rank']
- 2026-11-17 id 1257199 true #3 arm3 #5 bucket b a=[] b=['api_rank', 'n_c', 'u_out']
- 2026-11-18 id 1316478 true #2 arm3 #6 bucket a a=['ph_hunter_followers', 'x_maker_sum_followers', 'promo_reactions', 'promo_posts'] b=['api_rank']
- 2026-11-18 id 1259097 true #3 arm3 #24 bucket a a=['promo_reactions', 'promo_posts'] b=['api_rank', 'n_c', 'u_out']
- 2026-11-19 id 1320414 true #2 arm3 #10 bucket a a=['ph_hunter_followers', 'promo_reactions', 'promo_posts'] b=['n_c', 'u_out']
- 2026-11-19 id 1311952 true #3 arm3 #4 bucket a a=['ph_hunter_followers', 'promo_posts'] b=['api_rank']

## Final (Nov 20; 4 live days, Nov 16–19)

**Buckets.** 9 misses: (a) 8 = 88.9%, (b) 1 = 11.1%, (c) 0.
- Every miss was also top 3 at 03:45 by hidden rank, comments or outside commenters.
- Bucket (a) takes precedence, so those cases count as (a).

**Cheapest rule (pre-registered counterfactual).** One 00:05 input, re-weighted z(arm3) + w·z(x), on the 4 live days:
- promo_reactions at w = 0.3: top-3 hits 3 → 6 of 12 (3 misses moved in, none lost). Best net gain, so this is the CHOSEN rule.
- promo_posts at w = 1.0: moves 4 misses in but loses 3 picks (net +1). At w = 0.3 it is net +1.
- hunter followers: net +1 at best. maker X / company X followers: net +1 at best.

**Backtest, leak-free arm-3 rows.**
- 2026 (n = 183 days, w chosen leave-one-month-out):
  - CHOSEN promo_reactions: top 3 −0.2 [−1.6, +1.3], top 5 −0.0 [−0.8, +0.8], top 10 −0.3 [−0.8, +0.1]. Not clear: a shadow line by the rule.
  - Reference (second look, not pre-chosen) promo_posts: top 3 +2.0 [+0.4, +3.8], top 5 −0.3 [−1.2, +0.4], top 10 −0.2 [−0.7, +0.4]. w = 0.1 in every fold.
- 2025: promo_* inputs are all null (old-row rule), so neither rule can be checked there.

**Caveats.**
- promo_posts clearing top 3 is a second look, after the chosen rule failed; two rules were tested.
- It has no 2025 replication, and promo_posts is already an arm-3 input, so this is a re-weight, not a new signal.
- I would not treat it as a deploy candidate without a forward shadow.
