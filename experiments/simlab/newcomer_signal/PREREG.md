# Pre-registration: a pre-launch signal for first-time hunters

Written 2026-11-17, before any model run; committed before the test.

## Dating finding, before any test

**The strict rule leaves 9 launches.** The orchestrator's rule was to use a person's file only if it was pulled before the launch day.
- Every person file in the store was pulled between Nov 4 and Nov 16 2026.
- Of 2,856 newcomer launches (Apr 1 – Nov 12), only 9 have a hunter pulled before the launch day, all from Nov 6 or later.
- So no backward test is possible under that rule. It can only be run forward.

**Undated inputs, excluded from any backward test:**
- **Upvotes:** 92% are dated only by when they were read ("snapshot"). Own upvote activity in the 30 days before a launch cannot be dated.
- **Follow lists:** also undated. In-store followers, active-voter followers and team reach are excluded too.

**Makers cannot be used live.** Maker identity is redacted in the 00:05 reads, so maker-based inputs could not run at 00:05. Only the hunter is known then.

## What can be tested backward: dated content of later-pulled files

The store's "hunted" and "launched" events carry exact launch dates going back to 2013. A hunt or launch dated before the launch day is a fact that existed before it, whenever the file was read.

**Features (hunter only), counting only events dated strictly before the launch day:**
- H1: log1p(hunter's hunts on Product Hunt, all time). Our table's hunter record starts in Jan 2025.
- H2: log1p(hunter's launches as a maker, all time).
- H3: log1p(days since the hunter's most recent hunt or launch). Missing if none.
- H4: hunter found in the store (0/1). Without it, the features would be missing for hunters not in the store.

**Selection check.** 79.3% of newcomer launches outside the final top 10 have their hunter in the store, against 81.5% of those inside it. That is close; the effect of H4 alone is reported separately.

## Test

- Arm-3 rebuild with and without H1–H4, month-forward, the same 195 days (Apr 1 – Nov 12 2026), 3 seeds.
- Paired against arm 3, bootstrap over days (2,000).
- **Primary:** top 10 on all launches.
- **Secondary:**
  - top 3 and top 5;
  - top-10 recall of newcomer launches (no record in our table) that finished top 10.

## Adopt if

- the top-10 interval is above 0, **and**
- top 3 is not down by more than 1 point.

Because the inputs come from files read after the launches, any adoption also needs the orchestrator's sign-off on the dating argument, and a forward check.
