"""Build person-day inputs for the Gemini Decisions API test (and its no-LLM baseline).

  python build_inputs.py <store_v3 dir> <launches table dir> <out dir>

Store: raw/population/store_v3 (persons.parquet, events.parquet, records/part-*.parquet).
Launches: tables/launches/*.parquet (id, day, name, tagline, topics, poster, votes).
Writes to <out dir> (scratchpad, never the repo): persondays.jsonl (text + per-launch label + baseline features),
fit_rows.parquet (baseline training rows from earlier days). Person ids stay salted and stay out of the repo.

Eligibility for day D (same rule as E5's backer prediction): complete person (persons.complete), first upvote read before
00:00 PT of D (held before), and an upvote read after D closed (so a non-vote is a real non-vote).
History for D: the person's upvote items (newest first) whose launch date is before D AND that sit below (older than) the
oldest item whose launch date is D or later (so an upvote cast after the person's first vote on a launch dated >= D is dropped).
Comments: activity items 'left a comment' with an exact datetime before 00:00 PT of D. Leak checks are asserted.
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd

ST, LT, OUT = sys.argv[1:4]
os.makedirs(OUT, exist_ok=True)
TEST_DAYS = ["2026-11-17", "2026-11-18", "2026-11-19"]
FIT_DAYS = ["2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16"]
N_BACK, N_NON = 150, 150          # per test day (pre-registered)
N_FIT = 400                       # people per fit day for the baseline (backers + non-backers, half each where possible)
N_HIST, N_COMM = 60, 8
rng = np.random.default_rng(20261122)


def start_utc(d): return pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC")


# launches: newest row per id
W = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{LT}/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["topics_l"] = W.topics.apply(lambda s: json.loads(s) if isinstance(s, str) and s.startswith("[") else [])
TOP = dict(zip(W.id, W.topics_l))


def hunter_prior(D):
    """Hunter (poster) track record from launches dated before D only: n earlier launches and median final votes."""
    prev = W[(W.day < D) & W.votes.notna()]
    g = prev.groupby("poster").votes.agg(["size", "median"])
    return g


# people
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete", "joined"])
comp = set(P[P.complete].person_id); JOINED = dict(zip(P.person_id, P.joined))
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "fetched_at"], filters=[("kind", "==", "upvote")])
last_read = E.groupby("person_id").fetched_at.max(); first_read = E.groupby("person_id").fetched_at.min(); del E


def eligible(D):
    s = start_utc(D); c = s + pd.Timedelta(days=1)
    return set(last_read[last_read > c].index) & set(first_read[first_read < s].index) & comp


ELIG = {D: eligible(D) for D in TEST_DAYS + FIT_DAYS}
need = set().union(*ELIG.values())
print("eligible:", {d: len(v) for d, v in ELIG.items()}, "union", len(need), flush=True)

# raw records for eligible people: upvote items (name, tagline, post_id, launch date) + comments
REC = {}
for f in sorted(glob.glob(f"{ST}/records/part-*.parquet")):
    t = pd.read_parquet(f, columns=["person_id", "record_json"])
    t = t[t.person_id.isin(need)]
    for pid, rj in zip(t.person_id, t.record_json):
        j = json.loads(rj)
        ups = []
        for it in ((j.get("upvotes") or {}).get("items") or []):
            if not it.get("post_id") or not it.get("date"): continue
            ups.append({"post_id": str(it["post_id"]), "name": it.get("name") or "", "tagline": it.get("tagline") or "",
                        "lday": str(it["date"])[:10]})   # PT launch date (the item's date is in PT, e.g. 2026-03-13T00:01:00-07:00)
        com = []
        for it in ((j.get("activity") or {}).get("items") or []):
            if it.get("type") == "left a comment" and it.get("datetime") and not it.get("comment_time_unknown"):
                com.append({"ts": pd.Timestamp(it["datetime"]).tz_convert("UTC"), "product": it.get("product") or "",
                            "text": re.sub(r"@\w+", "@someone", (it.get("text") or "").replace("\n", " "))[:200]})
        REC[pid] = {"ups": ups, "com": sorted(com, key=lambda x: x["ts"], reverse=True)}
print("records loaded", len(REC), flush=True)


def history(pid, D):
    ups = REC[pid]["ups"]
    later = [i for i, u in enumerate(ups) if u["lday"] >= D]
    cut = max(later) if later else -1                      # oldest position of an item dated D or later
    h = [u for i, u in enumerate(ups) if i > cut and u["lday"] < D]
    assert all(u["lday"] < D for u in h), "leak: history item dated on/after test day"
    s = start_utc(D)
    c = [x for x in REC[pid]["com"] if x["ts"] < s]
    assert all(x["ts"] < s for x in c), "leak: comment at/after test day start"
    return h, c


def person_text(pid, D, h, c):
    j = JOINED.get(pid)
    d0 = pd.Timestamp(D)
    n7 = sum(1 for u in h if pd.Timestamp(u["lday"]) >= d0 - pd.Timedelta(days=7))
    n30 = sum(1 for u in h if pd.Timestamp(u["lday"]) >= d0 - pd.Timedelta(days=30))
    lines = [f"A Product Hunt member. Account joined {str(j)[:7] if pd.notna(j) else 'unknown'}. "
             f"Upvotes on launches from the 7 days before today: {n7}; from the 30 days before today: {n30}; all earlier upvotes held: {len(h)}.",
             f"Their most recent upvotes before today (newest first; launch date | product - tagline [topics]):"]
    for u in h[:N_HIST]:
        tp = TOP.get(u["post_id"]) or []
        lines.append(f"- {u['lday']} | {u['name']} - {u['tagline']}" + (f" [{', '.join(tp)}]" if tp else ""))
    if not h: lines.append("- (none held)")
    if c:
        lines.append("Comments they wrote before today (newest first):")
        for x in c[:N_COMM]: lines.append(f"- {str(x['ts'])[:10]} on {x['product']}: \"{x['text']}\"")
    return "\n".join(lines), n7, n30


def lineup(D):
    L = W[W.day == D].sort_values("id").copy()
    hp = hunter_prior(D)
    L["h_n"] = L.poster.map(hp["size"]).fillna(0).astype(int); L["h_med"] = L.poster.map(hp["median"])
    return L


def lineup_text(D, L):
    lines = [f"Today's Product Hunt line-up ({D}, {len(L)} launches; launch name - tagline [topics]; hunter's earlier launches):"]
    for _, r in L.iterrows():
        hp = f"hunter has {r.h_n} earlier launches, median {int(r.h_med)} votes" if r.h_n else "hunter has no earlier launch held"
        lines.append(f"- {r['name']} - {r.tagline} [{', '.join(r.topics_l)}] ({hp})")
    return "\n".join(lines)


def topic_overlap(h, L):
    """Share of the person's topic-tagged past upvotes (last 60) carrying each launch topic, max over the launch's topics; plus name-token Jaccard."""
    cnt = {}; tagged = 0
    for u in h[:N_HIST]:
        tp = TOP.get(u["post_id"]) or []
        if tp: tagged += 1
        for t in tp: cnt[t] = cnt.get(t, 0) + 1
    out = []
    for _, r in L.iterrows():
        s = [cnt.get(t, 0) / tagged for t in r.topics_l if t != "Tech"] if tagged else []
        out.append(float(np.mean(s)) if s else 0.0)
    return out


def build_day(D, n_back, n_non, test):
    L = lineup(D); ids = list(L.id)
    rows = []
    for pid in sorted(ELIG[D]):
        if pid not in REC: continue
        up_ids = {u["post_id"] for u in REC[pid]["ups"] if u["lday"] == D}
        lab = [int(i in up_ids) for i in ids]
        h, c = history(pid, D)
        recent = any(pd.Timestamp(u["lday"]) >= pd.Timestamp(D) - pd.Timedelta(days=30) for u in h)
        rows.append((pid, lab, h, c, recent))
    back = [r for r in rows if sum(r[1]) > 0]
    non = [r for r in rows if sum(r[1]) == 0 and r[4]]
    sb = [back[i] for i in rng.choice(len(back), min(n_back, len(back)), replace=False)]
    sn = [non[i] for i in rng.choice(len(non), min(n_non, len(non)), replace=False)]
    lt = lineup_text(D, L) if test else None
    out = []
    for pid, lab, h, c, _ in sb + sn:
        txt, n7, n30 = person_text(pid, D, h, c)
        ov = topic_overlap(h, L)
        rec = {"day": D, "pid": pid, "group": "backer" if sum(lab) else "non_backer", "launch_ids": ids, "labels": lab,
               "n7": n7, "n30": n30, "n_hist": len(h), "n_comm": len(c), "overlap": ov,
               "h_n": L.h_n.tolist(), "h_med": L.h_med.fillna(-1).tolist(),
               "hist_max_lday": max([u["lday"] for u in h], default=None), "comm_max_ts": str(c[0]["ts"]) if c else None}
        if test:
            rec["text"] = txt + "\n\n" + lt
            rec["names"] = L.name.tolist(); rec["taglines"] = L.tagline.tolist()
        out.append(rec)
    print(D, "eligible", len(rows), "backers", len(back), "active non-backers", len(non), "sampled", len(out), flush=True)
    return out, {"eligible": len(rows), "backers_available": len(back), "active_non_backers_available": len(non),
                 "sampled_backers": len(sb), "sampled_non_backers": len(sn), "lineup": len(ids)}


meta = {}
with open(f"{OUT}/persondays.jsonl", "w") as f:
    for D in TEST_DAYS:
        recs, meta[D] = build_day(D, N_BACK, N_NON, True)
        for r in recs:
            assert r["hist_max_lday"] is None or r["hist_max_lday"] < D
            assert r["comm_max_ts"] is None or pd.Timestamp(r["comm_max_ts"]) < start_utc(D)
            f.write(json.dumps(r) + "\n")
fit = []
for D in FIT_DAYS:
    recs, meta[D] = build_day(D, N_FIT // 2, N_FIT // 2, False)
    for r in recs:
        for k, lid in enumerate(r["launch_ids"]):
            fit.append({"day": D, "pid": r["pid"], "y": r["labels"][k], "n7": r["n7"], "n30": r["n30"], "overlap": r["overlap"][k],
                        "h_n": r["h_n"][k], "h_med": r["h_med"][k], "lineup": len(r["launch_ids"])})
pd.DataFrame(fit).to_parquet(f"{OUT}/fit_rows.parquet")
json.dump(meta, open(f"{OUT}/build_meta.json", "w"), indent=1)
print("done", flush=True)
