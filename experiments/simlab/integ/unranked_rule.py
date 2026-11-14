"""Is "will end the day unranked" knowable at the 03:45 read? (orchestrator 20:43Z Nov 14). Counts only; no usernames leave the scratchpad.
Population: launches in the stored recorder reads (Oct 31-Nov 13, <= 03:45 PT) and 00:05 line-ups (Oct 25-Nov 4, Nov 8-13); truth = first
warehouse part after the close (acc_recompute.truth). Fields checked: line-up featuredAt / createdAt / dailyRank / votesCount at 00:05; recorder
rank_now / votes (hidden) / comments per read and presence across reads; raw live capture posts_ts (fetch_status, launch_state, list_source,
daily_rank_at_fetch, homepage_position, badges, launchDayScore, latestScore, hide_votes_count) <= 03:45; raw comments_ts <= 03:45 (non-maker,
non-hunter comments, distinct commenters, commenter follower counts). Candidate rule R: >= 5 non-maker comments before 03:45 PT and
comments per distinct commenter >= 2.5.
    python unranked_rule.py <acc dir> <recorder dir> <line-up dir> <raw comments dir>   (prints the confusion table)"""
import glob, json, os, sys
import pandas as pd
ACC, REC, LU, RAW = sys.argv[1:5]
sys.argv = ["x", ACC, REC, "/dev/null"]; exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "acc_recompute.py")).read().split("# ---------------- track_record_v1")[0])
pop = set()
for f in glob.glob(f"{REC}/2026-*.jsonl"):
    d = os.path.basename(f)[:10]
    for l in open(f):
        r = json.loads(l)
        if pd.Timestamp(r["at"]).tz_convert("America/Los_Angeles") < pd.Timestamp(d + " 03:46", tz="America/Los_Angeles"): pop.add((d, str(r["launch_id"])))
for f in glob.glob(f"{LU}/*.json"):
    d = os.path.basename(f)[:10]; pop |= {(d, str(r["id"])) for r in json.load(open(f))}
unr = sorted((d, i) for d, i in pop if truth(d)[0] is not None and pd.isna(truth(d)[0].get(i)))
rows = []
for f in sorted(glob.glob(f"{RAW}/*_comments_ts.jsonl")):
    d = os.path.basename(f)[:10]; T, _ = truth(d)
    if T is None: continue
    C = pd.DataFrame([json.loads(l) for l in open(f) if l.strip()])
    if C.empty: continue
    C["launch_id"] = C.launch_id.astype(str); C["t"] = pd.to_datetime(C.created_at, utc=True, errors="coerce").dt.tz_convert("America/Los_Angeles")
    C = C[C.t < pd.Timestamp(d + " 03:45", tz="America/Los_Angeles")].drop_duplicates("comment_id")
    C = C[~C.is_maker.fillna(False).astype(bool) & ~C.is_hunter.fillna(False).astype(bool)]
    for i, g in C.groupby("launch_id"):
        if (d, i) in pop: rows.append({"day": d, "id": i, "ranked": bool(pd.notna(T.get(i))), "n": len(g), "uniq": g.commenter_user_id.nunique()})
O = pd.DataFrame(rows); O["flag"] = (O.n >= 5) & (O.n / O.uniq.clip(lower=1) >= 2.5)
have = set(zip(O.day, O.id)); days_with_comments = sorted(O.day.unique())
print(json.dumps({"population launch-days": len(pop), "unranked": [f"{d} {i[-4:]}" for d, i in unr],
                  "nights with raw comments": len(days_with_comments), "launch-days with early comments": len(O),
                  "rule R: unranked caught": int((O.flag & ~O.ranked).sum()), "unranked evaluable (comments present)": int((~O.ranked).sum()),
                  "rule R: ranked wrongly dropped": int((O.flag & O.ranked).sum()), "ranked evaluated": int(O.ranked.sum()),
                  "unranked not evaluable": [f"{d} {i[-4:]}" for d, i in unr if (d, i) not in have]}, indent=1))
