"""gemini_decisions_shadow: Gemini Decisions API voter line, RECORDING ONLY (orchestrator 05:50Z Nov 22). Never touches the published 00:05
forecast. Reuses the inputs and questions of experiments/decisions_api (claude/cool-volta-l5nuo4: build_inputs.py / run_api.py / score.py).

  write <D>   after the 00:05 line-up of PT day D is frozen (raw/daily/<D>/today_0005.json):
              people = complete persons in store_v3 with >= 1 upvote on a launch dated in the 30 days before D, counting only upvote
              events first seen before D 00:00 PT (the input cut-off). Input per person = upvote history before D (newest first, up to 60;
              launch date | name - tagline [topics], names from the launches table) + D's line-up with hunter track record (launches dated
              before D only), as in build_inputs.py. Comments are NOT included: store_v3 no longer carries records/ (deviation, logged).
              One Decisions call per person, a "noul" question per launch (run_api.py wording). Key: Secret Manager
              "gemini-decisions-key" (project-amer-scs-sandbox), or $GEMINI_KEY_FILE; read into memory only, never printed or written.
              No key -> logs "key missing" and exits 0 (nothing written).
              Per-person P and baseline features -> PRIVATE prefix raw/population/gemini_decisions_shadow/<D>/ (person ids; never the repo).
              Per-launch aggregates -> results/calibration/<D>/gemini_decisions_shadow.json (expected votes = sum P, mean P, people, written_at,
              input cut-off, store generation, tokens and $).
  score <D>   after D closed and the store re-read its people: label = upvote on a D launch, for people whose upvotes were re-read after
              D closed (a non-vote is a real non-vote). AUC (API P), recall at N per launch, baseline alone vs baseline + API logit.
              The baseline (score.py features) is fitted on the 5 days before D. The stack is fitted only on earlier scored shadow days,
              and appears once one exists. Appends results/calibration/gemini_decisions_scorecard.jsonl. Aggregates only.
Spend: stops at $SPEND_CAP_USD (default 10/day; orchestrator soft cap $50/day); logs tokens and $.
"""
import json, os, subprocess, sys, tempfile, threading, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; STORE = f"{B}/raw/population/store_v3"; PRIV = f"{B}/raw/population/gemini_decisions_shadow"
URL = "https://generativelanguage.googleapis.com/v1beta/decisions"; PRICE = 0.10 / 1e6
CAP = float(os.environ.get("SPEND_CAP_USD", "10")); WORKERS = int(os.environ.get("WORKERS", "6")); N_HIST = 60
FEATS = ["l7", "l30", "overlap", "lhn", "lhmed", "lline"]
log = lambda *a: print(time.strftime("%H:%M:%SZ", time.gmtime()), *a, flush=True)
start = lambda d: pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC")
gs = lambda *a: subprocess.run(["gsutil", "-q", *a], capture_output=True, text=True)


def key():
    if os.environ.get("GEMINI_KEY_FILE") and os.path.exists(os.environ["GEMINI_KEY_FILE"]):
        return open(os.environ["GEMINI_KEY_FILE"]).read().strip() or None
    r = subprocess.run(["gcloud", "secrets", "versions", "access", "latest", "--secret=gemini-decisions-key",
                        "--project=project-amer-scs-sandbox"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def store(work):
    """Current store_v3 copy (events, persons) with its publish time (events.parquet generation)."""
    g = [l for l in subprocess.run(["gsutil", "stat", f"{STORE}/events.parquet"], capture_output=True, text=True).stdout.splitlines() if "Generation:" in l]
    gen = g[0].split()[-1]; d = os.path.join(work, f"store_{gen}"); os.makedirs(d, exist_ok=True)
    for f in ("events.parquet", "persons.parquet"):
        if not os.path.exists(f"{d}/{f}"): gs("cp", f"{STORE}/{f}", f"{d}/{f}")
    return d, gen, pd.Timestamp(int(gen) / 1e6, unit="s", tz="UTC")


def launches():
    from pipeline import warehouse
    W = warehouse.table("launches", do_sync=True); W["id"] = W.id.astype(str)
    W = W.sort_values("updated_at").drop_duplicates("id", keep="last"); W["day"] = W.day.astype(str).str[:10]
    W["topics_l"] = W.topics.apply(lambda s: json.loads(s) if isinstance(s, str) and s.startswith("[") else [])
    return W


def upvotes(sd):
    E = pd.read_parquet(f"{sd}/events.parquet", columns=["person_id", "target_id", "ts_lo", "first_seen_at", "fetched_at"],
                        filters=[("kind", "==", "upvote")])
    E["target_id"] = E.target_id.astype(str); E["lday"] = E.ts_lo.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
    P = pd.read_parquet(f"{sd}/persons.parquet", columns=["person_id", "complete", "joined"])
    return E, set(P[P.complete].person_id), dict(zip(P.person_id, P.joined))


def lineup(D, W):
    L = json.loads(subprocess.run(["gsutil", "cat", f"{B}/raw/daily/{D}/today_0005.json"], capture_output=True, text=True).stdout or "[]")
    prev = W[(W.day < D) & W.votes.notna()]; hp = prev.groupby("poster").votes.agg(["size", "median"])
    rows = []
    for x in sorted(L, key=lambda x: str(x["id"])):
        t = x.get("topics"); tp = [e["node"]["name"] for e in (t or {}).get("edges", [])] if isinstance(t, dict) else []
        hid = str(((x.get("user") or {}) if isinstance(x.get("user"), dict) else {}).get("id") or "")
        w = W[W.id == str(x["id"])]; poster = str(w.poster.iloc[0]) if len(w) else hid
        rows.append({"id": str(x["id"]), "name": x.get("name") or "", "tagline": x.get("tagline") or "", "topics_l": tp,
                     "h_n": int(hp["size"].get(poster, 0)), "h_med": (float(hp["median"].get(poster)) if poster in hp.index else -1.0)})
    return pd.DataFrame(rows)


def person_rows(D, E, comp, joined, W, L, cut, people=None):
    """History strictly before D from upvote events first seen before the cut; baseline features per (person, launch)."""
    H = E[(E.first_seen_at < cut) & (E.lday < D) & E.person_id.isin(comp)]
    if people is None:
        act = H[H.lday >= (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")].person_id.unique(); people = sorted(act)
    TOP = dict(zip(W.id, W.topics_l)); NAME = dict(zip(W.id, W.name)); TAG = dict(zip(W.id, W.tagline))
    H = H[H.person_id.isin(set(people))].sort_values("ts_lo", ascending=False)
    lt = [f"Today's Product Hunt line-up ({D}, {len(L)} launches; launch name - tagline [topics]; hunter's earlier launches):"] + \
         [f"- {r['name']} - {r.tagline} [{', '.join(r.topics_l)}] (" + (f"hunter has {r.h_n} earlier launches, median {int(r.h_med)} votes" if r.h_n else
          "hunter has no earlier launch held") + ")" for _, r in L.iterrows()]
    out = []
    for pid, g in H.groupby("person_id", sort=False):
        assert (g.lday < D).all() and (g.first_seen_at < cut).all(), "leak"
        d0 = pd.Timestamp(D); n7 = int((pd.to_datetime(g.lday) >= d0 - pd.Timedelta(days=7)).sum()); n30 = int((pd.to_datetime(g.lday) >= d0 - pd.Timedelta(days=30)).sum())
        hh = g.head(N_HIST); j = joined.get(pid)
        lines = [f"A Product Hunt member. Account joined {str(j)[:7] if pd.notna(j) else 'unknown'}. Upvotes on launches from the 7 days before today: "
                 f"{n7}; from the 30 days before today: {n30}; all earlier upvotes held: {len(g)}.",
                 "Their most recent upvotes before today (newest first; launch date | product - tagline [topics]):"]
        cnt, tagged = {}, 0
        for t, ld in zip(hh.target_id, hh.lday):
            tp = TOP.get(t) or []; tagged += bool(tp)
            for x in tp: cnt[x] = cnt.get(x, 0) + 1
            lines.append(f"- {ld} | {NAME.get(t, 'unknown')} - {TAG.get(t, '')}" + (f" [{', '.join(tp)}]" if tp else ""))
        ov = [float(np.mean([cnt.get(x, 0) / tagged for x in r.topics_l if x != "Tech"])) if tagged and [x for x in r.topics_l if x != "Tech"] else 0.0
              for _, r in L.iterrows()]
        out.append({"pid": pid, "text": "\n".join(lines) + "\n\n" + "\n".join(lt), "n7": n7, "n30": n30, "n_hist": len(g), "overlap": ov})
    return out


def call(K, D, r, L, spent, lock, fout):
    if spent[0] * PRICE >= CAP: return
    q = {f"l{lid}": {"type": "noul", "instructions": f"Would this person upvote \"{nm}\" ({tg}) on Product Hunt today? "
                                                    f"Answer yes only if they would upvote this launch today."}
         for lid, nm, tg in zip(L.id, L.name, L.tagline)}
    import requests
    for a in range(8):
        try:
            resp = requests.post(URL, json={"model": "gemini-decision-1", "input": r["text"], "questions": q},
                                 headers={"x-goog-api-key": K, "Content-Type": "application/json"}, timeout=180)
        except requests.RequestException:
            time.sleep(2 ** a); continue
        if resp.status_code == 200:
            j = resp.json(); p = {k[1:]: (v or {}).get("noul") for k, v in (j.get("answers") or {}).items()}
            tok = (j.get("usage") or {}).get("total_input_tokens") or 0
            with lock:
                spent[0] += tok; fout.write(json.dumps({"day": D, "pid": r["pid"], "p": p, "input_tokens": tok, "n7": r["n7"], "n30": r["n30"],
                                                        "n_hist": r["n_hist"], "overlap": r["overlap"]}) + "\n")
            return
        if resp.status_code in (429, 500, 502, 503, 504): time.sleep(min(60, 2 ** a * 2)); continue
        log("HTTP", resp.status_code, "(body not printed)"); return
    log("gave up on one person")


def write(D):
    K = key()
    if not K: log(f"{D}: key missing (Secret Manager gemini-decisions-key / GEMINI_KEY_FILE); skipped, nothing written"); return 0
    work = tempfile.mkdtemp(prefix="gds_"); cut = start(D)
    sd, gen, gtime = store(work); W = launches(); L = lineup(D, W)
    if not len(L): log(f"{D}: no 00:05 line-up; skipped"); return 1
    E, comp, joined = upvotes(sd)
    R = person_rows(D, E, comp, joined, W, L, cut); log(f"{D}: people {len(R)}, line-up {len(L)}, store {gtime:%m-%dT%H:%MZ}")
    spent, lock = [0], threading.Lock(); ans = os.path.join(work, "answers.jsonl")
    from concurrent.futures import ThreadPoolExecutor
    with open(ans, "w") as fout, ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(lambda r: call(K, D, r, L, spent, lock, fout), R))
    del K
    A = [json.loads(l) for l in open(ans)]
    gs("cp", ans, f"{PRIV}/{D}/answers.jsonl")
    P = pd.DataFrame([{"lid": lid, "p": a["p"].get(lid)} for a in A for lid in L.id]).dropna()
    agg = P.groupby("lid").p.agg(["sum", "mean", "size"])
    res = {"day": D, "line": "gemini_decisions_shadow (recording only; never the published 00:05 forecast)",
           "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "input_cutoff_utc": cut.isoformat(),
           "store_generation": gen, "store_published_utc": gtime.isoformat(), "store_after_cutoff": bool(gtime > cut),
           "people_asked": len(R), "people_answered": len(A), "input_tokens": spent[0], "usd": round(spent[0] * PRICE, 4),
           "deviation": "no comments in the input (store_v3 has no records/)",
           "launches": [{"id": lid, "name": nm, "expected_votes": round(float(agg["sum"].get(lid, 0)), 2),
                         "mean_p": round(float(agg["mean"].get(lid, np.nan)), 4) if lid in agg.index else None, "people": int(agg["size"].get(lid, 0))}
                        for lid, nm in zip(L.id, L.name)]}
    res["launches"].sort(key=lambda x: -x["expected_votes"])
    p = os.path.join(work, "agg.json"); json.dump(res, open(p, "w"), indent=1)
    out = os.path.join(HERE, "results", "calibration", D); os.makedirs(out, exist_ok=True); json.dump(res, open(f"{out}/gemini_decisions_shadow.json", "w"), indent=1)
    gs("cp", p, f"{B}/results/calibration/{D}/gemini_decisions_shadow.json")
    log(f"{D}: answered {len(A)}/{len(R)}, tokens {spent[0]}, ${spent[0] * PRICE:.3f}"); return 0


def feats(df):
    return pd.DataFrame({"l7": np.log1p(df.n7), "l30": np.log1p(df.n30), "overlap": df.overlap, "lhn": np.log1p(df.h_n),
                         "lhmed": np.log1p(df.h_med.clip(lower=0)), "lline": np.log(df.lineup)})


def labelled(D, E, comp, joined, W, people=None):
    """(person, launch) rows for day D with labels, for people held before D whose upvotes were re-read after D closed."""
    s, c = start(D), start(D) + pd.Timedelta(days=1); L = lineup(D, W)
    if not len(L): return pd.DataFrame()
    held = set(E[E.first_seen_at < s].person_id); reread = set(E.groupby("person_id").fetched_at.max().pipe(lambda x: x[x > c]).index)
    ok = held & reread & comp if people is None else set(people) & held & reread & comp
    R = person_rows(D, E, comp, joined, W, L, s, sorted(ok)); ids = set(L.id)
    up = E[E.target_id.isin(ids) & E.person_id.isin(ok)].groupby("person_id").target_id.apply(set).to_dict()
    rows = [{"day": D, "pid": r["pid"], "lid": lid, "y": int(lid in up.get(r["pid"], set())), "n7": r["n7"], "n30": r["n30"], "overlap": r["overlap"][k],
             "h_n": L.h_n.iloc[k], "h_med": L.h_med.iloc[k], "lineup": len(L)} for r in R for k, lid in enumerate(L.id)]
    return pd.DataFrame(rows)


def score(D):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    work = tempfile.mkdtemp(prefix="gds_"); a = os.path.join(work, "a.jsonl")
    if gs("cp", f"{PRIV}/{D}/answers.jsonl", a).returncode: log(f"{D}: no answers (job skipped that night)"); return 0
    A = {json.loads(l)["pid"]: json.loads(l)["p"] for l in open(a)}
    sd, gen, gtime = store(work); W = launches(); E, comp, joined = upvotes(sd)
    if gtime < start(D) + pd.Timedelta(days=1): log(f"{D}: store not re-published after the day closed yet"); return 1
    T = labelled(D, E, comp, joined, W, people=A.keys())
    T["api"] = [A.get(p, {}).get(l) for p, l in zip(T.pid, T.lid)]; T = T[T.api.notna()].copy()
    T["lapi"] = np.log(T.api.clip(1e-4, 1 - 1e-4) / (1 - T.api.clip(1e-4, 1 - 1e-4)))
    fit = pd.concat([labelled((pd.Timestamp(D) - pd.Timedelta(days=i)).strftime("%Y-%m-%d"), E, comp, joined, W) for i in range(1, 6)], ignore_index=True)
    base = LogisticRegression(max_iter=2000).fit(feats(fit), fit.y); T["base"] = base.predict_proba(feats(T))[:, 1]

    def rec_n(col):
        hit = tot = 0
        for _, g in T.groupby("lid"):
            n = int(g.y.sum()); hit += int(g.sort_values(col, ascending=False).head(n).y.sum()) if n else 0; tot += n
        return round(hit / tot, 4) if tot else None
    sc = {"day": D, "scored_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "store_generation": gen, "people": int(T.pid.nunique()),
          "rows": len(T), "positives": int(T.y.sum()), "auc_api": round(roc_auc_score(T.y, T.api), 4), "auc_baseline": round(roc_auc_score(T.y, T.base), 4),
          "recall_at_N_api": rec_n("api"), "recall_at_N_baseline": rec_n("base")}
    SC = os.path.join(HERE, "results", "calibration", "gemini_decisions_scorecard.jsonl"); hist = os.path.join(work, "hist.parquet")
    prev = pd.read_parquet(hist) if gs("cp", f"{PRIV}/scored_rows.parquet", hist).returncode == 0 else pd.DataFrame()
    prev = prev[prev.day < D] if len(prev) else prev
    if len(prev):
        X = feats(prev); X["lapi"] = prev.lapi.values; st = LogisticRegression(max_iter=3000).fit(X, prev.y)
        Xt = feats(T); Xt["lapi"] = T.lapi.values; T["stack"] = st.predict_proba(Xt)[:, 1]
        sc.update({"auc_stack": round(roc_auc_score(T.y, T.stack), 4), "recall_at_N_stack": rec_n("stack"), "stack_fit_days": sorted(prev.day.unique().tolist())})
    else:
        sc["auc_stack"] = None; sc["note"] = "no earlier scored shadow day: stack starts on the next scored day"
    allr = pd.concat([prev, T.drop(columns=[c for c in ("base", "stack") if c in T])], ignore_index=True); allr.to_parquet(hist); gs("cp", hist, f"{PRIV}/scored_rows.parquet")
    open(SC, "a").write(json.dumps(sc) + "\n"); gs("cp", SC, f"{B}/results/calibration/gemini_decisions_scorecard.jsonl"); log(json.dumps(sc)); return 0


def rehearse(D):
    """DRY: builds D's inputs (as write) and the baseline fit rows of the 5 days before D (as score); no API call, nothing written. Counts only."""
    from sklearn.linear_model import LogisticRegression
    work = tempfile.mkdtemp(prefix="gds_"); cut = start(D); sd, gen, gtime = store(work); W = launches(); L = lineup(D, W)
    E, comp, joined = upvotes(sd); R = person_rows(D, E, comp, joined, W, L, cut)
    tl = [len(r["text"]) for r in R]
    fit = pd.concat([labelled((pd.Timestamp(D) - pd.Timedelta(days=i)).strftime("%Y-%m-%d"), E, comp, joined, W) for i in range(1, 6)], ignore_index=True)
    m = LogisticRegression(max_iter=2000).fit(feats(fit), fit.y)
    print(json.dumps({"day": D, "lineup": len(L), "people": len(R), "store_published": f"{gtime:%m-%dT%H:%MZ}", "store_after_cutoff": bool(gtime > cut),
                      "text_chars_median": int(np.median(tl)) if tl else 0, "est_tokens_per_person": int(np.median(tl) / 4) if tl else 0,
                      "est_usd": round(len(R) * (np.median(tl) / 4 if tl else 0) * PRICE, 3), "fit_rows": len(fit), "fit_positive_rate": round(float(fit.y.mean()), 4),
                      "fit_days": sorted(fit.day.unique().tolist()), "baseline_coef_n": len(m.coef_[0]), "key_present": bool(key())}))
    return 0


if __name__ == "__main__":
    sys.exit({"write": write, "score": score, "rehearse": rehearse}[sys.argv[1]](sys.argv[2]))
