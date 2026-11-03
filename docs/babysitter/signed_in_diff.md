# Product Hunt: signed out vs signed in (evidence, 2026-11-03)

Status: **PARTIAL.** 21 of ~250 planned views. 3 launches + 3 profiles (main, upvotes) in both modes, plus followers, following and
activity for 1 profile. Box browser, box IP (not route 4), read-only, ~20 s between loads, ~15 min, 1 Cloudflare checkbox (passed),
no blocks after. Not done: profiles 4–10, the reviews/collections/stacks/forums/made/hunted tabs, XHR/JSON capture (box tooling can't
export it), full scrolls, signed-in HTML saves. Raw notes: `raw/_babysitter/signed_in_diff/notes.jsonl`, signed-out launch HTML `out/`.

| Page / field | Signed out | Signed in | Difference |
|---|---|---|---|
| Launch: vote count | 302 / 95 / 69 | 304 / 95 / 69 | none (live drift) |
| Launch: product followers | 508 / 2.5K / 27 | 511 / 2.5K / 27 | none (live drift) |
| Launch: who upvoted | not shown | not shown | **none: no voter list either way** |
| Launch: comment times | relative ("5h ago", "6d ago") | relative | none (exact ISO times are in the page's JSON / the API) |
| Launch: comments rendered | ~3–8 (partial scroll) | ~4–16 (partial scroll; one page not lazy-loaded) | not comparable: scroll depth differed |
| Launch: extra UI | Subscribe / Sign in, "Login to comment" | Reply links, comment box, Analytics link, onboarding banner | UI only, no data |
| Profile main (3 people) | counts, badges, maker history (month/year) | identical | none |
| Profile /upvotes (3 people) | header counts 25 / 30 / 384, items public, no dates | identical, no load-more seen | none in what was viewed |
| Profile followers (1 person, 3 followers) | 3 of 3 loaded, no sign-in wall | 3 of 3 | none |
| Profile following (1 person) | not viewed | 6 of 6 | — |
| Profile activity (1 person) | not viewed | 4+ comment events, relative times | — |

**Reading so far:** signing in showed no extra data in any view checked: no voter list, no upvote times, no absolute timestamps, same
counts and same list headers. Product Hunt hides who voted and when from everyone. Open: whether signed-out lists stop early on long
tabs (upvotes 384, followers >500) where signed-in keeps loading. Data Feeder's signed-out full pull of today's 74 people (all tabs, all
pages, header count vs items loaded) was meant to answer that at scale, but route 4 was blocked at its warm-up (21:03 and 21:20 UTC).

**Side finding:** the box browser on the box's own IP loaded Product Hunt normally (one checkbox, then no blocks) while route 4
(Camoufox + DataImpulse from GCP VMs) was blocked.
