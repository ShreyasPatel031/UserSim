"""BACKER PREDICTION (north-star metric, Shreyas Nov 14): of the held people who actually voted for a launch, the share we named in advance.
recall@N per launch, N = number of observed held backers; hits = observed backers among our top-N frozen list (tmp/e5/private/backer_pred/<day>.parquet,
frozen with reads fetched before 00:00 PT of the day). Observed backers = people already held at freeze time (a read before 00:00 PT of the day) whose own profile upvote list contains the launch (store
events kind=upvote); people first read after the freeze are counted separately and excluded. Only people re-read after the day closed can show the vote; each row records how many were.
Baseline: the N most active held people (upvotes on launches of the 30 days before the day), the same list for every launch of the day.
Pooled recall = sum(hits) / sum(N) over the day's launches; 95% interval = launch bootstrap. Aggregates only, no person ids in the output.
  python backer_score.py <store dir> <scratchpad> <day> [<day> ...] [--no-upload]
Writes <SP>/backer/backer_score.json, gs://.../results/web/backer_prediction.json (rows by day and store lag) and north-star rows in PH ops'
table format at results/web/north_star_rows_e5.json (for PH ops to merge into north_star_table.json)."""
import json, os, subprocess, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import period_parts as PP
from pipeline import warehouse  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]; ST, SP, DAYS = args[0], args[1], args[2:]; UP = "--no-upload" not in sys.argv
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0); os.makedirs(f"{SP}/backer", exist_ok=True)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id); last_read = U.groupby("person_id").ft.max(); first_read = U.groupby("person_id").ft.min(); store_time = U.ft.max()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
lday = dict(zip(W.id, W.day)); U["lday"] = U.target_id.map(lday)
def ci(h, n):
    h, n = np.asarray(h, float), np.asarray(n, float)
    if n.sum() == 0: return [None, None, None]
    bs = [h[i].sum() / max(n[i].sum(), 1) for i in (rng.integers(0, len(h), len(h)) for _ in range(2000))]
    return [round(100 * h.sum() / n.sum(), 1), round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]
rows = []
for D in DAYS:
    raw = subprocess.run(["gsutil", "cat", f"{B}/tmp/e5/private/backer_pred/{D}.parquet"], capture_output=True).stdout
    lp = os.path.join(SP, "backer", f"_bp_{D}.parquet")
    if raw: open(lp, "wb").write(raw)
    elif os.path.exists(os.path.join(SP, "bp", f"backer_pred_{D}.parquet")): lp = os.path.join(SP, "bp", f"backer_pred_{D}.parquet")
    else: rows.append({"day": D, "status": "no frozen prediction"}); continue
    FR = pd.read_parquet(lp); close = PP.close_utc(D); lag_days = round((store_time - close).total_seconds() / 86400, 2)
    reread = set(last_read[last_read > close].index) & held
    held_at_freeze = set(first_read[first_read < close - pd.Timedelta(days=1)].index) & held   # held when the list was frozen (a read before 00:00 PT of D)
    obs_all = U[(U.lday == D) & U.person_id.isin(held)].groupby("target_id").person_id.agg(set).to_dict()
    obs = {k: v & held_at_freeze for k, v in obs_all.items()}
    n_new = sum(len(v - held_at_freeze) for v in obs_all.values())
    hist = U[(U.lday < D) & (U.lday >= (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")) & (U.ft < close - pd.Timedelta(days=1))]
    popular = hist.groupby("person_id").size().sort_values(ascending=False).index.tolist()
    H, Hb, N, n_in_scored = [], [], [], 0
    for lid, g in FR.groupby("launch_id"):
        o = obs.get(str(lid), set()) & reread; n = len(o)
        if n == 0: continue
        # only people re-read after the close can show a vote: rank within them (else unverifiable people fill the top N)
        gg = g[g.person_id.isin(reread)].sort_values("rank"); pop_r = [x for x in popular if x in reread]
        top = set(gg.person_id.iloc[:n]); H.append(len(top & o)); Hb.append(len(set(pop_r[:n]) & o)); N.append(n)
        n_in_scored += len(o & set(g.person_id))
    rows.append({"day": D, "status": "scored" if N else "no observed held backers", "store_read_until": str(store_time)[:16], "days_after_close": lag_days,
                 "launches_scored": len(N), "observed_held_backers": int(sum(N)), "observed backers first read after the freeze (excluded: could not be named)": int(n_new), "held_people_reread_after_close": len(reread),
                 "recall_at_N % [CI]": ci(H, N), "baseline most-active % [CI]": ci(Hb, N),
                 "share of observed backers inside our frozen top 2000": round(n_in_scored / max(sum(N), 1), 3),
                 "frozen_at": str(FR.frozen_at.iloc[0])[:16], "n_active_scored": int(FR.n_active.iloc[0])})
    print(json.dumps(rows[-1]))
# accumulate: keep earlier rows (other days / earlier store reads = the day-1 / 3 / 7 measurements), replace same (day, store read)
prev = json.loads(subprocess.run(["gsutil", "cat", f"{B}/results/web/backer_prediction.json"], capture_output=True, text=True).stdout or "{}").get("rows", [])
keyf = lambda r: (r.get("day"), r.get("store_read_until"))
rows = [r for r in prev if keyf(r) not in {keyf(x) for x in rows}] + rows
latest = {}
for r in sorted(rows, key=lambda r: str(r.get("store_read_until"))): latest[r["day"]] = r   # newest measurement per day for the headline
out = {"metric": "BACKER PREDICTION: of held people who actually voted for a launch, the share we named in advance (recall at N, N = observed held backers)",
       "how": __doc__.split("\n")[1:7], "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "rows": rows}
p = f"{SP}/backer/backer_score.json"; json.dump(out, open(p, "w"), indent=1, default=float)
sc = [r for r in latest.values() if r.get("status") == "scored"]
ns = []
if sc:
    h = sum(r["recall_at_N % [CI]"][0] * r["observed_held_backers"] for r in sc) / sum(r["observed_held_backers"] for r in sc)
    hb = sum(r["baseline most-active % [CI]"][0] * r["observed_held_backers"] for r in sc) / sum(r["observed_held_backers"] for r in sc)
    ns = [{"point": "0005", "model": "backer prediction (voter_harness pair model)", "method": f"replay with strict timing (reads before 00:00 PT), scored against held people's own upvote lists read up to {sc[0]['store_read_until']}",
           "metric": "recall at N (N = observed held backers per launch), pooled", "value": round(h, 1), "baseline_most_active": round(hb, 1),
           "n_days": len(sc), "n_backers": int(sum(r["observed_held_backers"] for r in sc)), "first_day": min(r["day"] for r in sc), "last_day": max(r["day"] for r in sc),
           "rule": "observed backers = people held before the freeze and re-read after the day closed whose own upvote list contains the launch; our list and the baseline are ranked within those re-read people; N = observed backers per launch", "source": "results/web/backer_prediction.json",
           "top3": None, "top5": None, "top10": None}]
json.dump({"computed_at": out["written_at"], "rows": ns}, open(f"{SP}/backer/north_star_rows_e5.json", "w"), indent=1)
if UP:
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/backer_prediction.json"], check=True)
    subprocess.run(["gsutil", "-q", "cp", f"{SP}/backer/north_star_rows_e5.json", f"{B}/results/web/north_star_rows_e5.json"], check=True)
print("north-star row:", json.dumps(ns))
