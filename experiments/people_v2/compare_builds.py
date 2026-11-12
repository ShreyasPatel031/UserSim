"""Compare two people_v2 build directories (e.g. v3g vs the new one). Read-only. python compare_builds.py PREV_DIR NEW_DIR"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd


def tbl(d, n):
    return pd.read_parquet(os.path.join(d, f"{n}.parquet"))


def main(prev: str, new: str) -> None:
    for n in ("persons", "handles", "profiles", "events"):
        a, b = len(tbl(prev, n)), len(tbl(new, n))
        print(f"rows.{n}: {a} -> {b} ({b - a:+d})")
    pa, pb = tbl(prev, "persons"), tbl(new, "persons")
    print(f"persons added: {len(set(pb.person_id) - set(pa.person_id))}, removed: {len(set(pa.person_id) - set(pb.person_id))}")
    ra, rb = (json.load(open(os.path.join(d, "build_report.json"))) for d in (prev, new))
    for k in sorted(set(ra.get("stats", {})) | set(rb.get("stats", {}))):
        print(f"stats.{k}: {ra.get('stats', {}).get(k)} -> {rb.get('stats', {}).get(k)}")
    ea, eb = tbl(prev, "events"), tbl(new, "events")
    g = pd.concat([ea.groupby(["platform", "kind"]).size().rename("prev"), eb.groupby(["platform", "kind"]).size().rename("new")], axis=1).fillna(0).astype(int)
    g["delta"] = g["new"] - g["prev"]
    print("events by platform/kind:\n" + g.to_string())
    ha, hb = tbl(prev, "handles"), tbl(new, "handles")
    c = pd.concat([ha.groupby(["platform", "source", "confidence"]).size().rename("prev"), hb.groupby(["platform", "source", "confidence"]).size().rename("new")], axis=1).fillna(0).astype(int)
    c = c[c.prev != c.new]
    print("handle rows that changed by platform/source/confidence:\n" + (c.to_string() if len(c) else "  none"))
    qa, qb = (tbl(d, "profiles").groupby(["platform", "observed_on_quality"]).size() for d in (prev, new))
    q = pd.concat([qa.rename("prev"), qb.rename("new")], axis=1).fillna(0).astype(int)
    print("profile date quality:\n" + q.to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
