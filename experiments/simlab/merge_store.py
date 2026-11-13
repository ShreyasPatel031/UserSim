"""Merged people store for the voter_harness re-run (orchestrator 05:38Z Nov 13). Inputs (local copies, usernames stay in scratch):
store_v3 (Nov 10), the 22,614 merged / replaced full pulls listed in raw/_cursor/audit_20261113T0453Z.tsv (people_live/vm/<handle>.json,
parsed with the population agent's own tools/population/full_pull.load_full, origin/claude/population-data), latest_complete.txt.
Rules: replaced people lose all their store_v3 rows from full pulls (source people_live*) and get the new pull's rows; merged people are
added. complete = store_v3 complete U latest_complete (as of the read) U merged / replaced. Output: events / persons / tabs parquet.
    python merge_store.py <store_v3 dir> <merge dir (data/people_live/vm, tools, audit tsv)> <salt dir> <latest_complete.txt> <out dir>
"""
import glob, json, os, sys
from multiprocessing import Pool
import pandas as pd
V3, MD, SALTD, LC, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); sys.path.insert(0, os.path.join(MD, "tools"))
import full_pull, store  # noqa: E402
IDS = store.Ids(open(os.path.join(SALTD, "salt")).read().strip())
def parse(fp):
    try: return full_pull.load_full(fp, IDS)
    except Exception as e: return ("ERR", type(e).__name__)
if __name__ == "__main__":
    au = pd.read_csv(glob.glob(os.path.join(MD, "audit_*.tsv"))[0], sep="\t", comment=None); au.columns = [c.lstrip("# ").strip() for c in au.columns]
    au = au[au.result.isin(["merge", "replace"])]; files = [os.path.join(MD, "data/people_live/vm", f"{n}.json") for n in au.name]
    with Pool(8) as p: R = p.map(parse, files, chunksize=50)
    bad = [r for r in R if isinstance(r[0], str)]; ok = [r for r in R if not (isinstance(r[0], str))]
    T = pd.concat([t for t, _ in ok if len(t)], ignore_index=True); E = pd.concat([e for _, e in ok if len(e)], ignore_index=True)
    E = E.sort_values("first_seen_at").drop_duplicates(["person_id", "kind", "target_id", "ts_lo"], keep="first")
    pulled = {IDS(n) for n in au.name}; newp = (set(T.person_id) & pulled) | (set(E.person_id) & pulled); rep = {IDS(n) for n in au[au.result == "replace"].name}
    T = T[T.person_id.isin(pulled)]   # tabs: pulled people only; events keep follower-tab edges of other people, as store_v3
    E3 = pd.read_parquet(os.path.join(V3, "events.parquet")); P3 = pd.read_parquet(os.path.join(V3, "persons.parquet")); T3 = pd.read_parquet(os.path.join(V3, "tabs.parquet"))
    drop = E3.person_id.isin(rep) & E3.source.astype(str).str.startswith("people_live")
    for c in ["ts_lo", "ts_hi", "first_seen_at", "fetched_at"]: E[c] = pd.to_datetime(E[c], utc=True)
    EV = pd.concat([E3[~drop], E[E3.columns.intersection(E.columns)]], ignore_index=True).drop_duplicates(["person_id", "kind", "target_id", "ts_lo", "source"])
    TB = pd.concat([T3[~T3.person_id.isin(newp)], T], ignore_index=True)
    lc = {IDS(l.split("\t")[0]) for l in open(LC) if l.strip()}
    old_c = set(P3[P3.complete].person_id); comp = old_c | lc | newp
    P = pd.DataFrame({"person_id": sorted(set(P3.person_id) | newp)}); P["in_pool"] = P.person_id.isin(set(P3[P3.in_pool].person_id)); P["complete"] = P.person_id.isin(comp)
    has_ev = set(EV[EV.source.astype(str).str.startswith("people_live")].person_id); P.loc[~P.person_id.isin(has_ev), "complete"] = False
    EV.to_parquet(os.path.join(OUT, "events.parquet"), index=False); P.to_parquet(os.path.join(OUT, "persons.parquet"), index=False); TB.to_parquet(os.path.join(OUT, "tabs.parquet"), index=False)
    rep_ = {"files": len(files), "parse_errors": len(bad), "parsed_people": len(newp), "replaced": len(rep & newp), "new_people": len(newp - set(P3.person_id)),
            "store_v3_complete": len(old_c), "latest_complete_ids": len(lc), "complete_after_merge": int(P.complete.sum()),
            "complete_dropped_no_full_pull_rows": int(len(comp) - P.complete.sum()), "events": len(EV), "upvotes": int((EV.kind == "upvote").sum()), "follows": int((EV.kind == "follows").sum())}
    json.dump(rep_, open(os.path.join(OUT, "merge_report.json"), "w"), indent=1); print(rep_)
