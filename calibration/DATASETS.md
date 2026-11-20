# Calibration data for simulated users

Simulated users built on general models are completion-biased: they keep going where real people leave. This file
tracks public data of real human behaviour that can calibrate them, and whether each source has been shown to help.
"Helps?" is filled only from a measured run (paired, held-out, against the uncalibrated simulator). Private data
(anyone's personal activity) is never committed here; only its aggregate verdict, with the owner's OK.

Use: **Path** = which step comes next, **Drop** = when people leave or abandon, **Time** = dwell and time per step.

## Eval sets (in use)

| Set | What it tests | Status |
|---|---|---|
| OPeRA (NEU-HAI, CC BY 4.0, hf.co/datasets/NEU-HAI/OPeRA) | Real shoppers on real sites: next action, session end (`terminate`), stated reasons | next to wire up |
| Owner's own daily activity (private, not in repo) | Next app/site, dwell, leave-within-2-min, first visits to new products | running |
| Online-Mind2Web (300 tasks) | Only the human step count per task (no human traces released) | step-count reference only |

## Catalog

| Dataset | Human data | Size | Access | Path | Drop | Time | Helps? |
|---|---|---|---|---|---|---|---|
| OPeRA | Real users' web actions, timestamps, HTML, personas, in-the-moment rationales, terminate | 692 sessions, 51 users | CC BY 4.0, open | High | Med | Med-High | not yet tested |
| GA4 obfuscated sample (Google Merch Store) | Real GA4 events, full funnel, new vs returning, engagement time | 3 months | BigQuery public | Med | High | High | not yet tested |
| Coveo SIGIR eCom'21 | Session events with ms timestamps, cart abandonment task | ~5M sessions | request form, research | Med | High | High | not yet tested |
| OTTO | Click / cart / order sessions with timestamps | 12.9M sessions | CC BY 4.0 | Med | High | High | not yet tested |
| UCI Online Shoppers | Per-session page counts, durations, bounce and exit rates, bought or not | 12,330 sessions | CC BY 4.0 | - | High | High | not yet tested |
| REES46 | view / cart / remove / purchase with user ids over months | multi-GB | Kaggle | Low-Med | High | Med-High | not yet tested |
| OULAD | Daily learning-platform activity with withdrawal | 32,593 students | CC BY 4.0 | Low | High (retention) | Med | not yet tested |
| KDD Cup 2015 (XuetangX) | Timestamped MOOC clickstream with dropout label | ~79k users | research | Low | High (retention) | Med-High | not yet tested |
| RetailRocket / YOOCHOOSE | view / cart / buy sessions | 2.8M events / ~9M sessions | Kaggle / research | Low | Med | Med | not yet tested |
| Mind2Web (+ Multimodal) | Crowdworker action sequences, raw dump has traces, video | 2,350 tasks | CC BY 4.0 | High | none (finished tasks only) | Low-Med | not yet tested |
| WebLINX | Expert navigation demos with chat, timestamps | 2,337 demos | CC BY-NC-SA 4.0 | High | none | Med | not yet tested |
| WONDERBREAD | Screen recordings, action logs, step guides | 2,928 demos | Zenodo | High | none | Med | not yet tested |
| AgentNet (OpenCUA) | Human desktop and web computer-use demos | 22.6k tasks | MIT | High | none | Low-Med | not yet tested |
| AITW / AndroidControl | Mobile rater demos | 715k / 15k episodes | public | High (mobile) | Low | none | not yet tested |

Paid-annotator demos (Mind2Web, WebLINX, WONDERBREAD, AgentNet, AITW) finish assigned tasks, so they share the
simulator's completion bias: use them for paths, never for drop-off.

No public dataset of real first-session SaaS onboarding was found; only vendor aggregates (for example, an average
activation of 37.5% across 62 B2B SaaS products, a vendor figure). Closest stand-ins: GA4 sample (new vs returning
funnel), OULAD and KDD Cup 2015 (first weeks, then dropout).

Evidence of the gap: Lu et al. 2025 (arXiv 2503.20749), untuned LLMs over-purchase on real e-commerce sessions
(outcome F1 about 13-20%); arXiv 2604.07929, humans explore widely while agents stay search-centric.
