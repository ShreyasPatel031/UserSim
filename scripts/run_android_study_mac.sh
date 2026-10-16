#!/usr/bin/env bash
# Run the Reframe vs Sunnyside vs I Am Sober Android study against the emulator on this Mac.
# Prereqs and steps: docs/ANDROID_STUDY_MAC.md
#
#   scripts/run_android_study_mac.sh /path/to/signup_gmail.env
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
ENV_FILE="${1:-$ROOT/secrets/signup_gmail.env}"
[ -f "$ENV_FILE" ] || { echo "Pass the signup_gmail.env path as the first argument"; exit 1; }
set -a; . "$ENV_FILE"; set +a

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
adb devices | grep -q "emulator-.*device$" || { echo "No running emulator. Start it in Android Studio first."; exit 1; }
for pkg in com.glucobit.reframe co.sunnyside com.thehungrywasp.iamsober; do
  adb shell pm list packages | grep -q "$pkg" || { echo "Missing app $pkg on the emulator. Install it from Play Store."; exit 1; }
done

command -v node >/dev/null || { echo "Install Node 22: https://nodejs.org (LTS)"; exit 1; }
command -v appium >/dev/null || npm i -g appium@3
appium driver list --installed 2>&1 | grep -qi uiautomator2 || appium driver install uiautomator2
pip3 install -q Appium-Python-Client google-genai httpx pillow pyotp

pgrep -f "appium.*4723" >/dev/null || (appium --address 127.0.0.1 --port 4723 >/tmp/appium.log 2>&1 &)
sleep 5

export GCP_PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}" VERTEX_LOCATION=us-central1
export GMAIL_USER="$SIGNUP_GMAIL_USER" GMAIL_APP_PASSWORD="$SIGNUP_GMAIL_APP_PASSWORD"
export MVP_PLATFORM=Android MVP_IOS_MODEL="${MVP_IOS_MODEL:-gemini-2.5-flash}" MVP_EMAIL_DROP=0
export MVP_ANDROID_PLAN="mvp/android_plans/reframe.json,mvp/android_plans/sunnyside.json,mvp/android_plans/iamsober.json"

PYTHONPATH=.:src python3 -u -m mvp.ios_study --backend android --max-steps 50 --persona-budget 1500 2>&1 | tee /tmp/android_study.log
echo "Reports: $(ls -d reports/android-* | tail -3 | tr '\n' ' ')"
