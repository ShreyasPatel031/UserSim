# MCP SMS without a token: lease + denylist, live check (Oct 17, 2026, 21:03 PDT)

Prod `https://35-202-98-224.sslip.io/mcp` runs main **7b4883b** (`/health` engine_version 7b4883b). The changes went in through four PRs:
- PR #71: one-session SMS lease, texts only after the lease started, sender denylist.
- PR #72: `anon_allow_sms` set to true. The running server picked it up from main without a redeploy.
- PR #73: the phone number can come from `MVP_SMS_PHONE`.
- VM env: `MVP_SMS_BACKEND=ntfy`, `MVP_NTFY_SMS_TOPIC`, `MVP_NTFY_BASE` and `MVP_SMS_PHONE` added. Before this, the VM had no SMS config at all, so `usersim_signup_phone` failed with "no phone in secrets/credentials.json" even with a token.

## Live run, no token (`open-mcp-oct17/smscheck.py`; the phone number is masked, it is the owner's real phone)
```
sessions A 0fd3d4fe B dd4d8962
A signup_phone: {"phone": "***07", "lease_seconds_left": 599, "lease": "new", ...}
B signup_phone: {"error": "the SMS number is busy: another simulated user holds it. Retry in 600 s (call usersim_signup_phone again then), or continue without SMS if the site allows it", "busy": true, "retry_after_s": 600}
B wait_for_sms_code: {"error": "call usersim_signup_phone first"}
A wait_for_sms_code: {"found": false, "code": null, "lease_seconds_left": 577, "note": "no SMS code yet (waited 20s). ..."} (22s)
A finish: fce31edb-53d4-4337-a4e3-6a9944d23193
B signup_phone after A ended: {"phone": "***07", "lease_seconds_left": 599, "lease": "new", ...}
B finish: 367fef7d-8219-4b5e-84f6-0fac84b51f04
```
What this shows:
- A caller without a token gets the number.
- A second session is refused with busy and `retry_after_s`.
- A session that doesn't hold the lease can't wait for codes.
- The lease holder's wait times out cleanly after 20 s.
- Finishing A frees the number for B right away.

## Unit tests (`mvp/test_sim_mcp_limits.py::SmsLeaseTests`, all passing)
- A second caller is busy.
- Only the lease holder can wait, with `newer_than` = lease start, `slack_s=0`, and the denylist passed in.
- The lease frees when the session closes or the lease expires.
- `anon_daily_sms_leases_per_ip` is enforced.
- The ntfy reader drops "Your Apple Account Code is: …" and texts from before the lease, and returns the Acme code.
- Denylist: Apple, "G-123456 … Google" and Chase are blocked. "Pineapple" and "City Bikes" are not (whole-word match).

## Settings (`mvp/sim_mcp/limits.json`)
| key | value |
|---|---|
| `anon_allow_sms` | true |
| `sms_lease_s` | 600 |
| `anon_daily_sms_leases_per_ip` | 10 |
| `sms_sender_denylist` | 45 words: apple, icloud, google, g-, gmail, microsoft, banks (chase, wells fargo, citi, …), paypal, venmo, coinbase, searce, okta, duo, authy, whatsapp, facebook, instagram, github, carriers, … |

The denylist applies to every caller, with or without a token. `usersim_wait_for_sms_code` returns only the code, never the text.

Not tested live: a real text arriving during a lease. Doing that would mean texting the owner's phone or posting to its ntfy topic. The code path is covered by the unit test above.
