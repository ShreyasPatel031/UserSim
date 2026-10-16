#!/usr/bin/env bash
# GCE startup script: Android emulator + Appium + UserSim Android study, no SSH needed.
#
# Instance metadata:
#   usersim-bucket   GCS bucket for code, logs, reports, email-code drop
#   usersim-run      run id (gs://$BUCKET/android_runs/$RUN/...)
#   usersim-args     extra args for `python -m mvp.ios_study --backend android`
#   usersim-env      newline-separated KEY=VALUE (non-secret: ntfy topic, GCP project)
#   usersim-secrets  newline-separated SIGNUP_GMAIL_* login for Play + IMAP (instance-only)
# Progress: gs://$BUCKET/android_runs/$RUN/{status,boot.log,study.log,report/}
set -uo pipefail
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
md() { curl -sf -H "Metadata-Flavor: Google" "$MD/$1"; }
BUCKET=$(md usersim-bucket); RUN=$(md usersim-run); ARGS=$(md usersim-args || true)
G="gs://$BUCKET/android_runs/$RUN"
HOME=/root; export HOME
SDK=/opt/android-sdk; export ANDROID_HOME=$SDK
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$SDK/emulator:/opt/node22/bin:$PATH"
LOG=/var/log/usersim-boot.log
status() { echo "$(date -u +%T) $*" | tee -a $LOG; echo "$*" | gsutil -q cp - "$G/status"; gsutil -q cp $LOG "$G/boot.log"; }

status "setup: packages"
apt-get update -qq && apt-get install -y -qq openjdk-17-jdk-headless unzip python3-pip qemu-kvm \
  libpulse0 libgl1 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libasound2 libxdamage1 libxrandr2 \
  libxkbfile1 libdrm2 libgbm1 libbz2-1.0 libx11-xcb1 libxkbcommon0 libdbus-1-3 libfontconfig1 >/dev/null
# Appium 3 (required by the current UiAutomator2 driver) needs Node >= 20.19.
if [ ! -x /opt/node22/bin/node ]; then
  curl -sSL https://nodejs.org/dist/v22.12.0/node-v22.12.0-linux-x64.tar.xz | tar -xJ -C /opt && mv /opt/node-v22.12.0-linux-x64 /opt/node22
fi
status "setup: android sdk"
if [ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
  mkdir -p $SDK/cmdline-tools
  curl -sSLo /tmp/ct.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q /tmp/ct.zip -d $SDK/cmdline-tools && mv $SDK/cmdline-tools/cmdline-tools $SDK/cmdline-tools/latest
fi
IMAGE="system-images;android-34;google_apis_playstore;x86_64"
yes | sdkmanager --licenses >/dev/null 2>&1
sdkmanager "platform-tools" "emulator" "$IMAGE" >/dev/null 2>&1
[ -d /root/.android/avd/usersim.avd ] || (echo no | avdmanager create avd -n usersim -k "$IMAGE" -d pixel_7 --force >/dev/null)

status "setup: appium"
export APPIUM_HOME=/root/.appium
[ -x /opt/node22/bin/appium ] || npm i -g appium@3 >>$LOG 2>&1
appium --version >>$LOG 2>&1
for i in 1 2 3; do
  appium driver list --installed 2>&1 | grep -qi uiautomator2 && break
  appium driver install uiautomator2 >>$LOG 2>&1
done
appium driver list --installed >>$LOG 2>&1

status "boot: emulator"
ls -la /dev/kvm >>$LOG 2>&1
nohup emulator -avd usersim -no-window -no-audio -no-boot-anim -no-snapshot -gpu swiftshader_indirect \
  -feature -Vulkan -camera-back none -camera-front none -memory 4096 -cores 4 -verbose >/var/log/emulator.log 2>&1 &
( while true; do gsutil -q cp /var/log/emulator.log "$G/emulator.log" 2>/dev/null; gsutil -q cp /var/log/appium.log "$G/appium.log" 2>/dev/null; sleep 30; done ) &
booted=0
for i in $(seq 1 120); do
  [ "$(timeout 10 adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && { booted=1; break; }
  [ $i -gt 12 ] && ! pgrep -f "qemu-system|emulator -avd" >/dev/null && { status "boot: emulator process died"; tail -30 /var/log/emulator.log >>$LOG; break; }
  [ $((i % 12)) = 0 ] && echo "boot wait $i: $(timeout 5 adb devices | tail -n +2 | tr '\n' ' ')" >>$LOG
  sleep 5
done
gsutil -q cp /var/log/emulator.log "$G/emulator.log"
[ $booted = 1 ] || { status "boot: FAILED (see emulator.log)"; exit 1; }
status "boot: android ready"
adb shell settings put global window_animation_scale 0; adb shell settings put global transition_animation_scale 0; adb shell settings put global animator_duration_scale 0
APPIUM_HOME=/root/.appium nohup appium --address 127.0.0.1 --port 4723 >/var/log/appium.log 2>&1 &
sleep 8

status "code: fetch"
mkdir -p /opt/usersim && cd /opt/usersim
gsutil -q cp "$G/code.tgz" /tmp/code.tgz && tar xzf /tmp/code.tgz
pip3 install -q Appium-Python-Client google-genai httpx pillow >/dev/null 2>&1
md usersim-env > /opt/usersim/run.env || true
set -a; . /opt/usersim/run.env; set +a
export MVP_EMAIL_DROP=0 MVP_EMAIL_WAIT_S=300 MVP_IOS_MODEL="${MVP_IOS_MODEL:-gemini-2.5-flash}"

# Email-code drop shared with the operator through GCS.
mkdir -p secrets/email_codes
( while true; do
    gsutil -q -m rsync secrets/email_codes "$G/email_codes" >/dev/null 2>&1
    gsutil -q -m cp "$G/email_codes/*.txt" secrets/email_codes/ >/dev/null 2>&1
    sleep 4
  done ) &

# Google / Gmail login for Play and for reading persona email codes (IMAP works from GCE).
md usersim-secrets > /opt/usersim/secrets.env 2>/dev/null || true
chmod 600 /opt/usersim/secrets.env
set -a; . /opt/usersim/secrets.env; set +a
python3 - <<'PY'
import json, os
json.dump({"sites": [{"match": ["accounts.google.com", "google.com", "play.google.com"],
                      "username": os.environ.get("SIGNUP_GMAIL_USER", ""),
                      "password": os.environ.get("SIGNUP_GMAIL_PASSWORD", ""),
                      "totp_secret": os.environ.get("SIGNUP_GMAIL_TOTP_SECRET", ""),
                      "app_password": os.environ.get("SIGNUP_GMAIL_APP_PASSWORD", "")}]},
          open("secrets/credentials.json", "w"), indent=2)
PY
chmod 600 secrets/credentials.json
export GMAIL_USER="${SIGNUP_GMAIL_USER:-}" GMAIL_APP_PASSWORD="${SIGNUP_GMAIL_APP_PASSWORD:-}"
pip3 install -q pyotp >/dev/null 2>&1

status "study: running"
( while true; do gsutil -q cp /var/log/usersim-study.log "$G/study.log" 2>/dev/null; \
    [ -d reports ] && gsutil -q -m rsync -r reports "$G/reports" >/dev/null 2>&1; sleep 20; done ) &
PYTHONPATH=. python3 -u -m mvp.ios_study --backend android $ARGS >/var/log/usersim-study.log 2>&1
rc=$?
gsutil -q cp /var/log/usersim-study.log "$G/study.log"
gsutil -q -m rsync -r reports "$G/reports" >/dev/null 2>&1
gsutil -q cp /var/log/appium.log "$G/appium.log"
status "done rc=$rc"
