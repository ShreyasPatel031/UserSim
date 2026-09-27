# WiserUI-Bench: removing answer leaks from the 33 leaky pairs with an image-edit model (2026-09-27 PT)

Branch `grokbot/pairwise-judge`. Script `bench/wiserui/leak_fix.py`. Outputs (not committed) in
`/workspace/bench/wiserui/images_fixed/<idx>/{win,lose}.png` (+ `_raw/` edit outputs and merge variants, `meta.json`),
ledger `images_fixed/calls.jsonl`, per-pair results `images_fixed/results.jsonl` (summary committed as `fullset/leak_fix_results.json`).
The originals in `images_recovered/` were never modified. Benchmark accuracy was NOT re-scored.

## Result (33 pairs = 24 Gemini-leaky + 9 manual flags from fullset/sets.json)
| verdict | pairs | which |
|---|---|---|
| **fixed** | **15** | 106, 110, 119, 137, 168, 202, 212, 215, 226, 273, 279, 282, 284, 295 (edited) + 281 (not edited, see below) |
| **still leaked** | **13** | 104, 107, 111, 124, 164, 221, 254, 260, 261, 274, 277, 278, 297 |
| **damaged** | **5** | 109, 152, 166, 176, 243 |

Verdict rule per pair: damaged (the Flash damage check says an edited image changed real UI) > still leaked (the SAME
composites.py Flash leak check, or a targeted "is annotation X still visible?" check, finds a cue on either image) > fixed.
- Leak check alone (without the targeted check): 19 fixed / 9 still leaked / 5 damaged. The targeted check caught real
  leftovers (half a highlight outline, a label stub) that the generic leak check misses, as it missed them originally.
- First edit attempt only: 11 fixed / 13 still leaked / 9 damaged.
- Of the 13 still leaked, **5 are flags on content that is not a winner cue** (my review):
  - 124, 274, 278 were NOT edited: the flagged "cues" are the page's own UI (Paltalk "Best value" badges, Uber
    "Cheaper"/"New" tags, GitHub "Most popular" and banner). The LEAK prompt itself says such content is not a cue, and
    removing it would change the UI under test. 281 (Runtastic "-50%" corner) is the same case and came back clean.
  - 261: the red box and VWO widget are gone; the checker now flags the plan's own "MOST POPULAR" ribbon.
  - 111: the red box is gone; the checker flags the VWO watermark, which is on BOTH images (not a winner cue).
- **Real leftovers (8):** 104 (half the magenta outline), 107 (bottom-right "Variation... increase" banner untouched),
  164 (small red outline fragment), 221 (blue CONTROL tab stub + frame), 254 (VARIATION tab / arrow remnants), 260 (part of
  the red outline), 277 (yellow circle around "blockers"), 297 (a ghost artifact where the corner badge was).
- **Damaged (5):** 109 (red box removed, but the model also erased the VWO watermark on the loser only, so the two images now
  differ in the watermark), 152 (a thumbnail dropped + garbled text), 166 (link styling / text garbled), 176 ("50 €" -> "10"
  in the top bar), 243 (red arrows cross body text; the text is garbled wherever they are removed).

Contact sheets (original vs fixed, both sides, verdict flags): `images_fixed/contact_examples.png` (106, 202, 215, 273 fixed;
104 still leaked; 243 damaged) and `images_fixed/contact_0.png` ... `contact_8.png` (all 33 pairs, 4 per sheet).

## Method
1. **What to remove**: a hand-written list per image (`EDITS`), from the sets.json reasons plus a look at every image
   (the Gemini reasons miss some annotations, e.g. the red boxes on 176-lose and 119-win, and flag native UI).
   38 images edited. The VWO watermark (109, 111, 243) was dropped from the lists: it is on both images of each pair, and
   Nano Banana refuses watermark removal (returns no image).
2. **Locate**: gemini-2.5-flash returns boxes for each listed annotation (kind outline vs solid).
3. **Edit**: gemini-2.5-flash-image ("Nano Banana", Vertex) on the region around the boxes (the whole image if the region
   is > 60% of it), padded (never stretched) to the nearest supported aspect ratio, temperature 0.
4. **Merge back**: the output is scaled back and registered onto the original (OpenCV ECC affine; the model shifts and
   rescales the page by a few px). Three variants: **m2** changed pixels inside the located boxes only (everything else
   stays pixel-identical); **m3** plus strong-change blobs touching the boxes (Flash boxes are loose, so m2 leaves outline
   fragments); **m4** the whole aligned edited region (checked only if m2 and m3 both fail). Chosen: m2 29, m3 8, m4 1.
5. **Check** each candidate: (a) the SAME leak check as composites.py (LEAK prompt, gemini-2.5-flash, thinking 0, crop
   wording, HIGH media resolution); (b) targeted check of the listed annotations; (c) damage check: original and edited
   stitched side by side into ONE image (Flash 2.5 allows HIGH media resolution only for single-image requests), "is the
   UI content the same apart from the removed markers?" (thinking 1024). Unedited partner images get (a) only.
6. **Retry**: failures got one more edit with the failure fed back (2 attempts max). The best candidate is kept
   (fewest failures, then earlier attempt, then m2 > m3 > m4). 61 edit attempts for 38 images.
7. Everything runs in parallel (asyncio, concurrency 64). Each call starts in a region picked by hashing its key and moves to
   the next region on 429/5xx (edit: global, us-central1, us-east4, us-west1, europe-west4; asia-northeast1 has no
   flash-image). Full pass about 2-3 min wall time. Every call is cached, so the script can be resumed.

## Per pair
| pair | verdict | win edit | lose edit | first-attempt verdict | notes |
|---|---|---|---|---|---|
| 104 | still_leaked | a1/m2 | - | still_leaked | win leak check: arrow_or_highlight '' |
| 106 | fixed | a1/m2 | a1/m2 | fixed |  |
| 107 | still_leaked | a1/m2 | - | still_leaked | win leak check: label 'Variatic'; trophy '' |
| 109 | damaged | - | a1/m3 | damaged | lose damage: The 'VWO' logo at the bottom of the screen is removed. |
| 110 | fixed | - | a1/m2 | fixed |  |
| 111 | still_leaked | - | a1/m2 | still_leaked | lose leak check: other 'VWO' |
| 119 | fixed | a1/m2 | a2/m4 | still_leaked |  |
| 124 | still_leaked | - | - | still_leaked | not edited (native UI: 'BEST VALUE' ribbon (VIP) / 'Best value' starburst (Extreme): Paltalk pricing UI) / win leak check: other 'BEST VALUE' / lose leak check: other 'Best value' |
| 137 | fixed | - | a1/m3 | fixed |  |
| 152 | damaged | a1/m2 | - | damaged | win damage: One product thumbnail image and the 'scroll down' arrow below the thumbnails are missing from the left sidebar.; A typo was introduced in th |
| 164 | still_leaked | a1/m2 | - | still_leaked | win remnant: a small red rectangle fragment on the right edge of the screen, next to 'Quick Conditional Approval?' |
| 166 | damaged | a1/m2 | - | damaged | win damage: The text 'modes de paiement' in the first paragraph of the main content is a blue, underlined link in IMAGE 1, but it is plain black text in |
| 168 | fixed | a1/m2 | - | fixed |  |
| 176 | damaged | a1/m2 | a2/m3 | damaged | win damage: In the top bar, the text 'GRATIS VERSAND AB 50 €' in IMAGE 1 has changed to 'GRATIS VERSAND AB 10' in IMAGE 2, with the '50 €' part being re |
| 202 | fixed | - | a1/m2 | fixed |  |
| 212 | fixed | a1/m3 | - | fixed |  |
| 215 | fixed | a1/m2 | a1/m2 | fixed |  |
| 221 | still_leaked | a2/m3 | a1/m2 | still_leaked | lose remnant: the blue 'CONTROL' label tab cut off at the top-left; the thin colored frame/border line (blue) along the image edges |
| 226 | fixed | a1/m2 | - | fixed |  |
| 243 | damaged | a1/m2 | a2/m3 | damaged | win damage: Several bold text segments in the product description bullet points in IMAGE 1 are rendered as regular text in IMAGE 2.; The shipping inform |
| 254 | still_leaked | a1/m3 | a1/m2 | still_leaked | win leak check: label 'VARIATION' / lose leak check: trophy '' |
| 260 | still_leaked | a1/m2 | - | still_leaked | win remnant: the red rectangle outline around the e-mail signup form |
| 261 | still_leaked | a1/m2 | - | still_leaked | win leak check: label 'MOST POPULAR' |
| 273 | fixed | a2/m2 | - | damaged |  |
| 274 | still_leaked | - | - | still_leaked | not edited (native UI: 'Cheaper' / 'New' ride tags: Uber app UI) / lose leak check: label 'New' |
| 277 | still_leaked | - | a1/m2 | still_leaked | lose leak check: arrow_or_highlight '' |
| 278 | still_leaked | - | - | still_leaked | not edited (native UI: 'MOST POPULAR' plan header / 'GitHub is now free for teams' banner: GitHub pricing UI) / win leak check: label 'MOST POPULAR' / lose leak check: other 'NEW' |
| 279 | fixed | a1/m2 | - | fixed |  |
| 281 | fixed | - | - | fixed | not edited (native UI: '-50%' corner on the 12-month plan: Runtastic pricing UI) |
| 282 | fixed | a1/m2 | a1/m2 | fixed |  |
| 284 | fixed | a2/m2 | - | damaged |  |
| 295 | fixed | a1/m2 | a2/m3 | damaged |  |
| 297 | still_leaked | a2/m2 | - | damaged | win remnant: a partial circular letter badge (a quarter/half circle, blue) cut off at the very top-left corner |

## Cost (Vertex usage metadata, list price)
flash-image: $0.30/M in, $30/M image out (1290 tokens = $0.039 per edit); flash: $0.30/$2.50.
| item | calls | $ |
|---|---|---|
| Nano Banana edits (incl. the pilot's whole-image v1 edits) | 75 | 2.94 |
| damage checks | 202 | 0.57 |
| leak checks (same prompt) | 290 | 0.23 |
| targeted checks | 202 | 0.13 |
| locate | 40 | 0.08 |
| ledger total | | **3.95** |
| region probe before the ledger (5 flash-image calls, one per region) | 5 | about 0.20 |
| **total** | | **about $4.15** (cap $5; the script stops itself at $4.30 in the ledger) |
No tuning or other paid jobs.

## Caveats
- **Selection bias**: each image had up to 6 candidates (2 attempts x 3 merges), and the best was picked by the same Flash
  checks that grade it. So "fixed" is optimistic: a noisy check can pass a bad candidate. Look at the contact sheets
  before using the fixed images.
- The damage check is strict but noisy. On blurry small text it sometimes reports "typos" that are its own misreadings,
  and it is not always the same between candidates. Its real catches include 176 ("50 €" -> "10"), 164 ("2 mins" -> "1 mins",
  that candidate was rejected) and 273/284 (a hallucinated phone thumbnail in the corner, that candidate was rejected).
- The leak check itself is not deterministic at temperature 0: 274-lose (unedited) came back clean twice and flagged once
  (final run: flagged), and 281-lose is clean now but was flagged in the original full-set run.
- 277: the "+32%" at the bottom-right is probably the whiteboard app's own zoom level, not a lift figure. It was in the
  removal list, and the model changed it to "+2%". The yellow circle on the canvas remains.
- Pixels outside the located regions are identical to the originals (m2/m3). Inside them the model re-renders, so text
  that an annotation crossed can come back slightly different (the main failure mode: 243, 166, 152).
