# Run the Reframe phone study on your Mac

Reframe vs Sunnyside vs I Am Sober on an Android emulator: 6 personas, 6 tasks,
2 personas × 2 tasks per app = 12 end-to-end runs, each from a fresh first launch.
You do the one Google sign-in yourself; everything after that is automatic.

Time: ~20 min setup (mostly downloads), then ~2.5 h unattended for the 12 runs.

## 1. Install Android Studio (one time)

1. Download from <https://developer.android.com/studio> and install it.
2. Open it and accept the default setup (it downloads the Android SDK).

## 2. Create the phone

1. Android Studio welcome screen → **More Actions** → **Virtual Device Manager**.
2. **Create device** (+) → **Pixel 7** → **Next**.
3. Pick a system image that shows the **Play Store icon**, API **34** (click the download
   arrow next to it if needed) → **Next** → **Finish**.
4. Press **▶** next to the new device. Wait until the Android home screen shows.

## 3. Sign in and install the apps

1. On the emulator, open **Play Store** → **Sign in**.
2. Use `usersim.signups@gmail.com` and the password from `signup_gmail.env`.
   - If Google shows "I'm not a robot" / an image puzzle, solve it.
   - For 2-step verification choose **Google Authenticator** and enter the code
     (`SIGNUP_GMAIL_TOTP_SECRET` in the env file, or the Authenticator app if it is set up there).
   - Skip backup / payment / extras. Never add a payment method.
3. In Play Store, install all three:
   - **Reframe: Drink Less & Thrive**
   - **Sunnyside: Drink Less Alcohol**
   - **I Am Sober**
4. Leave the emulator running.

## 4. One-time tools

- **Node 22** (LTS) from <https://nodejs.org> if `node -v` is missing or below 20.19.
- Google Cloud login for Gemini, if not already done on this Mac:
  ```
  gcloud auth application-default login
  ```

## 5. Run the study

```
cd UserSim
git fetch origin claude/great-dijkstra-hy0gnm && git checkout claude/great-dijkstra-hy0gnm
scripts/run_android_study_mac.sh /path/to/signup_gmail.env
```

The script checks the emulator and the 3 apps, installs Appium 3 + the Android driver
and the Python packages, starts Appium, and runs the 12 cells. Reframe's (and the rivals')
email confirmation codes are read from the signups Gmail inbox automatically.

## 6. Results

Each app gets a folder `reports/android-<app>-<time>/` with:

- `report.html` — findings, recommendations, per-persona cards with screenshots
- `p1/ … p4/` — every step's screenshot plus `trace.json` (action + persona reasoning)
- `results.json` — machine-readable summary

Send the three folders (or just say "done") and the combined comparison report gets built from them.

## If something stops

| Message | Fix |
|---|---|
| `No running emulator` | Start the device in Android Studio (step 2.4). |
| `Missing app …` | Install it from Play Store on the emulator (step 3.3). |
| `Install Node 22` | Install Node LTS, open a new Terminal, rerun. |
| Gemini / credentials error | Run `gcloud auth application-default login`, rerun. |
