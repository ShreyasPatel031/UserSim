# Pre-registration: persona panel vs real similar-launch comments (Nov 15, 22:20Z)

Orchestrator item (22:07Z): reconcile two results that point opposite ways.
- (a) Personas add nothing over real comments from similar launches (39 launches, strict judge).
- (b) The persona panel beat BEST by +6.0 theme recall on the 279-launch harness.

## Launch set
- Harness launches (`hist_sample.json`, dated 2026-08-01 to 2026-10-24) that have at least 8 real non-team comments in the launch-page dump.
- Random sample of 180, seed 0.

## Arms
1. **REAL24.** No personas. Gemini 2.5 Flash writes 24 comments (reaction, concern, question each). It is shown real non-team comments from the 12 most similar launches dated strictly before the target. Launches sharing a maker or hunter with the target are excluded.
2. **PANEL.** The 24-persona panel. This is the cached harness output `HYBRID_V3_K24`, the same text the harness scored.
3. **PANEL+REAL.** The same persona cards and prompt as arm 2, with the arm-1 real-comments block appended.
4. **BEST.** The cached harness output: 6 comments from Gemini 2.5 Flash at temperature 0.3, with themes of the 10 most similar launches.
5. **PANEL6** (volume control). The first 6 comments of arm 2, to compare with BEST at the same output size.

## Truth and judges
The same truth and both judges are applied to every arm.
- **Theme recall.** The harness truth themes and the harness JUDGE prompt, unchanged.
- **Strict-point recall.** The launch's real non-team comments are condensed once into up to 10 distinct concerns or questions. A candidate matches only on the same substance.
- Precision is reported for both judges.
- Paired by launch, with a 95% launch bootstrap.

## Readings fixed in advance
- **Personas add value over real comments:** the recall lower bound of (PANEL+REAL minus REAL24) is > 0 on either judge.
- **Real comments add value to the panel:** the recall lower bound of (PANEL+REAL minus PANEL) is > 0 on either judge.
- **The harness gap was output volume:** the interval of (PANEL6 minus BEST) includes 0 on theme recall while (PANEL minus BEST) excludes it.

## Spend
Stops at $10.
