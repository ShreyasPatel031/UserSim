#!/usr/bin/env bash
# Dry validation of the universal signup stack (no live browser signup).
# Checks imports, identity provisioning, access report, and blocked-reason constants.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src:${ROOT}"

if [[ -f secrets/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source secrets/env
  set +a
fi

PY="${ROOT}/.venv/bin/python"

echo "→ import modules"
"$PY" - <<'PY'
from mvp import identity, email_codes, sms_provider, captcha, auto_signup, access_report, auth_state, profile_pool, session_health
from mvp.auth_state import ensure_product_access, ensure_site_auth
from mvp.identity import provision_identity, list_identities
from mvp.auto_signup import BLOCK_REASONS
assert "card_required" in BLOCK_REASONS
print("imports ok")
PY

echo "→ provision identity (linear.app)"
"$PY" - <<'PY'
from mvp.identity import provision_identity, get_identity
ident = provision_identity("https://linear.app")
assert ident.email and "+" in ident.email and ident.email.endswith("@gmail.com") or "@" in ident.email
again = get_identity("https://linear.app")
assert again and again.email == ident.email and again.password == ident.password
print(f"  email={ident.email} host={ident.host} status={ident.status}")
PY

echo "→ access_report"
"$PY" -m mvp.access_report

echo "→ difficulty ladder (documentation check)"
"$PY" - <<'PY'
ladder = [
    ("email+password", "https://linear.app", "expect signed_up or reused"),
    ("email-link", "https://www.notion.so", "expect get_email_link path"),
    ("sms-gated", "fintech TBD", "expect get_sms_code path"),
    ("captcha-gated", "any with recaptcha", "expect solve_captcha"),
    ("card_required", "paid-only SaaS", "expect report_blocked(card_required)"),
]
for name, url, note in ladder:
    print(f"  [{name}] {url} — {note}")
print("ladder documented; run live signup per rung with:")
print("  PYTHONPATH=src:. .venv/bin/python -m mvp.auto_signup --url <url>")
PY

echo "OK signup stack smoke"
