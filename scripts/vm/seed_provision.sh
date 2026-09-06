#!/usr/bin/env bash
# Provision a usersim signup seed VM. Runs ON the VM, as the login user.
#
# Expects the repo payload already extracted at ~/usersim and the identity disk
# mounted at /var/lib/usersim-seed/<seed-id> by seed_startup.sh.
#
# Everything durable (Chrome profiles, storage states, credentials) is kept on
# the identity disk and symlinked into the checkout, so the boot disk stays
# disposable and re-provisioning never loses an account we already won.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

SEED_ID="$(curl -sf -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/seed-id)"
SEED_ROOT="/var/lib/usersim-seed/${SEED_ID}"
REPO="$HOME/usersim"

echo "==> seed ${SEED_ID} root ${SEED_ROOT}"
for _ in $(seq 1 60); do
  [[ -f /opt/usersim-seed-ready ]] && break
  sleep 2
done
if [[ ! -d "$SEED_ROOT" ]]; then
  echo "FATAL: identity disk not initialized at $SEED_ROOT" >&2
  exit 1
fi

# The startup script runs as root; hand the tree to the SSH user so agents can write.
sudo chown -R "$(id -u):$(id -g)" "$SEED_ROOT"
chmod 0700 "$SEED_ROOT/secrets" "$SEED_ROOT/profiles" "$SEED_ROOT/chrome"

echo "==> stop apt noise"
sudo systemctl stop unattended-upgrades.service 2>/dev/null || true
sudo systemctl disable unattended-upgrades.service 2>/dev/null || true
sudo killall apt-get apt dpkg 2>/dev/null || true
sleep 1

# Ubuntu 24.04 keeps its real sources in /etc/apt/sources.list.d/ubuntu.sources.
# Replacing them costs nothing only if the mirror we substitute actually resolves,
# so keep a backup and roll back rather than leaving the seed with no package lists
# (which silently yields "no installation candidate" for everything).
echo "==> apt sources"
sudo cp -an /etc/apt/sources.list.d/ubuntu.sources /etc/apt/ubuntu.sources.bak 2>/dev/null || true
printf '%s\n' \
  'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse' \
  'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble-updates main restricted universe multiverse' \
  'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse' \
  | sudo tee /etc/apt/sources.list >/dev/null
sudo rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true

apt_update() {
  # A freshly booted VM is still settling; 120s was not enough budget.
  timeout 300 sudo apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 update -qq
}
if ! apt_update; then
  echo "WARN: GCE mirror update failed — falling back to archive.ubuntu.com"
  printf '%s\n' \
    'deb http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse' \
    'deb http://archive.ubuntu.com/ubuntu/ noble-updates main restricted universe multiverse' \
    'deb http://security.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse' \
    | sudo tee /etc/apt/sources.list >/dev/null
  if ! apt_update; then
    echo "WARN: restoring stock ubuntu.sources"
    sudo cp -a /etc/apt/ubuntu.sources.bak /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
    sudo truncate -s 0 /etc/apt/sources.list 2>/dev/null || true
    apt_update || echo "WARN: apt update still failing"
  fi
fi

timeout 420 sudo apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 install -y -qq \
  xvfb x11-utils python3.12-venv python3-dev wget gnupg curl \
  libgtk-3-0 libx11-xcb1 libasound2t64 fonts-liberation libnss3 \
  libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
  libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libxshmfence1 libcups2 \
  >/tmp/apt_install.log 2>&1 || {
    echo "WARN: apt install partial; tail:"; tail -30 /tmp/apt_install.log || true
  }

# Headed Chrome is the whole point of a seed — a missing Xvfb must be loud, not a
# warning buried 200 lines up that silently downgrades every run to headless.
if command -v Xvfb >/dev/null 2>&1; then
  echo "Xvfb ok"
else
  echo "FATAL: Xvfb missing — seed cannot run headed Chrome" >&2
  exit 1
fi

echo "==> uv + venv"
cd "$REPO"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv venv .venv --python 3.12
uv pip install -q 'fastapi>=0.115' 'uvicorn[standard]>=0.32' 'httpx>=0.28' 'pyotp>=2.9' \
  playwright 'browser-use==0.13.8' 'browserbase>=1.0' pydantic

echo "==> playwright chromium"
.venv/bin/playwright install chromium

# ---- Durable state lives on the identity disk, not the checkout -------------
echo "==> link durable identity state"
mkdir -p "$REPO/secrets"

# Migrate any secrets shipped in the payload onto the disk once, then symlink.
for f in env sa.json credentials.json identities.json; do
  src="$REPO/secrets/$f"
  dst="$SEED_ROOT/secrets/$f"
  if [[ -f "$src" && ! -L "$src" ]]; then
    if [[ ! -s "$dst" ]]; then
      cp "$src" "$dst"
      echo "    seeded $f onto identity disk"
    else
      echo "    kept existing $f on identity disk"
    fi
    rm -f "$src"
  fi
  if [[ -s "$dst" ]]; then
    chmod 0600 "$dst"
    ln -sfn "$dst" "$src"
  fi
done

# Per-product Chrome profiles + storage states accumulate on the disk.
for pair in "product_profiles:profiles" "site_states:site_states"; do
  repo_name="${pair%%:*}"
  disk_name="${pair##*:}"
  repo_path="$REPO/secrets/$repo_name"
  if [[ -d "$repo_path" && ! -L "$repo_path" ]]; then
    cp -a "$repo_path/." "$SEED_ROOT/$disk_name/" 2>/dev/null || true
    rm -rf "$repo_path"
  fi
  ln -sfn "$SEED_ROOT/$disk_name" "$repo_path"
done

# youtube seed compatibility: the legacy single-profile path.
if [[ -d "$SEED_ROOT/chrome" ]]; then
  ln -sfn "$SEED_ROOT/chrome" "$REPO/secrets/youtube_browser_profile"
fi

echo "==> verify human-identity channels reachable from this seed"
set -a; [[ -f secrets/env ]] && source secrets/env; set +a
EGRESS_IP="$(timeout 20 curl -sf https://api.ipify.org || echo unknown)"
echo "    egress IP: ${EGRESS_IP}"

.venv/bin/python - <<'PY'
"""Prove the seed can do what a human does at signup: read email, get a phone."""
import json, os, sys, imaplib, socket

report = {"egress_checked": True}

# Email — Gmail IMAP is how the agent reads verification codes.
user = (os.environ.get("GMAIL_USER") or "").strip()
pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip()
if not user or not pw:
    report["email"] = "unconfigured: GMAIL_USER / GMAIL_APP_PASSWORD missing"
else:
    try:
        socket.setdefaulttimeout(30)
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.login(user, pw)
        m.select("INBOX")
        typ, data = m.search(None, "ALL")
        n = len((data[0] or b"").split())
        m.logout()
        report["email"] = f"ok: {user} INBOX reachable, {n} messages"
    except Exception as exc:
        report["email"] = f"FAIL: {type(exc).__name__}: {exc}"

# Phone — ask the provider itself rather than re-deriving the rules here. On a
# Linux seed this resolves to the ntfy backend: the handset forwards its own SMS
# to a topic, so no Mac sits in the path.
try:
    sys.path.insert(0, os.getcwd())
    from mvp.sms_provider import status as sms_status
    st = sms_status()
    backend = st.get("backend")
    if backend == "ntfy":
        if st.get("ntfy_reachable") and st.get("vault_phone"):
            report["phone"] = (
                f"ok: backend=ntfy topic reachable, owner phone in vault. "
                f"Requires the handset forwarding rule to be active."
            )
        else:
            report["phone"] = f"needs setup: backend=ntfy but {st}"
    elif backend in {"messages", "local", "macos"}:
        report["phone"] = f"UNAVAILABLE on VM: backend=messages ({st.get('messages_reason')})"
    else:
        report["phone"] = (
            f"ok: backend={backend}" if st.get("api_key_set")
            else f"unconfigured: backend={backend}, no api key"
        )
    report["phone_detail"] = st
except Exception as exc:
    report["phone"] = f"FAIL: {type(exc).__name__}: {exc}"

# TOTP is pure computation from a vault secret, so authenticator codes work on a
# seed with nothing else in the loop.
try:
    from mvp.credentials import _load_vault, totp_code
    secrets_with_totp = [
        s for s in (_load_vault().get("sites") or []) if s.get("totp_secret")
    ]
    if secrets_with_totp:
        sample = totp_code(secrets_with_totp[0]["totp_secret"])
        report["totp"] = (
            f"ok: {len(secrets_with_totp)} vault entries with totp_secret, "
            f"live code generated ({'6 digits' if sample and len(sample) == 6 else sample})"
        )
    else:
        report["totp"] = "none: no totp_secret in vault"
except Exception as exc:
    report["totp"] = f"FAIL: {type(exc).__name__}: {exc}"

# Identity registry — names, passwords, companies the agent presents at signup.
# Products are nested under a "products" key, not at the top level.
try:
    ids = json.load(open("secrets/identities.json"))
    products = ids.get("products", ids) if isinstance(ids, dict) else {}
    done = [k for k, v in products.items() if isinstance(v, dict) and v.get("status") == "signed_up"]
    report["identities"] = (
        f"ok: {len(products)} product identities on disk, {len(done)} already signed up"
    )
except Exception as exc:
    report["identities"] = f"missing: {exc}"

print(json.dumps(report, indent=2))
open("/tmp/seed_identity_report.json", "w").write(json.dumps(report, indent=2))
PY

python3 - "$SEED_ROOT" "$SEED_ID" "$EGRESS_IP" <<'PY'
import json, sys, pathlib, datetime
root, seed_id, egress = sys.argv[1], sys.argv[2], sys.argv[3]
health = pathlib.Path(root) / "state" / "health.json"
try:
    cur = json.loads(health.read_text())
except Exception:
    cur = {}
try:
    ident = json.loads(pathlib.Path("/tmp/seed_identity_report.json").read_text())
except Exception:
    ident = {}
profiles = sorted(p.name for p in (pathlib.Path(root) / "profiles").iterdir() if p.is_dir())
cur.update({
    "seed_id": seed_id,
    "healthy": True,
    "provisioned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "egress_ip": egress,
    "role": "signup",
    "channels": ident,
    "products": profiles,
    "auth_state": "provisioned" if not profiles else "has_accounts",
})
health.write_text(json.dumps(cur, indent=2) + "\n")
print(json.dumps(cur, indent=2))
PY

echo "==> seed provisioned"
