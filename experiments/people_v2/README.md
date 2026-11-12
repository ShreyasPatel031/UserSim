# <PROJECT>/tables_v2 (built 2026-10-30, ET)

A new person-centric dataset. It does not change anything in `tables/` or `raw/`. It was rebuilt from the raw captures in
`<GCS-BUCKET>/<PROJECT>/raw/ph_predict_data/` and from `tables/events/`. Build script: `build_v2.py`, validation: `validate_v2.py` (copies are in this folder).

## Why v2
The v1 `people` table came from an older PH parser. For 13,286 of 20,671 people (64%), that parser stored the wrong page object's name and user_id
(`name='Wispr Flow'`, `user_id=606339`; another 215 got 'Lovable'). The LinkedIn name search then queried 'Wispr Flow + username', so 1,674 of the 2,989 v1 LinkedIn rows (56%)
carry Wispr Flow employees' text. v1 also threw away the self-declared links and many PH and X fields.

## Tables (Parquet)
- `persons`: person_id ('ph:'+username), display_name (correct PH name, else X name, else null), ph_username, ph_name_poisoned_in_v1, first_seen, built_at.
- `handles`: person_id, platform (producthunt, x, linkedin, github, website, instagram, youtube, ...), handle, url, source, confidence, note, observed_on.
  - Sources and confidence: `ph_username` 1.0; `ph_self_link` (from the person's own PH links) 0.95; `ph_twitter_field` 0.8 when there is no own X link, or 0.2 with the note 'conflicts with self link; not used' when it disagrees (312 cases);
    `li_search_name_match` 0.6×name similarity, only when the similarity is ≥0.85 and the query name wasn't poisoned (0 rows passed).
  - Downstream code should use confidence ≥0.8.
- `profiles`: one row per person and platform. Columns: name, bio, location, website, joined, followers, following, post_count, likes_count, media_count, verified, protected, extra (JSON), source.
  - producthunt extra: ph_user_id, headline, is_maker, upvotes_total, products_made, hunted, collections, reviews_count, stacks_count, visit_streak_days, community_rank_year, current_product, badges_total, badges, voted_recent, stacks, reviews, segments.
  - x: from raw/x_people for the accepted handle only (location, website, joined, post_count=tweets, verification).
  - linkedin: either the full Apify profile, when its publicIdentifier equals the person's own LinkedIn URL, or a search row whose URL equals the person's own URL.
    For search rows from a poisoned query, or with a 'Wispr' headline the PH profile doesn't support, the headline, company, role and education are set to null.
- `events`: person_id, platform, event_id, ts, ts_quality (exact/day), kind, target_id, text, metrics (JSON), source. PH upvotes and comments from tables/events; X posts from raw/x_posts and raw/x_people (accepted handles only).
- `github_smoke`: a free-API smoke test on 20 linked GitHub accounts.
- `validation.json`: coverage numbers and checks on the sample people and 50 random people.

## Known gaps
- The extended PH fields (products_made, hunted, collections, streak, rank, verified) exist only for the 4,143 people in ph_profiles2. Everyone else needs a PH re-fetch with the fixed parser, which needs the proxy.
- display_name is null for people whose only PH capture was poisoned and who have no X profile.
- LinkedIn text is old or partial; logged-out LinkedIn shows only the authwall. 5,443 people have a LinkedIn URL but no LinkedIn profile row.
- X profiles exist only where raw/x_people had them. HN people are not included yet (tables/hn_people is unchanged).
- PH upvote times are day-level. The 5 HN people in the reconcile sample aren't covered.

## Coverage v1 → v2 (people out of 20,671)
v1: {"x_handle": 6663, "x_bio": 2444, "linkedin": 2989, "github": 0, "website": 0, "ph_name": "not stored"}
v2: {"x_handle": 8930, "x_profile": 2288, "linkedin_identity": 7084, "linkedin_low_conf_search": 0, "linkedin_profile_rows": 3641, "github": 712, "website": 5529, "other_links": 677, "display_name": 8990, "ph_extended_fields": 4143, "x_posts_events": 31595, "ph_events": 277733, "x_people_with_posts": 2226, "x_conflicts_demoted": 312}
Validation: 7 PH sample people with 0 issues; 50 random people with 0 issues. LinkedIn profile rows still mentioning Wispr: 1. GitHub smoke test: 19/20 OK, 1 hit the unauthenticated rate limit.
