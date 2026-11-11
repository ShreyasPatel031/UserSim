# Which audiences favour which kinds of product (K=12 segments)

How to read this: Product Hunt people were grouped into 12 audiences by what they upvoted before Sep 1. For each kind of product (an attribute or topic), we learned from one half of the people (Sep 1 - Oct 19) which audiences over- or under-vote it, after removing each audience's overall activity and each launch's popularity. We then checked against the OTHER half of the people on new launches (Oct 20 - Nov 8). Across all product kinds the agreement is a rank correlation of about 0.25 (0.19 on launches from brand-new teams), against about 0 for a shuffled control. It describes audiences in aggregate; it does not reliably predict a single person's vote.

## The 12 audiences

| audience | people | over-upvotes (attributes) | over-upvotes (topics) |
|---|---|---|---|
| S0 | 264 | finance, for enterprises, security privacy, other | Pitch NYC, Fintech, Data & Analytics, YC Application |
| S1 | 398 | marketing sales, for sales, for marketers, for founders | Marketing automation, SEO, Sales, E-Commerce |
| S2 | 706 | developer tools, api sdk, developer tool, open source | Software Engineering, API, Security, Developer Tools |
| S3 | 1288 | for sales, for enterprises, ai assistant or agent, for teams | Hiring, Meetings, Security, OpenAI Day |
| S4 | 234 | education, for students, b2c, ios | Languages, Education, Music, Games |
| S5 | 33 | education, for students, b2c, design creative | Photo & Video, User Experience, Vercel Day, Education |
| S6 | 614 | feature update, major update, design creative, for designers | Development, Design Tools, Hardware, Android |
| S7 | 385 | health fitness, social communication, other, b2c | Travel, Health & Fitness, iOS, Calendar |
| S8 | 312 | relaunch, cli, open source, windows | Open Source, GitHub, Development, YC Application |
| S9 | 1501 | other, mac, security privacy, free | Menu Bar Apps, Mac, Apple, Privacy |
| S10 | 432 | for creators, design creative, for designers, for marketers | Website Builder, Video, OpenAI Day, E-Commerce |
| S11 | 426 | data analytics, social communication, health fitness, for students | Data & Analytics, Analytics, Calendar, SEO |

## Ten largest product kinds: predicted vs actual audiences

| product kind | test launches (from new teams) | test votes | predicted top 3 | actual top 3 | predicted bottom 3 | actual bottom 3 | rank corr. |
|---|---|---|---|---|---|---|---|
| new product | 460 (210) | 912 | S3, S4, S8 | S1, S4, S11 | S9, S6, S1 | S0, S8, S10 | -0.21 |
| for developers | 390 (155) | 790 | S9, S2, S6 | S10, S2, S8 | S3, S4, S1 | S7, S4, S1 | +0.42 |
| ai native | 376 (115) | 782 | S3, S10, S2 | S10, S8, S3 | S9, S1, S8 | S6, S4, S9 | +0.39 |
| web | 314 (97) | 693 | S1, S3, S4 | S10, S8, S0 | S9, S10, S7 | S7, S9, S6 | +0.07 |
| b2b | 320 (101) | 674 | S3, S8, S0 | S10, S8, S2 | S4, S7, S10 | S7, S6, S9 | +0.37 |
| #Artificial Intelligence | 294 (87) | 573 | S3, S2, S10 | S3, S0, S7 | S9, S1, S4 | S6, S10, S9 | +0.38 |
| agent | 255 (75) | 499 | S3, S2, S0 | S10, S1, S3 | S1, S4, S10 | S6, S9, S2 | -0.13 |
| developer tool | 290 (110) | 493 | S9, S8, S6 | S8, S10, S0 | S3, S4, S1 | S7, S4, S11 | +0.55 |
| for teams | 191 (58) | 438 | S2, S7, S11 | S11, S1, S10 | S10, S6, S4 | S6, S4, S2 | +0.09 |
| developer tools | 255 (103) | 418 | S8, S9, S2 | S8, S0, S10 | S3, S4, S1 | S7, S1, S3 | +0.66 |

Over these 10: predicted top-3 audiences that were in the actual top 3: 10 of 30 (random about 7.5); bottom-3: 12 of 30; mean rank correlation +0.26.

Audience key: S0 finance, for enterprises / Pitch NYC, Fintech; S1 marketing sales, for sales / Marketing automation, SEO; S2 developer tools, api sdk / Software Engineering, API; S3 for sales, for enterprises / Hiring, Meetings; S4 education, for students / Languages, Education; S5 education, for students / Photo & Video, User Experience; S6 feature update, major update / Development, Design Tools; S7 health fitness, social communication / Travel, Health & Fitness; S8 relaunch, cli / Open Source, GitHub; S9 other, mac / Menu Bar Apps, Mac; S10 for creators, design creative / Website Builder, Video; S11 data analytics, social communication / Data & Analytics, Analytics.
