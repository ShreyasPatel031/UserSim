"""Predicted audience per launch, step 2: step 1 + what each person likes (from their profile snapshot).

Extra person x launch features, each built only from items dated before the launch day:
  up_sim     similarity of the launch to launches the person upvoted (recent upvotes on their profile)
  taste_sim  similarity of the launch to the products they use (stacks, by date added) and reviewed (by review date)
  n_reviews  reviews they had written before
  has_snap   whether we have a snapshot for them
Only the 4,143 Sep–Oct commenters have snapshots so far; everyone else gets zeros + has_snap = 0.

(Step 1 description follows.)
Predicted audience per launch from individual people's history (step 1).

For each launch L on day D, every person active in the 60 days before D gets a probability of commenting on L,
from features built only from comments dated before D:
  recent   comments in the last 30 days          total   all earlier comments
  team     earlier comments on launches by L's makers/hunter
  topic    overlap between L's topics and the topics they comment on
  text     similarity between L's pitch and the launches they comment on (TF-IDF -> 64-d)
The person model (logistic regression on person x launch pairs) is retrained each month on earlier months only.
Per launch: aud_exp (sum of probabilities), aud_top50 (sum of the 50 highest), aud_likely (people with p > 0.2),
aud_team_exp (expected from people who backed this team before), aud_max.
Comments by the launch's own team are never counted (they are not audience).
Output: data/aud_features.json, results/audience_person_eval.json (how well it ranks who actually comes)."""
import glob, json, os
from collections import Counter, defaultdict, deque
import numpy as np, pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
import commenters as K

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
FEATS = ["recent", "total", "team", "topic", "text", "up_sim", "taste_sim", "n_reviews"]  # no "has snapshot": it leaks future activity


def load():
    rows = []
    for fn in sorted(glob.glob(f"{D}/days/*.json")):
        day = os.path.basename(fn)[:10]
        for p in json.load(open(fn)):
            team = {m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")}
            rows.append({"id": p["id"], "slug": p["slug"], "day": day, "team": team - {None},
                         "topics": [e["node"]["name"] for e in p["topics"]["edges"]],
                         "text": f"{p['name']}. {p['tagline']}. {p.get('description') or ''}"})
    L = pd.DataFrame(rows).sort_values("day").reset_index(drop=True)
    cm = K.load_comments()
    ev = []
    for i, r in L.iterrows():
        for c in (cm.get(r.slug) or {}).get("rows", []):
            u = c["username"]
            if u and u != "[REDACTED]" and u not in r.team:
                ev.append((u, i, (c["created"] or "")[:10]))
    E = pd.DataFrame(ev, columns=["user", "launch", "date"]).drop_duplicates(["user", "launch", "date"])
    return L, E


def snapshots(L, vec_svd):
    """Per person: dated items -> (date, 64-d vector). Upvotes map to our launches; stack/review items embed the
    product name (+ tagline when present) with the launch text model."""
    import gzip
    id2i = {pid: i for i, pid in enumerate(L.id)}
    up, taste, revs, snap = defaultdict(list), defaultdict(list), defaultdict(list), set()
    for l in gzip.open(f"{D}/ph_profiles2.jsonl.gz", "rt"):
        p = json.loads(l); snap.add(p["username"])
        for pid in p.get("voted_recent") or []:
            if pid in id2i:
                up[p["username"]].append((L.day[id2i[pid]], id2i[pid]))
    items = []
    for l in gzip.open(f"{D}/profile_tabs.jsonl.gz", "rt"):
        t = json.loads(l); u = t["username"]
        for s_ in t.get("stacks") or []:
            if s_.get("added") and s_.get("name"):
                items.append((u, s_["added"][:10], s_["name"]))
        for r in t.get("reviews") or []:
            if r.get("created") and r.get("product_name"):
                items.append((u, r["created"][:10], r["product_name"] + " " + " ".join(r.get("pros") or []) + " " + " ".join(r.get("cons") or [])))
                revs[u].append(r["created"][:10])
    if items:
        V = vec_svd([x[2] for x in items])
        for (u, d, _), v in zip(items, V):
            taste[u].append((d, v))
    return up, taste, revs, snap


def run(sample_neg=0.03, seed=0):
    rng = np.random.default_rng(seed)
    L, E = load()
    users = sorted(E.user.unique()); uix = {u: k for k, u in enumerate(users)}; nU = len(users)
    topics = sorted({t for ts in L.topics for t in ts}); tix = {t: k for k, t in enumerate(topics)}
    vec = TfidfVectorizer(min_df=2, max_features=40000, ngram_range=(1, 2), sublinear_tf=True)
    svd = TruncatedSVD(64, random_state=0)
    emb = svd.fit_transform(vec.fit_transform(L.text))
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9

    def vec_svd(texts):
        v = svd.transform(vec.transform(texts))
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    UP, TASTE, REVS, SNAP = snapshots(L, vec_svd)
    Ltop = np.zeros((len(L), len(topics)), dtype=np.float32)
    for i, ts in enumerate(L.topics):
        for t in ts:
            Ltop[i, tix[t]] = 1
    E = E.sort_values("date").reset_index(drop=True)
    days = sorted(L.day.unique())
    by_day_launch = L.groupby("day").indices
    ev_by_date = E.groupby("date").indices
    labels = defaultdict(set)  # launch -> users who commented (any time)
    for u, i in zip(E.user, E.launch):
        labels[i].add(u)

    def passes(model_for_month):
        """Walk days in order; yields (day, launch indices, active user indices, feature tensor)."""
        total = np.zeros(nU, np.float32); topic = np.zeros((nU, len(topics)), np.float32)
        textsum = np.zeros((nU, 64), np.float32); last = np.full(nU, -10**6)
        recent_q = deque(); recent = np.zeros(nU, np.float32)
        team_cnt = defaultdict(Counter)  # team member -> Counter(user index -> earlier comments on their launches)
        dates_sorted = sorted(ev_by_date)
        p = 0
        for di, d in enumerate(days):
            while p < len(dates_sorted) and dates_sorted[p] < d:  # add every comment dated before d
                dd = dates_sorted[p]
                for k in ev_by_date[dd]:
                    u, i = uix[E.user[k]], E.launch[k]
                    total[u] += 1; topic[u] += Ltop[i]; textsum[u] += emb[i]; last[u] = di
                    recent[u] += 1; recent_q.append((dd, u))
                    for m in L.team[i]:
                        team_cnt[m][u] += 1
                p += 1
            cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            while recent_q and recent_q[0][0] < cut:
                _, u = recent_q.popleft(); recent[u] -= 1
            active = np.where(last >= di - 60)[0] if di else np.array([], int)
            if not len(active) or d not in by_day_launch:
                continue
            idx = by_day_launch[d]
            tn = topic[active] / (np.linalg.norm(topic[active], axis=1, keepdims=True) + 1e-9)
            xn = textsum[active] / (np.linalg.norm(textsum[active], axis=1, keepdims=True) + 1e-9)
            pos = {u: k for k, u in enumerate(active)}
            F = np.zeros((len(active), len(idx), len(FEATS)), np.float32)
            F[:, :, 0] = np.log1p(recent[active])[:, None]
            F[:, :, 1] = np.log1p(total[active])[:, None]
            for j, i in enumerate(idx):
                for m in L.team[i]:
                    for u, c in team_cnt.get(m, {}).items():
                        if u in pos:
                            F[pos[u], j, 2] += c
            F[:, :, 2] = np.log1p(F[:, :, 2])
            F[:, :, 3] = tn @ (Ltop[idx] / (np.linalg.norm(Ltop[idx], axis=1, keepdims=True) + 1e-9)).T
            F[:, :, 4] = xn @ emb[idx].T
            for a, u in enumerate(active):  # snapshot features: items dated strictly before d
                name = users[u]
                if name not in SNAP:
                    continue
                ups = [emb[i] for dd, i in UP.get(name, []) if dd < d]
                if ups:
                    c = np.mean(ups, 0); F[a, :, 5] = emb[idx] @ (c / (np.linalg.norm(c) + 1e-9))
                tv = [v for dd, v in TASTE.get(name, []) if dd < d]
                if tv:
                    c = np.mean(tv, 0); F[a, :, 6] = emb[idx] @ (c / (np.linalg.norm(c) + 1e-9))
                F[a, :, 7] = np.log1p(sum(1 for dd in REVS.get(name, []) if dd < d))
            yield d, idx, active, F

    # pass 1: sampled training pairs per month
    train = defaultdict(list)
    for d, idx, active, F in passes(None):
        y = np.array([[users[u] in labels[i] for i in idx] for u in active], bool)
        keep = y | (rng.random(y.shape) < sample_neg)
        w = np.where(y, 1.0, 1.0 / sample_neg)
        train[d[:7]].append((F[keep], y[keep], w[keep]))
    months = sorted(train)
    models = {}
    for m in months:
        prev = [x for mm in months if mm < m for x in train[mm]]
        if sum(len(a[1]) for a in prev) < 500:
            continue
        X = np.concatenate([a[0] for a in prev]); y = np.concatenate([a[1] for a in prev]); w = np.concatenate([a[2] for a in prev])
        models[m] = LogisticRegression(C=1.0, max_iter=500).fit(X, y, sample_weight=w)
    print("person models for months:", sorted(models), {m: np.round(models[m].coef_[0], 2).tolist() for m in list(models)[-1:]}, flush=True)
    # pass 2: score every active person for every launch, aggregate per launch, and check person-level ranking
    out, person_hits = {}, []
    for d, idx, active, F in passes(models):
        mdl = models.get(d[:7])
        if mdl is None:
            continue
        P = mdl.predict_proba(F.reshape(-1, len(FEATS)))[:, 1].reshape(len(active), len(idx))
        for j, i in enumerate(idx):
            p = P[:, j]
            team_mask = F[:, j, 2] > 0
            out[L.id[i]] = {"aud_exp": float(p.sum()), "aud_top50": float(np.sort(p)[-50:].sum()),
                            "aud_likely": int((p > 0.2).sum()), "aud_team_exp": float(p[team_mask].sum()),
                            "aud_max": float(p.max()), "aud_active_pool": int(len(active))}
            came = {users[u] for u in active} & labels[i]
            if came and d >= "2026-09":  # snapshots exist only for Sep–Oct commenters: score that period  # of the people who actually came, how many were in our top 100 for this launch?
                top = {users[active[k]] for k in np.argsort(-p)[:100]}
                person_hits.append(len(came & top) / len(came))
    json.dump({k: {kk.replace("aud_", "aud2_"): vv for kk, vv in v.items()} for k, v in out.items()}, open(f"{D}/aud2_features.json", "w"))
    ev = {"launches_scored": len(out), "people_recall_at_100": float(np.mean(person_hits)) if person_hits else None,
          "random_recall_at_100": float(np.mean([min(1, 100 / max(v["aud_active_pool"], 1)) for v in out.values()]))}
    json.dump(ev, open(f"{R}/audience2_person_eval.json", "w"), indent=1)
    print(ev)


if __name__ == "__main__":
    run()
