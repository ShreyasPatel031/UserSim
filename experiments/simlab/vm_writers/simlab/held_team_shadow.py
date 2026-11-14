"""Nightly forward shadow: arm 2 + held-team count (orchestrator 00:42Z Nov 14). Counts only; no handles written.
LIVE FEATURE, exactly as computed at 00:05 PT of launch day D:
  team      = the 00:05 read (raw/daily/D/today_0005.json): hunter (user.username) + named makers (redacted names dropped), hashed to person ids
  held      = person complete in the CURRENT store_v3 with pull_finished_utc < D 00:00 PT
  asof_any  = held team members with >= 1 event dated before D: an upvote on a launch dated < D (launch dates from the 2025 API lists +
              2026 warehouse) or a team role (hunter / named maker) on a launch dated < D
  route     = each counted member's entry route (request_provenance via persons.entry_route), logged
Shadow score = w0 z(pred_arm2) + w1 z(log1p asof_any) within D's line-up, weights FROZEN in reports/held_strict/frozen_weight.json
(full-fit backtest Apr-Oct, arm 2 + asof_any). pred_arm2 from raw/daily/D/forecast_D.parquet (published arm 2, from Nov 14).
Writes gs://.../tmp/e5/held_team_shadow/D.json (ids, scores, counts). Morning: score <day> scores D-1 vs official daily_rank and appends
reports/held_team_shadow/forward.jsonl (top 3/5/10 for arm 2 and shadow, coverage).
    python held_team_shadow.py predict <D> <scratchpad>  |  python held_team_shadow.py score <D> <scratchpad>
"""
import glob, hashlib, json, os, subprocess, sys
import numpy as np, pandas as pd
MODE, D, SP = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
OUTG = os.environ.get("HTS_OUT") or f"{B}/tmp/e5/held_team_shadow/{D}.json"; LOC = os.path.join(HERE, "reports", "held_team_shadow"); os.makedirs(LOC, exist_ok=True)
sys.path.insert(0, os.path.dirname(HERE)); from pipeline import warehouse as W
z = lambda s: (s - s.mean()) / (s.std() or 1)
def top(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
if MODE == "predict":
    SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
    gc = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
    LU = json.loads(gc(f"{B}/raw/daily/{D}/today_0005.json")); fc = os.path.join(SP, f"fc_{D}.parquet")
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{D}/forecast_{D}.parquet", fc]); F = pd.read_parquet(fc); F["id"] = F.id.astype(str)
    col = os.environ.get("HTS_COL") or ("pred_arm2" if "pred_arm2" in F and F.pred_arm2.notna().all() else None)
    if col is None: print(json.dumps({"day": D, "error": "no pred_arm2 in forecast parquet", "cols": F.columns.tolist()})); sys.exit(1)
    st = os.path.join(SP, "store_live"); os.makedirs(st, exist_ok=True)
    for f in ("persons.parquet", "events.parquet"): subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/population/store_v3/{f}", st])
    P = pd.read_parquet(f"{st}/persons.parquet", columns=["person_id", "complete", "pull_finished_utc", "entry_route"])
    d0 = pd.Timestamp(D).tz_localize("America/Los_Angeles").tz_convert("UTC")
    P = P[P.complete & (pd.to_datetime(P.pull_finished_utc, utc=True, errors="coerce") < d0)]; held = set(P.person_id); route = dict(zip(P.person_id, P.entry_route.fillna("unknown")))
    L = W.table("launches", do_sync=True); L["id"] = L.id.astype(str); lday = dict(zip(L.id, L.day)); roles = {}
    def mk(m):
        try: return [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
        except Exception: return []
    for p_, m_, d_ in zip(L.poster, L.makers, L.day):
        for h in ([p_] if isinstance(p_, str) and p_ and not p_.startswith("[") else []) + mk(m_): roles.setdefault(pid(h), []).append(d_)
    for f in sorted(glob.glob(f"{SP}/ph2025/*.json")):
        for p_ in json.load(open(f)):
            lday[str(p_["id"])] = os.path.basename(f)[:10]
            for u in [p_.get("user") or {}] + (p_.get("makers") or []):
                if u.get("username") and not str(u["username"]).startswith("["): roles.setdefault(pid(u["username"]), []).append(os.path.basename(f)[:10])
    team = {str(x["id"]): list(dict.fromkeys(pid(u["username"]) for u in [x.get("user") or {}] + (x.get("makers") or []) if u.get("username") and not str(u["username"]).startswith("["))) for x in LU}
    need = {p for t in team.values() for p in t} & held
    E = pd.read_parquet(f"{st}/events.parquet", columns=["person_id", "kind", "target_id"]); E = E[(E.kind == "upvote") & E.person_id.isin(need)]
    E["d"] = E.target_id.astype(str).map(lday); prior = set(E[E.d.notna() & (E.d < D)].person_id)
    prior |= {p for p in need if any(x < D for x in roles.get(p, []))}
    rows = []
    for i, t in team.items():
        cnt = [p for p in t if p in need and p in prior]
        rows.append({"id": i, "n_team": len(t), "n_held": sum(p in held for p in t), "asof_any": len(cnt), "routes": sorted(route.get(p, "unknown") for p in cnt)})
    X = pd.DataFrame(rows).merge(F[["id", col]], on="id", how="left"); X = X[X[col].notna()].copy()
    w = json.load(open(os.path.join(HERE, "reports", "held_strict", "frozen_weight.json")))["w"]
    X["shadow"] = w[0] * z(X[col]) + w[1] * z(np.log1p(X.asof_any))
    out = {"day": D, "made_at": pd.Timestamp.now(tz="UTC").isoformat(), "weights": w, "launches": len(X), "with asof_any > 0": int((X.asof_any > 0).sum()),
           "rows": X.rename(columns={col: "arm2"}).to_dict(orient="records")}
    p = os.path.join(SP, f"hts_{D}.json"); json.dump(out, open(p, "w"), default=float); subprocess.run(["gsutil", "-q", "cp", "-n", p, OUTG])
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))
else:
    O = json.loads(subprocess.run(["gsutil", "cat", OUTG], capture_output=True).stdout or b"{}")
    if not O: print(json.dumps({"day": D, "error": "no shadow file"})); sys.exit(0)
    L = W.table("launches", do_sync=True); L["id"] = L.id.astype(str); rk = dict(zip(L[L.day == D].id, L[L.day == D].daily_rank))
    X = pd.DataFrame(O["rows"]); X["rank"] = X.id.map(rk); X = X[X["rank"].notna()]
    if len(X) < 10: print(json.dumps({"day": D, "error": "final ranks not available", "n": len(X)})); sys.exit(0)
    t = X.sort_values("rank").id.tolist()
    rec = {"day": D, "n": len(X), "with asof_any > 0": int((X.asof_any > 0).sum()), "arm2 top3/5/10": top(X.sort_values("arm2", ascending=False).id.tolist(), t),
           "shadow top3/5/10": top(X.sort_values("shadow", ascending=False).id.tolist(), t)}
    with open(os.path.join(LOC, "forward.jsonl"), "a") as f: f.write(json.dumps(rec) + "\n")
    F = [json.loads(l) for l in open(os.path.join(LOC, "forward.jsonl"))]; dd = np.array([np.array(r["shadow top3/5/10"]) - np.array(r["arm2 top3/5/10"]) for r in F])
    print(json.dumps({"today": rec, "days to date": len(F), "mean shadow - arm2 top3/5/10": dd.mean(0).round(1).tolist()}))
