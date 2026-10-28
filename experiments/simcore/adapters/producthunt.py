"""Product Hunt adapter: turns the per-person scores from simlab/popscore.py (person model retrained each month on the
previous month, no popularity input) into simcore Contexts, one per launch day, and exports simcore's per-launch
outputs as launch-model inputs:
  sc_   all channels (dated past backing + undated follow lists)      scd_  dated channels only
Scoring uses the launch harness (daily / weekly / monthly lists).
usage: python -m simcore.adapters.producthunt check   (reproduce simbench's simulation-only numbers)
       python -m simcore.adapters.producthunt export  -> ph_predict/data/{sc,scd}_features.json"""
import bisect, json, os, sys
from collections import Counter, defaultdict
import numpy as np, pandas as pd
from simcore import Context, simulate, exposure

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))
ROWS = os.path.join(EXP, "simlab", "cache", "popscore", "rows")
RAW = os.path.join(EXP, "ph_predict", "data")
SEG_FIELDS = {"role": ["founder_exec", "engineer", "marketing_growth", "investor", "designer", "product", "creator"],
              "seniority": ["founder_c_level", "senior_lead"],
              "company_type": ["own_startup", "big_tech", "enterprise", "agency_consulting"],
              "tech_level": ["builds_software", "non_technical"],
              "buyer_type": ["enterprise_buyer", "team_lead_buyer", "developer_adopter", "individual_prosumer"]}
SETTINGS = dict(slots=4, tau=25.0, v0=0.5, beta=1.0)   # fitted on Apr-Jun in simlab/simbench.py


def contexts():
    for f in sorted(os.listdir(ROWS)):
        D = pd.read_parquet(f"{ROWS}/{f}")
        ppl = {u: k for k, u in enumerate(D.person.unique())}; items = list(D.id.unique()); ix = {x: k for k, x in enumerate(items)}
        r, c = D.person.map(ppl).values, D.id.map(ix).values
        P = np.zeros((len(ppl), len(items)), np.float32); P[r, c] = D.p.values
        T = {k: np.zeros_like(P) for k in ("backed", "follow")}
        T["backed"][r, c] = D.backed.values > 0; T["follow"][r, c] = D.follow.values > 0
        w = np.zeros(len(ppl), np.float32); w[r] = D.w.values
        yield Context(f[:10], items, w, P, T)


def check():
    sys.path.insert(0, EXP)
    from simlab import harness as H
    B = H.baseline().drop_duplicates("id")
    sim = {}
    for ctx in contexts():
        sim.update(simulate(ctx, **SETTINGS))
    T = B[B.mon.isin(["2026-07", "2026-08", "2026-09", "2026-10"])].copy(); T["sim"] = T.id.map(sim); T = T.dropna(subset=["sim"])
    print({f"day@{k}": round(100 * H.recall(T, "sim", k=k), 1) for k in H.KS})


def audiences():
    """Per launch, the whole population's audience by tie channel (active or not), dated before the launch except
    follows: team followers, hunter followers, past backers of the team, loyal fans (followers who backed before),
    people the team supported (team commented on their launches), and how many of those already returned the favour."""
    sys.path.insert(0, EXP)
    from simlab import store
    P, I, E = store.load()
    day = dict(zip(I.id, I.day)); poster = dict(zip(I.id, I.poster))
    team = {r.id: (set(json.loads(r.makers)) | {r.poster}) - {None} for r in I.itertuples()}
    fol = defaultdict(set)
    for u, f in zip(P.person, P.follows):
        for m in (json.loads(f) if isinstance(f, str) else []):
            fol[m].add(u)
    built = defaultdict(list)
    for it, t in team.items():
        for m in t:
            built[m].append(it)
    ev = E[E.item.isin(day)]
    backers = ev.groupby("item").person.apply(set).to_dict()
    com = ev[ev.kind == "comment"]
    acts = com.groupby("person").date.apply(sorted).to_dict()      # dated comment activity per person
    makers = {r.id: [m for m in json.loads(r.makers) if m != r.poster] for r in I.itertuples()}
    commented = com.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    seg = {u: json.loads(v) for u, v in zip(P.person, P.seg) if isinstance(v, str)}
    # comment events by launch (person, date), people active in the 30 days before each day, heavy commenters per day
    cby = com.groupby("item").apply(lambda g: list(zip(g.date, g.person)), include_groups=False).to_dict()
    days = sorted(set(day.values()))
    cdates = com.groupby("date").person.apply(set).to_dict()
    active30, heavy = {}, {}
    cnt = Counter(); seen_days = sorted(cdates)
    k = 0
    for dd in days:
        while k < len(seen_days) and seen_days[k] < dd:
            for u in cdates[seen_days[k]]:
                cnt[u] += 1
            k += 1
        d30 = (pd.Timestamp(dd) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        active30[dd] = set().union(*(cdates[x] for x in seen_days[bisect.bisect_left(seen_days, d30):k])) if k else set()
        cut = np.quantile(list(cnt.values()), 0.9) if cnt else 1
        heavy[dd] = {u for u, c in cnt.items() if c > cut}
    Z = np.load(f"{RAW}/emb.npz"); li = {x: j for j, x in enumerate(Z["launch_ids"])}; EM = Z["launch"]
    EM = EM / (np.linalg.norm(EM, axis=1, keepdims=True) + 1e-9)
    order = sorted(day, key=lambda x: day[x]); have = [x for x in order if x in li]
    H_ = EM[[li[x] for x in have]]; hday = np.array([day[x] for x in have])
    team_comments = {m: sorted(v) for m, v in commented.items()}
    out = {}
    for x, t in team.items():
        d = day[x]
        F = set().union(*(fol.get(m, set()) for m in t)) if t else set()
        B = set().union(*(backers.get(it, set()) for m in t for it in built[m] if day[it] < d)) - t
        R = set().union(*(team.get(it, set()) for m in t for dt, it in commented.get(m, []) if dt < d)) - t
        mf = [len(fol.get(m, ())) for m in makers[x]]
        d30 = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        active = sum(1 for u in F if bisect.bisect_left(acts.get(u, []), d) - bisect.bisect_left(acts.get(u, []), d30) > 0)
        row = {"aud_follow": len(F), "aud_follow_hunter": len(fol.get(poster[x], ())), "aud_follow_makers": sum(mf),
               "aud_follow_maker_max": max(mf, default=0), "aud_follow_active30": active, "aud_backed": len(B),
               "aud_loyal": len(F & B), "aud_supported": len(R), "aud_returned": len(R & B)}
        commenters = lambda it: {u for dt, u in cby.get(it, []) if dt < d}
        pre = [(dt, u) for dt, u in cby.get(x, []) if dt < d]                         # upcoming-page comments
        comm = set().union(*(commenters(it) for m in t for it in built[m] if day[it] < d)) - t if t else set()
        comps = []
        if x in li:
            sims = H_ @ EM[li[x]]; sims[hday >= d] = -9
            comps = [have[j] for j in np.argsort(-sims)[:10] if sims[j] > -9]
        cu = set().union(*(commenters(it) for it in comps)) - t if comps else set()
        A30, HV = active30.get(d, set()), heavy.get(d, set())
        tc = [(dt, it) for m in t for dt, it in team_comments.get(m, []) if dt < d and it not in team.get(x, ())]
        win = lambda n: (pd.Timestamp(d) - pd.Timedelta(days=n)).strftime("%Y-%m-%d")
        row.update({"aud_pre_comments": len(pre), "aud_pre_users": len({u for _, u in pre}),
                    "aud_comm": len(comm), "aud_comm_active30": len(comm & A30),
                    "aud_comp": len(cu), "aud_comp_active30": len(cu & A30), "aud_comp_overlap": len(cu & comm),
                    "aud_comp_heavy": len(cu & HV),
                    "team_c7": sum(dt >= win(7) for dt, _ in tc), "team_c30": sum(dt >= win(30) for dt, _ in tc),
                    "team_c90": sum(dt >= win(90) for dt, _ in tc), "team_launches90": len({it for dt, it in tc if dt >= win(90)}),
                    "team_days30": len({dt for dt, _ in tc if dt >= win(30)})})
        S = [seg[u] for u in F if u in seg]          # what kinds of people the followers are
        for f, vals in SEG_FIELDS.items():
            c = Counter(z.get(f) for z in S)
            for v in vals:
                row[f"aud_seg_{f}_{v}"] = c[v]
                row[f"share_seg_{f}_{v}"] = c[v] / len(S) if S else -1.0
        row["aud_seg_n"] = len(S)
        row["share_seg_us"] = sum("united states" in str(z.get("country", "")).lower() for z in S) / len(S) if S else -1.0
        row["share_comp_overlap"] = len(cu & comm) / len(cu) if cu else -1.0
        out[str(x)] = row
    return out


def export():
    aud = audiences()
    sc, scd = {}, {}
    for ctx in contexts():
        v_all = simulate(ctx, **SETTINGS, channels=("backed", "follow")); v_dat = simulate(ctx, **SETTINGS, channels=("backed",))
        e_all = exposure(ctx, ("backed", "follow")); tot_a, tot_d = sum(v_all.values()) or 1, sum(v_dat.values()) or 1
        for x in ctx.items:
            e = e_all[x]
            a = aud.get(str(x), {})
            sc[str(x)] = {"sc_votes": v_all[x], "sc_share": v_all[x] / tot_a, **{f"sc_{k}": v for k, v in e.items()},
                          **{f"sc_{k}": float(v if k.startswith("share") else np.log1p(v)) for k, v in a.items()}}
            scd[str(x)] = {"scd_votes": v_dat[x], "scd_share": v_dat[x] / tot_d,
                           **{f"scd_{k}": v for k, v in e.items() if "follow" not in k},
                           **{f"scd_{k}": float(np.log1p(v)) for k, v in a.items() if "follow" not in k and k != "aud_loyal" and "seg" not in k and not k.startswith("share")}}
    for x, a in aud.items():   # audiences need no person model: every launch gets them, simulated votes only Apr-Oct
        sc.setdefault(x, {f"sc_{k}": float(v if k.startswith("share") else np.log1p(v)) for k, v in a.items()})
        scd.setdefault(x, {f"scd_{k}": float(np.log1p(v)) for k, v in a.items() if "follow" not in k and k != "aud_loyal" and "seg" not in k and not k.startswith("share")})
    json.dump(sc, open(f"{RAW}/sc_features.json", "w")); json.dump(scd, open(f"{RAW}/scd_features.json", "w"))
    print("exported", len(sc), "launches;", list(next(iter(sc.values()))), list(next(iter(scd.values()))))


if __name__ == "__main__":
    check() if sys.argv[1] == "check" else export()
