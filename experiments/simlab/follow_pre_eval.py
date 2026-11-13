"""Evaluate the before-launch held-follower count on Nov 10 - 11 (and Nov 12 once final ranks land): coverage, within-day Spearman with
final rank, partial correlation beyond clean_v3_nosite (th_n_pre not held), vs the all-edges (leaky) count; and n days needed.
    python follow_pre_eval.py <store dir> <salt dir> <clean_nosite.parquet> <launches dir> <out dir> <day> [<day> ...]
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from follow_shadow import features, load_json
V3, SALTD, CNS, LDIR, OUT = sys.argv[1:6]; DAYS = sys.argv[6:]; os.makedirs(OUT, exist_ok=True)
CN = pd.read_parquet(CNS)[["id", "day", "clean_v3_nosite", "rank"]].rename(columns={"rank": "rank_cn"}); CN["id"] = CN.id.astype(str)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
rk = dict(zip(L.id, L.daily_rank))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
_W = warehouse.table("launches", do_sync=True); _W = _W.sort_values("updated_at").drop_duplicates("id", keep="last"); rk.update({str(i): r for i, r in zip(_W.id, _W.daily_rank) if r == r})
res = {"design": __doc__.split("\n    python")[0], "days": {}}; allpc = {"pre": [], "all": [], "ph_hunter": []}
def partial(y, c, x):
    y, c, x = (pd.Series(a).rank().to_numpy() for a in (y, c, x)); ry = y - np.polyval(np.polyfit(c, y, 1), c); rx = x - np.polyval(np.polyfit(c, x, 1), c)
    return float(np.corrcoef(ry, rx)[0, 1])
for d in DAYS:
    F = pd.DataFrame(features(load_json(f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{d}/today_0005.json"), d, V3, SALTD))
    F["rank"] = F.launch_id.map(rk); F = F.merge(CN[CN.day == d][["id", "clean_v3_nosite", "rank_cn"]], left_on="launch_id", right_on="id", how="left"); F["rank"] = F["rank"].fillna(F.rank_cn)
    base = "clean_v3_nosite"
    if F.clean_v3_nosite.notna().sum() < 8:   # no clean row for the day: deployed 00:05 pred (labelled)
        _fc = pd.read_parquet(__import__("io").BytesIO(__import__("subprocess").run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{d}/forecast_{d}.parquet"], capture_output=True).stdout))
        F["clean_v3_nosite"] = F.launch_id.map(dict(zip(_fc.id.astype(str), _fc.pred))); base = "deployed 00:05 pred"
    G = F[F["rank"].notna() & F.clean_v3_nosite.notna()]; y = -G["rank"].to_numpy()
    o = {"base": base, "launches": len(F), "with_rank_and_clean": len(G), "eligible_people": int(F.eligible_people.iat[0]), "coverage_pre>0": round(float((F.held_followers_pre > 0).mean()), 3),
         "median_pre": float(F.held_followers_pre.median()), "median_all": float(F.held_followers_all.median()),
         "leak_ratio_all_over_pre_median": round(float((F.held_followers_all / F.held_followers_pre.replace(0, np.nan)).median()), 3)}
    if len(G) >= 8:
        for nm, c in (("pre", "held_followers_pre"), ("all", "held_followers_all"), ("ph_hunter", "hunter_followers_ph")):
            o[f"spearman_{nm}"] = round(float(spearmanr(G[c], y).correlation), 3); p = partial(y, G.clean_v3_nosite.to_numpy(), G[c].fillna(0).to_numpy()); o[f"partial_{nm}"] = round(p, 3); allpc[nm].append(p)
        o["spearman_clean"] = round(float(spearmanr(G.clean_v3_nosite, y).correlation), 3)
        o["spearman_pre_vs_ph_hunter_followers"] = round(float(spearmanr(G.held_followers_pre, G.hunter_followers_ph.fillna(0)).correlation), 3)
        top10 = G["rank"] <= 10; rat = G.held_followers_all / G.held_followers_pre.replace(0, np.nan); o["median all/pre ratio: top10 / others"] = [round(float(rat[top10].median()), 3), round(float(rat[~top10].median()), 3)]; o["mean_all_minus_pre: top10 / others"] = [round(float((G.held_followers_all - G.held_followers_pre)[top10].mean()), 1), round(float((G.held_followers_all - G.held_followers_pre)[~top10].mean()), 1)]
    res["days"][d] = o; print(d, o, flush=True)
# days needed to detect a partial of 0.2 (two-sided 5%, 80% power), per-day sd from the 14-day all-edges follower partials (sim_sum check: mean 0.44, 95% CI [0.33, 0.55])
sd = 0.11 / 1.96 * np.sqrt(14); res["n_days_for_partial_0.2"] = {"per_day_sd_assumed": round(float(sd), 3), "n_days": int(np.ceil(((1.96 + 0.84) * sd / 0.2) ** 2)),
    "note": "per-day sd from the 14-day follower-count partials (Oct 26 - Nov 11); detection = mean partial's 95% interval excludes 0 with 80% power"}
json.dump(res, open(os.path.join(OUT, "follow_pre_eval.json"), "w"), indent=1, default=float); print(res["n_days_for_partial_0.2"])
