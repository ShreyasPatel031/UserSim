"""Native Android comparison study: one product app and its rival apps, every persona x task cell.

Mirrors the web comparison study (fast_plan personas/tasks, comparison scoring levels) but each
cell is a run of ``android_agent`` on the emulator. Apps must be installed and signed in already.

    python -m mvp.android_study --config results/android_study/config.json
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from mvp import android_agent as aa
from mvp.comparison import coerce_score

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "android_study"

SCORE_PROMPT = """You score one run of a mobile-app comparison study. Judge only the evidence below (the step trace and the final screenshot). Do not trust the agent's own claims.

Persona: {name}, {role}. {bio}
Job to be done: {task}
App: {app}
Agent outcome: {outcome}
Step trace:
{steps}

How well did this persona get what they needed for this job in this app?
level:
- in_product: the persona actually did the job (or saw the real result) inside the app. Score 7-10.
- clear_evidence: the app clearly showed where and how it does this job, but the persona did not finish it. Score 4-7.
- vague_marketing: only generic screens, upsells or tips; the persona still cannot tell if or how it does the job. Score 2-4.
- wall_or_nothing: blocked by a paywall, login or error, or nothing relevant was found. Score 0-2.
Within a band, score higher for less friction and a faster, clearer path for this persona.
friction: 0 none, 1 minor, 2 major, 3 severe (walls, dead ends, loops, confusing UI).

Return JSON only:
{{"level": "in_product|clear_evidence|vague_marketing|wall_or_nothing", "score": 0-10, "friction": 0-3,
  "reason": "one sentence naming what the screenshot or trace shows", "evidence_step": step number,
  "quote": "up to 20 words of on-screen text backing the reason, or empty", "friction_note": "at most 12 words, or empty"}}"""


def cell_task(persona: dict[str, Any], task: str, app: str) -> str:
    return (
        f"You are {persona['name']}, {persona.get('role', '')}. {persona.get('bio', '')} "
        f"You already have an account and are signed in to {app}. Your job: {task}. "
        "Use the app as this person would to get it done. Dismiss promos and permission prompts. "
        "Never start a purchase or subscription. Finish with done once the job is done (or you can see the result), "
        "or fail if the app cannot do it."
    )


def score_cell(client: Any, model: str, persona: dict[str, Any], task: str, app: str,
               outcome: dict[str, Any], history: list[dict], final_png: bytes) -> dict[str, Any] | None:
    from google.genai import types

    steps = "\n".join(
        f"{h.get('step')}. {h.get('action')} -> {h.get('result')}: {str(h.get('reason') or '')[:160]}" for h in history
    ) or "(no steps)"
    prompt = SCORE_PROMPT.format(
        name=persona["name"], role=persona.get("role", ""), bio=persona.get("bio", ""), task=task, app=app,
        outcome=f"{outcome.get('reason')}: {str(outcome.get('summary') or '')[:300]}", steps=steps,
    )
    parts: list[Any] = [prompt]
    if final_png:
        parts.insert(0, types.Part.from_bytes(data=final_png, mime_type="image/png"))
    resp = client.models.generate_content(
        model=model, contents=parts,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0),
    )
    try:
        return coerce_score(json.loads(resp.text or "{}"))
    except json.JSONDecodeError:
        return None


def cells(cfg: dict[str, Any]) -> list[tuple[int, int, int]]:
    """(persona, task, app) indices, app innermost so partial results stay comparable."""
    return [(p, t, a) for t in range(len(cfg["tasks"])) for p in range(len(cfg["personas"])) for a in range(len(cfg["apps"]))]


def summarize(cfg: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for app in cfg["apps"]:
        mine = [r for r in rows if r["app"] == app["name"] and r.get("score")]
        n = len(mine)
        out[app["name"]] = {
            "cells": n,
            "mean_score": round(sum(r["score"]["score"] for r in mine) / n, 2) if n else None,
            "done_in_app": sum(r["score"]["level"] == "in_product" for r in mine),
            "mean_friction": round(sum(r["score"]["friction"] for r in mine) / n, 2) if n else None,
            "by_task": {
                t: (round(sum(r["score"]["score"] for r in mine if r["task"] == t) / k, 1)
                    if (k := sum(r["task"] == t for r in mine)) else None)
                for t in cfg["tasks"]
            },
        }
    return out


def report_html(cfg: dict[str, Any], rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    e = html.escape
    apps = [a["name"] for a in cfg["apps"]]
    head = "".join(f"<th>{e(a)}</th>" for a in apps)
    lines = [f"<tr><td>Mean score (0-10)</td>{''.join(f'<td>{summary[a]['mean_score']}</td>' for a in apps)}</tr>",
             f"<tr><td>Done in app</td>{''.join(f'<td>{summary[a]['done_in_app']}/{summary[a]['cells']}</td>' for a in apps)}</tr>",
             f"<tr><td>Mean friction (0-3)</td>{''.join(f'<td>{summary[a]['mean_friction']}</td>' for a in apps)}</tr>"]
    lines += [f"<tr><td>{e(t)}</td>{''.join(f'<td>{summary[a]['by_task'][t]}</td>' for a in apps)}</tr>" for t in cfg["tasks"]]
    detail = "".join(
        f"<tr><td>{e(r['app'])}</td><td>{e(r['persona'])}</td><td>{e(r['task'])}</td>"
        f"<td>{(r.get('score') or {}).get('score', '')}</td><td>{e((r.get('score') or {}).get('level', ''))}</td>"
        f"<td>{(r.get('score') or {}).get('friction', '')}</td><td>{e((r.get('score') or {}).get('reason', ''))}</td>"
        f"<td>{r.get('steps', '')}</td></tr>"
        for r in rows
    )
    personas = "".join(f"<li><b>{e(p['name'])}</b>, {e(p.get('role', ''))}: {e(p.get('bio', ''))}</li>" for p in cfg["personas"])
    return f"""<!doctype html><meta charset="utf-8"><title>{e(cfg['title'])}</title>
<style>body{{font:14px system-ui;margin:24px;max-width:1200px}}table{{border-collapse:collapse;margin:12px 0}}
td,th{{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}}th{{background:#f4f4f4}}</style>
<h1>{e(cfg['title'])}</h1><p>Native Android apps on an emulator, {len(cfg['personas'])} personas x {len(cfg['tasks'])} tasks per app,
{len(rows)} runs scored from the final screen and step trace.</p>
<h2>Scorecard</h2><table><tr><th></th>{head}</tr>{''.join(lines)}</table>
<h2>Personas</h2><ul>{personas}</ul>
<h2>All runs</h2><table><tr><th>App</th><th>Persona</th><th>Task</th><th>Score</th><th>Level</th><th>Friction</th><th>Why</th><th>Steps</th></tr>{detail}</table>"""


def run_study(cfg: dict[str, Any], *, out_dir: Path, max_steps: int, serial: str | None,
              only_apps: set[str] | None = None, only_cells: set[str] | None = None) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    adb = aa.Adb(serial)
    client = aa._model_client()
    model = os.environ.get("MVP_ANDROID_MODEL", "gemini-2.5-flash")
    rows_path = out_dir / "rows.json"
    rows: list[dict[str, Any]] = json.loads(rows_path.read_text()) if rows_path.exists() else []
    done = {(r["persona"], r["task"], r["app"]) for r in rows}
    for p, t, a in cells(cfg):
        persona, task, app = cfg["personas"][p], cfg["tasks"][t], cfg["apps"][a]
        if (persona["name"], task, app["name"]) in done or (only_apps and app["name"] not in only_apps):
            continue
        if only_cells is not None and f"{a}-{p}-{t}" not in only_cells:
            continue
        adb.shell(f"am force-stop {app['package']}")
        run_dir = out_dir / "runs" / f"{a}-{p}-{t}"
        t0 = time.time()
        try:
            outcome = aa.run(cell_task(persona, task, app["name"]), app["package"], max_steps=max_steps,
                             serial=serial, run_dir=run_dir)
        except Exception as exc:  # noqa: BLE001
            outcome = {"ok": False, "reason": f"error: {exc!r}"[:200], "run_dir": str(run_dir)}
        trace = json.loads((run_dir / "trace.json").read_text()) if (run_dir / "trace.json").exists() else {}
        final = (run_dir / "final.png").read_bytes() if (run_dir / "final.png").exists() else b""
        try:
            score = score_cell(client, model, persona, task, app["name"], outcome, trace.get("history") or [], final)
        except Exception as exc:  # noqa: BLE001
            print(f"[study] score failed: {exc!r}", flush=True)
            score = None
        rows.append({"app": app["name"], "persona": persona["name"], "task": task, "ok": outcome.get("ok"),
                     "reason": outcome.get("reason"), "summary": outcome.get("summary"), "steps": outcome.get("steps"),
                     "seconds": round(time.time() - t0), "score": score, "run_dir": str(run_dir)})
        rows_path.write_text(json.dumps(rows, indent=2))
        summary = summarize(cfg, rows)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        (out_dir / "report.html").write_text(report_html(cfg, rows, summary))
        print(f"[study] {len(rows)}/{len(cells(cfg))} {app['name']} | {persona['name']} | {task} -> "
              f"{(score or {}).get('score')} ({outcome.get('reason')}, {rows[-1]['seconds']}s)", flush=True)
    return summarize(cfg, rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--serial")
    ap.add_argument("--apps", help="comma-separated app names to run (default: all); resume with the same --out")
    ap.add_argument("--cells", help="comma-separated <app>-<persona>-<task> index keys to run (for sharding)")
    args = ap.parse_args()
    cfg = json.loads(args.config.read_text())
    out = args.out or OUT / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    if args.config.resolve() != (out / "config.json").resolve():
        shutil.copy(args.config, out / "config.json")
    only = {a.strip() for a in args.apps.split(",") if a.strip()} if args.apps else None
    cells_only = {c.strip() for c in args.cells.split(",") if c.strip()} if args.cells else None
    print(json.dumps(run_study(cfg, out_dir=out, max_steps=args.max_steps, serial=args.serial, only_apps=only,
                               only_cells=cells_only), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
