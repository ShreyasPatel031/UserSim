#!/usr/bin/env python3
"""Build replay.html for a UserSim user-test run folder.

Usage: python3 replay.py <run_dir>

Reads <run_dir>/plan.json, <run_dir>/runs/*.json and (optional) <run_dir>/divergences.json, and writes
<run_dir>/replay.html: one lane per tester for each task, step by step with screenshots and thoughts, divergences
marked at the step where they happen, and the proposed variations with their status. Standard library only; the page
loads no scripts and fetches only the screenshot images linked from the UserSim reports.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def action_text(a) -> str:
    if isinstance(a, str):
        return a
    if not isinstance(a, dict):
        return ""
    t = a.get("type", "")
    if t == "type":
        return f'type "{str(a.get("text", ""))[:60]}"'
    if t == "navigate":
        return f"go to {a.get('url', '')}"
    if t == "key":
        return f"press {a.get('keys', '')}"
    if t == "scroll":
        return f"scroll {a.get('dy', '')}"
    if t == "select":
        return f'select "{a.get("option", "")}"'
    return t


def steps_of(run: dict) -> list[dict]:
    rep = run.get("report") or {}
    rsteps = rep.get("steps") if isinstance(rep, dict) else None
    shots = {}
    for s in rsteps or []:
        if isinstance(s, dict) and s.get("step") is not None:
            shots[s["step"]] = s
    out = []
    base = run.get("steps") or rsteps or []
    for s in base:
        if not isinstance(s, dict):
            continue
        n = s.get("step")
        r = shots.get(n, {})
        out.append({
            "step": n,
            "action": action_text(s.get("action") or r.get("action")),
            "thought": s.get("thought") or r.get("thought") or "",
            "url": s.get("url") or r.get("url") or "",
            "error": s.get("error") or r.get("error") or "",
            "screenshot": r.get("screenshot") or s.get("screenshot") or "",
        })
    return out


def task_index(name: str) -> int:
    m = re.search(r"__task(\d+)", name)
    return int(m.group(1)) if m else 1


CSS = """
:root{--bg:#fbfaf8;--fg:#1d1d1b;--muted:#6b6a66;--card:#ffffff;--line:#e4e1db;--ok:#2f7d4f;--warn:#a1661a;--bad:#b23a3a;--accent:#3d5a99;--mark:#fff3d6}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ecebe8;--muted:#a3a19b;--card:#1f1f1d;--line:#34332f;--ok:#6cc08f;--warn:#e0a85a;--bad:#e07b7b;--accent:#8fa8e0;--mark:#3a3220}}
:root[data-theme="dark"]{--bg:#161615;--fg:#ecebe8;--muted:#a3a19b;--card:#1f1f1d;--line:#34332f;--ok:#6cc08f;--warn:#e0a85a;--bad:#e07b7b;--accent:#8fa8e0;--mark:#3a3220}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1400px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px}h3{font-size:15px;margin:0}
.muted{color:var(--muted)}.note{border-left:3px solid var(--warn);padding:8px 12px;background:var(--card);margin:14px 0;font-size:14px}
.lanes{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(300px,1fr);gap:12px;overflow-x:auto;padding-bottom:8px}
.lane{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}
.badge{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid currentColor;margin-left:6px}
.completed{color:var(--ok)}.gave_up{color:var(--warn)}.blocked,.not_run{color:var(--bad)}
.step{border-top:1px solid var(--line);padding:8px 0}.step.div{background:var(--mark);margin:0 -12px;padding:8px 12px}
.step img{width:100%;border:1px solid var(--line);border-radius:6px;margin-top:6px}
.act{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--muted)}.thought{margin:2px 0}
.dv{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.var{margin:6px 0 0 0;padding:6px 10px;border-left:3px solid var(--accent)}
.st-applied{color:var(--ok)}.st-declined{color:var(--muted)}.st-proposed{color:var(--accent)}
a{color:var(--accent)}details summary{cursor:pointer;color:var(--muted);font-size:13px}
"""


def build(run_dir: Path) -> Path:
    plan = load(run_dir / "plan.json", {})
    div = load(run_dir / "divergences.json", {"divergences": []})
    runs = {}
    for f in sorted((run_dir / "runs").glob("*.json")):
        runs[f.stem] = load(f, {})
    tasks = plan.get("tasks") or []
    testers = plan.get("testers") or []
    marks: dict[tuple[str, object], list[str]] = {}
    for d in div.get("divergences", []):
        for ev in d.get("evidence", []):
            marks.setdefault((ev.get("run"), ev.get("step")), []).append(d.get("id", ""))

    h = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>UserSim replay</title><style>", CSS, "</style></head><body><main>"]
    h.append(f"<h1>User test replay</h1><div class='muted'>{esc(plan.get('product_url'))}"
             f"{' · compared with ' + esc(', '.join(plan.get('competitors') or [])) if plan.get('competitors') else ''}</div>")
    if plan.get("accuracy"):
        h.append(f"<div class='note'><b>How far to trust the groups.</b> {esc(plan['accuracy'])}"
                 f"{' (groups snapshot ' + esc(plan.get('groups_snapshot')) + ')' if plan.get('groups_snapshot') else ''}</div>")
    h.append("<h2>Who tested</h2><ul>")
    for t in testers:
        extra = f" — drawn from {esc(t.get('group'))}, {esc(t.get('people'))} people" if t.get("kind") == "group" else ""
        h.append(f"<li><b>{esc(t.get('label'))}</b>{extra}: <span class='muted'>{esc(t.get('persona'))}</span></li>")
    h.append("</ul>")

    n_tasks = max([len(tasks)] + [task_index(k) for k in runs])
    for ti in range(1, n_tasks + 1):
        title = tasks[ti - 1] if ti - 1 < len(tasks) else f"Task {ti}"
        h.append(f"<h2>Task {ti}: {esc(title)}</h2><div class='lanes'>")
        labels = [t.get("label") for t in testers] or sorted({k.split('__')[0] for k in runs})
        for lab in labels:
            key = f"{lab}__task{ti}"
            run = runs.get(key)
            if run is None:
                h.append(f"<div class='lane'><h3>{esc(lab)}<span class='badge not_run'>not run</span></h3></div>")
                continue
            oc = run.get("outcome") or "not_run"
            st = steps_of(run)
            watch = run.get("watch_url") or ((run.get("report") or {}).get("links") or {}).get("watch")
            h.append(f"<div class='lane'><h3>{esc(lab)}<span class='badge {esc(oc)}'>{esc(oc.replace('_', ' '))}</span></h3>")
            rec = (' · <a href="' + esc(watch) + '" target="_blank" rel="noopener">recording</a>') if watch else ""
            h.append(f"<div class='muted' style='font-size:13px'>{len(st)} steps{rec}</div>")
            if run.get("notes"):
                h.append(f"<p style='font-size:14px'>{esc(run['notes'])}</p>")
            for s in st:
                m = marks.get((key, s["step"]))
                cls = "step div" if m else "step"
                h.append(f"<div class='{cls}'><div class='act'>#{esc(s['step'])} {esc(s['action'])}"
                         f"{' · divergence ' + esc(', '.join(m)) if m else ''}</div>")
                if s["thought"]:
                    h.append(f"<div class='thought'>“{esc(s['thought'])}”</div>")
                if s["error"]:
                    h.append(f"<div class='blocked' style='font-size:13px'>{esc(s['error'])}</div>")
                if s["screenshot"]:
                    h.append(f"<details><summary>screenshot</summary><img loading='lazy' alt='step {esc(s['step'])}' src='{esc(s['screenshot'])}'></details>")
                h.append("</div>")
            h.append("</div>")
        h.append("</div>")

    ds = div.get("divergences", [])
    h.append(f"<h2>Divergences and variations ({len(ds)})</h2>")
    if not ds:
        h.append("<p class='muted'>None recorded yet.</p>")
    for d in ds:
        h.append(f"<div class='dv'><h3>{esc(d.get('id'))} · {esc(d.get('kind'))} · task {esc(d.get('task'))} · "
                 f"{esc(', '.join(d.get('groups') or []))}</h3><p>{esc(d.get('summary'))}</p>")
        for ev in d.get("evidence", []):
            h.append(f"<div class='muted' style='font-size:13px'>{esc(ev.get('run'))} step {esc(ev.get('step'))}: “{esc(ev.get('thought'))}”</div>")
        for v in d.get("variations", []):
            stt = v.get("status", "proposed")
            h.append(f"<div class='var'><b>{esc(v.get('id'))} {esc(v.get('title'))}</b> <span class='st-{esc(stt)}'>[{esc(stt)}]</span>"
                     f"<div style='font-size:14px'>{esc(v.get('change'))}</div>"
                     f"<div class='act'>{esc(', '.join(v.get('files') or []))}</div></div>")
        h.append("</div>")
    h.append("<p class='muted' style='margin-top:40px;font-size:13px'>Generated by the UserSim plugin for Claude Code.</p></main></body></html>")
    out = run_dir / "replay.html"
    out.write_text("".join(h), encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: replay.py <run_dir>")
    print(build(Path(sys.argv[1])))
