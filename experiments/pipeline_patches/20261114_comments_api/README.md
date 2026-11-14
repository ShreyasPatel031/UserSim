# Comments + sites failures (diagnosis 13:15Z Nov 14) and an undeployed comments fallback

**Root cause (both steps): the DataImpulse residential proxy rejects the session with HTTP 407 (Proxy Authentication Required) for every
host (producthunt.com and example.com alike), since the Nov 12 run.** Nov 11's run still used it ($0.04, 38 MB). Typical causes: credentials
rotated/expired or the account's traffic balance used up. Fix = Shreyas renews/tops up DataImpulse and updates the proxy entry in
/var/lib/usersim/discovery_keys.json (a credential: only Shreyas). No code change needed for recovery.

| step | since | per day before | lost per day now | recoverable later? |
|---|---|---|---|---|
| comments (page route via proxy) | Nov 12 run (launches of Nov 11, 12, 13) | 100-290 comments with commenters | all of it (21-37 launches/day) | yes: comments stay on PH; re-run the page fetch for those days once the proxy works (timing at fetch is lost, created_at is kept) |
| sites (Camoufox via proxy) | Nov 12 run | 7-69 sites with text | 20-47 links/day (96 so far) | yes: re-run with SITES_IDS for those launches |

Official-API alternative for comments: `ph_comments_api.py` (here; no proxy, PH_TOKEN). The API redacts commenters, so it gives counts,
timestamps, reply structure and votes per launch but NO people: it cannot feed the warehouse comment/event person rows, the people step or
comment_forecast's distinct-commenter and team inputs. Probe on one Nov 13 launch: 3 of 3 comments returned with createdAt, users redacted.
Sites has no API equivalent (the API's website field is the same producthunt.com/r/ redirect). Suggested small pipeline change (undeployed):
make fetch.py report "proxy 407" explicitly so the step status names the cause instead of "blocked or unparseable" / "0 of N links".
