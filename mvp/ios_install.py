"""Sign the BrowserStack iPhone into the App Store and install an app.

    python -m mvp.ios_install --app "Reframe: Drink Less & Thrive" \
        --bundle com.glucobit.cravingBuster.CravingBuster
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from mvp.ios_agent import ROOT, Device, run_goal

APP_STORE = "com.apple.AppStore"


def install_goal(app_name: str) -> str:
    return (
        f"Install the free iPhone app \"{app_name}\" from the App Store.\n"
        "1. If not signed in to the App Store: tap the account/profile icon (top right of Today or Apps), "
        "sign in with Apple ID {{APPLE_ID}} and password {{APPLE_PASSWORD}}. If asked for a verification "
        "code, get it sent by text message and use request_code. Dismiss any welcome/terms screens "
        "(agree to Apple's terms if required).\n"
        "2. Go to the Search tab, search for the app name, open the matching app by Glucobit / the exact name.\n"
        "3. Tap Get (or the cloud download icon), confirm Install if asked; if asked for the Apple ID password "
        "for this FREE download, type {{APPLE_PASSWORD}}.\n"
        "4. Wait until the button shows Open, then reply done."
    )


def ensure_installed(dev: Device, app_name: str, bundle: str, out_dir: Path, log=print) -> dict:
    if dev.installed(bundle):
        return {"ok": True, "already": True}
    dev.launch(APP_STORE)
    time.sleep(4)

    def _installed(d, _els, _src):
        return d.installed(bundle)

    res = run_goal(
        dev, install_goal(app_name), out_dir=out_dir, max_steps=45,
        budget_s=900, stop_when=_installed, log=log,
    )
    ok = dev.installed(bundle)
    return {"ok": ok, "outcome": res.outcome, "note": res.note, "steps": len(res.steps)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="Reframe: Drink Less & Thrive")
    ap.add_argument("--bundle", default="com.glucobit.cravingBuster.CravingBuster")
    ap.add_argument("--keep", action="store_true", help="launch the app after install")
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "results" / "ios" / f"install-{stamp}"
    dev = Device(session_name=f"install {args.app[:30]}")
    print("session", dev.session_id, flush=True)
    try:
        result = ensure_installed(dev, args.app, args.bundle, out)
        if result["ok"] and args.keep:
            dev.launch(args.bundle)
            time.sleep(5)
            (out / "launched.png").write_bytes(dev.driver.get_screenshot_as_png())
        dev.mark(result["ok"], json.dumps(result)[:250])
    finally:
        dev.quit()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
