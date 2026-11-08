# Scale-up vs scale-down (stop at first 403)

- GO: `run:scaleud-20261108t031811z`
- Arms: **a = scale_up** (4→32), **d = scale_down** (32→… via ramp list)
- Metric: people completed / minutes from first_pull → first `BLOCK` line

| sid | strat | people @ ding | first 403 (UTC) | elapsed | people/min |
|-----|-------|--------------:|-----------------|--------:|-----------:|
| a | scale_up | 20 | 04:35:57 `/@marcin_uchacz1` | 68.4 min | **0.292** |
| d | scale_down | 20 | 04:24:34 `/@pboersma` | 56.5 min | **0.354** |

**Winner: scale_down** — same people count, dinged ~12 min sooner → higher people/min.

Notes:
- Scale_up did reach `RAMP -> 32 tabs 160 /min` before its 403.
- Scale_down mostly ran at 24:140 after the first step-down (per-person Runner resets, so it re-enters from 32 each profile).
- `PH_STOP_ON_FIRST_BLOCK` was patched in, but both arms logged a *second* BLOCK ~5 min later (fresh-browser path still fired once). Score above uses **first** BLOCK only.
