"""Per launch, expected voters by data-driven group (orchestrator 03:30Z Nov 15, Shreyas's dynamic-groups spec, item 2).
For day D: the frozen CF-only list (top 2000 held people per launch, logistic p; reads before 00:00 PT of D) is
  1. recalibrated with an isotonic reliability curve fit on earlier scored days (observed voter = held before the freeze AND re-read after
     close AND the launch is in their upvote list; only people re-read after close count, as in backer_arms_score.py),
  2. scaled by a tail factor c = observed voters / summed calibrated p on those days (voters outside the 2000-person list),
  3. summed by group: expected_voters_tracked (people we hold), share, base share (group's share of held upvotes in the 30 days before D),
     lift = share / base, and expected_votes_on_ph = tracked x coverage factor (displayed votes per tracked voter on the history days).
History days are those < D-1 that the store can score. Validation (leave-one-day-out over history days): per (launch, group) predicted vs
observed counts (slope, correlation) and the mean total-variation distance of predicted vs observed group mix against the base mix.
    python expected_voters.py <store dir> <scratchpad> <D> [--history 2026-11-08,...] [--no-upload]   -> merges who.groups_expected into the explain file"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import period_parts as PP, segments_lib
from pipeline import warehouse  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]; ST, SP, D = args[:3]; UP = "--no-upload" not in sys.argv
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p, b=False: subprocess.run(["gsutil", "cat", p], capture_output=True, text=not b).stdout
GRP, PROF, SEGCUT = segments_lib.load_groups(SP)
_lab, _ = segments_lib.load(SP); SUBU = {p_: l for p_, l in _lab.items() if l != segments_lib.INACTIVE}   # person -> "group / subgroup" (finer validation unit)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id)
last_read = U.groupby("person_id").ft.max(); first_read = U.groupby("person_id").ft.min()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["votes"] = pd.to_numeric(W.votes, errors="coerce"); U["lday"] = U.target_id.map(dict(zip(W.id, W.day))); shown = dict(zip(W.id, W.votes))


def arms(day):
    lp = os.path.join(SP, "bp", f"backer_arms_{day}.parquet")
    if not os.path.exists(lp):
        raw = gcat(f"{B}/tmp/e5/private/backer_arms/{day}.parquet", True)
        if not raw: return None
        lp = os.path.join(SP, "bp", f"_arms_{day}.parquet"); open(lp, "wb").write(raw)
    F = pd.read_parquet(lp); return F[F.arm == "CF-only"][["launch_id", "person_id", "p"]].assign(launch_id=lambda x: x.launch_id.astype(str))


def history_rows(day):   # per listed re-read person: p, y; plus per-launch observed voters and coverage
    F = arms(day)
    if F is None: return None
    close = PP.close_utc(day); st = close - pd.Timedelta(days=1)
    reread = set(last_read[last_read > close].index) & held; hf = set(first_read[first_read < st].index) & held; ok = reread & hf
    if not ok: return None
    obs = U[(U.lday == day) & U.person_id.isin(ok)].groupby("target_id").person_id.agg(set).to_dict()
    F = F[F.person_id.isin(ok)].copy()
    if F.empty: return None   # no listed person was re-read after this day's close yet: not scorable
    F["y"] = [p_ in obs.get(l, ()) for l, p_ in zip(F.launch_id, F.person_id)]
    L = pd.DataFrame({"launch_id": list(F.launch_id.unique())}); L["obs"] = L.launch_id.map(lambda l: len(obs.get(l, ()))); L["shown"] = L.launch_id.map(shown)
    L["reread_share"] = len(ok) / max(1, len(hf)); L["day"] = day
    ov = {l: obs.get(l, set()) for l in L.launch_id}
    return F.assign(day=day), L, ov


hist_days = [x for x in (sys.argv[sys.argv.index("--history") + 1].split(",") if "--history" in sys.argv else
                         [str(d)[:10] for d in pd.date_range("2026-11-08", pd.Timestamp(D) - pd.Timedelta(days=2))]) if x < D]
H = {d: history_rows(d) for d in hist_days}; H = {d: v for d, v in H.items() if v is not None}
if not H: sys.exit("no scorable history days")
FH = pd.concat([v[0] for v in H.values()]); LH = pd.concat([v[1] for v in H.values()]); OV = {(d, l): s for d, v in H.items() for l, s in v[2].items()}


def fit(days):
    f = FH[FH.day.isin(days)]; iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(f.p, f.y)
    l = LH[LH.day.isin(days)]; c = l.obs.sum() / max(1e-9, iso.predict(f.p).sum())
    cov = l[l.obs > 0]; k_cov = float((cov.shown / (cov.obs / cov.reread_share)).median())
    return iso, float(c), k_cov


def base_share(day, M=None):
    d30 = (pd.Timestamp(day) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); st = PP.close_utc(day) - pd.Timedelta(days=1)
    b = U[(U.lday < day) & (U.lday >= d30) & (U.ft < st)].person_id.map(M or GRP).dropna().value_counts(normalize=True)
    return b


def group_table(F, iso, c, k_cov, bshare, M=None):
    F = F.assign(g=F.person_id.map(M or GRP)).dropna(subset=["g"])
    if F.empty: return {}
    F["pc"] = iso.predict(F.p) * c
    out = {}
    for lid, f in F.groupby("launch_id"):
        e = f.groupby(f.g).pc.sum(); tot = e.sum()
        out[lid] = {"tracked_total": float(tot), "groups": {g: float(v) for g, v in e.items()}}
    return out


# ---------- validation: leave one history day out (groups, and subgroups as a finer check)
def validate(UNIT):
    global GRP
    keep = GRP; GRP = UNIT; r = _validate(); GRP = keep; return r
def _validate():
  val, tv_m, tv_b = [], [], []
  for d in H:
      others = [x for x in H if x != d]
      if not others: continue
      iso, c, k_cov = fit(others); bs = base_share(d); F = FH[FH.day == d]
      T = group_table(F, iso, c, k_cov, bs)
      for lid, t in T.items():
          o = OV.get((d, lid), set()); og = pd.Series([GRP.get(p_) for p_ in o], dtype=object).dropna().value_counts()
          for g in set(t["groups"]) | set(og.index): val.append({"day": d, "launch": lid, "g": g, "pred": t["groups"].get(g, 0.0), "obs": float(og.get(g, 0))})
          if og.sum() >= 10:
              pm = pd.Series(t["groups"]); pm = pm / pm.sum(); om = og / og.sum(); bb = bs.reindex(om.index.union(pm.index)).fillna(0)
              idx = pm.index.union(om.index); tv_m.append(0.5 * np.abs(pm.reindex(idx).fillna(0) - om.reindex(idx).fillna(0)).sum())
              tv_b.append(0.5 * np.abs(bb.reindex(idx).fillna(0) / max(1e-9, bb.sum()) - om.reindex(idx).fillna(0)).sum())
  V = pd.DataFrame(val); tv_m, tv_b = np.array(tv_m), np.array(tv_b)
  bsci = lambda v: [round(float(v.mean()), 3)] + [round(float(np.percentile([v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)], q)), 3) for q in (2.5, 97.5)] if len(v) else None
  VAL = {"history_days": list(H), "launch_group_cells": int(len(V)),
         "count calibration: slope of observed on predicted (1 = calibrated)": round(float(np.polyfit(V.pred, V.obs, 1)[0]), 3) if len(V) > 2 else None,
         "count correlation": round(float(np.corrcoef(V.pred, V.obs)[0, 1]), 3) if len(V) > 2 else None,
         "observed / predicted total": round(float(V.obs.sum() / max(1e-9, V.pred.sum())), 3) if len(V) else None,
         "group-mix total variation (launches with >= 10 observed voters) [mean, 95% launch bootstrap]": {"expected-voters model": bsci(tv_m), "base mix": bsci(tv_b), "model minus base (paired)": bsci(tv_m - tv_b)}}
  return VAL
VAL = validate(GRP); VAL_SUB = validate(SUBU)
VAL["subgroup-level check"] = {k: v for k, v in VAL_SUB.items() if k != "history_days"}
print(json.dumps(VAL), flush=True)

# ---------- day D
iso, c, k_cov = fit(list(H)); bs = base_share(D); FD = arms(D)
if FD is None: sys.exit(f"no frozen CF list for {D}")
FD = FD[FD.person_id.isin(held)]; T = group_table(FD, iso, c, k_cov, bs)
LABEL = (f"Expected voters by group: the CF-only voter model's per-person probabilities (people we track; reads before 00:00 PT), recalibrated "
         f"on {len(H)} earlier scored days (isotonic reliability curve; tail factor {c:.2f} for voters outside each 2,000-person list), summed by "
         f"data-driven group (segments cut {SEGCUT}). 'Expected votes on PH' multiplies by {k_cov:.1f} displayed votes per tracked voter (history median; approximate). "
         f"Leave-one-day-out check: observed/predicted {VAL['observed / predicted total']}, group-count correlation {VAL['count correlation']}; "
         f"group mix vs base mix {VAL['group-mix total variation (launches with >= 10 observed voters) [mean, 95% launch bootstrap]']['model minus base (paired)']} (negative = better than base).")
out = {}
for lid, t in T.items():
    tot = t["tracked_total"]; rows = []
    for g, v in sorted(t["groups"].items(), key=lambda x: -x[1]):
        sh = v / tot if tot else 0; b = float(bs.get(g, np.nan))
        rows.append({"group_id": g, "group": (PROF.get(g) or {}).get("name"), "expected_voters_tracked": round(v, 2), "share": round(sh, 3),
                     "base_share": round(b, 3) if b == b else None, "lift": round(sh / b, 2) if b and b == b else None, "expected_votes_on_ph": round(v * k_cov, 1),
                     "group_size": (PROF.get(g) or {}).get("n_people")})
    out[lid] = {"expected_voters_tracked": round(tot, 1), "expected_votes_on_ph": round(tot * k_cov, 0), "groups": rows,
                "panel_groups (share >= 5% or >= 1 expected tracked voter)": [r["group_id"] for r in rows if r["share"] >= 0.05 or r["expected_voters_tracked"] >= 1]}
# who.group_mix (orchestrator 04:45Z fix 2): the launch's expected voter mix over the top-level groups, and the same for the hunter's and makers'
# earlier voters (pools from persona_cards.py, people who upvoted an earlier launch of the hunter / first maker, dated before D)
pf = os.path.join(SP, "persona", f"pools_{D}.json"); POOLS = json.load(open(pf)) if os.path.exists(pf) else {}
NAME = {g: (PROF.get(g) or {}).get("name") for g in PROF}; HOLDS = {g: ((PROF.get(g) or {}).get("calibration") or {}).get("votes_for_holds") for g in PROF}
def mix_rows(weights):   # weights: group -> amount (expected voters or people); base = group share of held upvotes in the 30 days before D
    tot = sum(weights.values()); rows = []
    for g in sorted(PROF):
        v = float(weights.get(g, 0)); sh = v / tot if tot else 0.0; b = float(bs.get(g, 0))
        rows.append({"group_id": g, "name": NAME.get(g), "expected_share": round(sh, 3), "base_share": round(b, 3), "lift": round(sh / b, 2) if b else None,
                     "n": round(v, 1), "votes_for_holds": HOLDS.get(g)})
    return sorted(rows, key=lambda r: -r["expected_share"])
for lid, v in out.items():
    gm = {"launch (expected voters)": mix_rows({r["group_id"]: r["expected_voters_tracked"] for r in v["groups"]})}
    for k in ("hunter", "maker"):
        ppl = (POOLS.get(lid) or {}).get(k) or []
        gm[f"{k}_past_voters (people)"] = mix_rows(pd.Series([GRP.get(p_) for p_ in ppl]).dropna().astype(int).value_counts().to_dict()) if len(ppl) >= 20 else {"note": f"{len(ppl)} held people; fewer than 20, not shown"}
    v["group_mix"] = gm
# who.group_mix_prior (orchestrator 10:24Z Nov 21, cohort scorecard v1 decision): the published WHO prior is P3, the topic-neighbour mix.
# For each launch on D: group mix of held upvoters (read before the day's start) of launches in the 30 days before D, weighted by topic overlap;
# backtest Nov 11-20 vs the 30-day base mix: -0.043 [-0.055, -0.027] JSD (cohort_calibration/results/who_blend_p6.json). Base stays as the shadow line.
import json as _j
TOP = {str(i): set(_j.loads(t) if isinstance(t, str) and t.startswith("[") else []) for i, t in zip(W.id, W.topics)}
_d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); _st = PP.close_utc(D) - pd.Timedelta(days=1)
_past = U[(U.lday < D) & (U.lday >= _d30) & (U.ft < _st)].assign(g=lambda x: x.person_id.map(GRP)).dropna(subset=["g"])
PMIX = {l: x.g.astype(int).value_counts(normalize=True).to_dict() for l, x in _past.groupby("target_id") if len(x) >= 5}
P3_LABEL = ("WHO prior (published line): group mix of held backers of launches from the 30 days before this day that share this launch's topics, "
            "weighted by the number of shared topics; falls back to the 30-day base mix when no earlier launch shares a topic. Backtest on Nov 11-20 "
            "(81 launches, held-out days): Jensen-Shannon distance to the real backer mix 0.321 vs 0.364 for the base mix, paired -0.043 "
            "[-0.055, -0.027]; still far from the 0.10 target, and real backer coverage is partial. The expected-voters table above is the shadow line.")
def p3_prior(lid):
    tp = TOP.get(str(lid), set()); acc, ws = {}, 0.0
    for l, m in PMIX.items():
        w_ = len(tp & TOP.get(l, set()))
        if w_:
            ws += w_
            for g, sh in m.items(): acc[g] = acc.get(g, 0) + w_ * sh
    return {"method": "topic-neighbour (P3)" if ws else "base mix (no topic neighbours)", "neighbour_launches": int(sum(1 for l in PMIX if tp & TOP.get(l, set()))),
            "groups": mix_rows({g: a / ws for g, a in acc.items()} if ws else {int(g): float(b) for g, b in bs.items()}), "accuracy_label": P3_LABEL}
# leaf units (every subgroup + groups without subgroups) for the spectrum panel (spectrum_say.py): same recalibrated probabilities, summed by unit
bsu = base_share(D, SUBU); TS = group_table(FD, iso, c, k_cov, bsu, SUBU)
json.dump({"day": D, "k_cov": k_cov, "base_share": {k: float(v) for k, v in bsu.items()}, "launches": {l: t for l, t in TS.items()},
           "validation_subgroup": VAL["subgroup-level check"]}, open(os.path.join(SP, "segments", f"expected_sub_{D}.json"), "w"), indent=1, default=float)
json.dump({"day": D, "validation": VAL, "label": LABEL, "launches": out}, open(os.path.join(SP, "segments", f"expected_{D}.json"), "w"), indent=1, default=float)
p = os.path.join(SP, "explain", f"{D}.json"); J = json.loads(gcat(f"{B}/results/web/explain/{D}.json") or (open(p).read() if os.path.exists(p) else "{}"))
if J.get("launches"):
    for lid, v in out.items():
        if lid in J["launches"]:
            w = J["launches"][lid].setdefault("who", {}); w["groups_expected"] = {**{k: x for k, x in v.items() if k != "group_mix"}, "accuracy_label": LABEL}
            w["group_mix"] = {**v["group_mix"], "accuracy_label": ("Mix of expected voters (launch) or of the hunter's / makers' earlier voters (pools) over the "
                              "top-level data-driven groups; base_share = the group's share of held upvotes in the 30 days before the day; lift = expected_share / "
                              "base_share; votes_for_holds = whether the group's 'votes for' description held out of sample last week. " + LABEL)}
    for lid in J["launches"]: J["launches"][lid].setdefault("who", {})["group_mix_prior"] = p3_prior(lid)   # every launch, CF list or not
    os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(J, open(p, "w"), indent=1)
    if UP: subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/explain/{D}.json"], check=True)
print(json.dumps({"day": D, "launches": len(out), "tail_factor": round(c, 2), "k_cov": round(k_cov, 2), "history_days": list(H)}))
