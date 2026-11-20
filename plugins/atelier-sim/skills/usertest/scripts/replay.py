#!/usr/bin/env python3
"""Build the interactive results page for a Atelier Sim user-test run folder.

Usage: python3 replay.py <run_dir>

Reads, from <run_dir>:
  plan.json      the approved plan (testers, tasks, competitors)
  runs/*.json    one file per tester x product (written by the sim-user agents)
  session.json   Claude's analysis: headline, lede, products, stages, voices, highlights,
                 divergences and ranked variations (see SKILL.md, step 4)
Writes <run_dir>/replay.html: a self-contained page (data inlined) built from
../assets/report.html. Screenshots are linked from the Atelier Sim report URLs, not copied.
Standard library only. Makes no network calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def norm_action(a):
    if isinstance(a, dict):
        return a
    if isinstance(a, str):
        try:
            v = json.loads(a)
            return v if isinstance(v, dict) else {"type": a}
        except ValueError:
            return {"type": a}
    return {}


def run_steps(run: dict) -> list[dict]:
    rep = run.get("report") if isinstance(run.get("report"), dict) else {}
    base = rep.get("steps_screenshot_base") or ""
    by_step = {s.get("step"): s for s in (rep.get("steps") or []) if isinstance(s, dict)}
    out = []
    for s in run.get("steps") or list(by_step.values()):
        if not isinstance(s, dict):
            continue
        n = s.get("step")
        r = by_step.get(n, {})
        shot = s.get("screenshot") or r.get("screenshot") or (base.replace("{n}", str(n)) if base and n is not None else "")
        out.append({"step": n, "action": norm_action(s.get("action") or r.get("action")),
                    "thought": s.get("thought") or r.get("thought") or "", "shot": shot})
    return out


def build(run_dir: Path) -> Path:
    plan = load(run_dir / "plan.json", {})
    sess = load(run_dir / "session.json", {})
    runs = {}
    for f in sorted((run_dir / "runs").glob("*.json")):
        r = load(f, {})
        steps = run_steps(r)
        fr = (sess.get("friction_steps") or {}).get(f.stem, {})
        for s in steps:
            if str(s["step"]) in fr:
                s["friction"] = fr[str(s["step"])]
        runs[f.stem] = {"outcome": r.get("outcome") or "not_run", "notes": r.get("notes") or "", "steps": steps,
                        "watch": r.get("watch_url") or ""}
    # Every tester x product the page can show must exist with at least one step, or the page breaks.
    labels = [t.get("label") for t in (sess.get("testers") or plan.get("testers") or []) if t.get("label")]
    for lab in labels:
        for pk in (sess.get("products") or {}):
            runs.setdefault(f"{lab}__{pk}", {"outcome": "not_run", "notes": "This run did not happen.", "steps": [],
                                             "watch": ""})
    for r in runs.values():
        if not r["steps"]:
            r["steps"] = [{"step": 0, "action": {}, "thought": r["notes"] or "No steps were recorded.", "shot": ""}]
    data = {k: v for k, v in sess.items() if k != "friction_steps"}
    data.setdefault("testers", plan.get("testers") or [])
    for i, t in enumerate(data["testers"]):
        t.setdefault("slot", i % 4)
        t.setdefault("name", t.get("label"))
        t.setdefault("short", t.get("name"))
    for key in ("stages", "voices"):
        data.setdefault(key, {})
    for key in ("highlights", "divergences", "variations", "method"):
        data.setdefault(key, [])
    data["runs"] = runs
    tpl = (Path(__file__).resolve().parent.parent / "assets" / "report.html").read_text(encoding="utf-8")
    page = tpl.replace("__SESSION_JSON__", json.dumps(data).replace("</", "<\\/"))
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + page + "</body></html>")
    out = run_dir / "replay.html"
    out.write_text(doc, encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: replay.py <run_dir>")
    print(build(Path(sys.argv[1])))
