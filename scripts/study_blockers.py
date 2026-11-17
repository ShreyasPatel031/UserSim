"""Why didn't cells reach the goal? Per site x task: the engine itself (browser/driver died), the signup wall (alias rejected / 'already registered', mail
never arrived, captcha, phone, blank signup page, third-party connect) versus the task itself (in the app but could
not do it, or ran out of turns). Heuristics over the judge's reason, the driver's notes, the final URL and the trace.

    python scripts/study_blockers.py STUDY_ID            # fetches https://35-202-98-224.sslip.io/api/studies/STUDY_ID
    python scripts/study_blockers.py path/to/study.json
"""

from __future__ import annotations

import collections
import json
import re
import sys
import urllib.request

BASE = "https://35-202-98-224.sslip.io"


def blocker(r: dict) -> str:
    v = r.get("page_verdict") or {}
    if v.get("goal_reached"):
        return "reached"
    t = ((r.get("driver_notes") or "") + " " + (v.get("reason") or "")).lower()
    fu = (r.get("final_url") or "").lower()
    steps = [s for s in r.get("trace") or [] if isinstance(s, dict)]
    cap = any(s.get("captcha") or "captcha" in str(s.get("action_kind", "")) for s in steps) or "captcha" in t
    authpage = bool(re.search(r"signup|sign-up|login|log-in|signin|sign-in|verify|auth", fu)) and "oauth" not in fu
    if re.search(r"(browser|session|context|connection)[^.]{0,40}(closed|dropped|unresponsive|error|lost)|new_cdp_session|"
                 r"unable to perform operation|bad state|calls are failing", t):
        return "INFRA: browser/driver died"
    if "already" in t and re.search(r"registered|exist|account", t):
        return "SIGNUP: email 'already registered'"
    if "blank" in t and ("sign" in t or authpage):
        return "SIGNUP: blank signup page"
    if re.search(r"code|verification|email", t) and re.search(
            r"never arrived|not (receive|arrive)|didn.t (receive|arrive)|no (verification|code|email)", t):
        return "SIGNUP: verification mail/code never arrived"
    if "connect.stripe.com" in fu or "stripe" in t:
        return "THIRD-PARTY: Stripe connect" + (" (captcha)" if cap else "")
    if cap:
        return "CAPTCHA"
    if re.search(r"phone|sms", t):
        return "SIGNUP: phone"
    if re.search(r"upgrade|paid plan|pro plan|premium|requires a plan|usage limit", t):
        return "PAYWALL / usage limit"
    if authpage:
        return "SIGNUP: stuck on signup/login"
    if "turn cap" in t:
        return "TASK: in app, ran out of turns"
    return "TASK: in app, could not do it"


def main(arg: str) -> None:
    if arg.endswith(".json"):
        d = json.load(open(arg))
    else:
        with urllib.request.urlopen(f"{BASE}/api/studies/{arg}", timeout=120) as r:
            d = json.load(r)
    tab: dict = collections.defaultdict(collections.Counter)
    for r in d["live_sessions"]:
        tab[(r.get("site_label") or "?", re.sub(r" \(vs .*", "", r.get("task_title") or "?"))][blocker(r)] += 1
    site_tot: dict = collections.defaultdict(collections.Counter)
    for (site, task), c in sorted(tab.items()):
        print(f"{site:10} {task[:40]:40} {dict(c.most_common())}")
        site_tot[site].update(c)
    print()
    for site, c in site_tot.items():
        n = sum(c.values())
        sig = sum(v for k, v in c.items() if k.startswith(("SIGNUP", "CAPTCHA", "THIRD", "PAYWALL")))
        infra = c["INFRA: browser/driver died"]
        print(f"{site:10} reached {c['reached']}/{n}; infra {infra}; signup/captcha/third-party/paywall {sig}; "
              f"task {n - c['reached'] - sig - infra}")


if __name__ == "__main__":
    main(sys.argv[1])
