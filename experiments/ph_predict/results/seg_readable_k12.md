# Audience segments (K=12) and three cold-start launches

Segments: k-means on 6,593 complete Product Hunt people from their upvotes before Sep 1 (product embedding, product attributes, topics). Each is described by the attributes and topics it over-upvotes relative to everyone. Predictions use only Sep 1 - Oct 19 behaviour; the launches are from Oct 20 - Nov 8 and their teams had never launched before.

| segment | people | over-upvotes (attributes) | over-upvotes (topics) |
|---|---|---|---|
| S0 | 526 | mat_feature_update, mat_major_update, aud_designers, cat_design_creative | Development, Hardware, Design Tools, Task Management |
| S1 | 1079 | aud_enterprises, cat_finance, aud_sales, plat_api_sdk | Security, Pitch NYC, Hiring, Fintech |
| S2 | 531 | cat_marketing_sales, aud_founders, cat_ai_assistant_or_agent, aud_sales | Marketing automation, E-Commerce, OpenAI Day, Search |
| S3 | 760 | cat_other, plat_mac, cat_security_privacy, price_free | Menu Bar Apps, Apple, Mac, Music |
| S4 | 173 | plat_cli, cat_education, cat_design_creative, aud_creators | Website Builder, Photo & Video, Development, Vercel Day |
| S5 | 232 | mat_relaunch, plat_cli, plat_windows, open_source | Open Source, GitHub, YC Application, Marketing automation |
| S6 | 703 | open_source, price_free, plat_cli, cat_developer_tools | Open Source, GitHub, Security, Developer Tools |
| S7 | 437 | cat_health_fitness, cat_social_communication, aud_students, mkt_b2c | Health & Fitness, Travel, iOS, Languages |
| S8 | 1556 | cat_social_communication, cat_health_fitness, cat_finance, cat_education | Email, Alpha, Writing, Android |
| S9 | 436 | cat_marketing_sales, aud_marketers, aud_sales, aud_founders | SEO, Advertising, Alpha, Marketing |
| S10 | 128 | cat_data_analytics, aud_enterprises, aud_students, cat_finance | Data & Analytics, Analytics, SaaS, Calendar |
| S11 | 32 | aud_marketers, mat_major_update, aud_designers, cat_design_creative | Search, Vercel Day, API, No-Code |

## Screen Studio 4.0 (2026-11-01)
_Glass Loupe, Camera Cutout, Edit by Transcript, and more_

Attributes: #Marketing, #Productivity, #Video, aud_creators, aud_developers, aud_marketers, cat_productivity, mat_major_update, mkt_b2b, plat_mac, price_not_stated

Segment voters: 37 votes from 158 people who voted that day.

| | predicted | actual (votes / exposed, lift) |
|---|---|---|
| top 1 | S4 (plat cli, education; Website Builder, Photo & Video) | S0 (mat feature update, mat major update; Development, Hardware): 4/10, +0.46 |
| top 2 | S2 (marketing sales, for founders; Marketing automation, E-Commerce) | S8 (social communication, health fitness; Email, Alpha): 8/21, +0.45 |
| bottom | S7 (health fitness, social communication; Health & Fitness, Travel) | S2 (marketing sales, for founders; Marketing automation, E-Commerce): 1/20, -1.26 |

Actual rank of the predicted top segment: 8 of 12; of the predicted bottom: 5 of 12.

## Embage (2026-11-01)
_Build agent for your customers, run workflows, analyzed. _

Attributes: #Artificial Intelligence, agent, ai_native, aud_consumers, aud_developers, aud_enterprises, aud_marketers, aud_sales, cat_ai_assistant_or_agent, developer_tool, mat_new_product, mkt_both, plat_api_sdk, plat_web, price_not_stated

Segment voters: 31 votes from 158 people who voted that day.

| | predicted | actual (votes / exposed, lift) |
|---|---|---|
| top 1 | S4 (plat cli, education; Website Builder, Photo & Video) | S1 (for enterprises, finance; Security, Pitch NYC): 17/42, +0.70 |
| top 2 | S1 (for enterprises, finance; Security, Pitch NYC) | S9 (marketing sales, for marketers; SEO, Advertising): 3/9, +0.45 |
| bottom | S7 (health fitness, social communication; Health & Fitness, Travel) | S2 (marketing sales, for founders; Marketing automation, E-Commerce): 1/20, -1.13 |

Actual rank of the predicted top segment: 4 of 12; of the predicted bottom: 10 of 12.

## Dedica (2026-10-28)
_Check if AI agents can use your website_

Attributes: #Developer Tools, ai_native, aud_developers, aud_teams, cat_developer_tools, developer_tool, mat_new_product, mkt_b2b, plat_web, price_free

Segment voters: 43 votes from 215 people who voted that day.

| | predicted | actual (votes / exposed, lift) |
|---|---|---|
| top 1 | S4 (plat cli, education; Website Builder, Photo & Video) | S0 (mat feature update, mat major update; Development, Hardware): 5/8, +0.99 |
| top 2 | S5 (mat relaunch, plat cli; Open Source, GitHub) | S10 (data analytics, for enterprises; Data & Analytics, Analytics): 1/1, +0.85 |
| bottom | S7 (health fitness, social communication; Health & Fitness, Travel) | S1 (for enterprises, finance; Security, Pitch NYC): 10/135, -0.97 |

Actual rank of the predicted top segment: 10 of 12; of the predicted bottom: 7 of 12.
