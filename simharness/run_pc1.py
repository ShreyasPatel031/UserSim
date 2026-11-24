"""PRESENCE-CHOICE-1 on Benchmark v0: Task V split into "does the person show up on day D" and "which launches do
they pick once there".

Stages (private files go to --out; with --sync gs://prefix they are copied there after each stage):

  presence   walk-forward presence models on test days; hindsight history and the as-known-at-00:05 view
  choice     the CHOICE benchmark rows (person-days x the day's 00:05 line-up) and the non-language models
  llm        prompt models pick from the whole shuffled line-up on a fixed subsample (--models, --cap USD)
  combine    P(present) x P(choose | present) as a full-pool Task V score, against the round-1 logistic
  agg        results.json + table.md (aggregates only) into --results-dir

  PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python -m simharness.run_pc1 STAGE --bench B --round1 R1 --ties T --out O

Leak rules: every input is dated before day D or is on the day's 00:05 line-up; outcomes of D are labels only.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import subprocess
import time

import numpy as np
import pandas as pd

NB = 2000


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


def load_bench(a):
    from simharness.bench import Benchmark
    return Benchmark(a.bench)


def _s(df, keys=("auc_mean", "auc_pooled", "ece", "recall_at_N_pooled")):
    from simharness.score import summarize
    df = df[(df.N > 0) & (df.n > df.N)]
    s = summarize(df, pooled_auc=True, n_boot=NB, cluster="day")
    out = {k: s[k] for k in keys}
    out.update(days=s["days"], rows=s["pairs"], positives=s["positives"])
    return out


def _d(dfa, dfb, metric):
    from simharness.score import paired_diff
    ok = lambda x: x[(x.N > 0) & (x.n > x.N)]  # noqa: E731
    return paired_diff(ok(dfa), ok(dfb), metric, NB, pooled_auc=True, cluster="day")


# ------------------------------------------------------------------------------------------------ presence
def stage_presence(a):
    from simharness.bench import day_ord
    from simharness.domains.producthunt import load_first_seen
    from simharness.presence import NAMES, PresenceData, walk_forward
    from simharness.score import score_rows
    b = load_bench(a)
    fs, reads = load_first_seen(b, a.events)
    kinds = ("baseline", "logistic", "lgbm")
    rf = f"{a.out}/presence_rows_test.parquet"
    if os.path.exists(rf):
        rows = pd.read_parquet(rf)
        fs_missing = float(np.isnat(np.asarray(fs, dtype="datetime64[ns]")).mean())
    else:
        pdata = PresenceData(b, fs)
        fs_missing = float(np.isnat(pdata.fs).mean())
        rows, fitted = walk_forward(pdata, b.days("test"), kinds)
        known, anyk = {k: [] for k in kinds}, []
        for d in b.days("test"):
            pool = b.pool(d)
            Xk = pdata.features(d, pdata.cutoff(d))[pool]
            for kind in kinds:
                known[kind].append(fitted[d][kind].predict(Xk))
            anyk.append(Xk[:, NAMES.index("ln_total")] > 0)
        for kind in kinds:
            rows[kind + "_asknown"] = np.concatenate(known[kind])
        rows["any_history_known"] = np.concatenate(anyk)
        rows.to_parquet(rf)
        pickle.dump({d: {k: (m.clf, getattr(m, "mu", None), getattr(m, "sd", None)) for k, m in ms.items()}
                     for d, ms in fitted.items()}, open(f"{a.out}/presence_models.pkl", "wb"))
    # how old is the newest read of each person at the start of the day (reads that found nothing leave no trace)
    r0 = int(reads.day_ord.min())
    R = np.zeros((b.n_people, int(reads.day_ord.max()) - r0 + 2), bool)
    R[reads.person_idx.to_numpy(), reads.day_ord.to_numpy() - r0] = True
    stale = np.full(len(rows), np.nan)
    for d, g in rows.groupby("day"):
        t = min(max(day_ord(d) - r0, 0), R.shape[1])
        sub = R[g.person_idx.to_numpy(), :t]
        has = sub.any(1)
        last = t - 1 - np.argmax(sub[:, ::-1], axis=1) if t > 0 else np.zeros(len(g), int)
        stale[g.index.to_numpy()] = np.where(has, t - last, np.nan)
    rows["days_since_last_read"] = stale
    rows.to_parquet(rf)
    st = rows.days_since_last_read
    res = {"definition": "label = the person (in the day's active pool) upvoted at least one launch that day",
           "base_rate_test": round(float(rows.y.mean()), 4), "person_days_test": int(len(rows)),
           "first_seen_missing_share": round(fs_missing, 4),
           "reading_lag": {"share_person_days_with_any_history_in_store_at_0005": round(float(rows.any_history_known.mean()), 4),
                           "share_read_on_the_previous_day": round(float((st == 1).mean()), 4),
                           "share_read_within_3_days": round(float((st <= 3).mean()), 4),
                           "share_read_within_7_days": round(float((st <= 7).mean()), 4),
                           "median_days_since_last_read_when_any": float(st.median())},
           "views": {}}
    views = {"everyone, history complete through D-1 (read later)": (rows, ""),
             "everyone, history as known at 00:05": (rows, "_asknown"),
             "people read on D-1, history as known at 00:05": (rows[st == 1], "_asknown"),
             "people read within 7 days before D, history as known at 00:05": (rows[st <= 7], "_asknown"),
             "people read within 7 days before D, history complete through D-1": (rows[st <= 7], "")}
    for vname, (r, suf) in views.items():
        if len(r) < 200 or r.y.sum() < 20:
            res["views"][vname] = {"person_days": int(len(r)), "note": "too few person-days to score"}
            print(vname, "person-days", len(r), flush=True)
            continue
        per = {k: score_rows(r, r[k + suf].to_numpy()) for k in kinds}
        res["views"][vname] = {"person_days": int(len(r)), "models": {k: _s(per[k]) for k in kinds},
                               "vs_baseline": {k: {m: _d(per[k], per["baseline"], m)
                                                   for m in ("auc_mean", "auc_pooled", "recall_at_N_pooled")}
                                               for k in ("logistic", "lgbm")}}
        print(vname, json.dumps({k: {m: v[m]["value"] for m in ("auc_mean", "ece", "recall_at_N_pooled")}
                                 for k, v in res["views"][vname]["models"].items()}), flush=True)
    ms = pickle.load(open(f"{a.out}/presence_models.pkl", "rb"))
    lg = ms[b.days("test")[-1]]["lgbm"][0].booster_.feature_importance("gain")
    res["lgbm_gain_share_last_fit"] = dict(zip(NAMES, np.round(lg / lg.sum(), 3).tolist()))
    res["walk_forward"] = "refit every 2 scored days on the 45 benchmark days before the refit day"
    json.dump(res, open(f"{a.out}/presence_results.json", "w"), indent=1, default=float)
    sync([f"{a.out}/presence_results.json", rf], a.sync)


# ------------------------------------------------------------------------------------------------ choice
CH_TASTE = ("tm", "tm_max", "emb_cos", "emb_max30", "emb_mean30")


def _choice_ctx(a, b):
    """Everything the choice features need: line-ups, taste features + taste-v1, tie tables, the dated-ties model."""
    from sklearn.linear_model import LogisticRegression
    from simharness.domains.producthunt import load_lineups
    from simharness.features import TasteFeatures
    from simharness.models.taste import TasteVote
    from simharness.ties import DATED, UNDATED, TieData, load_tables
    lineup = load_lineups(b, a.daily, a.forecast, b.days("val") + b.days("test"))
    tf = TasteFeatures(b, np.load(f"{a.round1}/item_emb_bge_small.npy"))
    rep = json.load(open(f"{a.round1}/taste_val_report.json"))
    tv = TasteVote(tf, "lgbm", name="taste-v1")
    tv.clf = pickle.load(open(f"{a.round1}/taste_models.pkl", "rb"))[rep["_chosen"]]
    td = TieData(b.n_people, len(b.items), load_tables(f"{a.ties}/tables"))
    hv = pd.read_parquet(f"{a.ties}/ties_rows_hard_val.parquet")      # VAL-HARD rows with tie features (TIES-1)
    Xv = hv[list(DATED)].to_numpy(dtype=np.float32)
    mu, sd = Xv.mean(0), Xv.std(0) + 1e-9
    tie_lr = LogisticRegression(max_iter=2000).fit((Xv - mu) / sd, hv.y.to_numpy())
    del UNDATED
    return {"lineup": lineup, "tf": tf, "tv": tv, "td": td, "tie": (tie_lr, mu, sd)}


def choice_features(b, ctx, day, persons, items, structural):
    """X [P, L, F] and the named single-model scores for one day. Structural: z-score and rank share within the
    given items (0 / 0.5 and a missing flag when the day has no frozen score for the item)."""
    from simharness.choice import upvotes_per_active_day
    from simharness.features import TASTE_NAMES
    from simharness.ties import DATED
    tf, tv, td = ctx["tf"], ctx["tv"], ctx["td"]
    tie_lr, mu, sd = ctx["tie"]
    P, L = len(persons), len(items)
    st = np.asarray(structural, dtype=float)
    ok = np.isfinite(st)
    z = np.zeros(L); rk = np.full(L, 0.5)
    if ok.sum() >= 2:
        z[ok] = (st[ok] - st[ok].mean()) / (st[ok].std() + 1e-9)
        rk[ok] = 1.0 - (np.argsort(np.argsort(-st[ok])) / max(ok.sum() - 1, 1))
    k = upvotes_per_active_day(b, day)[persons]
    blk = tf.person_block(day, persons)
    ti = [TASTE_NAMES.index(n) for n in CH_TASTE]
    names = ["struct_z", "struct_rank", "struct_missing"] + list(CH_TASTE) + list(DATED) + ["ln_k", "ln_L"]
    X = np.zeros((P, L, len(names)), np.float32)
    taste = np.zeros((P, L), np.float32)
    ties = np.zeros((P, L), np.float32)
    for j, it in enumerate(items):
        F = tf.features(day, persons, int(it), block=blk)
        T = td.features(day, int(it), persons, DATED)
        taste[:, j] = tv.predict(F)
        ties[:, j] = tie_lr.decision_function((T - mu) / sd)
        X[:, j, 0], X[:, j, 1], X[:, j, 2] = z[j], rk[j], float(not ok[j])
        X[:, j, 3:3 + len(ti)] = F[:, ti]
        X[:, j, 3 + len(ti):3 + len(ti) + len(DATED)] = T
    X[:, :, -2] = np.log1p(k)[:, None]
    X[:, :, -1] = np.log(max(L, 1))
    single = {"structural order": np.tile(np.where(ok, st, -np.inf), (P, 1)), "topic match": X[:, :, 3].copy(),
              "taste-v1": taste, "dated ties": ties}
    return X, names, single, k


class ChoiceCombo:
    def __init__(self, kind: str):
        self.kind = kind

    def fit(self, X, y):
        if self.kind == "lgbm":
            import lightgbm as lgb
            self.clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=100,
                                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1).fit(X, y)
        else:
            from sklearn.linear_model import LogisticRegression
            self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
            self.clf = LogisticRegression(max_iter=3000).fit((X - self.mu) / self.sd, y)
        return self

    def predict(self, X):
        sh = X.shape
        X2 = X.reshape(-1, sh[-1])
        p = self.clf.predict_proba(X2 if self.kind == "lgbm" else (X2 - self.mu) / self.sd)[:, 1]
        return p.reshape(sh[:-1])


def stage_choice(a):
    from simharness import choice as ch
    b = load_bench(a)
    ctx = _choice_ctx(a, b)
    lineup = ctx["lineup"]
    cds = ch.build(b, lineup, b.days("val") + b.days("test"))
    pdays, labels = ch.tables(b, cds)
    os.makedirs(f"{a.out}/choice", exist_ok=True)
    pdays.to_parquet(f"{a.out}/choice/choice_persondays.parquet")
    labels.to_parquet(f"{a.out}/choice/choice_labels.parquet")
    lineup[["day", "item_idx", "source", "structural"]].to_parquet(f"{a.out}/choice/choice_lineup.parquet")
    lineup[["day", "item_idx", "description"]].to_parquet(f"{a.out}/choice/choice_lineup_text.parquet")
    open(f"{a.out}/choice/SCHEMA.txt", "w").write(ch.SCHEMA_NOTE + "\n")
    sync([f"{a.out}/choice/{f}" for f in ("choice_persondays.parquet", "choice_labels.parquet", "choice_lineup.parquet",
                                          "choice_lineup_text.parquet", "SCHEMA.txt")], a.sync)
    info = {"person_days": pdays.groupby("split").size().to_dict(),
            "days": pdays.groupby("split").day.nunique().to_dict(),
            "mean_lineup_size": pdays.groupby("split").lineup_size.mean().round(1).to_dict(),
            "mean_upvoted_on_lineup": pdays.groupby("split").n_upvoted.mean().round(2).to_dict(),
            "median_upvoted_on_lineup": pdays.groupby("split").n_upvoted.median().to_dict(),
            "upvotes_off_lineup_share": (pdays.groupby("split").n_upvoted_off_lineup.sum()
                                         / (pdays.groupby("split").n_upvoted.sum()
                                            + pdays.groupby("split").n_upvoted_off_lineup.sum())).round(4).to_dict(),
            "lineup_source_by_day": lineup.drop_duplicates("day").set_index("day").source.to_dict(),
            "days_with_structural": sorted(lineup[lineup.structural.notna()].day.unique().tolist())}
    print(json.dumps(info, indent=1), flush=True)
    feats, single = {}, {}
    for d, c in cds.items():
        X, names, sg, k = choice_features(b, ctx, d, c.persons, c.items, c.structural)
        feats[d], single[d] = X, sg
        print("features", d, X.shape, flush=True)
    val_days = [d for d in b.days("val") if d in cds and np.isfinite(cds[d].structural).any()]
    test_days = [d for d in b.days("test") if d in cds]
    flat = lambda days: (np.vstack([feats[d].reshape(-1, feats[d].shape[-1]) for d in days]),  # noqa: E731
                         np.concatenate([cds[d].Y.reshape(-1) for d in days]).astype(np.int8))
    # choose the combination's learner by leave-one-day-out on validation, then refit on all validation days
    lodo = {}
    for kind in ("logistic", "lgbm"):
        sc = {}
        for d in val_days:
            Xtr, ytr = flat([x for x in val_days if x != d])
            sc[d] = ChoiceCombo(kind).fit(Xtr, ytr).predict(feats[d])
        lodo[kind] = ch.summarize(ch.per_personday(sc, cds), n_boot=200)
        print("validation leave-one-day-out", kind, json.dumps(lodo[kind]), flush=True)
    best = max(lodo, key=lambda k: lodo[k]["auc"]["value"])
    Xv, yv = flat(val_days)
    combo = ChoiceCombo(best).fit(Xv, yv)
    pickle.dump({"kind": best, "model": combo, "names": names}, open(f"{a.out}/choice_combo.pkl", "wb"))
    scores = {k: {d: single[d][k] for d in test_days} for k in ("structural order", "topic match", "taste-v1", "dated ties")}
    scores[f"combination ({best}, fit on validation)"] = {d: combo.predict(feats[d]) for d in test_days}
    rng = np.random.default_rng(1)
    scores["random order"] = {d: rng.random(cds[d].Y.shape) for d in test_days}
    per = {k: ch.per_personday(v, cds) for k, v in scores.items()}
    res = {"benchmark": info, "validation_days_for_fitting": val_days, "combination_learner_choice": lodo,
           "combination_features": names, "models": {}, "vs_structural": {}}
    for k, df in per.items():
        res["models"][k] = ch.summarize(df, NB)
        if k != "structural order":
            res["vs_structural"][k] = ch.paired(df, per["structural order"], NB)
        print(k, json.dumps(res["models"][k]), flush=True)
    if best == "logistic":
        res["combination_coef_standardised"] = dict(zip(names, np.round(combo.clf.coef_[0], 3).tolist()))
    else:
        g = combo.clf.booster_.feature_importance("gain")
        res["combination_gain_share"] = dict(zip(names, np.round(g / g.sum(), 3).tolist()))
    pickle.dump({"scores": scores, "per": per}, open(f"{a.out}/choice_test_scores.pkl", "wb"))
    json.dump(res, open(f"{a.out}/choice_results.json", "w"), indent=1, default=float)
    sync([f"{a.out}/choice_results.json", f"{a.out}/choice_combo.pkl"], a.sync)


# ------------------------------------------------------------------------------------------------ llm on CHOICE
def _choice_days(a, b):
    from simharness import choice as ch
    lineup = pd.read_parquet(f"{a.out}/choice/choice_lineup.parquet")
    return ch.build(b, lineup, b.days("test")), lineup


def _llm_sample(a, b, cds, n_per_day=25, seed=2026):
    f = f"{a.out}/choice/llm_sample.parquet"
    if os.path.exists(f):
        return pd.read_parquet(f)
    from simharness.bench import day_ord
    from simharness.choice import upvotes_per_active_day
    rng = np.random.default_rng(seed)
    rows = []
    for d, c in cds.items():
        pick = np.sort(rng.choice(len(c.persons), min(n_per_day, len(c.persons)), replace=False))
        k = upvotes_per_active_day(b, d)[c.persons[pick]]
        for i, p in enumerate(c.persons[pick]):
            L = len(c.items)
            perm = np.random.default_rng([day_ord(d), int(p), 7]).permutation(L)   # the recorded shuffle seed
            kk = int(max(1, round(float(k[i]))))
            rows.append({"day": d, "person_idx": int(p), "k": kk, "m": int(min(max(3, kk), 10, L)),
                         "shown_items": c.items[perm].tolist()})
    s = pd.DataFrame(rows)
    s.to_parquet(f)
    return s


def stage_llm(a):
    from concurrent.futures import ThreadPoolExecutor
    from simharness.models.llm import (Budget, BudgetExceeded, JsonlCache, build_choice_prompt, lineup_line,
                                       parse_picks)
    from simharness.run_round1 import backend_for
    b = load_bench(a)
    cds, _ = _choice_days(a, b)
    text = pd.read_parquet(f"{a.out}/choice/choice_lineup_text.parquet")
    desc = {(r.day, int(r.item_idx)): r.description for r in text.itertuples()}
    sample = _llm_sample(a, b, cds)
    sync([f"{a.out}/choice/llm_sample.parquet"], a.sync)
    prompts = {}
    for d, g in sample.groupby("day"):
        hb = b.batch(d, g.person_idx.to_numpy())
        for j, r in enumerate(g.itertuples()):
            lines = [lineup_line(i + 1, b.item(it), desc.get((d, int(it)), "")) for i, it in enumerate(r.shown_items)]
            prompts[(d, r.person_idx)] = (build_choice_prompt(hb.render(j), lines, r.k, r.m), len(lines))
    chars = sum(len(p) for p, _ in prompts.values())
    print("prompts", len(prompts), "chars", chars, "about tokens", int(chars / 3.8), flush=True)
    if not a.models:
        return
    budget = Budget(a.cap)
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    for name in a.models.split(","):
        cache = JsonlCache(f"{a.out}/llm_choice_cache/{name}")
        be = backend_for(name, project, budget)
        be.max_out = 1200 if name.startswith("gpt-oss") else 200
        t0, stopped, fails = time.time(), False, 0

        def one(key):
            if key in cache:
                return
            pr, n = prompts[key]
            out = be.call(pr)
            cache[key] = {"picks": parse_picks(out, n)}

        keys = list(prompts)
        gsdir = f"{a.sync.rstrip('/')}/llm_choice_cache/{name}" if a.sync else None
        for i in range(0, len(keys), 60):
            with ThreadPoolExecutor(a.workers) as ex:
                futs = [ex.submit(one, k) for k in keys[i:i + 60]]
                for f in futs:
                    try:
                        f.result()
                    except BudgetExceeded as e:
                        stopped = True
                        print("STOP", name, e, flush=True)
                    except Exception:  # noqa: BLE001 - a failed call is counted and left unscored
                        fails += 1
            part = cache.roll()
            sync([part] if part else [], gsdir)
            if stopped:
                break
        st = be.stats()
        st.update(model=name, failures=fails, wall_s=round(time.time() - t0), answered=int(sum(k in cache for k in keys)),
                  no_valid_pick=int(sum(k in cache and not cache[k]["picks"] for k in keys)))
        with open(f"{a.out}/llm_choice_ledger.jsonl", "a") as f:
            f.write(json.dumps(st) + "\n")
        picks = sample[["day", "person_idx", "k", "m"]].copy()
        picks["picks_pos"] = [cache[(r.day, r.person_idx)]["picks"] if (r.day, r.person_idx) in cache else None
                              for r in sample.itertuples()]
        picks.to_parquet(f"{a.out}/llm_choice_picks_{name}.parquet")
        sync([f"{a.out}/llm_choice_picks_{name}.parquet", f"{a.out}/llm_choice_ledger.jsonl"], a.sync)
        print(name, json.dumps(st), flush=True)
    print("this run spent", round(budget.spent, 4), {k: round(v, 4) for k, v in budget.lines.items()})


def _llm_results(a, b):
    """Score saved picks against the same person-days of the structural order and the non-language combination."""
    import glob
    from simharness import choice as ch
    cds, _ = _choice_days(a, b)
    sample = pd.read_parquet(f"{a.out}/choice/llm_sample.parquet")
    saved = pickle.load(open(f"{a.out}/choice_test_scores.pkl", "rb"))["per"]
    key = sample[["day", "person_idx"]]
    base = {k: v.merge(key, on=["day", "person_idx"]) for k, v in saved.items()}
    combo_name = [k for k in base if k.startswith("combination")][0]
    res = {"sample": {"person_days": int(len(sample)), "days": int(sample.day.nunique()),
                      "per_day": 25, "shuffle_seed": "numpy default_rng([day ordinal, person_idx, 7]).permutation(line-up size)",
                      "list_length": "max(3, k) capped at 10 and at the line-up size; k = the person's mean upvotes per "
                                     "active day before the day, rounded, minimum 1"},
           "models": {}, "paired": {}, "position": {}}
    for k in ("structural order", combo_name, "taste-v1", "random order"):
        res["models"][k + " (same person-days)"] = ch.summarize(base[k], NB)
    led = {}
    lf = f"{a.out}/llm_choice_ledger.jsonl"
    for line in (open(lf) if os.path.exists(lf) else []):
        r = json.loads(line)
        led[r["model"]] = r
    for f in sorted(glob.glob(f"{a.out}/llm_choice_picks_*.parquet")):
        name = os.path.basename(f)[len("llm_choice_picks_"):-len(".parquet")]
        pk = pd.read_parquet(f).merge(sample[["day", "person_idx", "shown_items"]], on=["day", "person_idx"])
        scores, pos_rel, first_pos, npk, hit_k, n_k = {}, [], [], [], 0, 0
        for d, g in pk.groupby("day"):
            c = cds[d]
            loc = {int(p): i for i, p in enumerate(c.persons)}
            col = {int(it): j for j, it in enumerate(c.items)}
            S = np.zeros(c.Y.shape, np.float32)
            for r in g.itertuples():
                picks = list(r.picks_pos) if r.picks_pos is not None else []
                L = len(r.shown_items)
                npk.append(len(picks))
                for rank, pos in enumerate(picks):
                    it = int(r.shown_items[pos - 1])
                    S[loc[r.person_idx], col[it]] = len(picks) - rank
                    pos_rel.append((pos - 0.5) / L)
                    if rank < r.k:
                        hit_k += int(c.Y[loc[r.person_idx], col[it]]); n_k += 1
                if picks:
                    first_pos.append((picks[0] - 0.5) / L)
            idx = np.array([loc[p] for p in g.person_idx])
            m = ch.metrics(S[idx], c.Y[idx], seed=11)
            m.insert(0, "person_idx", g.person_idx.to_numpy()); m.insert(0, "day", d)
            scores[d] = m
        per = pd.concat(scores.values(), ignore_index=True)
        st = led.get(name, {})
        e = ch.summarize(per, NB)
        e.update(cost_usd=st.get("cost_usd"), cost_per_1k_usd=st.get("cost_per_1k_usd"),
                 latency_s_median=st.get("latency_s_median"), tokens_in=st.get("tokens_in"),
                 no_valid_pick=st.get("no_valid_pick"), mean_picks=round(float(np.mean(npk)), 2),
                 precision_of_first_k_picks=round(hit_k / max(n_k, 1), 4))
        res["models"][name] = e
        res["paired"][name] = {"vs structural order": ch.paired(per, base["structural order"], NB),
                               "vs " + combo_name: ch.paired(per, base[combo_name], NB)}
        pr = np.array(pos_rel)
        res["position"][name] = {"share_of_picks_by_fifth_of_the_list": np.round(
            np.histogram(pr, bins=[0, .2, .4, .6, .8, 1.0])[0] / max(len(pr), 1), 3).tolist(),
            "first_pick_in_first_fifth": round(float((np.array(first_pos) < 0.2).mean()), 3),
            "mean_relative_position": round(float(pr.mean()), 3)}
    return res


# ------------------------------------------------------------------------------------------------ combine
def stage_combine(a):
    from simharness.score import paired_diff, score_item, summarize
    b = load_bench(a)
    ctx = _choice_ctx(a, b)
    combo = pickle.load(open(f"{a.out}/choice_combo.pkl", "rb"))["model"]
    pres = pd.read_parquet(f"{a.out}/presence_rows_test.parquet")
    lineup = ctx["lineup"]
    variants = ["P(present) alone [lgbm]", "P(present, logistic) x P(choose | present)",
                "P(present, lgbm) x P(choose | present)", "P(choose | present) alone"]
    full = {k: [] for k in variants}
    for d in b.days("test"):
        pool = b.pool(d)
        pr = pres[pres.day == d]
        assert (pr.person_idx.to_numpy() == pool).all()
        lu = lineup[lineup.day == d]
        st = dict(zip(lu.item_idx.astype(int), lu.structural))
        on = set(lu.item_idx.astype(int))
        targets = [int(i) for i in b.items_on(d) if len(b.positives(d, i))]
        items = np.array(sorted(on | set(targets)), dtype=np.int64)
        X, names, _, _ = choice_features(b, ctx, d, pool.astype(np.int64), items, [st.get(int(i), np.nan) for i in items])
        X[:, :, -1] = np.log(max(len(on), 1))                 # line-up size as in the choice benchmark
        pc = combo.predict(X)
        for j, it in enumerate(items):
            if int(it) not in targets:
                continue
            y = np.isin(pool, b.positives(d, it)).astype(np.int8)
            sc = {"P(present) alone [lgbm]": pr["lgbm"].to_numpy(),
                  "P(present, logistic) x P(choose | present)": pr["logistic"].to_numpy() * pc[:, j],
                  "P(present, lgbm) x P(choose | present)": pr["lgbm"].to_numpy() * pc[:, j],
                  "P(choose | present) alone": pc[:, j]}
            for k, v in sc.items():
                full[k].append({"day": d, "item_idx": int(it), "on_lineup": int(it) in on, **score_item(v, y)})
        print("combine", d, len(pool), len(items), flush=True)
    per = {k: pd.DataFrame(v) for k, v in full.items()}
    ref = pickle.load(open(f"{a.ties}/ties_full_test.pkl", "rb"))
    res = {}
    for k, df in list(per.items()) + [("logistic (round 1)", ref["logistic"]), ("logistic + dated ties (TIES-1)", ref["logistic + dated ties"])]:
        s = summarize(df, n_boot=NB)
        res[k] = {"recall_at_N_pooled": s["recall_at_N_pooled"], "recall_at_N_mean": s["recall_at_N_mean"],
                  "auc_mean": s["auc_mean"], "items": s["items"]}
        if k in per:
            res[k]["vs_logistic"] = paired_diff(df, ref["logistic"], "recall_at_N_pooled", NB)
            res[k]["vs_logistic_plus_ties"] = paired_diff(df, ref["logistic + dated ties"], "recall_at_N_pooled", NB)
            onl = df[df.on_lineup]
            ro = ref["logistic"].merge(onl[["day", "item_idx"]], on=["day", "item_idx"])
            res[k]["on_0005_lineup_only"] = {"recall_at_N_pooled": summarize(onl, n_boot=NB)["recall_at_N_pooled"],
                                             "items": int(len(onl)),
                                             "vs_logistic": paired_diff(onl, ro, "recall_at_N_pooled", NB)}
        print(k, json.dumps(res[k]), flush=True)
    pickle.dump(per, open(f"{a.out}/combine_full_test.pkl", "wb"))
    json.dump(res, open(f"{a.out}/combine_results.json", "w"), indent=1, default=float)
    sync([f"{a.out}/combine_results.json", f"{a.out}/combine_full_test.pkl"], a.sync)


# ------------------------------------------------------------------------------------------------ agg
def stage_agg(a):
    b = load_bench(a)
    res = {"task": "Benchmark v0, PRESENCE-CHOICE-1", "intervals": "day-clustered bootstrap 95%"}
    for k, f in (("presence", "presence_results.json"), ("choice", "choice_results.json"), ("combine", "combine_results.json")):
        if os.path.exists(f"{a.out}/{f}"):
            res[k] = json.load(open(f"{a.out}/{f}"))
    if os.path.exists(f"{a.out}/choice/llm_sample.parquet"):
        res["llm_choice"] = _llm_results(a, b)
    os.makedirs(a.results_dir, exist_ok=True)
    json.dump(res, open(f"{a.results_dir}/results.json", "w"), indent=1, default=float)
    f = lambda d, pct=False: (f"{d['value'] * 100:.1f} [{d['ci95'][0] * 100:.1f}, {d['ci95'][1] * 100:.1f}]" if pct  # noqa: E731
                              else f"{d['value']:.3f} [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]")
    fd = lambda d, pct=False: (f"{d['diff'] * 100:+.1f} [{d['ci95'][0] * 100:+.1f}, {d['ci95'][1] * 100:+.1f}]" if pct  # noqa: E731
                               else f"{d['diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]")
    L = []
    if "presence" in res:
        for vn, v in res["presence"]["views"].items():
            if "models" not in v:
                L += [f"**Presence: {vn}**: {v['person_days']} person-days, not scored", ""]
                continue
            L += [f"**Presence: {vn}** ({v['models']['baseline']['rows']} person-days)", "",
                  "| Model | AUC (mean per day) | ECE | voters in top N | vs baseline (top N) |", "|---|---|---|---|---|"]
            for k, e in v["models"].items():
                dd = v["vs_baseline"].get(k, {}).get("recall_at_N_pooled")
                L.append(f"| {k} | {f(e['auc_mean'])} | {f(e['ece'])} | {f(e['recall_at_N_pooled'], True)} | {fd(dd, True) if dd else ''} |")
            L.append("")
    if "choice" in res:
        L += ["**Choice (test person-days, 00:05 line-up)**", "", "| Model | top-3 hit | MRR | AUC | top-3 vs structural |",
              "|---|---|---|---|---|"]
        for k, e in res["choice"]["models"].items():
            dd = res["choice"]["vs_structural"].get(k)
            L.append(f"| {k} | {f(e['top3'], True)} | {f(e['mrr'])} | {f(e['auc'])} | {fd(dd['top3'], True) if dd else ''} |")
        L.append("")
    if "llm_choice" in res:
        L += ["**Language models on CHOICE (fixed subsample)**", "",
              "| Model | top-3 hit | MRR | AUC | top-3 vs structural | top-3 vs combination | $ / 1k | picks in first fifth of the list |",
              "|---|---|---|---|---|---|---|---|"]
        for k, e in res["llm_choice"]["models"].items():
            p = res["llm_choice"]["paired"].get(k, {})
            ps = p.get("vs structural order")
            pc = [v for kk, v in p.items() if kk.startswith("vs combination")]
            pos = res["llm_choice"]["position"].get(k, {})
            L.append(f"| {k} | {f(e['top3'], True)} | {f(e['mrr'])} | {f(e['auc'])} | {fd(ps['top3'], True) if ps else ''} "
                     f"| {fd(pc[0]['top3'], True) if pc else ''} | {e.get('cost_per_1k_usd') or ''} "
                     f"| {pos.get('share_of_picks_by_fifth_of_the_list', [''])[0]} |")
        L.append("")
    if "combine" in res:
        L += ["**Full pool, all test launches**", "", "| Model | recall@N | vs logistic | vs logistic + ties |", "|---|---|---|---|"]
        for k, e in res["combine"].items():
            L.append(f"| {k} | {f(e['recall_at_N_pooled'], True)} | {fd(e['vs_logistic'], True) if 'vs_logistic' in e else ''} "
                     f"| {fd(e['vs_logistic_plus_ties'], True) if 'vs_logistic_plus_ties' in e else ''} |")
    open(f"{a.results_dir}/table.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["presence", "choice", "llm", "combine", "agg"])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--round1", default="")
    ap.add_argument("--ties", default="")
    ap.add_argument("--sync", default="")
    ap.add_argument("--events", default="")
    ap.add_argument("--daily", default="")
    ap.add_argument("--forecast", default="")
    ap.add_argument("--models", default="")
    ap.add_argument("--cap", type=float, default=0.0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--results-dir", default="")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
