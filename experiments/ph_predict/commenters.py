"""cm_ features: who comments on Product Hunt, and whether the people who engage with a launch's competitors already
engage with its makers. Every feature uses only comments posted before the launch day (Pacific), so none can see
the launch's own result.

  cm_pre_comments / cm_pre_users   comments on this launch's upcoming page before launch day
  cm_maker_comm                    people who commented on the makers'/hunter's earlier launches
  cm_maker_comm_active30           ... of them, active (any comment) in the 30 days before launch
  cm_comp_users                    people who commented on the 10 most similar earlier launches (competitors)
  cm_comp_active30                 ... of them, active in the 30 days before launch
  cm_comp_verified_share           ... share verified
  cm_overlap / cm_overlap_share    competitor commenters who already commented on the makers'/hunter's launches
  cm_comp_heavy                    competitor commenters who comment on many launches (top 10% most active)

Input: data/comments/page*.jsonl.gz (fetched on the VM via vmfetch.py). Output: data/cm_features.json."""
import glob, gzip, json, os
from collections import defaultdict
import numpy as np, pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
import ph_comments as C

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_comments():
    by_slug = {}
    for fn in sorted(glob.glob(f"{D}/comments/page*.jsonl.gz")):
        lines = []
        try:  # a stopped stream leaves a truncated last line / gzip block
            for l in gzip.open(fn, "rt"):
                lines.append(l)
        except (EOFError, OSError):
            pass
        for l in lines:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r["status"] != 200:
                continue
            try:
                info, rows = C.parse(json.loads(r["html"]))
            except Exception:  # noqa: BLE001
                continue
            if info["slug"]:
                by_slug.setdefault(info["slug"], {"info": info, "rows": []})["rows"] += rows
    return by_slug


def build():
    posts = []
    for fn in sorted(glob.glob(f"{D}/days/*.json")):
        day = os.path.basename(fn)[:10]
        for p in json.load(open(fn)):
            posts.append({"id": p["id"], "slug": p["slug"], "day": day,
                          "people": {p["user"].get("id")} | {m["id"] for m in p.get("makers") or []},
                          "text": f"{p['name']}. {p['tagline']}. {p.get('description') or ''} "
                                  + " ".join(e["node"]["name"] for e in p["topics"]["edges"])})
    df = pd.DataFrame(posts).sort_values("day").reset_index(drop=True)
    cm = load_comments()
    # every comment as (user, launch index, date)
    events = []
    for i, r in df.iterrows():
        for c in (cm.get(r.slug) or {}).get("rows", []):
            if c["user_id"] and c["user_id"] != "0" and c["user_id"] not in r.people:
                events.append((c["user_id"], i, (c["created"] or "")[:10], bool(c["verified"])))
    ev = pd.DataFrame(events, columns=["user", "launch", "date", "verified"])
    verified = ev.groupby("user").verified.max().to_dict()
    # neighbours by pitch similarity (earlier launches only are used below)
    X = TfidfVectorizer(min_df=2, max_features=30000, ngram_range=(1, 2), sublinear_tf=True).fit_transform(df.text)
    nn = NearestNeighbors(n_neighbors=40, metric="cosine").fit(X)
    _, idx = nn.kneighbors(X)
    by_launch = {k: g for k, g in ev.groupby("launch")}
    # launches each person is a maker/hunter on, for the "makers' community"
    people_launches = defaultdict(list)
    for i, r in df.iterrows():
        for u in r.people:
            people_launches[u].append(i)
    ev_sorted = ev.sort_values("date")
    out = {}
    for i, r in df.iterrows():
        d = r.day
        d30 = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        before = ev_sorted[ev_sorted.date < d]  # strictly before launch day
        active30 = set(before[before.date >= d30].user)
        heavy_cut = before.groupby("user").size().quantile(0.9) if len(before) else 1
        heavy = set((before.groupby("user").size() > heavy_cut).pipe(lambda s: s[s].index)) if len(before) else set()
        own = by_launch.get(i)
        pre = own[own.date < d] if own is not None else own
        # makers' community: commenters (before d) on earlier launches by any of this launch's people
        mk = {j for u in r.people for j in people_launches.get(u, []) if df.day[j] < d}
        comm = set(before[before.launch.isin(mk)].user)
        comps = [j for j in idx[i] if df.day[j] < d][:10]
        cu = set(before[before.launch.isin(comps)].user)
        ov = comm & cu
        out[r.id] = {
            "cm_pre_comments": 0 if pre is None else len(pre), "cm_pre_users": 0 if pre is None else pre.user.nunique(),
            "cm_maker_comm": len(comm), "cm_maker_comm_active30": len(comm & active30),
            "cm_comp_users": len(cu), "cm_comp_active30": len(cu & active30),
            "cm_comp_verified_share": float(np.mean([verified.get(u, False) for u in cu])) if cu else np.nan,
            "cm_overlap": len(ov), "cm_overlap_share": len(ov) / len(cu) if cu else np.nan,
            "cm_comp_heavy": len(cu & heavy),
        }
    json.dump(out, open(f"{D}/cm_features.json", "w"))
    return out


if __name__ == "__main__":
    o = build()
    v = pd.DataFrame(o.values())
    print(len(o)); print(v.describe().T[["mean", "50%", "max"]].round(2))
