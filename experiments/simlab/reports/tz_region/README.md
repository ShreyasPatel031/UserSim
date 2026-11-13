# Time-zone mechanism for late climbers (orchestrator 02:04Z Nov 13; tz_region.py)

**Locations:**
- Sources: people_v3g profile locations (10% filled) + Grok X persons; keyword-mapped to a region.
- 4,401 people have a region: Americas 1,966, Europe-Africa 1,452, Asia-Pacific 983.
- No LinkedIn locations are held.

**(1) Team-region coverage** (Oct 26 – Nov 11; team = hunter + first named maker):
- 462 launches; region known for **16.5%**: Americas 46, Europe-Africa 15, Asia-Pacific 13, mixed 2, unknown 386.

**(2) Climb from the hidden rank to the final rank** (places; positive = climbed later), 7 hidden-window days, day-bootstrap interval:

| read | Americas (20 launches) | Europe-Africa (6) | Asia-Pacific (3) | unknown (151) |
|---|---|---|---|---|
| 01:00 | +1.50 [−1.32, 5.77] | +2.00 [−4.5, 9.3] | +4.67 [0, 8] | −0.50 |
| 02:00 | +0.95 [−0.5, 4.67] | +0.17 [−6, 5] | +7.67 [1, 12] | −0.19 |
| 03:00 | +0.85 [−0.88, 4.23] | +2.67 [−1.9, 7.9] | +8.67 [1, 13] | −0.22 |

**(3) Hidden rank + Americas offset** (leave-day-out): top 3 −4.8 [−14.3, 0] at 01:00 / 02:00 / 03:00. It hurts.

**(4) Held voters with a region:**
- 743 people. On the hidden days, 13 launches have ≥ 5 regioned voters.
- Spearman (Americas share, climb): +0.12 / −0.02 / −0.04 at 01:00 / 02:00 / 03:00.
- Oct 1 – Nov 10, 146 launches: Spearman (Americas share, finishing above the clean rank) +0.03 [−0.13, +0.19].

**Verdict:**
- No support for the hypothesis. Americas teams do not climb more than others; the only large climbs are 3 Asia-Pacific launches.
- An Americas offset costs top 3. The voter-side check is flat.
- Coverage is the binding limit: 16.5% of launches have a known team region.
