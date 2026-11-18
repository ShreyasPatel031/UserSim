"""Readable output for Shreyas (orchestrator 07:50Z Nov 11): K=12 segment descriptions (dominant attributes / topics by
lift of the segment's pre-Sep upvote shares over everyone's) and, for 3 recent cold-start launches (test period, most
segment voters), the predicted top / bottom segments (train-period segment x attribute lifts over the launch's
attributes) against what happened (segment votes / exposures, lift over the all-segment rate). Product names only; no
usernames. usage: SIMBT=<dir> python seg_readable.py -> results/seg_readable_k12.md"""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; K = 12


def main():
    import two_level as T
    ok, _ = T._label_maps()
    A = pickle.load(open(f"{WORK}/segattr_k{K}.pkl", "rb"))
    seg, ATTR, amat, lift, cold, desc = A["seg"], A["ATTR"], A["amat"], A["lift_train"]["voters"], A["cold"], A["desc"]
    si = {a: i for i, a in enumerate(ATTR)}
    I = pd.read_parquet(f"{WORK}/items.parquet"); I["id"] = I.id.astype(str); I = I.set_index("id")
    E = pd.read_parquet(f"{WORK}/events_cp.parquet"); E["item"] = E.item.astype(str); E["date"] = E.date.astype(str).str[:10]
    up = E[(E.kind == "upvote") & E.item.isin(I.index)].copy(); up["lday"] = up.item.map(I.day)
    up = up[(up.date == up.lday) & (up.lday >= "2026-10-20") & up.person.isin(seg.index)]
    tied = {}
    rows = []
    for d, g in up.groupby("lday"):
        g = g[ok(g.person, d)]
        f = f"{WORK}/arrivals/{d}.parquet"
        ts = set(zip(*pd.read_parquet(f, columns=["person", "id"]).astype(str).values.T)) if os.path.exists(f) else set()
        act = g.person.unique(); votes = set(zip(g.person, g.item))
        for L in I[I.day == d].index:
            if L not in cold:
                continue
            pp = [p for p in act if (p, L) not in ts]
            s = seg.reindex(pp).values.astype(int); y = np.array([(p, L) in votes for p in pp], float)
            rows.append((d, L, s, y))
    rows.sort(key=lambda r: (r[3].sum(), r[0]), reverse=True)
    pick = sorted(rows[:6], key=lambda r: r[0], reverse=True)[:3]
    nm = lambda s_: f"S{s_} ({', '.join(x.replace('cat_', '').replace('aud_', 'for ').replace('_', ' ') for x in desc[s_]['top_attrs'][:2])}; {', '.join(desc[s_]['top_topics'][:2])})"
    out = ["# Audience segments (K=12) and three cold-start launches", "",
           "Segments: k-means on 6,593 complete Product Hunt people from their upvotes before Sep 1 (product embedding, product "
           "attributes, topics). Each is described by the attributes and topics it over-upvotes relative to everyone. "
           "Predictions use only Sep 1 - Oct 19 behaviour; the launches are from Oct 20 - Nov 8 and their teams had never "
           "launched before.", "", "| segment | people | over-upvotes (attributes) | over-upvotes (topics) |", "|---|---|---|---|"]
    for s_ in range(K):
        out.append(f"| S{s_} | {desc[s_]['size']} | {', '.join(desc[s_]['top_attrs'])} | {', '.join(desc[s_]['top_topics'])} |")
    for d, L, s, y in pick:
        ix = [si[a] for a in amat.get(L, ()) if a in si]
        pred = lift[:, ix].mean(1)
        rL = y.mean(); n = np.bincount(s, minlength=K); v = np.bincount(s, weights=y, minlength=K)
        real = np.log((v + 2 * rL) / (n * rL + 2 * rL + 1e-9))
        po = np.argsort(-pred); ro = np.argsort(-real)
        it = I.loc[L]
        out += ["", f"## {it['name']} ({d})", f"_{it.tagline}_", "",
                f"Attributes: {', '.join(sorted(a.replace('topic:', '#') for a in amat.get(L, ())))}", "",
                f"Segment voters: {int(y.sum())} votes from {len(y)} people who voted that day.", "",
                "| | predicted | actual (votes / exposed, lift) |", "|---|---|---|"]
        for lab, ps, rs in (("top 1", po[0], ro[0]), ("top 2", po[1], ro[1]), ("bottom", po[-1], ro[-1])):
            out.append(f"| {lab} | {nm(ps)} | {nm(rs)}: {int(v[rs])}/{int(n[rs])}, {real[rs]:+.2f} |")
        rk = {s_: int(np.where(ro == s_)[0][0]) + 1 for s_ in range(K)}
        out.append(f"\nActual rank of the predicted top segment: {rk[po[0]]} of {K}; of the predicted bottom: {rk[po[-1]]} of {K}.")
    open(os.path.join(HERE, "results", f"seg_readable_k{K}.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
