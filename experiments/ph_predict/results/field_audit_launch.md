# Launch-side field audit (sample day 2026-11-12; field names and presence counts only)

Columns: present = rows with the field / rows in the sampled file; feature build = referenced in ph_predict/features.py (the 00:05 model's build); any code = referenced anywhere in experiments/*.py; warehouse launches = one of the 15 launches columns.
Fields in daily files that the feature build ignores are now kept as a raw_fields JSON text column (features.py, not a model input).

## api_teams.jsonl (90 rows, 12 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| day | 90/90 | yes | yes | yes |
| fetched_at | 90/90 | - | yes | - |
| headline | 90/90 | yes | yes | - |
| kind | 90/90 | - | yes | - |
| maker_id | 90/90 | - | NO | - |
| name | 90/90 | yes | yes | yes |
| post_id | 90/90 | - | yes | - |
| slug | 90/90 | - | yes | yes |
| snapshot_tag | 90/90 | - | NO | - |
| src | 90/90 | yes | yes | - |
| twitterUsername | 90/90 | yes | yes | - |
| username | 90/90 | - | yes | - |

## daily_day.json (37 rows, 30 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| commentsCount | 37/37 | yes | yes | - |
| createdAt | 37/37 | yes | yes | - |
| dailyRank | 37/37 | yes | yes | - |
| description | 37/37 | yes | yes | yes |
| featuredAt | 37/37 | yes | yes | - |
| id | 37/37 | yes | yes | yes |
| makers[].createdAt | 35/37 | yes | yes | - |
| makers[].followersCount | 35/37 | yes | yes | - |
| makers[].headline | 35/37 | yes | yes | - |
| makers[].id | 35/37 | yes | yes | yes |
| makers[].name | 35/37 | yes | yes | yes |
| makers[].twitterUsername | 35/37 | yes | yes | - |
| makers[].username | 35/37 | - | yes | - |
| makers[].websiteUrl | 35/37 | yes | yes | - |
| media[].type | 37/37 | yes | yes | - |
| monthlyRank | 37/37 | yes | yes | - |
| name | 37/37 | yes | yes | yes |
| slug | 37/37 | - | yes | yes |
| tagline | 37/37 | yes | yes | yes |
| topics.edges[].node.name | 37/37 | yes | yes | yes |
| user.createdAt | 37/37 | yes | yes | - |
| user.followersCount | 37/37 | yes | yes | - |
| user.headline | 37/37 | yes | yes | - |
| user.id | 37/37 | yes | yes | yes |
| user.name | 37/37 | yes | yes | yes |
| user.twitterUsername | 37/37 | yes | yes | - |
| user.username | 37/37 | - | yes | - |
| votesCount | 37/37 | yes | yes | - |
| website | 37/37 | yes | yes | - |
| weeklyRank | 37/37 | yes | yes | - |

## daily_page.jsonl.gz (26 rows, 4 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| html | 26/26 | yes | yes | - |
| route | 26/26 | - | yes | - |
| status | 26/26 | - | yes | - |
| url | 26/26 | yes | yes | - |

## daily_today_0005.json (37 rows, 30 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| commentsCount | 37/37 | yes | yes | - |
| createdAt | 37/37 | yes | yes | - |
| dailyRank | 37/37 | yes | yes | - |
| description | 37/37 | yes | yes | yes |
| featuredAt | 37/37 | yes | yes | - |
| id | 37/37 | yes | yes | yes |
| makers[].createdAt | 35/37 | yes | yes | - |
| makers[].followersCount | 35/37 | yes | yes | - |
| makers[].headline | 35/37 | yes | yes | - |
| makers[].id | 35/37 | yes | yes | yes |
| makers[].name | 35/37 | yes | yes | yes |
| makers[].twitterUsername | 35/37 | yes | yes | - |
| makers[].username | 35/37 | - | yes | - |
| makers[].websiteUrl | 35/37 | yes | yes | - |
| media[].type | 37/37 | yes | yes | - |
| monthlyRank | 37/37 | yes | yes | - |
| name | 37/37 | yes | yes | yes |
| slug | 37/37 | - | yes | yes |
| tagline | 37/37 | yes | yes | yes |
| topics.edges[].node.name | 37/37 | yes | yes | yes |
| user.createdAt | 37/37 | yes | yes | - |
| user.followersCount | 37/37 | yes | yes | - |
| user.headline | 37/37 | yes | yes | - |
| user.id | 37/37 | yes | yes | yes |
| user.name | 37/37 | yes | yes | yes |
| user.twitterUsername | 37/37 | yes | yes | - |
| user.username | 37/37 | - | yes | - |
| votesCount | 37/37 | yes | yes | - |
| website | 37/37 | yes | yes | - |
| weeklyRank | 37/37 | yes | yes | - |

## hist2025.json (16 rows, 32 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| commentsCount | 16/16 | yes | yes | - |
| createdAt | 16/16 | yes | yes | - |
| dailyRank | 16/16 | yes | yes | - |
| description | 16/16 | yes | yes | yes |
| featuredAt | 16/16 | yes | yes | - |
| id | 16/16 | yes | yes | yes |
| makers[].createdAt | 16/16 | yes | yes | - |
| makers[].followersCount | 16/16 | yes | yes | - |
| makers[].headline | 16/16 | yes | yes | - |
| makers[].id | 16/16 | yes | yes | yes |
| makers[].name | 16/16 | yes | yes | yes |
| makers[].twitterUsername | 16/16 | yes | yes | - |
| makers[].username | 16/16 | - | yes | - |
| makers[].websiteUrl | 16/16 | yes | yes | - |
| media[].type | 16/16 | yes | yes | - |
| monthlyRank | 16/16 | yes | yes | - |
| name | 16/16 | yes | yes | yes |
| reviewsCount | 16/16 | yes | yes | - |
| reviewsRating | 16/16 | yes | yes | - |
| slug | 16/16 | - | yes | yes |
| tagline | 16/16 | yes | yes | yes |
| topics.edges[].node.name | 16/16 | yes | yes | yes |
| user.createdAt | 16/16 | yes | yes | - |
| user.followersCount | 16/16 | yes | yes | - |
| user.headline | 16/16 | yes | yes | - |
| user.id | 16/16 | yes | yes | yes |
| user.name | 16/16 | yes | yes | yes |
| user.twitterUsername | 16/16 | yes | yes | - |
| user.username | 16/16 | - | yes | - |
| votesCount | 16/16 | yes | yes | - |
| website | 16/16 | yes | yes | - |
| weeklyRank | 16/16 | yes | yes | - |

## makers_header.jsonl (50 rows, 16 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| collections | 50/50 | - | yes | - |
| day | 50/50 | yes | yes | yes |
| fetched_at | 50/50 | - | yes | - |
| fetched_at_source | 50/50 | - | NO | - |
| followers | 50/50 | yes | yes | - |
| following | 50/50 | - | yes | - |
| hunted | 50/50 | - | yes | - |
| name | 50/50 | yes | yes | yes |
| posts[] | 50/50 | - | yes | - |
| products | 50/50 | - | yes | - |
| reviews | 50/50 | - | yes | - |
| roles[] | 50/50 | - | yes | - |
| stacks | 50/50 | - | yes | - |
| status | 50/50 | - | yes | - |
| upvotes | 50/50 | - | yes | - |
| username | 50/50 | - | yes | - |

## month_reread.jsonl (381 rows, 19 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| _header | 1/381 | - | yes | - |
| budget_rule | 1/381 | - | NO | - |
| commentsCount | 380/381 | yes | yes | - |
| dailyRank | 380/381 | yes | yes | - |
| dedupe_rule | 1/381 | - | NO | - |
| duplicate_ids_dropped | 1/381 | - | NO | - |
| featuredAt | 380/381 | yes | yes | - |
| fetched_at | 381/381 | - | yes | - |
| fetched_at_end | 1/381 | - | yes | - |
| id | 380/381 | yes | yes | yes |
| launch_day_PT | 380/381 | - | yes | - |
| monthlyRank | 380/381 | yes | yes | - |
| read_date_PT | 1/381 | - | NO | - |
| rows | 1/381 | - | yes | - |
| slug | 380/381 | - | yes | yes |
| source | 1/381 | - | yes | - |
| status | 1/381 | - | yes | - |
| votesCount | 380/381 | yes | yes | - |
| weeklyRank | 380/381 | yes | yes | - |

## api_comments/20261112T2345PT.jsonl (215 rows, 17 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| body | 215/215 | - | yes | - |
| comment_id | 215/215 | - | yes | - |
| commenter_followers_count | 215/215 | - | NO | - |
| commenter_user_id | 215/215 | - | yes | - |
| createdAt | 215/215 | yes | yes | - |
| day | 215/215 | yes | yes | yes |
| kind | 215/215 | - | yes | - |
| parentId | 215/215 | - | yes | - |
| post_comments_count | 215/215 | - | NO | - |
| post_id | 215/215 | - | yes | - |
| post_top_level_total | 215/215 | - | NO | - |
| repliesCount | 215/215 | - | NO | - |
| snapshot_at | 215/215 | - | yes | - |
| snapshot_tag | 215/215 | - | NO | - |
| src | 215/215 | yes | yes | - |
| username | 215/215 | - | yes | - |
| votesCount | 215/215 | yes | yes | - |

## api_hourly/20261112T2300PT.jsonl (40 rows, 7 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| followersCount | 40/40 | yes | yes | - |
| id | 40/40 | yes | yes | yes |
| kind | 40/40 | - | yes | - |
| name | 40/40 | yes | yes | yes |
| postsCount | 40/40 | - | NO | - |
| slug | 40/40 | - | yes | yes |
| snapshot_at | 40/40 | - | yes | - |

## snapshots/20261113T0430PT_api.jsonl (37 rows, 17 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| commentsCount | 37/37 | yes | yes | - |
| dailyRank | 37/37 | yes | yes | - |
| day | 37/37 | yes | yes | yes |
| featuredAt | 37/37 | yes | yes | - |
| id | 37/37 | yes | yes | yes |
| kind | 37/37 | - | yes | - |
| latestScore | 37/37 | - | yes | - |
| monthlyRank | 37/37 | yes | yes | - |
| name | 37/37 | yes | yes | yes |
| reviewsCount | 37/37 | yes | yes | - |
| reviewsRating | 37/37 | yes | yes | - |
| slug | 37/37 | - | yes | yes |
| snapshot_at | 37/37 | - | yes | - |
| snapshot_tag | 37/37 | - | NO | - |
| src | 37/37 | yes | yes | - |
| votesCount | 37/37 | yes | yes | - |
| weeklyRank | 37/37 | yes | yes | - |

## api_fills/comments_today.jsonl (118 rows, 13 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| body | 118/118 | - | yes | - |
| comment_id | 118/118 | - | yes | - |
| createdAt | 118/118 | yes | yes | - |
| fetched_at | 118/118 | - | yes | - |
| post_id | 118/118 | - | yes | - |
| post_slug | 118/118 | - | NO | - |
| since | 118/118 | - | yes | - |
| source | 118/118 | - | yes | - |
| status | 118/118 | - | yes | - |
| user.id | 118/118 | yes | yes | yes |
| user.username | 118/118 | - | yes | - |
| userId | 118/118 | - | yes | - |
| votesCount | 118/118 | yes | yes | - |

## api_fills/posts_makers_fields.jsonl (378 rows, 24 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| fetched_at | 378/378 | - | yes | - |
| id | 378/378 | yes | yes | yes |
| launch_day_PT | 378/378 | - | yes | - |
| makers[].headline | 350/378 | yes | yes | - |
| makers[].id | 350/378 | yes | yes | yes |
| makers[].name | 350/378 | yes | yes | yes |
| makers[].twitterUsername | 350/378 | yes | yes | - |
| makers[].username | 350/378 | - | yes | - |
| makers_named_count | 378/378 | - | NO | - |
| makers_redacted_count | 378/378 | - | NO | - |
| makers_total | 378/378 | - | NO | - |
| media[].type | 378/378 | yes | yes | - |
| name | 378/378 | yes | yes | yes |
| productLinks[].type | 378/378 | yes | yes | - |
| productLinks[].url | 378/378 | yes | yes | - |
| reviewsCount | 378/378 | yes | yes | - |
| reviewsRating | 378/378 | yes | yes | - |
| scope | 378/378 | - | yes | - |
| slug | 378/378 | - | yes | yes |
| source | 378/378 | - | yes | - |
| status | 378/378 | - | yes | - |
| url | 378/378 | yes | yes | - |
| website | 378/378 | yes | yes | - |
| website_note | 378/378 | - | NO | - |

## api_replies/20261112T2345PT.jsonl (7 rows, 17 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| body | 7/7 | - | yes | - |
| comment_id | 7/7 | - | yes | - |
| commenter_followers_count | 7/7 | - | NO | - |
| commenter_user_id | 7/7 | - | yes | - |
| createdAt | 7/7 | yes | yes | - |
| day | 7/7 | yes | yes | yes |
| kind | 7/7 | - | yes | - |
| parentId | 7/7 | - | yes | - |
| post_comments_count | 7/7 | - | NO | - |
| post_id | 7/7 | - | yes | - |
| post_top_level_total | 7/7 | - | NO | - |
| repliesCount | 7/7 | - | NO | - |
| snapshot_at | 7/7 | - | yes | - |
| snapshot_tag | 7/7 | - | NO | - |
| src | 7/7 | yes | yes | - |
| username | 7/7 | - | yes | - |
| votesCount | 7/7 | yes | yes | - |

## api_detail/20261112T2300PT.jsonl (37 rows, 36 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| commentsCount | 37/37 | yes | yes | - |
| createdAt | 37/37 | yes | yes | - |
| dailyRank | 37/37 | yes | yes | - |
| day | 37/37 | yes | yes | yes |
| featuredAt | 37/37 | yes | yes | - |
| id | 37/37 | yes | yes | yes |
| kind | 37/37 | - | yes | - |
| latestScore | 37/37 | - | yes | - |
| makers[].followersCount | 36/37 | yes | yes | - |
| makers[].followingCount | 36/37 | - | NO | - |
| makers[].headline | 36/37 | yes | yes | - |
| makers[].id | 36/37 | yes | yes | yes |
| makers[].name | 36/37 | yes | yes | yes |
| makers[].twitterUsername | 36/37 | yes | yes | - |
| makers[].username | 36/37 | - | yes | - |
| monthlyRank | 37/37 | yes | yes | - |
| name | 37/37 | yes | yes | yes |
| productLinks[].type | 37/37 | yes | yes | - |
| productLinks[].url | 37/37 | yes | yes | - |
| reviewsCount | 37/37 | yes | yes | - |
| reviewsRating | 37/37 | yes | yes | - |
| slug | 37/37 | - | yes | yes |
| snapshot_at | 37/37 | - | yes | - |
| snapshot_tag | 37/37 | - | NO | - |
| tagline | 37/37 | yes | yes | yes |
| thumbnail.url | 37/37 | yes | yes | - |
| topics.nodes[].name | 37/37 | yes | yes | yes |
| topics.nodes[].slug | 37/37 | - | yes | yes |
| user.followersCount | 37/37 | yes | yes | - |
| user.followingCount | 37/37 | - | NO | - |
| user.id | 37/37 | yes | yes | yes |
| user.username | 37/37 | - | yes | - |
| userId | 37/37 | - | yes | - |
| votesCount | 37/37 | yes | yes | - |
| website | 37/37 | yes | yes | - |
| weeklyRank | 37/37 | yes | yes | - |

## api_comments_catchup/catchup_20261113T0650Z.jsonl (22 rows, 14 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| body | 22/22 | - | yes | - |
| catchup_for | 22/22 | - | NO | - |
| comment_id | 22/22 | - | yes | - |
| commenter_followers_count | 22/22 | - | NO | - |
| commenter_user_id | 22/22 | - | yes | - |
| createdAt | 22/22 | yes | yes | - |
| day | 22/22 | yes | yes | yes |
| fetched_at | 22/22 | - | yes | - |
| kind | 22/22 | - | yes | - |
| parentId | 22/22 | - | yes | - |
| post_id | 22/22 | - | yes | - |
| src | 22/22 | yes | yes | - |
| username | 22/22 | - | yes | - |
| votesCount | 22/22 | yes | yes | - |

## live/board_ts.jsonl (3886 rows, 14 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| daily_rank | 3886/3886 | - | yes | yes |
| day | 3886/3886 | yes | yes | yes |
| fetched_at | 3886/3886 | - | yes | - |
| is_page_view | 3886/3886 | - | yes | - |
| launch_id | 3886/3886 | - | yes | - |
| note | 3886/3886 | - | yes | - |
| page | 3886/3886 | - | yes | - |
| position | 3886/3886 | - | yes | - |
| section | 3886/3886 | - | yes | - |
| slug | 3886/3886 | - | yes | yes |
| snapshot_id | 3886/3886 | - | yes | - |
| snapshot_ts | 3886/3886 | - | yes | - |
| source | 3886/3886 | - | yes | - |
| votes_shown | 3886/3886 | - | NO | - |

## live/comments_ts.jsonl (501 rows, 20 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| body | 501/501 | - | yes | - |
| comment_id | 501/501 | - | yes | - |
| commenter_followers_count | 501/501 | - | NO | - |
| commenter_user_id | 501/501 | - | yes | - |
| created_at | 501/501 | - | yes | - |
| created_at_kind | 501/501 | - | NO | - |
| day | 501/501 | yes | yes | yes |
| fetched_at | 501/501 | - | yes | - |
| is_hunter | 501/501 | - | yes | - |
| is_maker | 501/501 | - | yes | - |
| launch_id | 501/501 | - | yes | - |
| parent_id | 501/501 | - | yes | - |
| replies_count | 31/501 | - | NO | - |
| slug | 501/501 | - | yes | yes |
| snapshot_id | 501/501 | - | yes | - |
| snapshot_ts | 501/501 | - | yes | - |
| source | 501/501 | - | yes | - |
| user_id | 501/501 | - | yes | - |
| username | 501/501 | - | yes | - |
| votes_at_fetch | 501/501 | - | yes | - |

## live/content_ts.jsonl (38 rows, 14 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| content_hash | 38/38 | - | NO | - |
| day | 38/38 | yes | yes | yes |
| fetched_at | 38/38 | - | yes | - |
| html_saved | 38/38 | - | NO | - |
| launch_id | 38/38 | - | yes | - |
| name | 38/38 | yes | yes | yes |
| note | 38/38 | - | yes | - |
| slug | 38/38 | - | yes | yes |
| snapshot_id | 38/38 | - | yes | - |
| snapshot_ts | 38/38 | - | yes | - |
| source | 38/38 | - | yes | - |
| tagline | 38/38 | yes | yes | yes |
| topics[] | 38/38 | yes | yes | yes |
| website | 38/38 | yes | yes | - |

## live/coverage_ts.jsonl (105 rows, 29 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| budget_today | 105/105 | - | NO | - |
| clean_day | 105/105 | - | NO | - |
| day | 105/105 | yes | yes | yes |
| ended_at | 105/105 | - | NO | - |
| failed | 105/105 | - | yes | - |
| fetched_200 | 105/105 | - | yes | - |
| file | 105/105 | - | yes | - |
| homepage_reads | 105/105 | - | NO | - |
| late_over_20min | 105/105 | - | NO | - |
| late_s | 105/105 | - | NO | - |
| launches_expected | 105/105 | - | yes | - |
| new_comments | 105/105 | - | NO | - |
| next_day_budget | 105/105 | - | NO | - |
| pages_used | 105/105 | - | NO | - |
| proxy_MB | 105/105 | - | NO | - |
| reads_of_slot | 105/105 | - | NO | - |
| route4_budget_day | 105/105 | - | NO | - |
| route4_budget_state | 105/105 | - | NO | - |
| snapshot_id | 105/105 | - | yes | - |
| snapshot_ts | 105/105 | - | yes | - |
| source | 105/105 | - | yes | - |
| span_s | 105/105 | - | NO | - |
| started_at | 105/105 | - | NO | - |
| tier_reached | 105/105 | - | NO | - |
| view_cf_colo | 105/105 | - | NO | - |
| view_exit_country | 105/105 | - | NO | - |
| view_logged_out | 105/105 | - | NO | - |
| view_sort_mode | 105/105 | - | NO | - |
| view_user_agent | 105/105 | - | NO | - |

## live/people_ts.jsonl (2264 rows, 14 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| day | 2264/2264 | yes | yes | yes |
| fetch_status | 2264/2264 | - | yes | - |
| fetched_at | 2264/2264 | - | yes | - |
| followers | 2264/2264 | yes | yes | - |
| following | 254/2264 | - | yes | - |
| launch_ids[] | 2264/2264 | - | yes | - |
| role | 2264/2264 | - | yes | - |
| snapshot_id | 2264/2264 | - | yes | - |
| snapshot_ts | 2264/2264 | - | yes | - |
| source | 2264/2264 | - | yes | - |
| user_id | 2264/2264 | - | yes | - |
| username | 2264/2264 | - | yes | - |
| x_fetched_at | 2264/2264 | - | yes | - |
| x_followers | 2264/2264 | - | yes | - |

## live/posts_ts.jsonl (3935 rows, 28 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| badges | 3886/3935 | - | yes | - |
| comments_count_at_fetch | 3886/3935 | - | yes | - |
| daily_rank_at_fetch | 3886/3935 | - | yes | - |
| day | 3935/3935 | yes | yes | yes |
| error | 3886/3935 | - | yes | - |
| featured_at | 3886/3935 | - | yes | - |
| fetch_status | 3935/3935 | - | yes | - |
| fetched_at | 3935/3935 | - | yes | - |
| first_seen_snapshot | 3935/3935 | - | NO | - |
| hide_votes_count | 3886/3935 | - | yes | - |
| hide_votes_count_src | 3886/3935 | - | NO | - |
| homepage_position | 3886/3935 | - | yes | - |
| hunter | 3886/3935 | yes | yes | - |
| latestScore | 3886/3935 | - | yes | - |
| launchDayScore | 3886/3935 | - | yes | - |
| launch_id | 3935/3935 | - | yes | - |
| launch_state | 3886/3935 | - | yes | - |
| list_source | 3935/3935 | - | NO | - |
| makers | 3886/3935 | yes | yes | yes |
| monthly_rank_at_fetch | 2072/3935 | - | NO | - |
| note | 3886/3935 | - | yes | - |
| reviews_count | 3886/3935 | - | yes | - |
| slug | 3935/3935 | - | yes | yes |
| snapshot_id | 3935/3935 | - | yes | - |
| snapshot_ts | 3935/3935 | - | yes | - |
| source | 3935/3935 | - | yes | - |
| votes_at_fetch | 3886/3935 | - | yes | - |
| weekly_rank_at_fetch | 3886/3935 | - | yes | - |

## live/products_ts.jsonl (668 rows, 14 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| day | 668/668 | yes | yes | yes |
| fetch_status | 668/668 | - | yes | - |
| fetched_at | 668/668 | - | yes | - |
| followers | 668/668 | yes | yes | - |
| note | 668/668 | - | yes | - |
| product_links[].type | 222/668 | yes | yes | - |
| product_links[].url | 222/668 | yes | yes | - |
| product_slug | 668/668 | - | yes | - |
| reviews_count | 668/668 | - | yes | - |
| reviews_rating | 668/668 | - | yes | - |
| snapshot_id | 668/668 | - | yes | - |
| snapshot_ts | 668/668 | - | yes | - |
| source | 668/668 | - | yes | - |
| thumbnail_url | 222/668 | - | NO | - |

## precut/20261113T0428PT_api.jsonl (37 rows, 17 field paths)

| field | present | feature build | any code | warehouse launches |
|---|---|---|---|---|
| commentsCount | 37/37 | yes | yes | - |
| dailyRank | 37/37 | yes | yes | - |
| day | 37/37 | yes | yes | yes |
| featuredAt | 37/37 | yes | yes | - |
| id | 37/37 | yes | yes | yes |
| kind | 37/37 | - | yes | - |
| latestScore | 37/37 | - | yes | - |
| monthlyRank | 37/37 | yes | yes | - |
| name | 37/37 | yes | yes | yes |
| reviewsCount | 37/37 | yes | yes | - |
| reviewsRating | 37/37 | yes | yes | - |
| slug | 37/37 | - | yes | yes |
| snapshot_at | 37/37 | - | yes | - |
| snapshot_tag | 37/37 | - | NO | - |
| src | 37/37 | yes | yes | - |
| votesCount | 37/37 | yes | yes | - |
| weeklyRank | 37/37 | yes | yes | - |

## Capped / incomplete reads

| read | cap | effect | evidence |
|---|---|---|---|
| api_comments/<snapshot>.jsonl | at most 20 top-level comments per launch per snapshot | none after union over the day's snapshots | Nov 12: 2 of 37 launches above 20 in one file (41, 31 top-level); union over 65 files: 0 launches short; first reads Nov 1-13: 0 capped (Nov 1-3 reads were late re-reads with up to 3 capped) |
| board_ts homepage rows | homepage read only on some days | homepage order NOT captured each snapshot | homepage rows only Nov 4 (39) and Nov 8 (861); Nov 1-3, 5-7, 9-13: api_v2_ranking rows only |
| posts_ts.homepage_position | never filled | no per-snapshot homepage position | 0 of 3,935 rows (Nov 12), 0 of 395 (Nov 13 so far) |
| board_ts leaderboard_daily | page 1 only (20 items, has_next_page) | ranks 21+ absent from the page read (the API ranking rows cover them) | rows only Nov 4 (37), Nov 7 (340), Nov 8 (340) |
| daily list makers (raw/daily/<d>/*.json) | featured list redacts makers | 48 maker entries with id 0 / no username on Nov 12 | api_fills/posts_makers_fields: 320 redacted of 713 in the list read; per-post post(id) fills recover them |
| people_ts / followers_ts | followers page 1 only (hourly) | follower usernames beyond page 1 not captured | live/README: 'follower usernames first seen in an hourly page-1 read' |
| warehouse launches | 15 columns | commentsCount, featuredAt, createdAt, website, media, reviews, maker/hunter details, comment-level fields not in the warehouse; the feature build reads the JSON files directly | information_schema |

