# Arm-3 live top-3 miss anatomy

- days 2: {'2026-11-16': {'source': 'shadow_arm3', 'launches': 38, 'a3_top3_hits': 0, 'p345': True}, '2026-11-17': {'source': 'published pred_arm3', 'launches': 43, 'a3_top3_hits': 1, 'p345': True}}
- misses 5; buckets {'a': 4, 'b': 1}; shares {'a': 0.8, 'b': 0.2}
- bucket (a) features (00:05 input at/above arm-3's top-3 minimum): {'ph_hunter_followers': 3, 'promo_posts': 3, 'promo_reactions': 2, 'x_maker_sum_followers': 1, 'x_company_followers': 1}
- bucket (b) 03:45 signals (top 3 by): {'api_rank': 1, 'n_c': 1, 'u_out': 1}

- 2026-11-16 id 1306136 true #1 arm3 #4 bucket a a=['ph_hunter_followers'] b=['api_rank', 'n_c', 'u_out']
- 2026-11-16 id 1302625 true #2 arm3 #5 bucket a a=['ph_hunter_followers', 'promo_posts'] b=['n_c', 'u_out']
- 2026-11-16 id 1309589 true #3 arm3 #6 bucket a a=['ph_hunter_followers', 'x_maker_sum_followers', 'promo_reactions', 'promo_posts'] b=['api_rank']
- 2026-11-17 id 1316291 true #2 arm3 #7 bucket a a=['x_company_followers', 'promo_reactions', 'promo_posts'] b=['api_rank']
- 2026-11-17 id 1257199 true #3 arm3 #5 bucket b a=[] b=['api_rank', 'n_c', 'u_out']
