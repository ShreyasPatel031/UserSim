# Which mix of review data predicts held-out products best (18 Oct 2026)

Model-free test (no model calls). Each held-out product is predicted from other products' reviews only: its own
reviews are always excluded, and so is the same product under another name.

## Setup

- **Sources:**
  - **C**: FreshCrawl Capterra snapshot, same category.
  - **G**: FreshCrawl G2 snapshot, same category.
  - **L**: live G2 / Capterra / TrustRadius / Gartner scrapes of the 3 competitors the model names for the product
    (`out/mixture/competitors.json`, `out/live/`).
  - A mixture averages its sources with equal weight.
- **Metrics:**
  - error of the product's mean overall rating;
  - TVD of the reviewer role mix;
  - TVD of the company-size mix (3 bands).
- **Held-out sets:**
  - 9 Capterra test products (`router_eval.TEST` with live rivals);
  - 8 G2 test products (`g2_merge`);
  - 9 live products that are in neither snapshot (Copper, Gorgias, Teamwork.com, GetResponse, Personio, Zoho Books,
    Sisense, Mattermost, Bitwarden, Ecwid, minus any without complete data).

## Results (`out/mixture/mix_eval.csv`)

| mix | mean rank over 9 cells (3 sets × 3 metrics) |
| --- | --- |
| **CL** (Capterra snapshot + live rivals) | **2.56** |
| CGL | 2.89 |
| L (live rivals only) | 3.67 |
| GL | 3.89 |
| C | 4.00 |
| CG | 4.67 |
| G | 6.33 |

- **Capterra held-out set:** C wins all three metrics. It is in-domain: the same site and the same reviewer
  population.
- **G2 set:** GL wins rating level (0.161 vs 0.213 for C) and role mix; L alone wins size mix (0.140 vs 0.272).
- **Live set:** CL wins rating level (0.111). L alone wins role mix (0.189) and size mix (0.110 vs 0.153 for C).
- **Keep:** live named rivals in every mix. Adding L improved the snapshot-only C on 2 of 3 held-out sets.
  - In production, only L is allowed (rule: the snapshots are research data, never a product's competitors).
  - L is what agent mode (`mvp/agent_mode.py`) and human mode use.
  - For research packages, CL is the best mixture.
- **Not covered here:** pros/cons and per-person outputs. The agent-mode session tested words with the product's own
  reviews plus live rivals (`experiments/human_experience/`).
