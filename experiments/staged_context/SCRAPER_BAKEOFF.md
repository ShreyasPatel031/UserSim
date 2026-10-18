# Review scraper comparison (Apify, 18 Oct 2026)

Same product for all: **GitHub Copilot**, ~20 reviews per scraper (the all-in-one has a 100-review minimum).
Fill rates were checked field by field by hand. Numeric ids, one-word theme tags and review headlines don't count.

| Scraper | Reviews | Job title | Company size | Industry | Time used | Rating | Pros / cons text | Use case / extras | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **zen-studio/software-review-scraper** (G2 + Gartner + TrustRadius + Capterra, one schema) | 98 (G2 47, Gartner 37, TrustRadius 8, Capterra 6) | 84% (G2 77%, Gartner 100%, TrustRadius 38%, Capterra 100%) | 100% (Gartner gives revenue bands) | 72% | Capterra only | 100%, normalised to 0–5 | G2, TrustRadius, Capterra: 100%. Gartner: none | TrustRadius alternatives considered | $0.54 / 98 |
| **zen-studio/g2-reviews-scraper** | 20 | 100% | 80% | 20% | – | 100% | likes + dislikes 100% | **problems solved 100%** | ~$0.04–0.13 |
| zen-studio/trustradius-review-scraper | 8 (all that exist) | 38% (department 100%) | 100% | 88% | – | 0–10 + recommend score | pros/cons lists 100% | use cases, ROI, alternatives, other software used | small |
| zen-studio/gartner-review-scraper | 20 | 100% | 100% (revenue band) | 100% | – | 100% | headline + summary only | – | ~$0.13 |
| thenetaji/g2-reviews-scraper | 20 | 100% | 0% (its company_size field holds the industry) | via mislabelled field | – | 100% | full body text | – | 4 GB runs |
| automation-lab/g2-scraper (current) | 20 | 0% | 3-band id, decoded below | id only | – | star + ease/setup/support/NPS | none (one-word themes) | switched yes/no | ~$0.04 |
| trakk/capterra-reviews-scraper (current) | 0 for Copilot, Cursor, Tabnine | – | – | – | – | – | – | search returned other products | – |
| focused_vanguard/multi-platform-reviews-scraper | 0 (cursor.com) | – | – | – | – | – | – | – | – |

The all-in-one found Capterra's Copilot listing, which trakk's search could not.

## Decoded G2 ids (automation-lab/g2-scraper)

- **companySegment:** 179 = Small-Business (≤50 employees), 180 = Mid-Market (51–1,000), 181 = Enterprise (>1,000).
  Joined on review id with zen-studio's labels; 16 of 16 agreed.
- **industry:** only 313 = IT & Services, 381 = Consulting and 274 = Computer Software are known. G2 has hundreds of
  industries, so use a scraper that returns labels instead.

## Recommendation

Use **zen-studio/software-review-scraper** as the one source. It is a single call by product name, covers 4 sites in one
schema, and fills job title, size, industry and real pros/cons. Add **zen-studio/g2-reviews-scraper** when the
"problems solved" text (use case) is wanted. Drop trakk (it can't find many products) and automation-lab (no titles or
text).
