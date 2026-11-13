# Can held follows be dated? (orchestrator 04:51Z Nov 13): no. The +0.44 follower count cannot be cleaned from the store

Scripts: follow_order/fo1_order.py, fo2_page1.py and fo3_bracket.py. Run them as `python fo2_page1.py <scratchpad> fo1_order.py`. Data: the Nov 10 store, complete people only.

**(1) Order.**
- The store keeps no list position. Follow rows carry one timestamp per pull, have no position field, and are stored sorted by target id for 63% of people.
- Row position is flat across anchor months (relative position 0.52–0.57 for every month, Jan – Nov). Here an anchor is the day the person upvoted a launch by the followed account.
- A direct test of PH's list order uses the 758 complete people with a page-1-only pull on Nov 2, compared with their later full pull. The page-1 edges have EARLIER anchors than the rest of the same person's list: −22 days [−29.9, −14.5], over 182 people. If the list were newest-first, page 1 would hold the most recent follows. So the list is not newest-first, and its position cannot date follows.

**(2) Before vs after launch.**
- The only bracket is presence in a pull made before the launch day. The sole earlier pulls are the Nov 2 page-1 pulls.
- Teams of launches Nov 3 – 11 have 394,049 held follower edges. Only 8,701 of them (2.2%) were seen before launch.
- Re-pulls (9,386 people with pulls more than 12 h apart) do not help. Their first pull was page 1 only, so an edge that is "new" in the later pull can be a new follow or an old one beyond page 1.

**(3) Size of the leak.** It cannot be measured from the store, because no follow edge has a date.

**(4) Re-test with before-launch-only follows.** Not possible at 2.2% coverage (gate 15%).

**What would clean it:**
- (a) The 00:07 PT read's team followersCount, which is clean at 00:05 (stored from tonight). It can be validated after a few nights.
- (b) Daily diffs of follow lists for a fixed panel of complete people, so each new edge is dated by the pull in which it first appears.

The correlation between the held follower count and followersCount needs those first nights of data; none is stored yet.

Until then, the +0.44 partial correlation must be treated as possibly leaky (follows made after upvoting) and not used.
