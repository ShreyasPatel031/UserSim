#!/usr/bin/env python3
"""Synthesize comparative UX reviews after persona triad runs (Bland/Vapi/Retell)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from google import genai
from google.genai import types

from auth import vertex_credentials
from capability.voice_ai_personas import (
    COMPARATIVE_SYNTHESIS_PROMPT,
    PERSONA_BY_ID,
    PERSONA_GOALS,
)
from config import GCP_PROJECT, MODEL


def _synthesize_group(persona_id: str, goal_key: str, runs: list[dict]) -> dict:
    persona = PERSONA_BY_ID[persona_id]
    goals = {g["task_key"]: g for g in PERSONA_GOALS[persona_id]}
    goal = goals[goal_key]
    by_plat = {r["website"]: r for r in runs}
    lines = []
    for plat in ("bland", "vapi", "retell"):
        r = by_plat.get(plat)
        if not r:
            lines.append(f"{plat}: MISSING RUN")
            continue
        lines.append(
            f"{plat}: success={r.get('success')} status={r.get('status')} "
            f"url={r.get('final_url')} actions={r.get('num_actions')}\n"
            f"  judge={r.get('judge_reason')}\n"
            f"  stop={r.get('stop_reason')}\n"
            f"  agent_notes={_agent_done_text(r)}"
        )
    prompt = COMPARATIVE_SYNTHESIS_PROMPT.format(
        persona_name=persona.name,
        persona_role=persona.role,
        goal_title=goal["title"],
        user_goal=goal["user_goal"],
    )
    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location="us-central1",
        credentials=vertex_credentials(),
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt + "\n\nRUNS:\n" + "\n".join(lines),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    text = (resp.text or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"raw": text, "parse_error": True}
    data["persona_id"] = persona_id
    data["goal_key"] = goal_key
    data["runs"] = {
        plat: {
            "success": by_plat.get(plat, {}).get("success"),
            "final_url": by_plat.get(plat, {}).get("final_url"),
            "status": by_plat.get(plat, {}).get("status"),
        }
        for plat in ("bland", "vapi", "retell")
    }
    return data


def _agent_done_text(run: dict) -> str:
    actions = run.get("actions") or []
    for a in reversed(actions):
        act = a.get("action")
        blob = json.dumps(act, default=str) if not isinstance(act, str) else act
        if "done" in blob.lower() or "success" in blob.lower():
            return blob[:1200]
    return (run.get("judge_evidence") or "")[:600]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, help="Bakeoff JSON with persona runs")
    ap.add_argument(
        "--out",
        default=None,
        help="Output comparative JSON (default: sibling *_comparative.json)",
    )
    args = ap.parse_args()
    path = Path(args.manifest)
    data = json.loads(path.read_text())
    runs = data.get("runs") or []
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in runs:
        pid = r.get("persona_id")
        gk = r.get("goal_key") or r.get("comparative_group")
        if pid and gk:
            groups[(pid, gk)].append(r)
        else:
            # Infer from task_id like p1_t1_call_logs_overview_bland
            tid = r.get("task_id") or ""
            for persona in PERSONA_BY_ID:
                for g in PERSONA_GOALS[persona]:
                    if tid.startswith(g["task_key"]):
                        groups[(persona, g["task_key"])].append(r)
    reviews = []
    for (pid, gk), group_runs in sorted(groups.items()):
        print(f"Synthesizing {pid} / {gk} ({len(group_runs)} runs)...", flush=True)
        reviews.append(_synthesize_group(pid, gk, group_runs))
    out = Path(args.out) if args.out else path.with_name(path.stem + "_comparative.json")
    out.write_text(json.dumps({"n": len(reviews), "reviews": reviews}, indent=2))
    print(f"Wrote {out}", flush=True)
    for rev in reviews:
        print(
            f"  {rev.get('persona_id')} {rev.get('goal_key')}: "
            f"winner={rev.get('most_likely_to_use')} "
            f"why={str(rev.get('why_winner', ''))[:120]}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
