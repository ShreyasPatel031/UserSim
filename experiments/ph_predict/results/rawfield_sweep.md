# Raw-field sweep

69 fields; 29 excluded (arm-2 input / clean policy / identifier); 40 candidates; 28 knowable at 00:05; 2 clear of 0 on 184 days.

| field | status | 00:05 check | rho with arm-2 residual [95%] | days | coverage |
|---|---|---|---|---|---|
| name:nonempty | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| tagline:nonempty | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| slug:len | knowable | present_0005 1.0, spearman 0.988, n 421 | -0.034 [-0.066, -0.002] | 184 | 1.0 |
| slug:nonempty | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| website:len | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| website:nonempty | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| website:words | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| votesCount | leaky | why outcome field | - | - | - |
| commentsCount | leaky | why outcome field | - | - | - |
| dailyRank | leaky | why outcome field | - | - | - |
| weeklyRank | leaky | why outcome field | - | - | - |
| monthlyRank | leaky | why outcome field | - | - | - |
| description:nonempty | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| description:words | knowable | present_0005 1.0, spearman 0.995, n 421 | +0.020 [-0.014, +0.055] | 184 | 0.999 |
| reviewsCount | leaky | why outcome field | - | - | - |
| reviewsRating | leaky | why outcome field | - | - | - |
| media[].type:nonempty | knowable | present_0005 1.0, spearman 0.977, n 421 | +0.021 [-0.011, +0.053] | 184 | 1.0 |
| user.username:len | knowable | present_0005 1.0, spearman 0.999, n 421 | +0.008 [-0.022, +0.038] | 184 | 1.0 |
| user.username:nonempty | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| user.name:len | knowable | present_0005 1.0, spearman 0.991, n 421 | -0.011 [-0.041, +0.018] | 184 | 1.0 |
| user.name:nonempty | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| user.headline:len | knowable | present_0005 1.0, spearman 0.986, n 377 | +0.026 [-0.008, +0.059] | 184 | 0.943 |
| user.headline:nonempty | knowable | present_0005 1.0, exact_agree 0.997, n 377 | +0.046 [-0.011, +0.100] | 56 | 0.943 |
| user.followersCount | leaky | present_0005 1.0, spearman 0.949, n 421, why stored value includes outcome-dependent post-launch follower growth (log stored/00:05: others +0.89, top 3 +0.06) | +0.081 [+0.046, +0.115] | 184 | 1.0 |
| user.twitterUsername:len | knowable | present_0005 0.961, spearman 0.999, n 232 | -0.006 [-0.049, +0.039] | 161 | 0.558 |
| user.twitterUsername:nonempty | knowable | present_0005 0.961, exact_agree 1.0, n 232 | -0.007 [-0.059, +0.043] | 144 | 0.558 |
| drv.created_min_pt | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 8 | - |
| drv.featured_minus_created_h | knowable | present_0005 1.0, exact_agree 1.0, n 421 | - | 0 | - |
| drv.slug_suffix_n | knowable | present_0005 1.0, spearman 0.985, n 421 | +0.046 [+0.009, +0.083] | 183 | 1.0 |
| drv.name_has_digit | knowable | present_0005 1.0, exact_agree 1.0, n 421 | +0.000 [-0.035, +0.035] | 154 | 1.0 |
| drv.hunter_has_twitter | knowable | present_0005 1.0, exact_agree 0.976, n 421 | +0.002 [-0.032, +0.038] | 184 | 1.0 |
| drv.hunter_headline_len | knowable | present_0005 1.0, spearman 0.989, n 421 | +0.027 [-0.006, +0.059] | 184 | 1.0 |
| tagline:words | knowable | present_0005 0.991, spearman 0.968, n 339 | -0.023 [-0.056, +0.010] | 177 | 0.78 |
| user.twitterUsername:null | knowable | present_0005 0.995, exact_agree 1.0, n 189 | - | 0 | - |
| user.headline:null | knowable | present_0005 1.0, exact_agree 1.0, n 44 | - | 0 | - |
| slug:words | leaky | why stored on only 9 launches in the window | - | - | - |
| dailyRank:null | leaky | why outcome field | - | - | - |
| weeklyRank:null | leaky | why outcome field | - | - | - |
| monthlyRank:null | leaky | why outcome field | - | - | - |
| name:words | leaky | why stored on only 0 launches in the window | - | - | - |

Excluded: id:len (identifier / timestamp text); id:nonempty (identifier / timestamp text); name:len (arm-2 input (ph_name_len)); tagline:len (arm-2 input (ph_tagline_len)); createdAt:len (identifier / timestamp text); createdAt:nonempty (identifier / timestamp text); featuredAt:len (identifier / timestamp text); featuredAt:nonempty (identifier / timestamp text); description:len (arm-2 input (ph_desc_len)); topics.edges:n (arm-2 input (ph_n_topics)); topics.edges[].node:nonempty (arm-2 input (ph_n_topics)); topics.edges[].node.name:nonempty (arm-2 input (ph_n_topics)); media:n (arm-2 input (ph_n_media)); makers:n (arm-2 input (ph_n_makers)); makers[].twitterUsername:nonempty (clean policy: needs named makers); makers[].headline:nonempty (clean policy: needs named makers); makers[].username:nonempty (clean policy: needs named makers); makers[].name:nonempty (clean policy: needs named makers); makers[].createdAt:nonempty (clean policy: needs named makers); makers[].websiteUrl:nonempty (clean policy: needs named makers); makers[].followersCount:nonempty (clean policy: needs named makers); makers[].followersCount:mean (clean policy: needs named makers); makers[].followersCount:max (clean policy: needs named makers); makers[].id:nonempty (clean policy: needs named makers); user.id:len (identifier / timestamp text); user.id:nonempty (identifier / timestamp text); user.createdAt:len (identifier / timestamp text); user.createdAt:nonempty (identifier / timestamp text); drv.hunter_age_d_at_create (arm-2 input (ph_hunter_age_d))

Picked for the arm-2 test: ['drv.slug_suffix_n', 'slug:len']
