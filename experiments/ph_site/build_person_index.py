"""Build the REDACTED person index used by the public "try a product URL" page (/try).

Input (GCS, read only): raw/population/store_v3/{persons,events}.parquet (salted person ids, no usernames) and
raw/simlab_data_v2/items.parquet (launch id/slug -> topics, final votes, daily rank).

Output: site/person_index_v1.npz + site/person_index_v1.json under gs://usersim-bakeoff-347838016394/usersim_sim/.
The artifact carries NO identifier of any kind: no username, no salted person id, no launch id per person. Rows are
shuffled so row order carries nothing. Each row is one complete person with >= MIN_EVENTS joinable events:
  X        float16 [N, T]  share of the person's joinable activity per topic (sums to 1)
  act      int8    [N]     activity band (0 light / 1 regular / 2 heavy / 3 very heavy) from all PH events
  cmt      int8    [N]     comment band (0 never / 1 sometimes / 2 often)
  maker    bool    [N]     has launched or hunted a product
  seg      int16   [N]     segment id (k-means on X)
The JSON holds the topic vocabulary, segment names/top topics/sizes, and the typical-day vote curve
(median and quartiles of final votes per daily rank, Jan-Oct 2026).

usage: python build_person_index.py <local_dir_with_parquets> [--upload]
"""
import json
import os
import sys

import numpy as np
import pandas as pd

MIN_EVENTS = 3
N_TOPICS = 60
K_SEG = 12
# Event-like tags are not interests.
SKIP_TOPICS = {"Vercel Day", "OpenAI Day", "YC Application", "Pitch NYC", "Pitch Berlin", "Pitch Tel Aviv",
               "Pitch Singapore", "Alpha", "Tech", "GitHub"}


def band(x, cuts):
    return np.digitize(x, cuts).astype(np.int8)


def main(d, upload=False):
    it = pd.read_parquet(f"{d}/items.parquet")
    it["tl"] = it.topics.map(lambda s: [t for t in json.loads(s or "[]") if t not in SKIP_TOPICS])
    from collections import Counter
    cnt = Counter(t for tl in it.tl for t in tl)
    vocab = [t for t, _ in cnt.most_common(N_TOPICS)]
    vi = {t: i for i, t in enumerate(vocab)}
    by_id = dict(zip(it.id.astype(str), it.tl))
    by_slug = dict(zip(it.slug, it.tl))

    p = pd.read_parquet(f"{d}/persons.parquet")
    comp = set(p[p.complete].person_id)
    e = pd.read_parquet(f"{d}/events.parquet", columns=["person_id", "kind", "target_id", "platform"])
    e = e[e.person_id.isin(comp) & (e.platform == "producthunt")]
    allc = e.groupby(["person_id", "kind"]).size().unstack(fill_value=0)

    t = e.target_id.fillna("")
    tl = t.map(by_id)
    miss = tl.isna()
    tl[miss] = t[miss].str.replace("launch:", "", regex=False).map(by_slug)
    j = e.assign(tl=tl).dropna(subset=["tl"])
    j = j[j.kind.isin(["upvote", "comment", "launched", "hunted", "review"])]
    nj = j.groupby("person_id").size()
    keep = nj[nj >= MIN_EVENTS].index
    j = j[j.person_id.isin(keep)]
    w = j.kind.map({"upvote": 1.0, "comment": 2.0, "review": 2.0, "launched": 3.0, "hunted": 1.0})
    rows = []
    for (pid, tl_, ww) in zip(j.person_id, j.tl, w):
        for tp in tl_:
            if tp in vi:
                rows.append((pid, vi[tp], ww / max(len(tl_), 1)))
    R = pd.DataFrame(rows, columns=["pid", "ti", "w"]).groupby(["pid", "ti"]).w.sum().reset_index()
    pids = sorted(R.pid.unique())
    pi = {x: i for i, x in enumerate(pids)}
    X = np.zeros((len(pids), len(vocab)), np.float32)
    X[R.pid.map(pi).values, R.ti.values] = R.w.values
    X /= X.sum(1, keepdims=True) + 1e-9

    a = allc.reindex(pids).fillna(0)
    col = lambda k: a[k].values if k in a else np.zeros(len(pids))
    total = a.drop(columns=[c for c in ("follows",) if c in a]).sum(1).values
    act = band(total, [20, 100, 400])
    cmt = band(col("comment") + col("reply") + col("review"), [1, 10])
    maker = (col("launched") + col("hunted")) > 0

    from sklearn.cluster import KMeans
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    km = KMeans(n_clusters=K_SEG, n_init=10, random_state=0).fit(Xn)
    seg = km.labels_.astype(np.int16)
    base = X.mean(0)
    segs = []
    for s in range(K_SEG):
        m = seg == s
        mu = X[m].mean(0)
        lift = mu / (base + 1e-9)
        top = [vocab[i] for i in np.argsort(-mu)[:4]]
        dist = [vocab[i] for i in np.argsort(-(lift * (mu > 0.02)))[:3]]
        segs.append({"id": s, "size": int(m.sum()), "share": round(float(m.mean()), 4), "top_topics": top,
                     "distinctive": dist, "maker_share": round(float(maker[m].mean()), 3),
                     "commenter_share": round(float((cmt[m] > 0).mean()), 3),
                     "heavy_share": round(float((act[m] >= 2).mean()), 3),
                     "name": " / ".join(dict.fromkeys(dist[:2] + top[:1]))})

    rng = np.random.default_rng(0)
    order = rng.permutation(len(pids))  # row order carries nothing
    out = {"X": X[order].astype(np.float16), "act": act[order], "cmt": cmt[order], "maker": maker[order],
           "seg": seg[order]}
    pr = it.dropna(subset=["out_dailyRank"])
    curve = pr[pr.out_dailyRank <= 30].groupby("out_dailyRank").out_votes.quantile([0.25, 0.5, 0.75]).unstack()
    meta = {"version": "person_index_v1", "built_from": "store_v3 complete persons (salted ids dropped), items v2 topics",
            "n_persons": int(len(pids)), "min_joinable_events": MIN_EVENTS, "vocab": vocab, "segments": segs,
            "act_bands": ["light (<20 actions)", "regular (20-99)", "heavy (100-399)", "very heavy (400+)"],
            "cmt_bands": ["rarely comments", "comments sometimes", "comments often"],
            "lineup_size": {"median": float(pr.groupby("day").size().median()),
                            "p25": float(pr.groupby("day").size().quantile(.25)),
                            "p75": float(pr.groupby("day").size().quantile(.75))},
            "vote_curve": {str(int(r)): {"p25": float(v[0.25]), "p50": float(v[0.5]), "p75": float(v[0.75])}
                           for r, v in curve.iterrows()},
            "days": int(pr.day.nunique()), "day_range": [pr.day.min(), pr.day.max()]}
    # Topic base rates for the rank band: where launches with each topic finished, as a share of the line-up.
    pr = pr.assign(n=pr.groupby("day").id.transform("size"))
    pr = pr.assign(pct=(pr.out_dailyRank - 0.5) / pr.n)
    recent = pr[pr.day >= sorted(pr.day.unique())[-60]]
    meta["lineup_recent60"] = {"median": float(recent.groupby("day").size().median()),
                               "p25": float(recent.groupby("day").size().quantile(.25)),
                               "p75": float(recent.groupby("day").size().quantile(.75))}
    qs = [0.1, 0.25, 0.5, 0.75, 0.9]
    def stats(df):
        return {"n": int(len(df)), "pct": [round(float(df.pct.quantile(q)), 4) for q in qs],
                "votes": [float(df.out_votes.quantile(q)) for q in qs]}
    meta["topic_rank"] = {"_all": stats(pr)}
    ex = pr.assign(tl=pr.topics.map(lambda s: json.loads(s or "[]"))).explode("tl")
    for tp in vocab:
        g = ex[ex.tl == tp]
        if len(g) >= 30:
            meta["topic_rank"][tp] = stats(g)
    os.makedirs(f"{d}/out", exist_ok=True)
    np.savez_compressed(f"{d}/out/person_index_v1.npz", **out)
    json.dump(meta, open(f"{d}/out/person_index_v1.json", "w"), indent=1)
    print(json.dumps({k: meta[k] for k in ("n_persons", "days", "lineup_size")}),
          os.path.getsize(f"{d}/out/person_index_v1.npz"))
    for s in segs:
        print(s["id"], s["size"], s["name"], s["top_topics"])
    if upload:
        from google.cloud import storage
        bk = storage.Client(project="project-amer-scs-sandbox").bucket("usersim-bakeoff-347838016394")
        for n in ("person_index_v1.npz", "person_index_v1.json"):
            bk.blob(f"usersim_sim/site/{n}").upload_from_filename(f"{d}/out/{n}")
        print("uploaded")


if __name__ == "__main__":
    main(sys.argv[1], "--upload" in sys.argv)
