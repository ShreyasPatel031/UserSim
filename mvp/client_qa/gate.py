"""Publish gate for client QA findings: nothing reaches the review page or Slack unless it passes every check here.

    python -m mvp.client_qa.gate OUT        (reads OUT/findings.json, writes OUT/findings.json + OUT/gate.json)

Why (Reframe build 4255, Nov 26): 51 cards went to the page. A share "freeze" seen only under Appium on an old iOS 17 phone was
reported as an app bug 8 times; screenshots of the phone's home screen were filed as problems; one problem appeared as up to
17 cards; low-confidence detector nitpicks went straight to a person. Each rule below closes one of those holes.

  1. held: crash / freeze / hang / app-closed findings are never published from an automated run alone. They wait for a manual
     reproduction (set "manual_confirmed": true on the finding) because automation itself can crash the app.
  2. no screenshot, no card: a finding without a marked screenshot is held.
  3. weak detector flags (confidence < 0.6) are dropped before review.
  4. one independent review call per card (it never saw the finding being made): is the screenshot the app (not the home screen
     or another app), is the problem plainly visible, is it a real user-facing problem rather than taste, does the mark sit on it.
  5. duplicates: one call groups cards that describe the same problem; the best-evidenced one is kept.
Everything removed is listed in gate.json with its reason, so the cut can be audited.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys

CRASHY = re.compile(r"\b(freez|froze|hang|hung|crash|app (was )?(gone|closed|killed)|home screen|unresponsive|stops responding)", re.I)
MIN_DETECTOR = 0.7

REVIEW = {"type": "object", "properties": {
    "is_app_screen": {"type": "boolean"}, "problem_visible": {"type": "boolean"}, "real_problem": {"type": "boolean"},
    "mark_on_problem": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["is_app_screen", "problem_visible", "real_problem", "mark_on_problem", "why"]}
GROUPS = {"type": "object", "properties": {"groups": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}},
          "required": ["groups"]}


def review(cl, d, f: dict, img: str, brief: str = "") -> dict:
    r, _ = d.call_json(cl, REVIEW, "You are a strict QA lead deciding whether a reported problem is worth a developer's time. "
                       "Reject anything you would not file yourself.", [d.img_block(img, 900), {"type": "text", "text":
        (("What the client's team checks on this build (their own words, treat these as real problems):\n" + brief[:3000] + "\n\n") if brief else "") +
        f"Reported problem ({f['type']}): {f['title']}. {f.get('detail', '')[:600]}\n\n"
        "is_app_screen: the screenshot shows the app under test (not the phone's home screen, a system sheet only, or another app). "
        "problem_visible: the problem itself is plainly visible in this image. "
        "real_problem: a user-facing defect (wrong/inconsistent text or numbers, broken or hidden control, wrong behaviour, layout hiding "
        "content, anything the client's checklist above asks about), not a matter of taste, not speculation, not a momentary loading state. "
        "mark_on_problem: the pen loop(s), if any, surround the element the problem names (true if there is no loop at all). "
        "why: one short sentence."}], effort="low", max_tokens=3000)
    return r or {"is_app_screen": False, "problem_visible": False, "real_problem": False, "mark_on_problem": False, "why": "no answer"}


def gate(out: str, local_img, brief: str = "") -> dict:
    """local_img(f) -> path of the card's screenshot image on disk (marked if it has one), or None."""
    import mvp.client_qa.detect_eval as d
    F = json.load(open(os.path.join(out, "findings.json")))
    keep, held, dropped = [], [], []
    for f in F:
        text = f["title"] + " " + f.get("detail", "")
        if CRASHY.search(text) and not f.get("manual_confirmed"):
            held.append({**f, "reason": "crash/freeze: needs a manual reproduction before it is reported"})
        elif f.get("source") == "detector" and f.get("confidence", 0) < MIN_DETECTOR:
            dropped.append({**f, "reason": f"detector confidence {f.get('confidence')} < {MIN_DETECTOR}"})
        elif not local_img(f):
            held.append({**f, "reason": "no screenshot showing it yet"})
        else:
            keep.append(f)
    cl = d.client()
    with cf.ThreadPoolExecutor(8) as ex:
        revs = list(ex.map(lambda f: review(cl, d, f, local_img(f), brief), keep))
    ok = []
    for f, r in zip(keep, revs):
        bad = [k for k in ("is_app_screen", "problem_visible", "real_problem", "mark_on_problem") if not r.get(k)]
        (dropped.append({**f, "reason": "review: " + ", ".join(bad) + ": " + r.get("why", "")}) if bad else ok.append(f))
    if len(ok) > 1:
        listing = "\n".join(f"{i}: [{f['type']}] {f['title']}. {f.get('detail', '')[:200]}" for i, f in enumerate(ok))
        r, _ = d.call_json(cl, GROUPS, "You merge duplicate QA findings.", [{"type": "text", "text":
            "Group the findings that describe the SAME underlying problem (same screen element or same root cause). Every index appears "
            "in exactly one group; a finding with no duplicate is a group of one.\n\n" + listing}], effort="low", max_tokens=4000)
        seen, final = set(), []
        for g in (r or {}).get("groups", []):
            g = [i for i in g if isinstance(i, int) and 0 <= i < len(ok) and i not in seen]
            if not g:
                continue
            seen.update(g)
            best = max(g, key=lambda i: (ok[i].get("source") == "tester", ok[i].get("confidence", 0)))
            final.append(ok[best])
            dropped += [{**ok[i], "reason": f"duplicate of: {ok[best]['title']}"} for i in g if i != best]
        final += [f for i, f in enumerate(ok) if i not in seen]
        ok = final
    rep = {"published": len(ok), "held": [{"title": f["title"], "reason": f["reason"]} for f in held],
           "dropped": [{"title": f["title"], "reason": f["reason"]} for f in dropped]}
    json.dump(ok, open(os.path.join(out, "findings.json"), "w"), indent=1)
    json.dump({**rep, "held_findings": held}, open(os.path.join(out, "gate.json"), "w"), indent=1)
    return rep


def main() -> None:
    out = sys.argv[1]

    def local_img(f):
        p = os.path.join(out, f.get("marked_img") or "")
        return p if f.get("marked_img") and os.path.exists(p) else None
    bp = os.path.join(out, "brief.txt")   # the client's checklist and watch list for this build
    rep = gate(out, local_img, open(bp).read() if os.path.exists(bp) else "")
    print(f"published {rep['published']}, held {len(rep['held'])}, dropped {len(rep['dropped'])}")
    for x in rep["held"] + rep["dropped"]:
        print(" -", x["title"], "|", x["reason"][:140])


if __name__ == "__main__":
    main()
