"""Bitrise public install page -> .ipa -> LambdaTest, in one step.

    python -m mvp.client_qa.fetch_build "<bitrise public-install-page URL>" [--out mvp/client_qa/private/builds]

Plain HTTP requests to the install page get 404 (bot protection); a real browser (the pre-installed Playwright Chromium)
loads it and exposes a short-lived signed download link. The .ipa is checked (bundle id, version, build number), saved
under --out/<build>/ (gitignored: client builds never go in the repo), uploaded to LambdaTest, and the lt:// URL printed.
LT credentials come from the network proxy; LT_USERNAME / LT_ACCESS_KEY may be placeholders.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import tempfile
import zipfile

JS = r"""
const { chromium } = require('playwright');
(async () => { const b = await chromium.launch(); const p = await b.newPage();
  await p.goto(process.argv[2], { waitUntil: 'networkidle', timeout: 90000 });
  await p.waitForTimeout(1500);
  const url = await p.evaluate(() => [...document.querySelectorAll('a')].map(a => a.href).find(h => /\.ipa(\?|$)/i.test(h)) || '');
  process.stdout.write(JSON.stringify({ url })); await b.close(); })().catch(e => { process.stdout.write(JSON.stringify({ error: String(e) })); process.exit(1); });
"""


def ipa_link(page_url: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(JS)
    try:
        out = subprocess.run(["node", f.name, page_url], capture_output=True, text=True, timeout=180)
    finally:
        os.unlink(f.name)
    res = json.loads(out.stdout or "{}")
    if not res.get("url"):
        raise SystemExit(f"no .ipa link on the install page: {res.get('error') or 'link not found'}")
    return res["url"]


def ipa_info(path: str) -> dict:
    z = zipfile.ZipFile(path)
    name = next(n for n in z.namelist() if n.count("/") == 2 and n.endswith(".app/Info.plist"))
    d = plistlib.loads(z.read(name))
    return {"bundle": d.get("CFBundleIdentifier"), "version": d.get("CFBundleShortVersionString"), "build": d.get("CFBundleVersion")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("page"); ap.add_argument("--out", default="mvp/client_qa/private/builds")
    a = ap.parse_args()
    link = ipa_link(a.page)
    tmp = os.path.join(a.out, "_download.ipa"); os.makedirs(a.out, exist_ok=True)
    subprocess.run(["curl", "-sS", "-f", "-m", "900", "-o", tmp, link], check=True)
    info = ipa_info(tmp)
    dest_dir = os.path.join(a.out, str(info["build"])); os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"Reframe-{info['build']}.ipa"); os.replace(tmp, dest)
    os.environ.setdefault("LT_USERNAME", "proxy-injected"); os.environ.setdefault("LT_ACCESS_KEY", "proxy-injected")
    from mvp.device.ios_lambdatest import upload
    app = upload(dest, name=f"Reframe-{info['build']}.ipa")
    print(json.dumps({**info, "ipa": dest, "app": app}))


if __name__ == "__main__":
    main()
