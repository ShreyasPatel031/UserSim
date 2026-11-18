"""T4 (orchestrator Nov 11): is the browsers' shared preference intrinsic appeal or herding after the reveal?
PH shows the homepage in random order with vote counts hidden for ~4 h after featuring; then counts show and the list is
ranked. Data: raw/ph_at_launch/<d>/live/posts_ts.jsonl, 15-min snapshots, votes_at_fetch (the API returns real counts
even while hidden) and the derived hide_votes_count flag. Days with near-full trajectories.
(a) Leaders at time t = top 3 by cumulative votes at t. Share of the NEXT 2 h of vote increments going to those leaders,
    for t = 1, 2, 3, 4, 5, 6, 8, 10, 12 h, against their share of cumulative votes at t and the top-3 share of the
    line-up. A jump at t = 4 h (the reveal) over the hidden-window values = herding.
(b) Concentration of each hour's increments: top-3 share and Gini, per hour of day.
(c) Hidden-window behaviour: does votes_at_fetch grow while hide_votes_count is true (sanity of the pre-reveal data)?
usage: CASCADE_DIR=<dir with posts_*.jsonl> python t4_reveal.py -> results/t4_reveal.json"""
import glob, json, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); CD = os.environ["CASCADE_DIR"]


def gini(x):
    x = np.sort(np.clip(np.asarray(x, float), 0, None)); n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1) @ x / (n * x.sum())) if x.sum() > 0 else np.nan


def main():
    rows = []
    for f in sorted(glob.glob(f"{CD}/posts_*.jsonl")):
        for l in open(f):
            r = json.loads(l)
            if r.get("fetch_status") == 200:
                rows.append((r["day"], str(r["launch_id"]), r["snapshot_ts"], r.get("votes_at_fetch"), r.get("hide_votes_count"), r.get("featured_at")))
    T = pd.DataFrame(rows, columns=["day", "id", "ts", "votes", "hidden", "featured_at"])
    T["ts"] = pd.to_datetime(T.ts, utc=True)
    T["h"] = (T.ts.dt.tz_convert("America/Los_Angeles") - pd.to_datetime(T.day).dt.tz_localize("America/Los_Angeles")).dt.total_seconds() / 3600
    T = T[(T.h >= 0) & (T.h <= 24)]
    res = {"days": [], "a": {}, "b": {}, "c": {}}
    A, Bh, C = [], [], []
    for d, g in T.groupby("day"):
        if g.ts.nunique() < 40 or g.h.max() < 16:
            continue
        res["days"].append(d)
        V = g.pivot_table(index="h", columns="id", values="votes", aggfunc="max").sort_index().ffill().fillna(0)
        H = g.pivot_table(index="h", columns="id", values="hidden", aggfunc="first").sort_index()
        hrs = V.index.values
        def at(t):
            j = np.searchsorted(hrs, t, side="right") - 1
            return V.iloc[max(j, 0)]
        n = V.shape[1]
        for t in (1, 2, 3, 4, 5, 6, 8, 10, 12):
            v0, v1 = at(t), at(t + 2); inc = (v1 - v0).clip(lower=0)
            lead = v0.nlargest(3).index
            A.append({"day": d, "t": t, "lead_share_next2h": float(inc[lead].sum() / max(1, inc.sum())),
                      "lead_share_cum": float(v0[lead].sum() / max(1, v0.sum())), "lineup_share": 3 / n,
                      "hidden_frac_at_t": float(H.iloc[max(np.searchsorted(hrs, t, side="right") - 1, 0)].astype(float).mean())})
        for hh in range(0, 20):
            inc = (at(hh + 1) - at(hh)).clip(lower=0)
            if inc.sum() > 0:
                Bh.append({"day": d, "hour": hh, "top3_share": float(inc.nlargest(3).sum() / inc.sum()), "gini": gini(inc.values), "votes": float(inc.sum())})
        hid = g[g.hidden == True]   # noqa: E712
        C.append({"day": d, "hidden_rows": int(len(hid)), "hidden_max_h": float(hid.h.max()) if len(hid) else None,
                  "votes_at_4h_share_of_final": float(at(4).sum() / max(1, V.iloc[-1].sum())),
                  "grows_while_hidden": bool(len(hid) and hid.groupby("id").votes.max().sum() > 0)})
    A, Bh = pd.DataFrame(A), pd.DataFrame(Bh)
    res["a"] = {str(t): {"lead_share_next2h": round(float(g.lead_share_next2h.mean()), 3), "lead_share_cum": round(float(g.lead_share_cum.mean()), 3),
                         "lineup_share": round(float(g.lineup_share.mean()), 3), "hidden_frac_at_t": round(float(g.hidden_frac_at_t.mean()), 2),
                         "per_day_next2h": [round(x, 3) for x in g.lead_share_next2h]} for t, g in A.groupby("t")}
    res["b"] = {str(h): {"top3_share": round(float(g.top3_share.mean()), 3), "gini": round(float(g.gini.mean()), 3), "votes_per_day": round(float(g.votes.mean()), 1)}
                for h, g in Bh.groupby("hour")}
    res["c"] = C
    json.dump(res, open(os.path.join(HERE, "results", "t4_reveal.json"), "w"), indent=1)
    print("days", res["days"])
    print("t  lead_next2h  lead_cum  lineup  hidden_frac")
    for t, v in res["a"].items():
        print(t, v["lead_share_next2h"], v["lead_share_cum"], v["lineup_share"], v["hidden_frac_at_t"], v["per_day_next2h"])
    print("hour top3_share gini votes"); [print(h, v["top3_share"], v["gini"], v["votes_per_day"]) for h, v in res["b"].items()]
    print(json.dumps(C))


if __name__ == "__main__":
    main()
