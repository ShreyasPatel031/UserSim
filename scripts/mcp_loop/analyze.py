"""Summarise one run_study.py output dir: per-cell outcome, judge verdict, and every harness error.

  python scripts/mcp_loop/analyze.py <out_dir> [--cells] [--errors]

Reads <out>/cells/*.jsonl (Claude Code stream-json traces) and <out>/report.json.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path


def tool_results(content) -> str:
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return str(content or "")


def parse_cell(path: Path) -> dict:
    row = {"cell": path.stem, "tools": collections.Counter(), "errors": [], "finish": None, "end": None,
           "acts": 0, "last_url": "", "signup_email": None, "turns": None, "cost": None, "start_error": None}
    pending: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = e.get("type")
        if t == "assistant":
            for c in e["message"]["content"]:
                if c.get("type") == "tool_use":
                    name = c["name"].replace("mcp__usersim__", "")
                    row["tools"][name] += 1
                    pending[c["id"]] = name
                    if name == "usersim_act":
                        row["acts"] += 1
                    if name == "usersim_finish":
                        row["finish"] = {k: c["input"].get(k) for k in ("outcome", "notes")}
        elif t == "user":
            for c in e["message"]["content"]:
                if not (isinstance(c, dict) and c.get("type") == "tool_result"):
                    continue
                name = pending.get(c.get("tool_use_id"), "?")
                text = tool_results(c.get("content"))
                try:
                    meta = json.loads(text.split("\n", 1)[0]) if text.startswith("{") else {}
                except ValueError:
                    meta = {}
                if c.get("is_error") or meta.get("error"):
                    msg = meta.get("error") or text[:200]
                    row["errors"].append(f"{name}: {msg}"[:240])
                    if name == "usersim_start_session":
                        row["start_error"] = msg
                for key in ("action_error",):
                    if meta.get(key):
                        row["errors"].append(f"{name}.{key}: {meta[key]}"[:240])
                if meta.get("url"):
                    row["last_url"] = meta["url"]
                if name == "usersim_signup_identity" and meta.get("email"):
                    row["signup_email"] = meta["email"]
                if name == "usersim_finish":
                    row["judge"] = {k: meta.get(k) for k in ("goal_reached", "proof_pass")}
        elif t == "result":
            row["end"] = e.get("subtype")
            row["turns"] = e.get("num_turns")
            row["cost"] = e.get("total_cost_usd")
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--cells", action="store_true", help="one line per cell")
    ap.add_argument("--errors", action="store_true", help="list every error")
    a = ap.parse_args()
    out = Path(a.out)
    rows = [parse_cell(p) for p in sorted((out / "cells").glob("*.jsonl"))]
    n = len(rows)
    fin = [r for r in rows if r["finish"]]
    goal = [r for r in rows if (r.get("judge") or {}).get("goal_reached")]
    proof = [r for r in rows if (r.get("judge") or {}).get("proof_pass")]
    outcomes = collections.Counter((r["finish"] or {}).get("outcome") or "never_finished" for r in rows)
    print(f"cells {n} | called finish {len(fin)} | judge goal_reached {len(goal)} | proof_pass {len(proof)}")
    print("driver outcomes:", dict(outcomes))
    cost = sum(r["cost"] or 0 for r in rows)
    print(f"agent cost ${cost:.2f} | mean acts {sum(r['acts'] for r in rows) / max(n, 1):.1f}")
    by_site = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        site = r["cell"].split("__")[-1]
        by_site[site][0] += 1
        by_site[site][1] += bool((r.get("judge") or {}).get("goal_reached"))
    print("goal by site:", {k: f"{v[1]}/{v[0]}" for k, v in sorted(by_site.items())})
    errs = collections.Counter(re.sub(r"[0-9a-f]{16,}|\d+", "#", e)[:120] for r in rows for e in r["errors"])
    print("\nerror kinds:")
    for k, v in errs.most_common(25):
        print(f"  {v:4d}  {k}")
    if a.cells:
        print()
        for r in rows:
            j = r.get("judge") or {}
            print(f"{r['cell']:28s} acts={r['acts']:2d} out={(r['finish'] or {}).get('outcome') or '-':9s} "
                  f"goal={j.get('goal_reached')!s:5s} end={r['end']} errs={len(r['errors'])} url={r['last_url'][:60]}")
    if a.errors:
        for r in rows:
            for e in r["errors"]:
                print(r["cell"], e)
    rep = out / "report.json"
    if rep.is_file():
        try:
            d = json.loads(rep.read_text())
            print("\nreport:", d.get("status"), "|", str(d.get("headline"))[:200])
        except ValueError:
            print("\nreport (raw):", rep.read_text()[:300])


if __name__ == "__main__":
    main()
