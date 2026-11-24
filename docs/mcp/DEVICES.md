# Real phones (LambdaTest) and Bitrise

Simulated users can test a mobile app on a real Android phone. The phone runs on LambdaTest real devices,
driven by the MCP server over Appium, and anyone who can call `https://atelier-sim.com/mcp` can use it, within
the limits below.

## Tools
- `usersim_start_device_session(app, task, persona, platform="android", device="")`: `app` is an https:// link that
  downloads the `.apk` (for example a Bitrise artifact link) or an `lt://APP...` id from an earlier upload. Returns
  the first screenshot, on-screen elements with x/y, and `session_id`.
- `usersim_device_act(session_id, action, thought, x, y, text, direction, key)`: `tap` (x, y in screenshot pixels),
  `type` (into the focused field; tap it first), `swipe` (up/down/left/right), `key` (back/home/enter), `wait`.
- `usersim_device_observe(session_id)`, `usersim_device_finish(session_id, outcome, notes)`.

Email, SMS and Google signup tools are for browser sessions; in an app, type the email the app asks for by hand
from `usersim_signup_identity` in a browser session (to be wired into device sessions next).

## From Bitrise
Add a **Script** step after the step that builds the APK (`android-build` / `gradle-runner`):

```bash
#!/usr/bin/env bash
set -euo pipefail
resp=$(curl -sS --fail -X POST https://35-202-98-224.sslip.io/api/apps/upload \
  -H "X-Filename: $(basename "$BITRISE_APK_PATH")" --data-binary @"$BITRISE_APK_PATH")
echo "$resp"
app=$(echo "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["app"])')
envman add --key ATELIER_SIM_APP --value "$app"
echo "Ask Claude: Test my Android app $app with Atelier Sim: <what a new user should try>"
```

The upload goes straight to the MCP server (not through Vercel, whose request limit is 4.5 MB). The returned
`lt://APP...` id is what you give Claude. Without a token, 5 uploads per IP per day.

## Limits (mvp/sim_mcp/limits.json)
`devices_enabled`, `device_max_concurrent` (5 = the LambdaTest plan's parallel sessions), `device_session_max_s` (600),
`device_max_steps` (40), `est_usd_per_device_session` (0.5) and `est_usd_per_device_step` (0.01) charged to the
anonymous $5/day per IP, `anon_daily_app_uploads_per_ip` (5).

## Credentials
`LT_USERNAME` and `LT_ACCESS_KEY` from Secret Manager (`usersim-LT_USERNAME`, `usersim-LT_ACCESS_KEY`), hot-reloaded
by `mvp/secrets_store.py`. Never logged.

## Not yet
- iOS: needs a signed (development or ad-hoc) `.ipa`; the code path exists (`platform="ios"`) but is untested.
- Signup helpers (email codes, SMS) inside device sessions.
