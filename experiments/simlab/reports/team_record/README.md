# Team track record (stopped at the coverage gate)

**What clean 00:05 already uses** (experiments/ph_predict/forecast.py on main, plus ph-ops features.py):
- Hunter history is in: hist_hunter_n / _rel / _top5, ph_hunter_followers, ph_hunter_age_d.
- All maker history is excluded: hist_maker_*, ph_maker, x_maker.

**New candidates.** Each uses only launches dated strictly before the target day, taken from complete people-store pulls (made and hunted tabs, v3, Nov 10 snapshot):
- First-named maker: past launch count, best and median ln votes, top-5 count, days since the last launch.
- Relaunch flag (same slug stem or name) and the prior launch's votes.
- Hunter median past final rank.

**Coverage over 6,024 ranked launches, Mar 1 – Nov 10:**

| what | share of launches |
|---|---|
| maker identified and complete in store | 23.1% |
| maker has a past launch before the day | 3.1% |
| relaunch | 3.1% |
| hunter has past hunts in store | 1.8% |
| **any new feature** | **5.9%** |

That is below the 15% gate, so I stopped and ran no leave-day-out.

**Read timing.** Past launches' final votes and ranks are frozen. Tab membership was read in November, but launches after the target day are dropped by date, so no count could have changed.

**Why coverage is low.** Most complete people in the store are voters, not makers. The maker's first launch in the window is, by construction, a launch with no prior one.
