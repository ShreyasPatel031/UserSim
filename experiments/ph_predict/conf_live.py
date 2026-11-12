"""Day label and per-pick probabilities from the CLEAN shadow model (orchestrator 08:53Z Nov 12, confidence_v1).
Rule: gs://.../tmp/orchestrator/conf/confidence_v1.json (copied to results/confidence_v1.json), fitted on honest_preds_v2
(clean OOF scores); live input = results/shadow_makerfix/<d>.json pred_clean (the same clean_v3 inputs, daily refit).
  day label   ridge on day features (score gaps, spread, entropy, line-up size, weekend, strong hunters), cut into
              hard / normal / easy at the JSON cut-points; h3 / h5 for every day, h10 only for days with > 10 launches
  per pick    logistic: one-hot pick position 1..10 + z(m_next, z, ln) -> P(finish top 3 / 5 / 10)
  strong      launches whose hunter had >= 2 earlier ranked launches (days before d) with >= 30% top-3 (warehouse; counts only)
usage: python conf_live.py <day>            -> results/web/confidence/<day>.json (+ latest.json), bucket copy
       python conf_live.py score            -> results/web/confidence_scoreboard.json (hits by label, finished days)"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
RULE = os.path.join(HERE, "results", "confidence_v1.json")
OUT = os.path.join(HERE, "results", "web", "confidence")
TMP = os.environ.get("TMPDIR", "/tmp")


def day_feats(s, n_above_thr, strong):
    s = np.sort(np.asarray(s, float))[::-1]; n = len(s)
    gap = lambda i: s[i - 1] - s[i] if n > i else 0.0
    top = s[:10]; p = np.exp((top - top.max()) / 0.2); p /= p.sum()
    return {"ln": float(np.log(n)), "g12": gap(1), "g34": gap(3), "g56": gap(5), "g1011": gap(10), "top_sd": float(top.std()),
            "ent": float(-(p * np.log(p)).sum()), "n_above": float((s > n_above_thr).sum()), "strong": float(strong)}


def strong_count(day, ids):
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank, poster FROM launches", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    pr = L[(L.day < day) & L.daily_rank.notna() & (L.poster != "")]
    h = pr.assign(t3=(pr.daily_rank <= 3).astype(float)).groupby("poster").t3.agg(["size", "mean"])
    good = set(h[(h["size"] >= 2) & (h["mean"] >= 0.3)].index)
    today = dict(zip(L.id, L.poster))
    miss = sum(1 for i in ids if not today.get(i))
    return sum(1 for i in ids if today.get(i) in good), miss


def label(m, x):
    z = sum(((x[f] - m["standardize_mean"][f]) / m["standardize_sd"][f]) * c for f, c in m["coef"].items())
    pred = m["intercept"] + z; c = m["cutpoints"]
    lab = "hard" if pred < c["hard_below"] else ("easy" if pred >= c["easy_at_or_above"] else "normal")
    rel = m["oos_reliability"][lab]
    return {"label": lab, "pred": round(float(pred), 3), "oos_rates": {k: round(float(v), 3) for k, v in rel.items()}}


def main(day):
    R = json.load(open(RULE))
    sp = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
    if not os.path.exists(sp):
        subprocess.run(["gsutil", "-q", "cp", f"{B}/results/shadow_makerfix/{day}.json", sp])
    SF = pd.DataFrame(json.load(open(sp))["forecast"]); SF["id"] = SF.id.astype(str)
    if "pred_clean" not in SF or SF.pred_clean.isna().all():
        print(json.dumps({"day": day, "skipped": "no pred_clean in shadow file"})); return
    S = SF[["id", "pred_clean"]].dropna().sort_values(["pred_clean", "id"], ascending=[False, True]).reset_index(drop=True)
    st, miss = strong_count(day, S.id.tolist())
    x = day_feats(S.pred_clean.values, R["day_models"]["h3"]["n_above_threshold"], st)
    x["weekend"] = float(pd.Timestamp(day).weekday() >= 5)
    n = len(S)
    out = {"day": day, "source": "from the clean shadow model (clean_v3, 00:05 inputs; results/shadow_makerfix pred_clean)",
           "rule": R["version"], "launches": n, "strong_hunters": st, "poster_unknown": miss,
           "note": "Labels and probabilities fitted month-forward on the clean backtest (194 days); oos_rates = that bin's out-of-sample "
                   "mean hits (h3 of our top 3, h5, h10) and #1-in-top-3 rate (p1t3). Live-scored forward in confidence_scoreboard.json.",
           "labels": {}, "picks": []}
    for k in ("h3", "h5", "h10"):
        if k == "h10" and n <= 10:
            out["labels"][k] = None; continue
        out["labels"][k] = label(R["day_models"][k], x)
    sc = S.pred_clean; z = (sc - sc.mean()) / sc.std(); m_next = (sc - sc.shift(-1)).fillna(0)
    for j in range(min(10, n)):
        row = {"pick": j + 1, "id": S.id[j]}
        for K in ("top3", "top5", "top10"):
            pm = R["pick_models"][K]
            if K == "top10" and n <= 10:
                row["p_" + K] = None; continue
            f = {"m_next": m_next[j], "z": z[j], "ln": np.log(n)}
            v = pm["intercept"] + pm["coef"][f"k_{j + 1}"] + sum((f[c] - pm["standardize_mean"][c]) / pm["standardize_sd"][c] * pm["coef"][c] for c in f)
            row["p_" + K] = round(float(1 / (1 + np.exp(-v))), 3)
        out["picks"].append(row)
    out["written_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    os.makedirs(OUT, exist_ok=True)
    for nm in (f"{day}.json", "latest.json"):
        p = os.path.join(OUT, nm); json.dump(out, open(p, "w"), indent=1)
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/confidence/{nm}"], check=True)
    print(json.dumps({k: out[k] for k in ("day", "launches", "strong_hunters", "poster_unknown")} | {"labels": {k: (v or {}).get("label") for k, v in out["labels"].items()}}))


def score():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rows = []
    for f in sorted(os.listdir(OUT)):
        if not f[:4].isdigit():
            continue
        c = json.load(open(os.path.join(OUT, f))); d = c["day"]; t = R[R.day == d].sort_values("daily_rank").id.tolist()
        if len(t) < 3:
            continue
        ids = [p["id"] for p in c["picks"]]
        hit = lambda k: len(set(ids[:k]) & set(t[:k]))
        r = {"day": d, "h3": hit(3), "h5": hit(5), "h10": hit(10) if len(t) > 10 else None, "p1t3": float(ids[0] in t[:3])}
        for k in ("h3", "h5", "h10"):
            r["label_" + k] = (c["labels"].get(k) or {}).get("label")
        rows.append(r)
    X = pd.DataFrame(rows)
    out = {"source": "clean shadow model, confidence_v1 labels, live days scored forward", "n_days": int(len(X)), "by_label": {}, "days": rows}
    for k in ("h3", "h5", "h10"):
        if len(X) and X["label_" + k].notna().any():
            out["by_label"][k] = {lab: {"n": int(len(g)), "mean_hits": round(float(g[k].mean()), 2), "p1t3": round(float(g.p1t3.mean()), 2)}
                                  for lab, g in X.dropna(subset=["label_" + k]).groupby("label_" + k)}
    p = os.path.join(HERE, "results", "web", "confidence_scoreboard.json"); json.dump(out, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/confidence_scoreboard.json"], check=True)
    print(json.dumps(out["by_label"]))


if __name__ == "__main__":
    score() if sys.argv[1] == "score" else main(sys.argv[1])
