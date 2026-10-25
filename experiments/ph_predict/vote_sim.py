"""Simulate who upvotes: a per-person upvote model on a sample of real voters, summed per launch.

Sample: people whose Product Hunt profile lists their recent upvotes (ph_profiles2.jsonl.gz, more as profiles land).
Each profile shows only the latest ~20 upvotes, so each person's upvotes are complete only from the launch date of the
oldest listed one onward ("coverage"); person-days outside coverage are not used.

For person u and launch L on day D (only information dated before D):
  ups        u's upvotes on earlier launches (within coverage), log
  cms        u's comments before D, log
  hunter     earlier upvotes/comments by u on launches posted by L's poster
  team       earlier upvotes/comments by u on launches by L's makers
  topic      overlap of L's topics with topics u upvoted/commented on
  text       similarity of L's pitch to launches u upvoted/commented on
  prior      the current launch model's score for L (from results/predictions.csv; leak-free rolling folds)
Train on TRAIN days, test on TEST days. Per launch: sim_votes = sum of probabilities over the sample.
Scored like the main backtest: within-day top-k recall vs PH's dailyRank, for prior alone, sim alone, and both."""
import glob, gzip, json, os, sys
from collections import Counter, defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
import commenters as K

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
TRAIN = ("2026-10-01", "2026-10-14")
TEST = ("2026-10-15", "2026-10-24")
FEATS = ["ups", "cms", "hunter", "team", "topic", "text", "prior"]


def load():
    L = []
    for f in sorted(glob.glob(f"{D}/days/2026-*.json")):
        day = os.path.basename(f)[:10]
        for p in json.load(open(f)):
            L.append({"id": p["id"], "slug": p["slug"], "day": day, "rank": p["dailyRank"],
                      "hunter": (p.get("user") or {}).get("username"),
                      "makers": {m["username"] for m in p.get("makers") or []},
                      "topics": [e["node"]["name"] for e in p["topics"]["edges"]],
                      "text": f"{p['name']}. {p['tagline']}. {p.get('description') or ''}"})
    L = pd.DataFrame(L).sort_values("day").reset_index(drop=True)
    pred = pd.read_csv(f"{R}/predictions.csv", usecols=["id", "pred"]); pred["id"] = pred.id.astype(str)
    L = L.merge(pred, on="id", how="left")
    L["prior"] = L.groupby("day").pred.rank(pct=True)  # within-day percentile of the current model's score
    return L


def main(files):
    L = load(); id2i = {pid: i for i, pid in enumerate(L.id)}; slug2i = {s: i for i, s in enumerate(L.slug)}
    emb = TruncatedSVD(64, random_state=0).fit_transform(
        TfidfVectorizer(min_df=2, max_features=40000, ngram_range=(1, 2), sublinear_tf=True).fit_transform(L.text))
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    topics = sorted({t for ts in L.topics for t in ts}); tix = {t: k for k, t in enumerate(topics)}
    Ltop = np.zeros((len(L), len(topics)), np.float32)
    for i, ts in enumerate(L.topics):
        for t in ts:
            Ltop[i, tix[t]] = 1
    ups, cover = {}, {}
    for fn in files:
        for l in gzip.open(fn, "rt"):
            p = json.loads(l)
            idx = [id2i[x] for x in p.get("voted_recent") or [] if x in id2i]
            if idx:
                ups[p["username"]] = idx
                cover[p["username"]] = min(L.day[i] for i in idx)
    cm = K.load_comments()
    cms = defaultdict(list)
    for s, v in cm.items():
        if s in slug2i:
            for c in v["rows"]:
                if c["username"] in ups:
                    cms[c["username"]].append(((c["created"] or "")[:10], slug2i[s]))
    people = sorted(ups); print("sample people with upvotes:", len(people), flush=True)
    days = sorted(L.day[(L.day >= TRAIN[0]) & (L.day <= TEST[1])].unique())
    rows = []  # (day, launch, person, features..., label)
    for d in days:
        idx = np.where(L.day.values == d)[0]
        for u in people:
            if cover[u] > d:  # person's listed upvotes don't reach back to this day: labels unknown
                continue
            hist = [i for i in ups[u] if L.day[i] < d] + [i for dt, i in cms[u] if dt < d and L.day[i] < d]
            label = set(i for i in ups[u] if L.day[i] == d)
            hun = Counter(L.hunter[i] for i in hist); mk = Counter(m for i in hist for m in L.makers[i])
            tv = Ltop[hist].sum(0) if hist else np.zeros(len(topics)); tv = tv / (np.linalg.norm(tv) + 1e-9)
            xv = emb[hist].mean(0) if hist else np.zeros(64); xv = xv / (np.linalg.norm(xv) + 1e-9)
            n_up = np.log1p(sum(1 for i in ups[u] if L.day[i] < d)); n_cm = np.log1p(sum(1 for dt, _ in cms[u] if dt < d))
            for i in idx:
                rows.append((d, i, u, n_up, n_cm, np.log1p(hun[L.hunter[i]]), np.log1p(sum(mk[m] for m in L.makers[i])),
                             float(Ltop[i] @ tv / (np.linalg.norm(Ltop[i]) + 1e-9)), float(emb[i] @ xv),
                             L.prior[i] if pd.notna(L.prior[i]) else 0.5, int(i in label)))
    P = pd.DataFrame(rows, columns=["day", "launch", "person"] + FEATS + ["y"])
    tr, te = P[P.day <= TRAIN[1]], P[P.day >= TEST[0]].copy()
    print("pairs train/test:", len(tr), len(te), "| positives", tr.y.sum(), te.y.sum(), flush=True)
    out = {}
    for name, cols in (("person model, no launch prior", FEATS[:-1]), ("person model + launch prior", FEATS)):
        m = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced").fit(tr[cols], tr.y)
        te["p"] = m.predict_proba(te[cols])[:, 1]
        # person-level: of each person's real upvotes that day, how many were in their top-3 predicted launches
        hits = [len(set(g.nlargest(3, "p").launch) & set(g[g.y == 1].launch)) / g.y.sum()
                for _, g in te.groupby(["person", "day"]) if g.y.sum()]
        agg = te.groupby("launch").p.sum()
        L[f"sim|{name}"] = L.index.map(agg)
        out[name] = {"person_recall_top3": round(float(np.mean(hits)), 3), "coef": dict(zip(cols, np.round(m.coef_[0], 2).tolist()))}
    T = L[(L.day >= TEST[0]) & (L.day <= TEST[1])].copy()
    T["sample_real"] = T.id.map(Counter(L.id[i] for u in people for i in ups[u]))  # after-the-fact ceiling
    res = []
    for name, col in [("current model (prior)", "pred"), *[(f"simulated votes: {k}", f"sim|{k}") for k in out],
                      ("after the fact: sample's real upvotes (ceiling)", "sample_real")]:
        r = {"score": name}
        for k in (3, 5, 10):
            r[f"day@{k}"] = round(100 * np.mean([len(set(g.nsmallest(k, "rank").id) & set(g.nlargest(k, col).id)) / k
                                                 for _, g in T.groupby("day") if len(g) >= k]))
        r["rho"] = round(float(np.nanmean([spearmanr(g[col], -g["rank"])[0] for _, g in T.groupby("day")])), 3)
        res.append(r)
    res = pd.DataFrame(res)
    print(json.dumps(out, indent=1)); print(res.to_string(index=False))
    res.to_csv(f"{R}/vote_sim.csv", index=False)


if __name__ == "__main__":
    main(sys.argv[1:] or [f"{D}/ph_profiles2.jsonl.gz"])
