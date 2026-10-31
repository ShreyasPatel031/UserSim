"""Two person inputs from the HN simulation, tested on Product Hunt (plan_presence_experiment.md).
PRESENCE: when a person is usually active, from the timestamps of their own Product Hunt comments (Pacific time; the
  Product Hunt day starts at 00:00 PT). Only comments before the day count. Fewer than 5 timed comments -> unknown (NaN).
    pres_early2  share of their comments posted 00:00-02:00 PT
    pres_early6  share posted 00:00-06:00 PT
    pres_late    share posted 18:00-24:00 PT
    pres_n       log number of timed comments before the day
TWIN: a vector twin = recency-weighted mean (half-life 60 days) of the launch embeddings of the person's past picks
  (upvotes and comments before the day).
    twin_cos     cosine of the twin to the launch
    twin_rank    standing of that cosine within the person's line-up that day (1 = closest)
Both are dated before the day. Used by popscore.py / pick_boost.py with PRESENCE=1 / TWIN=1."""
import glob, gzip, json, os
from collections import defaultdict
import numpy as np, pandas as pd
from . import store

G = {}
HALF_LIFE = 60.0


def _comments():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(store.HERE), "ph_predict"))
    import ph_comments as C
    rows, seen = [], set()
    files = sorted(glob.glob(f"{store.RAW}/comments/page*.jsonl.gz")) + sorted(glob.glob(f"{store.RAW}/comments/daily/*.jsonl.gz"))
    for fn in files:
        try:
            for l in gzip.open(fn, "rt"):
                try:
                    r = json.loads(l)
                    if r.get("status") != 200:
                        continue
                    _, cs = C.parse(json.loads(r["html"]))
                except Exception:  # noqa: BLE001  (truncated line or non-JSON page)
                    continue
                for c in cs:
                    if c["comment_id"] and c["comment_id"] not in seen and c["username"] and c["created"]:
                        seen.add(c["comment_id"]); rows.append((c["username"], c["created"]))
        except (EOFError, OSError):
            pass
    T = pd.DataFrame(rows, columns=["person", "created"])
    t = pd.to_datetime(T.created, utc=True, errors="coerce").dt.tz_convert("America/Los_Angeles")
    T["date"], T["hour"] = t.dt.strftime("%Y-%m-%d"), t.dt.hour
    return T.dropna().sort_values("date")


def presence_table():
    if "pres" not in G:
        T = _comments()
        G["pres"] = {u: (g.date.values, g.hour.values) for u, g in T.groupby("person")}
        G["pres_stats"] = {"comments": len(T), "people": T.person.nunique(),
                           "people_5plus": int((T.person.value_counts() >= 5).sum())}
    return G["pres"]


def add_presence(D):
    P = presence_table(); cache = {}
    cols = {k: [] for k in ("pres_early2", "pres_early6", "pres_late", "pres_n")}
    for u, d in zip(D.person, D.day):
        k = (u, d)
        if k not in cache:
            v = P.get(u)
            if v is None:
                cache[k] = (np.nan, np.nan, np.nan, 0.0)
            else:
                n = int(np.searchsorted(v[0], d))   # comments on dates before d
                h = v[1][:n]
                cache[k] = (np.nan, np.nan, np.nan, np.log1p(n)) if n < 5 else \
                    (float((h < 2).mean()), float((h < 6).mean()), float((h >= 18).mean()), float(np.log1p(n)))
        for c, x in zip(cols, cache[k]):
            cols[c].append(x)
    for c, x in cols.items():
        D[c] = x
    return D


def twin_table():
    if "twin" not in G:
        _, I, E = store.load()
        Z = np.load(f"{store.RAW}/emb.npz"); li = {str(x): k for k, x in enumerate(Z["launch_ids"])}
        V = Z["launch"] / np.linalg.norm(Z["launch"], axis=1, keepdims=True)
        E = E.assign(item=E.item.astype(str)); E = E[E.item.isin(li)]
        E = E.groupby(["person", "item"]).date.min().reset_index().sort_values("date")
        E["od"] = pd.to_datetime(E.date).map(pd.Timestamp.toordinal)
        G["twin"] = ({u: (g.date.values, g.od.values, np.array([li[i] for i in g.item])) for u, g in E.groupby("person")}, V, li)
    return G["twin"]


def add_twin(D):
    H, V, li = twin_table(); cache = {}
    cos = np.full(len(D), np.nan)
    for r, (u, d, x) in enumerate(zip(D.person, D.day, D.id.astype(str))):
        k = (u, d)
        if k not in cache:
            h = H.get(u); vec = None
            if h is not None:
                n = int(np.searchsorted(h[0], d))
                if n:
                    w = 0.5 ** ((pd.Timestamp(d).toordinal() - h[1][:n]) / HALF_LIFE)
                    vec = (w[:, None] * V[h[2][:n]]).sum(0); vec /= np.linalg.norm(vec) + 1e-9
            cache[k] = vec
        if cache[k] is not None and x in li:
            cos[r] = float(V[li[x]] @ cache[k])
    D["twin_cos"] = cos
    D["twin_rank"] = D.groupby(["person", "day"]).twin_cos.rank(ascending=False, method="average")
    return D


if __name__ == "__main__":
    presence_table(); print(G["pres_stats"])
