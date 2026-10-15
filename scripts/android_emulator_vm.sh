#!/usr/bin/env bash
# Android emulator + Appium on a GCP VM, for `python -m mvp.ios_study --backend android`.
#
#   scripts/android_emulator_vm.sh create   # create the VM (nested virtualization, ~$0.19/h)
#   scripts/android_emulator_vm.sh setup    # on the VM: SDK, Play Store image, AVD, Appium
#   scripts/android_emulator_vm.sh start    # on the VM: boot emulator + Appium
#   scripts/android_emulator_vm.sh delete   # delete the VM when done
#
# Only official sources: Google's Android SDK (dl.google.com) and npm (appium).
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-a}"
VM="${MVP_ANDROID_VM:-usersim-android-emu}"
API="${ANDROID_API:-34}"
IMAGE="system-images;android-${API};google_apis_playstore;x86_64"
SDK="${ANDROID_HOME:-$HOME/android-sdk}"

case "${1:-}" in
create)
  gcloud compute instances create "$VM" --project "$PROJECT" --zone "$ZONE" \
    --machine-type n2-standard-4 --enable-nested-virtualization --min-cpu-platform "Intel Cascade Lake" \
    --image-family ubuntu-2204-lts --image-project ubuntu-os-cloud --boot-disk-size 60GB \
    --subnet "${GCP_SUBNET:-usersim-seed-subnet}" --scopes cloud-platform \
    --labels usersim-role=android-emulator
  ;;
setup)
  sudo apt-get update -qq
  sudo apt-get install -y -qq openjdk-17-jdk-headless unzip qemu-kvm python3-pip nodejs npm >/dev/null
  sudo usermod -aG kvm "$USER" || true
  mkdir -p "$SDK/cmdline-tools"
  if [ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
    curl -sSLo /tmp/cmdtools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
    unzip -q /tmp/cmdtools.zip -d "$SDK/cmdline-tools" && mv "$SDK/cmdline-tools/cmdline-tools" "$SDK/cmdline-tools/latest"
  fi
  export ANDROID_HOME="$SDK" PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$SDK/emulator:$PATH"
  yes | sdkmanager --licenses >/dev/null
  sdkmanager "platform-tools" "emulator" "$IMAGE" >/dev/null
  echo no | avdmanager create avd -n usersim -k "$IMAGE" -d pixel_7 --force
  sudo npm i -g appium >/dev/null && appium driver install uiautomator2
  pip3 install -q Appium-Python-Client google-genai httpx pillow
  ;;
start)
  export ANDROID_HOME="$SDK" PATH="$SDK/platform-tools:$SDK/emulator:$PATH"
  nohup emulator -avd usersim -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect >/tmp/emulator.log 2>&1 &
  adb wait-for-device
  until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 3; done
  nohup appium --address 127.0.0.1 --port 4723 >/tmp/appium.log 2>&1 &
  echo "emulator + appium up"
  ;;
delete)
  gcloud compute instances delete "$VM" --project "$PROJECT" --zone "$ZONE" --quiet
  ;;
*)
  sed -n '2,10p' "$0"; exit 1
  ;;
esac
