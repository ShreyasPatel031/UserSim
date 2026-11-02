"""Seeded sample of own-link-versus-PH-field X conflicts, for hand labeling. Read-only on the build output.
    python sample_conflicts.py --dir work/v3c --n 50 --out work/out/x_conflict_audit_50.csv [--lookup-list work/out/x_lookup_handles.txt]
A conflict = a person whose own PH link gives one X handle (ph_self_link, 0.95) while PH's `twitter` field names a different one
(ph_twitter_field, 0.2). Label which account is the person: link / field / both / neither / unsure, with evidence.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd


def main(d: str, n: int, out: str, seed: int, lookup_list: str | None = None) -> pd.DataFrame:
    H = pd.read_parquet(f"{d}/handles.parquet")
    P = pd.read_parquet(f"{d}/persons.parquet")
    Pr = pd.read_parquet(f"{d}/profiles.parquet")
    x = H[H.platform == "x"]
    field = x[(x.source == "ph_twitter_field") & (x.confidence < 0.5)][["person_id", "handle"]].rename(columns={"handle": "field_handle"})
    link = x[x.source == "ph_self_link"][["person_id", "handle"]].rename(columns={"handle": "link_handle"})
    c = field.merge(link, on="person_id").drop_duplicates("person_id")
    c = c[c.field_handle != c.link_handle]
    total = len(c)
    if lookup_list:  # every handle (all conflicts, not the sample) a read-only X lookup must resolve for build_v3's x_lookup.json
        with open(lookup_list, "w") as f:
            f.write("\n".join(sorted(set(c.field_handle) | set(c.link_handle))) + "\n")
    c = c.sample(min(n, total), random_state=seed).merge(P[["person_id", "display_name"]], on="person_id", how="left")
    ph = Pr[Pr.platform == "producthunt"].set_index("person_id")
    c["ph_headline"] = c.person_id.map(lambda p: (json.loads(ph.extra[p]).get("headline") if p in ph.index and isinstance(ph.extra[p], str) else None))
    c["ph_bio"] = c.person_id.map(lambda p: (str(ph.bio[p])[:200] if p in ph.index and ph.bio[p] is not None else ""))
    for col in ("label_link_field_both_neither_unsure", "evidence"):
        c[col] = ""
    c.to_csv(out, index=False)
    print(f"{len(c)} of {total} conflicts sampled (seed {seed}) -> {out}")
    return c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--out", default="x_conflict_audit_50.csv")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--lookup-list", help="also write every conflict handle (one per line) for an X lookup")
    a = ap.parse_args()
    main(a.dir, a.n, a.out, a.seed, a.lookup_list)
