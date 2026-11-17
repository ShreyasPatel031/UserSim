"""Nightly forward backer-prediction audit (orchestrator Nov 17). For each of the last K closed days (default 4), score the frozen lists
(tmp/e5/private/backer_arms/<day>.parquet) with backer_forward_score.py on the current store, twice: all held people and complete people
(persons.complete, the population agent's current rule). Writes one aggregate file per day to raw/_audit/backer_prediction/<day>.json
(counts and rates only, no person ids) with the coverage diagnostics that decide whether the line is scorable.
  python backer_forward_nightly.py <store dir> <scratchpad> <D = today PT> [K] [--no-upload]"""
import io, json, os, subprocess, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
args = [a for a in sys.argv[1:] if not a.startswith("--")]; ST, SP, D = args[:3]; K = int(args[3]) if len(args) > 3 else 4; UP = "--no-upload" not in sys.argv
days = [(pd.Timestamp(D) - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(K, 0, -1)]; out_dir = f"{SP}/bkf/nightly"; os.makedirs(out_dir, exist_ok=True)
res = {}
for hf in ("all", "complete"):
    p = f"{out_dir}/score_{hf}.json"
    subprocess.run([sys.executable, f"{HERE}/backer_forward_score.py", ST, SP, *days, "--no-upload"], env=dict(os.environ, HELD_FILTER=hf, OUTJ=p), capture_output=True)
    res[hf] = json.load(open(p)) if os.path.exists(p) else {}
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "fetched_at"]); U = E[E.kind == "upvote"]; del E
last = U.assign(ft=pd.to_datetime(U.fetched_at, utc=True)).groupby("person_id").ft.max(); store_time = str(last.max())[:16]
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"] + (["complete_rule"] if "complete_rule" in pd.read_parquet(f"{ST}/persons.parquet").columns else []))
for d in days:
    close = pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC") + pd.Timedelta(days=1)
    raw = subprocess.run(["gsutil", "cat", f"{B}/tmp/e5/private/backer_arms/{d}.parquet"], capture_output=True).stdout
    L = set(pd.read_parquet(io.BytesIO(raw)).query("arm == 'CF-only'").person_id) if raw else set()
    o = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat()[:19] + "Z", "store_upvotes_read_until": store_time,
         "complete_rule": str(P.complete_rule.iloc[0]) if "complete_rule" in P else None, "complete_people": int(P.complete.sum()),
         "metric": "recall at N: of held people who voted for a launch (held before the freeze, re-read after the day closed), the share named in advance; N = observed backers; pooled; day bootstrap when pooled",
         "frozen_list_found": bool(raw), "listed_people_CF": len(L), "listed_people_reread_after_close": int((last.reindex(list(L)) > close).sum()) if L else 0,
         "held_people_reread_after_close": int((last > close).sum()), "scores": {}}
    for hf in ("all", "complete"):
        s = (res[hf].get("summary") or {}).get(d); row = next((r for r in res[hf].get("rows", []) if r.get("day") == d), {})
        o["scores"][hf + " held people"] = {"status": row.get("status"), **(s or {})}
    o["scorable_CF"] = o["listed_people_reread_after_close"] > 0
    if not o["scorable_CF"]: o["why_not_scorable"] = "none of the people on the frozen CF list was re-read after the day closed; only the raw most-active arm can be scored"
    p = f"{out_dir}/{d}.json"; json.dump(o, open(p, "w"), indent=1, default=float)
    if UP: subprocess.run(["gsutil", "-q", "cp", p, f"{B}/raw/_audit/backer_prediction/{d}.json"], check=False)
    print(d, o["listed_people_reread_after_close"], {k: (v.get("raw most-active"), v.get("CF-only")) for k, v in o["scores"].items()})
