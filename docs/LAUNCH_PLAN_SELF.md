# Launch plan for a maker with 0 followers and no launches (UserSim as its own customer)

Run Nov 17 03:10–03:25Z on the pipeline VM, read-only. Code: `experiments/launch_plan/counterfactual_arm2.py`. Raw output:
`counterfactual_arm2.out`.

## Method
- **Model.** The published midnight model (arm 2, LightGBM, 5 seeds), trained on all days before Sep 21 2026.
- **Test days.** Each test launch is dropped into every real line-up from Sep 21 to Nov 15 2026 (56 days, 8 of each weekday).
- **Rank and probability.** The predicted rank is turned into P(top 3/5/10) using how often the model's predicted rank landed
  in the real top 3/5/10 on those same days. For example, predicted #1 lands in the real top 5 82% of the time, and predicted
  #7 only 32%. On these days the model hits 60.7% of the top 3.
- **Interval.** The 95% interval on P(top 5) is a bootstrap over days.
- **Not causal.** This is what the model predicts for a launch with these traits. "Team of 5" partly stands for "a company
  that has 5 people who bring their own networks". Changing the number on the form does not buy that.

## The base case: you, today
Self-hunted, account 60 days old, 1 maker, 6 images plus video, a median pitch, no launch-day posts, AI topic:
**median predicted rank 25. P(top 5) 2.3% [1.6, 3.3]. P(top 10) 11.6%.**

## One change at a time, from the base case

| Change | Median rank | P(top 3) | P(top 5) [95%] | P(top 10) |
|---|---|---|---|---|
| Base | 25.5 | 0.6 | 2.3 [1.6, 3.3] | 11.6 |
| **Posted by an active hunter (median record: 66 launches, 47% top 5)** | **10** | **6.9** | **17.6 [14.1, 21.2]** | **47.1** |
| Posted by a top-10% hunter (508 launches, 77% top 5) | 9 | 8.3 | 21.7 [18.2, 25.5] | 53.0 |
| Team of 5 makers on the page | 12 | 3.7 | 10.3 [7.6, 12.9] | 33.5 |
| Team of 3 | 16 | 1.9 | 5.3 [3.7, 7.4] | 21.8 |
| Pitch score 85 (Gemini read of the tagline and description) | 15.5 | 2.1 | 6.0 [4.3, 8.0] | 23.6 |
| Pitch score 75 | 16 | 1.9 | 5.4 [3.8, 7.3] | 21.3 |
| Founder posts plus organic coverage (1 press, 1 HN, 1 Reddit) | 16 | 2.0 | 5.6 [3.9, 7.4] | 22.1 |
| Founder posts only (3 posts on launch day) | 20 | 0.9 | 3.2 [2.3, 4.4] | 15.1 |
| Your own account 3 years old instead of 60 days | 21 | 0.8 | 3.0 [2.0, 4.2] | 13.9 |
| Company X account | 23 | 0.7 | 2.5 | 12.7 |
| 9 media + video vs 3 media, no video | 24.5 vs 27 | ≈ | 2.4 vs 2.2 | 12.0 vs 10.7 |
| Topic: AI vs AI+dev vs non-AI | 25.5 / 26.5 / 23.5 | ≈ | 2.3 / 2.2 / 2.4 | — |

**Levers, biggest first:**
1. The hunter's track record.
2. Team size.
3. Pitch quality.
4. Launch-day reach (founder posts plus organic coverage).

Media count, topic and having a company X account barely matter.

## Stacking the levers: the first launch
The levers compound; they don't add up linearly.

| First launch | Median rank | P(top 3) | P(top 5) [95%] | P(top 10) |
|---|---|---|---|---|
| Everything you control: self-hunt, 3 makers, 9 media + video, pitch 75, company X, founder posts + organic coverage | 7 | 15.8 | **31.2 [26.5, 35.7]** | 63.0 |
| Same, posted by a top-10% hunter | 2 | 55.8 | **71.4 [68.8, 74.0]** | 90.3 |

### Day of week (the "everything you control" launch)

| Day | Launches that day | Median rank | P(top 5) | P(top 10) |
|---|---|---|---|---|
| Mon | 23 | 7 | 28.6 | 63.6 |
| Tue | 36 | 8 | 18.6 | 52.8 |
| Wed | 34 | 8 | 20.9 | 56.1 |
| Thu | 34 | 9 | 14.9 | 44.5 |
| Fri | 37 | 6.5 | 35.1 | 66.9 |
| **Sat** | 23 | **4** | **52.5** | **80.4** |
| **Sun** | 19 | 5.5 | 47.6 | 77.1 |

Weekends carry about 20 launches against about 35 on weekdays. A zero-follower maker's chance of top 5 roughly triples on a
Saturday compared with a Thursday. A weekend top 5 also gets less traffic than a Tuesday top 5.

## The trajectory: each launch builds the hunter record for the next
You hunt your own launches, so each one adds to your own hunter record, which is the model's strongest input. The model's
prediction for each launch is fed in as the record of that launch.

That is optimistic: it assumes each launch lands where the model says. A launch that does worse slows every step after it.

| Step | When | What | Your hunter record going in | Median rank | P(top 5) [95%] | P(top 10) |
|---|---|---|---|---|---|---|
| 1 | Week 1, Saturday | **Launch Simulator (/try)**: free, instant, visual. The most "try it now" product. | none | 7 | 31.2 [26.1, 35.6] | 63.0 |
| 2 | Week 4–5, weekday or weekend | **PH Daily Forecast board**: a free daily product with a public accuracy number. | 1 launch | 3.5 | 60.4 [56.1, 64.4] | 84.4 |
| 3 | Week 8–9 | **Synthetic launch audience**: the 24-persona panel, as its own product. | 2 launches | 2 | 71.5 [69.4, 73.8] | 90.4 |
| 4 | Week 12–14 | **Launch Pack / Pro**: the paid product, launched once the free products have built your record. Or a major v2 of /try. | 3 launches | 2 | 75.0 [73.5, 76.4] | 92.3 |
| 5 | Later | **API** for agencies and tools | 4 | ≈ step 4 | — | — |

**Fastest path:** the "everything you control" launch on a Saturday, and a second launch 3–4 weeks later. After 2 launches
your own record puts you at about the level of an active hunter. Getting a top-10% hunter to post launch 1 starts you near
step 3, at P(top 5) 71%, and saves about 2 months.

### Why /try goes first
- It is the most demo-able product: paste a URL and get a result.
- Every visitor who tries it on their own launch is a prospect for the Launch Pack.
- The board (step 2) needs a few weeks of public live accuracy before it is credible.

Each launch is a distinct product. Re-launching the same product needs a major update. That rule sets the 3–4 week spacing,
together with the time to ship a real v1 of the next product.

## What "everything you control" means in practice
- **3 makers on the page:** real team members or contributors, each with a complete profile.
- **Pitch score 75 or higher:** test tagline and description variants through the pitch scorer before launch day. This one is
  cheap to raise.
- **9 images plus a video.**
- **Launch-day reach:**
  - founder posts on X and LinkedIn that show the product;
  - one honest write-up each on HN (Show HN), a relevant subreddit and one newsletter or press outlet.
  - Share what the product does and invite people to try it. Never ask for upvotes; Product Hunt penalizes that, and it is
    against the rules.
- **A Product Hunt account that is older and active:** comment usefully on other launches in the weeks before.

## Still to come (E5, today)
- Gemini pitch scores for 3 real tagline and description versions of each product. This replaces the assumed scores of 55 and
  75 above with measured ones.
- The persona panel and the /try rank band on each product's best page: the main concerns of each voter group, and what to
  fix before launch.
