# LLM-as-the-user and blind appeal, product-only (orchestrator, Nov 11)

Sample: 400 voting person-days of complete people, Oct 20–Nov 8 (20 days). Mean line-up 26.9 launches, 2.5 real picks.
History: the person's last 40 upvoted launches dated before the day. Person lists read at d+2 or later.
Scripts: `llm_user.py`, `llm_appeal.py`, `llm_appeal_pro.py`. Gemini 2.5 Flash (no thinking) unless noted; about 1.3M tokens in.

| Ranker (product-only) | Hit@1 | Hit@3 | Hit@3, untied picks (240 person-days) |
|---|---|---|---|
| Random | 0.099 | 0.242 | 0.216 |
| Gemini as the person (history → picks) | 0.130 [0.103, 0.164] | 0.300 [0.243, 0.358] | 0.263 |
| Embedding centroid of history (bge-small) | 0.170 [0.113, 0.232] | 0.367 [0.280, 0.454] | 0.283 |
| Gemini blind crowd appeal, same for everyone | 0.100 | 0.265 | 0.237 |
| Gemini 2.5 Pro (thinking) blind ranking | n/a | 0.282 | n/a |
| ORACLE: rank by the day's final votes, same for everyone | 0.362 | 0.728 | 0.613 |

Blind appeal vs real votes, within day: Flash Spearman 0.125 (top 3/5/10 17/29/47); Pro 0.163 (20/31/53).

Reading:
- Which launch a person upvotes is mostly "what is winning that day": the non-personal oracle (0.73) beats the full
  personalised model with PH ties (0.60) and every product-only model (0.30–0.37).
- That shared term is not readable from the listing text: Gemini, Flash or Pro, gets 0.13–0.16.
- Taste from history is real but small (embedding 0.37 vs random 0.24).
- So a PH upvote is mostly exposure and mobilisation, not a clean "this person wants this product" signal.

**Void (Nov 11 05:05Z):** the 'untied picks' column used the launches `makers` field, which lists the redaction placeholder `[REDACTED]` as a maker on 6,712 of 6,965 launches. The tied/untied split is unreliable until rerun with the placeholder filtered. The 'all' columns are unaffected.
