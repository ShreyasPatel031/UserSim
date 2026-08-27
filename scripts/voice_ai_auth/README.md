# Voice AI dashboard sign-in (for Bland call prep)

**Google account:** `shreyashfs@gmail.com`

## Right now (Cursor browser tab)

1. **Bland** — Google sign-in is open with your email filled in.
2. Enter your **Google password** (and 2FA if prompted) in the Cursor browser panel.
3. Approve access for bland.ai → you should land on `https://app.bland.ai/dashboard`.

## Save sessions for the agent (Chrome, persists Google SSO)

After Bland works, run this in a terminal (opens real Chrome):

```bash
./scripts/voice_ai_auth/login_all.sh
```

For each product it opens the login page. Use **Sign in with Google** → `shreyashfs@gmail.com`. When the dashboard loads, press **Enter** in the terminal to save cookies.

Sessions saved under `secrets/voice_ai_sessions/` (gitignored).

## Products & URLs

| Key | Login | Dashboard |
|-----|-------|-----------|
| bland | https://app.bland.ai/login | https://app.bland.ai/dashboard |
| vapi | https://dashboard.vapi.ai/login | https://dashboard.vapi.ai/ |
| retell | https://dashboard.retellai.com/login | https://dashboard.retellai.com/ |
| synthflow | https://app.synthflow.ai/login | https://app.synthflow.ai/ |
| elevenlabs | https://elevenlabs.io/app/sign-in | https://elevenlabs.io/app |
| telnyx | https://portal.telnyx.com/#/login | https://portal.telnyx.com/#/home |

### Google says “This browser or app may not be secure”

Google blocks **Playwright-driven** sign-in. Use **real Chrome** instead:

```bash
./scripts/voice_ai_auth/open_auth_chrome.sh
```

Sign in with Google in that window → then:

```bash
./scripts/voice_ai_auth/save_sessions.sh --only bland
```

Do **not** use Playwright-headed login for Google OAuth.

## After signing in (real Chrome)

Save cookies for agents (auto, no Enter):

```bash
./scripts/voice_ai_auth/quick_save_bland.sh
```

Or all products:

```bash
PYTHONPATH=src python3 scripts/voice_ai_auth/snapshot_sessions.py --headed --wait 180
```

Agents (`browser_use_runner`) auto-load `secrets/voice_ai_sessions/*.json` for app URLs (Bland, Vapi, Retell, etc.). Default `VOICE_AI_AUTH=1`.

```bash
PYTHONPATH=src python3 scripts/voice_ai_auth/verify_dashboards.py
```

## Notes

- Bland login has **Cloudflare Turnstile** — check “Verify you are human” before Google works.
- One Chrome profile (`secrets/voice_ai_browser_profile/`) shares Google login across sites.
- Marketing sites (bland.ai) are not the product — always use **app** / **dashboard** URLs.
