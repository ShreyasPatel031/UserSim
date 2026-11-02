"""E5: a trained person model (two-tower, PyTorch, CPU) against the hand-built LightGBM person model, on the within-person
test of pick_boost (same person, same day, same line-up; train on earlier months, test on the next; May-Oct).
  person tower   the person's dated history before the day, newest 64 events: each past event = the launch's encoding
                 (team ids, topics, meaning embedding, page scores) + kind (upvote/comment) + age bucket; recency-aware
                 attention pooling with a learned query, plus static facts (log history size, no history flag)
  launch tower   team member ids (makers + hunter), topic ids, meaning embedding (emb.npz), page scores (page_taste's
                 z-scored table), day context (weekday, line-up size)
  score          dot(person, launch) / sqrt(d) + bias MLP over the hand tie-strength inputs (popscore.tie_features, with
                 the TIE2 extensions when on); WIDE=1 feeds every hand feature of the baseline to the bias MLP instead
  loss           per person-day: listwise softmax over the real line-up (each pick against the launches skipped) + BCE,
                 so the whole line-up is the negative set (no sampling needed: ~30 launches a day)
Training months: all months before the test month (TRAIN=all, default) or only the previous month (TRAIN=prev, the
baseline's protocol). The baseline is trained both ways too, on the same rows. Everything is dated before the day.
Scores, paired on the same test rows (200 people a day, pick_boost's sample): person-level top-3 hit, mean within-
person-day AUC, and the pool-vote Spearman within day (expected picks summed over the day's active people vs the real
number of pool people who picked each launch), with bootstrap intervals over person-days / days and per-month wins.
usage (VM, from ~/w/experiments):
  SIMLAB_DATA=data_v2 TASTE=1 TIE2=1 python -m simlab.two_tower build [workers]   -> cache/tt/rows_<month>_<train|test>.parquet
  SIMLAB_DATA=data_v2 TASTE=1 TIE2=1 python -m simlab.two_tower run [workers]     -> reports/two_tower[_<tag>].json
  SIMLAB_DATA=data_v2 TASTE=1 TIE2=1 python -m simlab.two_tower features [workers] -> ph_predict/data/psv_features.json"""
import json, os, sys, time
from collections import defaultdict
import multiprocessing as mp
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TT = os.path.join(HERE, "cache", "tt")
TRAIN_MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
TEST_MONTHS = os.environ.get("MONTHS", "2026-05,2026-06,2026-07,2026-08,2026-09,2026-10").split(",")
TRAIN = os.environ.get("TRAIN", "all")        # all | prev
WIDE = os.environ.get("WIDE") == "1"          # bias MLP sees every hand feature, not only tie strength
TAG = os.environ.get("TAG", "")
EPOCHS = int(os.environ.get("EPOCHS", "8"))
D = int(os.environ.get("DIM", "64"))
HLEN = 64
AGE_EDGES = np.array([1, 2, 4, 8, 15, 30, 60, 120, 240, 480])


# ---------------------------------------------------------------- stage 1: featurized tables (hand features, all active person-days)
def build_month(args):
    """Rows of one month (every active person-day, the full line-up), with the baseline's hand features. 'train' tables
    use collaborative filtering / category priors fitted before that month (as pick_boost does for its training month);
    'test' tables use ones fitted before the previous month (as pick_boost does for its test month)."""
    M, variant = args
    from . import choice, popscore as PS
    path = f"{TT}/rows_{M}_{variant}.parquet"
    if os.path.exists(path):
        return M, variant, -1
    t0 = time.time()
    cut = PS.month_start(M, 0 if variant == "train" else 1)
    R = choice.rows(day_from=M + "-01", day_to=PS.month_end(M))
    R = PS.featurize(R, PS.fit_cf(cut), cut)
    R, pc = PS.page_cols(R)
    keep = ["person", "day", "id", "y", "w"] + PS.FEATS + pc
    R = R[keep].copy(); R["id"] = R.id.astype(str)
    for c in PS.FEATS + pc:
        R[c] = R[c].astype(np.float32)
    R.to_parquet(path)
    return M, variant, len(R), round(time.time() - t0)


def build(workers):
    from . import popscore as PS, harness
    os.makedirs(TT, exist_ok=True)
    PS.load(); harness.baseline()
    from .page_taste import traits
    traits()
    jobs = [(M, "train") for M in TRAIN_MONTHS] + [(M, "test") for M in TEST_MONTHS]
    with mp.get_context("fork").Pool(min(workers, len(jobs))) as pool:
        for r in pool.imap_unordered(build_month, jobs):
            print("built", r, flush=True)
    json.dump({"feats": PS.FEATS, "tie": PS.TIE_COLS}, open(f"{TT}/cols.json", "w"))


# ---------------------------------------------------------------- stage 2: tensors for the towers
class Data:
    """Static launch arrays and per-person event histories, built once per process from the store."""

    def __init__(self):
        from . import popscore as PS, store
        from .page_taste import traits
        g = PS.load(); I, E = g["I"], g["E"]
        Z, _ = traits()
        ids = list(I.id.astype(str)); self.ix = {x: k + 1 for k, x in enumerate(ids)}   # 0 = padding
        n = len(ids) + 1
        members = sorted({m for r in I.itertuples() for m in set(json.loads(r.makers)) | {r.poster} if m})
        self.team_ix = {m: k + 1 for k, m in enumerate(members)}
        topics = sorted({t for ts in I.topics for t in json.loads(ts)}); self.topic_ix = {t: k + 1 for k, t in enumerate(topics)}
        self.team = np.zeros((n, 6), np.int64); self.topic = np.zeros((n, 5), np.int64)
        self.emb = np.zeros((n, 384), np.float32); self.page = np.zeros((n, Z.shape[1]), np.float32)
        self.wday = np.zeros(n, np.int64); self.lsize = np.zeros(n, np.float32)
        Zn = np.load(f"{store.RAW}/emb.npz"); li = {str(x): k for k, x in enumerate(Zn["launch_ids"])}; EM = Zn["launch"]
        EM = EM / (np.linalg.norm(EM, axis=1, keepdims=True) + 1e-9)
        zi = {x: k for k, x in enumerate(Z.index)}; ZV = Z.values
        size = I.groupby("day").id.transform("size"); size = dict(zip(I.id.astype(str), size))
        for r in I.itertuples():
            k = self.ix[str(r.id)]
            t = [self.team_ix[m] for m in ([r.poster] + json.loads(r.makers)) if m in self.team_ix][:6]; self.team[k, :len(t)] = t
            t = [self.topic_ix[x] for x in json.loads(r.topics)][:5]; self.topic[k, :len(t)] = t
            if str(r.id) in li:
                self.emb[k] = EM[li[str(r.id)]]
            if str(r.id) in zi:
                self.page[k] = ZV[zi[str(r.id)]]
            self.wday[k] = pd.Timestamp(r.day).weekday(); self.lsize[k] = np.log1p(size[str(r.id)])
        self.n_team, self.n_topic, self.n_page = len(members) + 1, len(topics) + 1, Z.shape[1]
        Es = E[E.item.astype(str).isin(self.ix)].sort_values("date")
        self.hist = {u: (np.array(list(q.date), dtype="datetime64[D]"), np.array([self.ix[x] for x in q.item.astype(str)]),
                         (q.kind == "comment").to_numpy(dtype=np.int64, na_value=0)) for u, q in Es.groupby("person")}

    def history(self, keys):
        """keys: list of (person, day) -> item idx [n, HLEN], kind [n, HLEN], age bucket [n, HLEN], n_hist [n]; 0-padded."""
        n = len(keys); it = np.zeros((n, HLEN), np.int64); kd = np.zeros((n, HLEN), np.int64); ag = np.zeros((n, HLEN), np.int64)
        nh = np.zeros(n, np.float32)
        for i, (u, d) in enumerate(keys):
            h = self.hist.get(u)
            if h is None:
                continue
            dd = np.datetime64(d); k = int(np.searchsorted(h[0], dd)); nh[i] = k
            if k == 0:
                continue
            lo = max(0, k - HLEN); m = k - lo
            it[i, :m] = h[1][lo:k]; kd[i, :m] = h[2][lo:k]
            ag[i, :m] = np.searchsorted(AGE_EDGES, (dd - h[0][lo:k]).astype(int), side="right") + 1
        return it, kd, ag, nh


def make_net(data, n_bias):
    import torch, torch.nn as nn, torch.nn.functional as F

    class Net(nn.Module):
        def __init__(s):
            super().__init__()
            s.team = nn.Embedding(data.n_team, 32, padding_idx=0); s.topic = nn.Embedding(data.n_topic, 16, padding_idx=0)
            s.emb = nn.Linear(384, 64); s.page = nn.Sequential(nn.Linear(data.n_page, 64), nn.ReLU())
            s.wday = nn.Embedding(7, 8)
            s.launch = nn.Sequential(nn.Linear(32 + 16 + 64 + 64 + 8 + 1, 128), nn.ReLU(), nn.Linear(128, D))
            s.kind = nn.Embedding(2, 8); s.age = nn.Embedding(len(AGE_EDGES) + 2, 16, padding_idx=0)
            s.hproj = nn.Linear(D + 8 + 16, D); s.query = nn.Parameter(torch.randn(D) * 0.1)
            s.person = nn.Sequential(nn.Linear(D + 2, 128), nn.ReLU(), nn.Linear(128, D))
            s.bias = nn.Sequential(nn.Linear(n_bias, 64), nn.ReLU(), nn.Linear(64, 1))
            s.b0 = nn.Parameter(torch.zeros(1))
            s.register_buffer("T_team", torch.from_numpy(data.team)); s.register_buffer("T_topic", torch.from_numpy(data.topic))
            s.register_buffer("T_emb", torch.from_numpy(data.emb)); s.register_buffer("T_page", torch.from_numpy(data.page))
            s.register_buffer("T_wday", torch.from_numpy(data.wday)); s.register_buffer("T_size", torch.from_numpy(data.lsize))

        def enc_launch(s, idx):
            """idx: long tensor of item indices (any shape) -> [..., D]"""
            t = s.T_team[idx]; m = (t > 0).float().unsqueeze(-1); te = (s.team(t) * m).sum(-2) / m.sum(-2).clamp(min=1)
            t = s.T_topic[idx]; m = (t > 0).float().unsqueeze(-1); to = (s.topic(t) * m).sum(-2) / m.sum(-2).clamp(min=1)
            x = torch.cat([te, to, s.emb(s.T_emb[idx]), s.page(s.T_page[idx]), s.wday(s.T_wday[idx]), s.T_size[idx].unsqueeze(-1)], -1)
            return s.launch(x)

        def enc_person(s, it, kd, ag, nh):
            h = torch.cat([s.enc_launch(it), s.kind(kd), s.age(ag)], -1); h = torch.tanh(s.hproj(h))   # [n, HLEN, D]
            valid = it > 0
            a = (h @ s.query).masked_fill(~valid, -1e9); a = torch.softmax(a, -1) * valid.any(-1, keepdim=True).float()
            pooled = (a.unsqueeze(-1) * h).sum(-2)
            x = torch.cat([pooled, torch.log1p(nh).unsqueeze(-1), (nh > 0).float().unsqueeze(-1)], -1)
            return s.person(x)

        def forward(s, pv, lv, bias_x):
            return (pv * lv).sum(-1) / D ** 0.5 + s.bias(bias_x).squeeze(-1) + s.b0
    return Net()


def batches(R, data, bias_cols, order, bs=256):
    """Yield one batch per `bs` person-days: tensors for the rows of those person-days."""
    import torch
    g = R.g.values; gi = R.gi.values; items = R.ii.values; y = R.y.values.astype(np.float32); X = R[bias_cols].values.astype(np.float32)
    starts = R.groupby("gi", sort=True).indices
    K = R.drop_duplicates("gi"); keys = dict(zip(K.gi, zip(K.person, K.day)))
    for b0 in range(0, len(order), bs):
        gs = order[b0:b0 + bs]
        idx = np.concatenate([starts[k] for k in gs])
        it, kd, ag, nh = data.history([keys[k] for k in gs])
        local = {k: j for j, k in enumerate(gs)}; pi = np.array([local[k] for k in gi[idx]])
        yield (torch.from_numpy(it), torch.from_numpy(kd), torch.from_numpy(ag), torch.from_numpy(nh), torch.from_numpy(pi),
               torch.from_numpy(items[idx]), torch.from_numpy(X[idx]), torch.from_numpy(y[idx]), idx)


def group_loss(logits, y, pi, n_groups):
    """BCE over all rows + listwise: each pick against the skipped launches of the same person-day."""
    import torch, torch.nn.functional as F
    bce = F.binary_cross_entropy_with_logits(logits, y)
    neg = logits.masked_fill(y > 0, -1e9)
    lse = torch.full((n_groups,), -1e9, dtype=logits.dtype).scatter_reduce(0, pi, neg, reduce="amax")
    lse = lse + torch.log(torch.zeros(n_groups).scatter_add(0, pi, torch.exp(neg - lse[pi])).clamp(min=1e-9))
    pos = y > 0
    lw = F.softplus(lse[pi][pos] - logits[pos]).mean() if pos.any() else logits.sum() * 0
    return bce + lw


def fit_predict(train, test, data, bias_cols, seed=0, log=print):
    import torch
    torch.manual_seed(seed); np.random.seed(seed)
    net = make_net(data, len(bias_cols)); opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-5)
    rng = np.random.default_rng(seed)
    groups = train.gi.unique(); rng.shuffle(groups); nval = max(200, len(groups) // 10)
    val, trn = groups[:nval], groups[nval:]
    mu, sd = train[bias_cols].mean(), train[bias_cols].std() + 1e-6
    train = train.copy(); test = test.copy()
    for Dx in (train, test):
        Dx[bias_cols] = ((Dx[bias_cols] - mu) / sd).fillna(0.0).clip(-5, 5)

    def run(R, order, train_mode):
        net.train(train_mode); tot, n, out = 0.0, 0, np.zeros(len(R), np.float32)
        with torch.set_grad_enabled(train_mode):
            for it, kd, ag, nh, pi, items, X, y, idx in batches(R, data, bias_cols, order):
                pv = net.enc_person(it, kd, ag, nh); lv = net.enc_launch(items)
                logits = net(pv[pi], lv, X); loss = group_loss(logits, y, pi, len(it))
                if train_mode:
                    opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0); opt.step()
                tot += float(loss.detach()) * len(y); n += len(y); out[idx] = logits.detach().numpy()
        return tot / max(n, 1), out
    best, best_state, bad = 1e9, None, 0
    for ep in range(EPOCHS):
        t0 = time.time(); order = trn.copy(); rng.shuffle(order)
        tl, _ = run(train, order, True); vl, _ = run(train, val, False)
        log(f"  epoch {ep + 1} train {tl:.4f} val {vl:.4f} {time.time() - t0:.0f}s")
        if vl < best - 1e-4:
            best, bad = vl, 0; best_state = {k: v.clone() for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= 2:
                break
    net.load_state_dict(best_state)
    _, s = run(test, np.sort(test.gi.unique()), False)
    return s, {"state": best_state, "mu": mu, "sd": sd, "bias_cols": bias_cols}


def load_net(m, data):
    import torch
    art = torch.load(f"{TT}/net_{m}{TAG}.pt", weights_only=False)
    net = make_net(data, len(art["bias_cols"])); net.load_state_dict(art["state"]); net.eval()
    return net, art


def predict(net, art, R, data):
    """Scores (probabilities) for the rows of R (needs person, day, id and the bias columns)."""
    import torch
    R = R.copy(); R["g"] = R.person + "|" + R.day; R["gi"] = pd.factorize(R.g)[0]; R["ii"] = R.id.astype(str).map(data.ix).fillna(0).astype(np.int64)
    bc = art["bias_cols"]; R[bc] = ((R[bc] - art["mu"]) / art["sd"]).fillna(0.0).clip(-5, 5)
    out = np.zeros(len(R), np.float32)
    with torch.no_grad():
        for it, kd, ag, nh, pi, items, X, y, idx in batches(R, data, bc, np.sort(R.gi.unique())):
            out[idx] = net(net.enc_person(it, kd, ag, nh)[pi], net.enc_launch(items), X).numpy()
    return 1 / (1 + np.exp(-out.astype(np.float64)))


# ---------------------------------------------------------------- stage 3: paired evaluation
def load_rows(M, variant):
    R = pd.read_parquet(f"{TT}/rows_{M}_{variant}.parquet")
    R["g"] = R.person + "|" + R.day
    return R


def sample(R, n, rng):
    """pick_boost's sampler: up to n people per day, in the table's own order."""
    keep = set()
    for d, g in R.groupby("day"):
        keep |= {u + "|" + d for u in rng.permutation(g.person.unique())[:n]}
    return R[R.g.isin(keep)].copy()


def person_scores(R, col):
    """Per person-day with at least one pick and one skip: top-3 hit, AUC."""
    from sklearn.metrics import roc_auc_score
    rows = []
    for gk, g in R.groupby("g", sort=False):
        if g.y.sum() == 0 or g.y.all():
            continue
        rows.append((gk, g.day.iloc[0], float(g.y.values[np.argsort(-g[col].values)[:3]].any()), roc_auc_score(g.y, g[col])))
    return pd.DataFrame(rows, columns=["g", "day", "hit", "auc"])


def pool_scores(R, col):
    """Per day: Spearman between expected picks summed over the day's active people (sigmoid scores) and the real number
    of pool people who picked each launch; and the top-3 hit of that ranking."""
    from scipy.stats import spearmanr
    S = pd.DataFrame({"day": R.day.values, "id": R.id.values, "p": R[col].values, "y": R.y.values}).groupby(["day", "id"], as_index=False).sum()
    rows = []
    for d, g in S.groupby("day"):
        if len(g) < 5 or g.y.sum() == 0:
            continue
        top = set(g.nlargest(3, "y").id)
        rows.append((d, spearmanr(g.p, g.y).correlation, len(set(g.nlargest(3, "p").id) & top) / 3))
    return pd.DataFrame(rows, columns=["day", "spearman", "top3"])


def ci(x, rng, n=4000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 4), round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]


def month(m):
    import lightgbm as lgb, torch
    torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "5")))
    tie = json.load(open(f"{TT}/cols.json"))["tie"]
    data = Data()
    prev = TRAIN_MONTHS[TRAIN_MONTHS.index(m) - 1] if m in TRAIN_MONTHS else "2026-09"
    months = [M for M in TRAIN_MONTHS if M < m] if TRAIN == "all" else [prev]
    rng = np.random.default_rng(0)
    te_full = load_rows(m, "test"); te = sample(te_full, 200, rng)
    trs = {M: load_rows(M, "train") for M in months}
    hand = [c for c in te.columns if c not in ("person", "day", "id", "y", "w", "g")]   # = pick_boost's PS.FEATS + page + taste columns
    log = lambda s: print(f"[{m}] {s}", flush=True)
    log(f"train months {months}: {sum(len(t) for t in trs.values())} rows, {sum(t.g.nunique() for t in trs.values())} person-days; test {te.g.nunique()} person-days ({te_full.g.nunique()} active)")
    out = {"month": m, "train_months": months, "test_person_days": int(te.g.nunique()), "active_person_days": int(te_full.g.nunique())}
    # --- baseline: LightGBM on the hand features, 300 people a day from the previous month (pick_boost base) and from all training months
    kw = dict(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50, colsample_bytree=0.5, verbose=-1, n_jobs=4)
    tr_prev = sample(trs[prev] if prev in trs else load_rows(prev, "train"), 300, rng)
    mdl = lgb.LGBMClassifier(**kw).fit(tr_prev[hand], tr_prev.y)
    te["s_gbm_prev"] = mdl.predict_proba(te[hand])[:, 1]; te_full["s_gbm_prev"] = mdl.predict_proba(te_full[hand])[:, 1]
    if TRAIN == "all":
        tr_all = pd.concat([sample(t, 300, rng) for t in trs.values()])
        mdl = lgb.LGBMClassifier(**kw).fit(tr_all[hand], tr_all.y)
        te["s_gbm_all"] = mdl.predict_proba(te[hand])[:, 1]; te_full["s_gbm_all"] = mdl.predict_proba(te_full[hand])[:, 1]
    # --- two-tower
    tr = pd.concat(trs.values(), ignore_index=True)
    for R in (tr, te, te_full):
        R["gi"] = pd.factorize(R.g)[0]; R["ii"] = R.id.map(data.ix).fillna(0).astype(np.int64)
    bias_cols = hand if WIDE else tie
    t0 = time.time()
    s_tt, art = fit_predict(tr, te_full, data, bias_cols, log=log)
    te_full["s_tt"] = 1 / (1 + np.exp(-s_tt.astype(np.float64)))
    torch.save(art, f"{TT}/net_{m}{TAG}.pt")
    te = te.drop(columns=["gi", "ii"]).merge(te_full[["g", "id", "s_tt"]], on=["g", "id"], how="left")
    out["tt_train_seconds"] = round(time.time() - t0)
    # --- scores
    models = [c for c in te.columns if c.startswith("s_")]
    P = {c: person_scores(te, c).set_index("g") for c in models}
    Q = {c: pool_scores(te_full, c).set_index("day") for c in models}
    rb = np.random.default_rng(1)
    for c in models:
        out[c] = {"top3_hit": round(100 * float(P[c].hit.mean()), 1), "auc": round(float(P[c].auc.mean()), 3), "n": len(P[c]),
                  "pool_spearman": round(float(Q[c].spearman.mean()), 3), "pool_top3": round(100 * float(Q[c].top3.mean()), 1), "days": len(Q[c])}
        if c != "s_tt":
            d = P["s_tt"].join(P[c], rsuffix="_b"); q = Q["s_tt"].join(Q[c], rsuffix="_b")
            out[c]["tt_minus"] = {"top3_hit": [round(100 * v, 1) for v in ci(d.hit - d.hit_b, rb)], "auc": ci(d.auc - d.auc_b, rb),
                                  "pool_spearman": ci(q.spearman - q.spearman_b, rb), "pool_top3": [round(100 * v, 1) for v in ci(q.top3 - q.top3_b, rb)]}
    os.makedirs(f"{TT}/scores", exist_ok=True)
    te[["person", "day", "id", "y"] + models].to_parquet(f"{TT}/scores/{m}{TAG}.parquet")
    te_full[["person", "day", "id", "y"] + models].to_parquet(f"{TT}/scores/{m}{TAG}_full.parquet")
    log(json.dumps(out))
    return out


def run(workers):
    with mp.get_context("fork").Pool(min(workers, len(TEST_MONTHS))) as pool:
        res = pool.map(month, TEST_MONTHS)
    models = [k for k in res[0] if k.startswith("s_")]
    summ = {}
    for c in models:
        summ[c] = {k: round(float(np.mean([r[c][k] for r in res])), 3 if k in ("auc", "pool_spearman") else 1) for k in ("top3_hit", "auc", "pool_spearman", "pool_top3")}
        if c != "s_tt":
            summ[c]["months_tt_better"] = {k: sum(r["s_tt"][k] > r[c][k] for r in res) for k in ("top3_hit", "auc", "pool_spearman")}
    # pooled paired intervals over all test person-days / days (from the saved scores)
    S = pd.concat([pd.read_parquet(f"{TT}/scores/{m}{TAG}.parquet") for m in TEST_MONTHS]); S["g"] = S.person + "|" + S.day
    F = pd.concat([pd.read_parquet(f"{TT}/scores/{m}{TAG}_full.parquet") for m in TEST_MONTHS])
    rb = np.random.default_rng(2)
    P = {c: person_scores(S, c).set_index("g") for c in models}; Q = {c: pool_scores(F, c).set_index("day") for c in models}
    for c in models:
        if c == "s_tt":
            continue
        d = P["s_tt"].join(P[c], rsuffix="_b"); q = Q["s_tt"].join(Q[c], rsuffix="_b")
        summ[c]["tt_minus_pooled"] = {"top3_hit": [round(100 * v, 1) for v in ci(d.hit - d.hit_b, rb)], "auc": ci(d.auc - d.auc_b, rb),
                                      "pool_spearman": ci(q.spearman - q.spearman_b, rb), "pool_top3": [round(100 * v, 1) for v in ci(q.top3 - q.top3_b, rb)]}
    res_out = {"config": {"train": TRAIN, "wide": WIDE, "epochs": EPOCHS, "dim": D, "hlen": HLEN}, "summary": summ, "months": res}
    json.dump(res_out, open(f"{HERE}/reports/two_tower{TAG}.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


# ---------------------------------------------------------------- stage 4: launch-level features from the whole population (as popscore phase B)
POP = os.path.join(TT, "pop" + TAG)


def score_day(d):
    """Everyone active in the 30 days before d (weight = share of those days active), scored on every launch of d with
    the month's net (trained on months before d's month), summed per launch exactly as popscore.score_day."""
    import torch
    from . import choice, popscore as PS
    path = f"{POP}/day_{d}.parquet"
    if os.path.exists(path):
        return d, -1
    torch.set_num_threads(2)
    data = G.setdefault("data", Data())
    net, art = load_net(d[:7], data)
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    if not len(D):
        return d, 0
    D = PS.tie_features(D); D["id"] = D.id.astype(str)
    D["p"] = predict(net, art, D, data); D["wp"] = D.w * D.p
    by = D.groupby("person").p
    D["ws"] = D.w * D.p / by.transform("sum") * by.transform("sum").clip(upper=3)
    rk = by.rank(ascending=False, method="first")
    D["w1"] = D.w * (rk == 1); D["w3"] = D.w * (rk <= 3)
    out = []
    for x, g in D.groupby("id"):
        out.append({"id": x, "day": d, "psn_ev": g.wp.sum(), "psn_fans": np.sort(g.wp.values)[-100:].sum(),
                    "psn_ev_ties": g.wp[g.backed > 0].sum(), "psn_reach": g.w.sum(), "psn_pmax": g.p.max(),
                    "psn_share": g.ws.sum(), "psn_top1": g.w1.sum(), "psn_top3": g.w3.sum()})
    pd.DataFrame(out).to_parquet(path)
    return d, len(D)


G = {}


def features(workers):
    """psv_features.json: the two-tower's launch-level features in the psr_features.json format, for every day whose
    month has a trained net (run first). Day files land in cache/tt/pop/day_<d>.parquet (pool_check.py can read them)."""
    from . import popscore as PS, store, harness
    assert not WIDE, "features: the population pass computes tie features only (WIDE=0 nets)"
    os.makedirs(POP, exist_ok=True); PS.load(); harness.baseline()
    from .page_taste import traits
    traits(); G["data"] = Data()
    nets = {f[4:11] for f in os.listdir(TT) if f.startswith("net_") and f.endswith(TAG + ".pt")}
    days = sorted(d for d in PS.G["lineup"] if d[:7] in nets and d <= "2026-10-24")
    with mp.get_context("fork").Pool(workers) as pool:
        for k, r in enumerate(pool.imap_unordered(score_day, days)):
            if k % 20 == 0:
                print("scored", k, "of", len(days), r, flush=True)
    S = pd.concat([pd.read_parquet(f"{POP}/day_{d}.parquet") for d in days if os.path.exists(f"{POP}/day_{d}.parquet")])
    S = S.rename(columns={c: "psv_" + c[4:] for c in S.columns if c.startswith("psn_")})
    cols = [c for c in S.columns if c.startswith("psv_")]
    json.dump({str(r["id"]): {c: float(r[c]) for c in cols} for r in S.to_dict("records")}, open(os.path.join(store.RAW, "psv_features.json"), "w"))
    print("saved", len(S), "launches", "months", sorted(nets))


if __name__ == "__main__":
    cmd = sys.argv[1]; w = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    {"build": build, "run": run, "features": features}[cmd](w)
