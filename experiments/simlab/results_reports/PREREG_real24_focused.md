# Pre-registration: REAL24-focused vs the persona panel (Nov 15, 22:40Z)

Orchestrator item (22:32Z). Follows `PREREG_panel_vs_real_comments.md`.

## Launch set
The same sample as that test: seed 0, 180 drawn, 167 scored.

## Arms
- **FOCUSED.** One Gemini 2.5 Flash call, with no personas.
  - It sees the launch text and the same block of real comments from the 12 most similar earlier launches.
  - It writes 24 comments (reaction, concern, question).
  - Each must name a specific feature or claim from this launch's own text.
  - A real point is carried over only where it applies to this launch.
  - Generic praise, and points about things the launch does not mention, are forbidden.
- **REAL24.** Regenerated with the earlier prompt at temperature 0.
- **PANEL.** The cached `HYBRID_V3_K24` output.

## Judges and metrics
- The same two judges and the same truth as before, applied to every arm.
- Theme F1 is computed per launch as 2PR / (P + R) from the theme judge, with 0 when P + R = 0, then averaged over launches.
- Paired by launch, with a 95% launch bootstrap.

## Decision rule
FOCUSED replaces the panel if both hold:
1. mean theme F1 (FOCUSED minus PANEL, paired) is ≥ 0, and
2. strict recall is not worse: the paired interval of FOCUSED minus PANEL is not entirely below 0.

Also reported:
- whether the F1 lower bound is > 0 (clearly better);
- FOCUSED minus REAL24.

## Spend
Stops at $5.
