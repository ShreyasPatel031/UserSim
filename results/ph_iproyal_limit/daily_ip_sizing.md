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

**Recommended daily pool: 3 IPs** — third is overlap/spare (bad-list day toward 700 pages, or heavy pass + people same morning).

## Answer vs your 5 provisional IPs

| Pool | IPs |
|------|-----|
| **Daily feeds (browser + reserve)** | **2 required, 3 recommended** |
| **Official API loop** | **0** |
| **Under 5?** | **Yes** — allocate **3** to daily, **2** to historical `pdeep` at L3 (~2.2 complete/min) until a larger historical order |

## Role map (apply when `secrets/iproyal.pool` is filled)

See `scripts/vm/ph_iproyal_daily_pool.sh` and `scripts/vm/iproyal.pool.example`.
