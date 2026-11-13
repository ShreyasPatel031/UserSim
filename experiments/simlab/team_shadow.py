"""Nightly shadow feature: the launch team's own community upvoting before launch (orchestrator 10:38Z Nov 13). SCRIPT ONLY - not
scheduled. Run on launch day D after the 00:05 read exists. No LLM, no Product Hunt requests.
Team = the hunter (user) + every maker named in the 00:05 read (today_0005.json; redacted members skipped). A member counts only if
COMPLETE in the store AND their upvotes tab was pulled before D 00:00 PT (tabs.fetched_at), so every counted upvote was cast before
the launch. An upvote's date = the acted-on launch's day (upvote rows carry no cast time).
Per launch (ids and counts only): team_up7 / team_up30 = upvotes the eligible members gave on launches dated in the 7 / 30 days before D;
team_makers30 = distinct first-named makers of those 30-day launches; *_lag2 variants keep only launches dated >= 2 days before D (for
members pulled after their launch, this drops the post-launch "vote back" window); n_team, n_team_complete, n_team_eligible,
covered (>= 1 eligible member), store path.
    python team_shadow.py <today_0005.json (path or gs://)> <YYYY-MM-DD> <store dir> <salt dir> <out .jsonl>
"""
import hashlib, json, os, subprocess, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
def load_json(p): return json.loads(subprocess.check_output(["gsutil", "cat", p]) if p.startswith("gs://") else open(p).read())
def features(lineup, day, store, salt_dir):
    from pipeline import warehouse
    salt = open(os.path.join(salt_dir, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
    D = pd.Timestamp(day); cut = D.tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
    W = warehouse.table("launches", do_sync=True); W["id"] = W.id.astype(str); W = W.sort_values("updated_at").drop_duplicates("id", keep="last")
    lday = dict(zip(W.id, pd.to_datetime(W.day)))
    def fm(m):
        try: ms = [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
        except Exception: ms = []
        return pid(ms[0]) if ms else None
    fmaker = dict(zip(W.id, [fm(m) for m in W.makers]))
    P = pd.read_parquet(os.path.join(store, "persons.parquet")); comp = set(P[P.complete].person_id)
    T = pd.read_parquet(os.path.join(store, "tabs.parquet")); T = T[(T.tab == "upvotes") & T.person_id.isin(comp)]
    pulled = dict(zip(T.person_id, pd.to_datetime(T.fetched_at, utc=True)))
    real = lambda u: bool(u.get("username")) and not str(u["username"]).startswith("[") and str(u.get("id")) != "0"
    team = {str(x["id"]): list(dict.fromkeys(pid(u["username"]) for u in [x.get("user") or {}] + (x.get("makers") or []) if real(u))) for x in lineup}
    elig = {m for ms in team.values() for m in ms if m in pulled and pulled[m] < cut}
    E = pd.read_parquet(os.path.join(store, "events.parquet"), columns=["person_id", "kind", "target_id"]); U = E[(E.kind == "upvote") & E.person_id.isin(elig)].copy()
    U["target_id"] = U.target_id.astype(str); U = U.drop_duplicates(["person_id", "target_id"]); U["d"] = U.target_id.map(lday); U = U[U.d.notna() & (U.d < D) & (U.d >= D - pd.Timedelta(days=30))]
    G = {p: g for p, g in U.groupby("person_id")}; out = []
    for lid, ms in team.items():
        em = [m for m in ms if m in elig]; o = {"launch_id": lid, "day": day, "n_team": len(ms), "n_team_complete": sum(m in comp for m in ms), "n_team_eligible": len(em), "covered": bool(em)}
        for suf, lag in (("", 1), ("_lag2", 2)):
            rows = pd.concat([G[m] for m in em if m in G]) if any(m in G for m in em) else pd.DataFrame(columns=["d", "target_id"])
            r = rows[rows.d <= D - pd.Timedelta(days=lag)] if len(rows) else rows
            o[f"team_up7{suf}"] = int((r.d >= D - pd.Timedelta(days=7)).sum()) if len(r) else 0; o[f"team_up30{suf}"] = int(len(r))
            o[f"team_makers30{suf}"] = len({fmaker.get(t) for t in r.target_id} - {None}) if len(r) else 0
        o["store"] = os.path.abspath(store); out.append(o)
    return out
if __name__ == "__main__":
    lp, day, store, saltd, outp = sys.argv[1:6]; rows = features(load_json(lp), day, store, saltd)
    with open(outp, "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    print("wrote", len(rows), "launches; covered", sum(r["covered"] for r in rows))
