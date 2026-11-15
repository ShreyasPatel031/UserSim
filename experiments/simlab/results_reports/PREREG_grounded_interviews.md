# Pre-registration: grounding simulated interviews in real comments (Nov 15, 23:10Z)

## Question
Do simulated user interviews predict what real commenters raise better when each simulated user also sees what real users said on similar earlier launches?

## Test set
- 40 past launches dated 2026-10-20 to 2026-11-10 with at least 10 real non-team comments in the launch-page dump.
- Random sample, seed 0.

## Arms (each returns exactly 12 points for the launch)
- **PERSONA.** 12 personas built from real members (own upvote history and own past comments) of the 4 subgroups the launch is predicted to pull most. Each gives one main concern or question. Ungrounded, as run on Nov 14.
- **PERSONA+REAL.** The same personas, plus real non-team comments from the 12 most similar launches dated strictly before the target. Comments are tagged by subgroup where the commenter is tracked.
- **REAL-ONLY.** No personas. The same real comments, with the ask "list the 12 concerns or questions commenters will raise".

## Truth and scoring
- **Truth:** the launch's own real non-team comments, condensed once into up to 10 distinct points. The same list is used for every arm.
- **Judge:** Gemini 2.5 Flash, same-substance matching, blind to arm.
- **Metrics:** recall (real points matched) and precision (arm points that match a real point).
- **Pairing:** by launch, with a 95% launch bootstrap.

## Decision rule
- Grounding helps if the paired recall difference, PERSONA+REAL minus PERSONA, has a lower bound > 0.
- Personas add value if the paired recall difference, PERSONA+REAL minus REAL-ONLY, has a lower bound > 0.

## Constraints
- No comment from the target launch is shown to any arm.
- Similar launches are dated before the target.
- Spend stops at $5.

## Deviations (recorded after the first run)
- The comment dump ends 2026-10-24, so only 19 launches qualified in the registered window (results: `kinds_grounded.json`).
- A second run on a 40-launch sample from 2026-10-01 to 2026-10-24 was added (results: `kinds_grounded_oct.json`).
- The second run adds a topic-level judge as a secondary measure. The decision rule stays on strict recall.
