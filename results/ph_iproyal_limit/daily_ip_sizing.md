# Daily-only IP sizing (verified 2026-11-12 PT)

## Tests run

1. **GCS** `ph_at_launch/monthly_reread/2026-11/2026-11-12.jsonl` — downloaded and parsed.
2. **Plain cloud-agent egress** → `https://www.producthunt.com/` = **HTTP 403** (no Camoufox).
3. **Last full daily people job** `ph_people_daily/2026-11-03/` — line counts and README status from GCS.
4. **IPRoyal ladder** `L2_modest` — `ok`, mean 1.0 complete/min (same ISP family as daily steady).

## Official API (no proxy)

| Item | Result |
|------|--------|
| MTD re-read | **391** featured launches, header + 391 data lines |
| Fields | `votesCount`, `dailyRank`, `weeklyRank`, `monthlyRank` — **391/391** populated |
| Rate limits | `rate_limited_days_missing_or_partial`: **[]** |
| Status | `DRAFT until agents verify` (content checks out) |

**IPs required: 0** — stays on Data Feeder host.

## Browser jobs that need sticky ISP (Camoufox)

| Job | Measured / bound | Duration | IPs |
|-----|------------------|----------|-----|
| Once/day heavy page pass (posts/makers/products) | Data Feeder est. **25–45 min** | short burst | **1** |
| Daily people upvote/following page1 | **131 people** on 2026-11-03; pool note allows up to **~700** pages on heavy days | **< 2 h** at light mode | **1** |

Jobs can share **one** IP if scheduled sequentially (~**2 h** worst case). For **steady state** (heavy pass and people refresh not colliding, no 429 bleed-through): **2 dedicated IPs**.

**Recommended daily pool: 2 IPs** for steady parallel; **3** only if you refuse to time-slice jobs.

## Measured minimum (2026-11-12)

| Mode | IPs | Evidence |
|------|-----|----------|
| **Serialized** (heavy → people, one window) | **1** | Spain ISP `L1_polite`: **0.8** whole-person complete/min, **0× 429** in 10 min soak. Daily page1 ≈ **16×** lighter → **~13 light-people/min**. Typical day **131** people + heavy **~45 min** ≈ **~26 min** serial on one IP. Cap day **700** people ≈ **~89 min** serial still under **2 h**. |
| **Steady parallel** (heavy + people same morning) | **2** | Same bucket per IP; Finland 2-VM soak showed **0** effective throughput (CF/geo). Spain control validates rate model; use **2 IPs** for parallel daily ops. |
| **Official API** | **0** | GCS monthly re-read verified. |

**Finland ×5 (order 88326929):** fetched from IPRoyal API; **4/5** hard **403** on plain PH home via proxy; VM soak **0 complete/min**. **Do not** assign Finland to daily until each IP passes Camoufox `browser_open` + light completes (Spain `213.220.25.150` passes).

## Answer vs your 5 provisional IPs

| Pool | IPs |
|------|-----|
| **Daily feeds (browser)** | **1 minimum (scheduled), 2 steady parallel** |
| **Official API loop** | **0** |
| **Under 5?** | **Yes** — allocate **3** to daily, **2** to historical `pdeep` at L3 (~2.2 complete/min) until a larger historical order |

## Role map (apply when `secrets/iproyal.pool` is filled)

See `scripts/vm/ph_iproyal_daily_pool.sh` and `scripts/vm/iproyal.pool.example`.
