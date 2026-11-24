"""FROZEN forward shadow (orchestrator 10:29Z Nov 20; POST-HOC: found on a second look after the pre-registered miss-anatomy rule failed,
no 2025 replication). Rule frozen in results/frozen/promo_posts_w01_20261120.json: score = z(pred_arm3) + 0.1 * z(promo_posts) within day,
missing promo_posts -> day median; inputs exactly as in the published 00:05 parquet; no refit, ever.
  write <D>   order for day D from raw/daily/D/forecast_D.parquet (published arm 3 only) -> results/promo_posts_shadow.jsonl
  score       for every logged day with truth_daily: top 3/5/10 of the shadow and of published arm 3 -> results/promo_posts_shadow_scores.jsonl;
              prints n days and, from 5 days, the paired day-bootstrap 95% (decision at 25 scored days).
Counts and launch ids only."""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = lambda p: os.path.join(HERE, "results", p)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
FROZEN = json.load(open(R("frozen/promo_posts_w01_20261120.json")))
W, FEAT = FROZEN["w"], FROZEN["feature"]
LOG, SC = R("promo_posts_shadow.jsonl"), R("promo_posts_shadow_scores.jsonl")
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
z = lambda s: (s - s.mean()) / (s.std(ddof=0) or 1.0)
done = lambda p: {json.loads(l)["day"] for l in open(p)} if os.path.exists(p) else set()


def write(d):
    if d in done(LOG): return {"day": d, "status": "already logged"}
    p = tempfile.mkdtemp() + "/f.parquet"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p], capture_output=True).returncode:
        return {"day": d, "status": "missing input: no 00:05 parquet"}
    F = pd.read_parquet(p); F["id"] = F.id.astype(str)
    if "pred_arm3" not in F or F.pred_arm3.isna().any() or str(F.get("published_model", pd.Series([""])).iloc[0]) != "arm3":
        return {"day": d, "status": "missing input: published model is not arm3"}
    x = F[FEAT].astype(float); n_missing = int(x.isna().sum()); x = x.fillna(x.median() if x.notna().any() else 0.0)
    s = z(F.pred_arm3) + W * z(x)
    shadow = F.assign(s=s).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
    arm3 = F.sort_values(["pred_arm3", "id"], ascending=[False, True]).id.tolist()
    row = {"day": d, "rule": FROZEN["rule"], "launches": len(F), "feature_missing": n_missing, "shadow_order": shadow, "arm3_order": arm3,
           "top3_differs": shadow[:3] != arm3[:3], "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
    open(LOG, "a").write(json.dumps(row) + "\n")
    return {"day": d, "status": "ok", "launches": len(F), "feature_missing": n_missing, "top3_differs": row["top3_differs"]}


def score():
    TD = json.loads(cat(f"{B}/results/web/truth_daily.json"))["days"]; have = done(SC)
    for l in open(LOG):
        r = json.loads(l); d = r["day"]
        if d in have or d not in TD: continue
        tr = {str(i): int(v) for i, v in TD[d]["ranks"].items()}
        h = lambda o: [round(100 * len(set(o[:k]) & {i for i, v in tr.items() if v <= k}) / k, 1) for k in (3, 5, 10)]
        open(SC, "a").write(json.dumps({"day": d, "shadow": h(r["shadow_order"]), "arm3": h(r["arm3_order"])}) + "\n")
    S = [json.loads(l) for l in open(SC)] if os.path.exists(SC) else []
    out = {"n_scored": len(S), "decision_at": 25}
    if len(S) >= 5:
        D = np.array([np.array(s["shadow"]) - np.array(s["arm3"]) for s in S]); rng = np.random.default_rng(0)
        bs = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(10000)])
        out["shadow_minus_arm3"] = {f"top{k}": [round(float(D[:, i].mean()), 1), round(float(np.percentile(bs[:, i], 2.5)), 1),
                                                 round(float(np.percentile(bs[:, i], 97.5)), 1)] for i, k in enumerate((3, 5, 10))}
    return out


if __name__ == "__main__":
    if sys.argv[1] == "write":
        for d in sys.argv[2:]: print(json.dumps(write(d)))
    else:
        print(json.dumps(score()))
