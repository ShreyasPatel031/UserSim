# Pre-registration: data-driven panel groups and panel size (orchestrator 03:30Z Nov 15; Shreyas's dynamic-groups spec)

Written before any panel-variant output exists.

- **Harness:** reactions_v2 on the launches that have cards in every arm (up to 279; the same 300-launch sample).
  - Judge, truth themes and complaint truth are as in the earlier PERSONA12R test.
  - Pairs by launch, launch bootstrap 4000, 95%.
- **Segments:** fit with cut 2026-08-01, before every harness launch.
  - Upvotes are dated by launch day, comment text by comment time. Profile header state is undated (Nov 2026 read).
  - v1 = taste groups (live since 03:00Z). v2 = kind-of-user groups (k by held-out fit) with nested subgroups.
- **Panel:** one persona per group (v1) or subgroup (v2) whose share of the launch's expected voters is at or above a threshold.
  - Share = the group mix of the team's earlier voters when there are ≥ 20 of them, else the topic model.
  - Each persona carries the group's who / says (paraphrased from its own comments dated before the cut) / votes_for, plus its share.
- **Arms:** V1_SHARE10, V1_SHARE5, V1_SHARE3, V1_TOP12, V2_SHARE5 (V2_SHARE3 if spend allows), and the live PERSONA12 as baseline (cached).
- **Panel-size rule:** order the v1 arms by median size (SHARE10 < SHARE5 < SHARE3 < TOP12). Choose the smallest arm whose next-larger arm's recall gain (paired) has an interval including 0.
- **Segmentation choice:** v2 replaces v1 only if V2_SHARE5 − V1_SHARE5 recall has a lower bound > 0.
- **Adoption vs the live panel:** the chosen arm replaces PERSONA12 if its paired recall difference has a lower bound > −1.0 AND its precision point estimate is ≥ −3.0. Complaint recall is reported only.
- **Spend:** a hard stop at $15 of Gemini.
