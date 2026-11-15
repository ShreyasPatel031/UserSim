"""ph_discounted_likely: people whose upvotes Product Hunt likely discounts (orchestrator 00:51Z Nov 15). Never deletes anyone: a flag column.
Over-count launch = held upvoters (people in the store whose own upvote list contains the launch) > displayed votes (warehouse, final).
Person features: n_oc = number of over-count launches the person upvoted (LEAVE-ONE-OUT when evaluating a launch), n30 = upvotes on launches of
the 30 days before the person's last read, account age (days at last read; from persons.joined). Candidate rules:
  oc>=k (k = 3, 5, 8) alone; and with young account (< 365 days) or heavy (n30 >= the held population's 80th percentile).
Validation (per candidate):
  recall    = sum over over-count launches of min(flagged held voters, excess) / sum of excess   (flags leave-one-out: the launch's own
              upvotes are not counted in n_oc)
  base_rate = share of held voters flagged on launches at or below their count (flagged people should rarely be needed there)
  needed    = share of at-or-below-count launches that are still at or below the count WITHOUT their flagged voters (always 1 by
              construction; reported as the share whose margin to the count is < flagged voters, i.e. where the flag would matter)
Dated variant for forward use: flag_for_day(D) uses only over-count launches dated before D-1 and reads fetched before 00:00 PT of D.
    python ring_flag.py <store dir> <scratchpad> [--upload]   -> <SP>/ring/ring_flag.json (+ flags parquet, person ids only, PRIVATE)"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pipeline import warehouse  # noqa: E402
ST, SP = sys.argv[1:3]; UP = "--upload" in sys.argv; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; os.makedirs(f"{SP}/ring", exist_ok=True)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str)
W["day"] = W.day.astype(str).str[:10]; W["votes"] = pd.to_numeric(W.votes, errors="coerce")
U["lday"] = U.target_id.map(dict(zip(W.id, W.day))); U = U[U.lday.notna()]
PJ = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "joined"]).drop_duplicates("person_id")
held = U.groupby("target_id").person_id.nunique(); shown = W.set_index("id").votes.reindex(held.index)
L = pd.DataFrame({"held": held, "shown": shown}).dropna(); L["excess"] = (L.held - L.shown).clip(lower=0); OC = set(L[L.excess > 0].index)
voters = U.groupby("target_id").person_id.agg(set).to_dict()
n_oc = U[U.target_id.isin(OC)].groupby("person_id").target_id.nunique()
last = U.groupby("person_id").ft.max(); lastday = last.dt.strftime("%Y-%m-%d")
up_day = U.assign(ld=U.person_id.map(lastday)); up_day = up_day[(pd.to_datetime(up_day.lday) >= pd.to_datetime(up_day.ld) - pd.Timedelta(days=30))]
n30 = up_day.groupby("person_id").size(); heavy_cut = float(n30.quantile(0.8))
jt = pd.to_datetime(PJ.set_index("person_id").joined, utc=True, errors="coerce")
age = (last - jt.reindex(last.index)).dt.days
n_all = U.groupby("person_id").target_id.nunique()
cands = {}
for k, sh in ((5, 0.10), (5, 0.20), (5, 0.30), (3, 0.30), (8, 0.20)):   # concentration: share of the person's upvoted launches that are over-count
    cands[f"oc>={k} & oc share>={sh}"] = lambda p, noc, k=k, sh=sh: noc >= k and noc / max(n_all.get(p, 1) - (0 if noc == n_oc.get(p, 0) else 1), 1) >= sh
for k in (5,):
    cands[f"oc>={k}"] = lambda p, noc, k=k: noc >= k
    cands[f"oc>={k} & young(<365d)"] = lambda p, noc, k=k: noc >= k and (age.get(p, np.nan) < 365)
    cands[f"oc>={k} & heavy"] = lambda p, noc, k=k: noc >= k and n30.get(p, 0) >= heavy_cut
res = {"over_count_launches": len(OC), "launches_with_held_and_shown": int(len(L)), "excess_total": int(L.excess.sum()),
       "heavy cut (upvotes in 30 days)": heavy_cut, "candidates": {}}
for nm, f in cands.items():
    expl, flagged_on_oc, held_on_oc = 0, 0, 0
    for l in OC:   # leave-one-out: the launch itself does not count towards n_oc
        vs = voters.get(l, set()); fl = [p for p in vs if f(p, n_oc.get(p, 0) - 1)]
        expl += min(len(fl), L.excess[l]); flagged_on_oc += len(fl); held_on_oc += len(vs)
    under = [l for l in L.index if l not in OC]; fu, hu, matter = 0, 0, 0
    for l in under:
        vs = voters.get(l, set()); fl = sum(1 for p in vs if f(p, n_oc.get(p, 0))); fu += fl; hu += len(vs)
        if L.shown[l] - L.held[l] < fl: matter += 1
    res["candidates"][nm] = {"recall of over-count excess %": round(100 * expl / max(L.excess.sum(), 1), 1),
                             "flagged share of held voters on over-count launches %": round(100 * flagged_on_oc / max(held_on_oc, 1), 1),
                             "flagged share of held voters on at-or-below-count launches %": round(100 * fu / max(hu, 1), 1),
                             "people flagged": int(sum(1 for p in n_oc.index if f(p, n_oc[p])))}
    print(nm, json.dumps(res["candidates"][nm]), flush=True)
json.dump(res, open(f"{SP}/ring/ring_flag.json", "w"), indent=1, default=float)
