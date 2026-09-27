#!/usr/bin/env bash
# Run product signup on a seed VM. Runs ON the seed.
#
#   bash scripts/vm/seed_signup.sh todoist.com calendly.com
#
# Headed Chrome under Xvfb, low concurrency. Concurrency is deliberately small:
# the seed has one egress IP, and a burst of simultaneous signups from a single
# address is a strong bot signal regardless of how good the fingerprint is.
#
# Won sessions land on the identity disk via the symlinks provisioning created,
# so they outlive this VM.
set -euo pipefail

PARALLEL="${PARALLEL:-1}"
TIMEOUT_S="${TIMEOUT_S:-420}"
MAX_STEPS="${MAX_STEPS:-30}"

cd "$HOME/usersim"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="$PWD/src:$PWD"

SEED_ID="$(curl -sf -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/seed-id)"
SEED_ROOT="/var/lib/usersim-seed/${SEED_ID}"

set -a
# shellcheck disable=SC1091
source secrets/env
set +a

# Signup on a seed: prefer Browserbase (residential + captcha solve) over local
# Chrome. Local Chrome from a GCP ASN is what made Todoist/Figma die on captcha
# even when the form itself was fine. Override with MVP_FORCE_LOCAL_BROWSER=1.
export MVP_SIGNUP_BROWSERBASE="${MVP_SIGNUP_BROWSERBASE:-1}"
export USE_BROWSERBASE="${USE_BROWSERBASE:-1}"
# secrets/env may pin MVP_CAPTCHA_SOLVER=0; force-on for seed signup unless
# the operator explicitly sets MVP_CAPTCHA_SOLVER_FORCE=0.
if [[ "${MVP_CAPTCHA_SOLVER_FORCE:-1}" == "1" ]]; then
  export MVP_CAPTCHA_SOLVER=1
else
  export MVP_CAPTCHA_SOLVER="${MVP_CAPTCHA_SOLVER:-1}"
fi
export MVP_CAPTCHA_OSS="${MVP_CAPTCHA_OSS:-1}"
export MVP_CAPTCHA_AUDIO="${MVP_CAPTCHA_AUDIO:-1}"
export MVP_CAPTCHA_ALLOW_HUMAN=0
export MVP_SMS_BACKEND="${MVP_SMS_BACKEND:-ntfy}"
# Browserbase project defaultTimeout is often 300s; signup agents overrun that
# and CDP dies with HTTP 410 mid-onboarding. Keep sessions alive for the run.
export BROWSERBASE_SESSION_TIMEOUT_S="${BROWSERBASE_SESSION_TIMEOUT_S:-1800}"
# Tag every signup session so e2e cleanup can spare/own them separately.
export BROWSERBASE_SESSION_OWNER="${BROWSERBASE_SESSION_OWNER:-signup}"
# Shared BB project: never exceed 1 concurrent signup session.
export PARALLEL="${PARALLEL:-1}"
if [[ "${PARALLEL}" -gt 1 ]]; then
  echo "==> WARNING: PARALLEL=${PARALLEL} forced down to 1 (e2e needs BB headroom)" >&2
  PARALLEL=1
fi
# Only force local Chrome when explicitly requested — that path is the debug fallback.
if [[ "${MVP_FORCE_LOCAL_BROWSER:-0}" == "1" ]]; then
  export MVP_BROWSER_HEADLESS="${MVP_BROWSER_HEADLESS:-0}"
  export MVP_SIGNUP_BROWSERBASE=0
  export USE_BROWSERBASE=0
else
  # Browserbase sessions are remote; local headless/headed flags are irrelevant.
  unset MVP_FORCE_LOCAL_BROWSER || true
fi
export MVP_CHROMIUM_NO_SANDBOX=1

# browser_agent / local fallback looks for a Chrome binary; Playwright's is fine.
CHROME_CAND="$(find "$HOME/.cache/ms-playwright" \( -type f -o -type l \) \
  -name chrome -path '*/chrome-linux*/chrome' 2>/dev/null | head -1 || true)"
if [[ -n "$CHROME_CAND" ]]; then
  export MVP_CHROME_PATH="$CHROME_CAND"
  echo "==> chrome: $CHROME_CAND"
fi

echo "==> egress $(timeout 15 curl -sf https://api.ipify.org || echo unknown)"
echo "==> signup backend: browserbase=$([[ "${MVP_SIGNUP_BROWSERBASE}" == "1" ]] && echo ON || echo OFF) sms=${MVP_SMS_BACKEND}"
echo "==> signup: $* (parallel=${PARALLEL})"

# Reclaim leaked Browserbase sessions before creating more (cap is easy to hit).
# Only release sessions we tagged owner=signup — never touch e2e/demo sessions.
if [[ "${MVP_SIGNUP_BROWSERBASE}" == "1" && "${MVP_BB_RELEASE_STALE:-1}" == "1" ]]; then
  .venv/bin/python - <<'PY' || true
import os, time
try:
    from browserbase import Browserbase
    c = Browserbase(api_key=os.environ.get("BROWSERBASE_API_KEY", ""))
    items = list(getattr(c.sessions.list(status="RUNNING"), "data", []) or [])
    released = 0
    for s in items:
        meta = getattr(s, "user_metadata", None) or getattr(s, "userMetadata", None) or {}
        if isinstance(meta, str):
            try:
                import json
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        if meta.get("owner") != "signup":
            continue
        try:
            c.sessions.update(s.id, status="REQUEST_RELEASE")
            released += 1
        except Exception:
            pass
    if released:
        print(f"==> released {released} stale signup Browserbase session(s)", flush=True)
        time.sleep(1.5)
except Exception as exc:
    print(f"==> bb release skipped: {exc}", flush=True)
PY
fi

# Wait for shared-project headroom: e2e may hold up to 24/25. Never create when
# the pool is full — back off instead of fighting e2e for the last slot.
if [[ "${MVP_SIGNUP_BROWSERBASE}" == "1" ]]; then
  .venv/bin/python - <<'PY'
import os, time, json
from browserbase import Browserbase

cap = int(os.environ.get("BROWSERBASE_MAX_CONCURRENT", "25") or "25")
# Leave room for e2e (up to 24) + our single signup session.
reserve_e2e = int(os.environ.get("BROWSERBASE_E2E_RESERVE", "24") or "24")
max_wait = float(os.environ.get("BROWSERBASE_HEADROOM_WAIT_S", "900") or "900")
c = Browserbase(api_key=os.environ.get("BROWSERBASE_API_KEY", ""))
deadline = time.time() + max_wait
while True:
    running = list(c.sessions.list(status="RUNNING"))
    owners = {}
    for s in running:
        md = getattr(s, "user_metadata", None) or {}
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except Exception:
                md = {}
        o = (md or {}).get("owner", "?")
        owners[o] = owners.get(o, 0) + 1
    n = len(running)
    # Free slot exists AND e2e is not already above its reserve with us adding one.
    e2e_n = owners.get("e2e", 0)
    if n < cap and e2e_n <= reserve_e2e and (n < cap):
        # Our 1 session needs n+1 <= cap
        if n + 1 <= cap:
            print(f"==> bb headroom ok running={n}/{cap} owners={owners}", flush=True)
            break
    if time.time() >= deadline:
        raise SystemExit(
            f"FATAL: no Browserbase headroom after {max_wait:.0f}s "
            f"(running={n}/{cap} owners={owners}); e2e reserve={reserve_e2e}"
        )
    print(
        f"==> bb headroom wait running={n}/{cap} owners={owners} "
        f"(need ≤{cap - 1}; e2e reserve {reserve_e2e})",
        flush=True,
    )
    time.sleep(30)
PY
fi

# Display only needed for local Chrome fallback.
if [[ "${MVP_SIGNUP_BROWSERBASE}" != "1" ]]; then
  export DISPLAY=:99
  if ! xdpyinfo -display :99 >/dev/null 2>&1; then
    echo "==> starting Xvfb :99"
    setsid nohup Xvfb :99 -screen 0 1440x900x24 >/tmp/xvfb.log 2>&1 < /dev/null &
    for _ in $(seq 1 15); do
      xdpyinfo -display :99 >/dev/null 2>&1 && break
      sleep 1
    done
  fi
  xdpyinfo -display :99 >/dev/null 2>&1 || { echo "FATAL: no display :99" >&2; exit 1; }
  echo "==> display :99 live"
fi

SIGNIN_FLAG=()
if [[ "${SIGNIN:-0}" == "1" ]]; then
  SIGNIN_FLAG=(--signin)
fi
.venv/bin/python scripts/local/signup_targets.py \
  --parallel "$PARALLEL" --timeout "$TIMEOUT_S" --max-steps "$MAX_STEPS" \
  "${SIGNIN_FLAG[@]}" "$@"

# Record what this seed can actually serve, verified against its own cookie jars
# rather than the global credential registry.
python3 scripts/vm/seed_status.py "$SEED_ROOT"
