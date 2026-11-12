"""Day label and per-pick probabilities from the CLEAN shadow model (orchestrator 08:53Z Nov 12, confidence_v1; day label
from confidence_v2 since 09:00Z: two bins clear_leader / open_field, logistic on g12z, z1, t3z, ln with day sd = population sd, ddof 0).
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
RULE = os.path.join(HERE, "results", "confidence_v1.json")   # pick model
RULE2 = os.path.join(HERE, "results", "confidence_v2.json")  # day label (orchestrator 09:00Z Nov 12: v2 replaces the v1 3-bin label)
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
    V2 = json.load(open(RULE2)); r2 = V2["rule"]; n = len(S)
    sc = S.pred_clean; sd = sc.std(ddof=0)   # numpy-style sd: reproduces the rule's training means (ddof 1 gives 28% clear vs 33%)
    f2 = {"g12z": (sc[0] - sc[1]) / sd if n > 1 else 0.0, "z1": (sc[0] - sc.mean()) / sd,
          "t3z": (sc[:3].mean() - sc[3:].mean()) / sd if n > 3 else 0.0, "ln": float(np.log(n))}
    v = r2["intercept"] + sum((f2[f] - r2["standardize_mean"][f]) / r2["standardize_sd"][f] * c for f, c in r2["coef"].items())
    p2 = float(1 / (1 + np.exp(-v))); lab = "clear_leader" if p2 >= r2["cutoff"] else "open_field"
    st = V2["statement"]
    out = {"day": day, "applies_to": "clean shadow model", "stable": True, "rule": V2["version"], "launches": n,
           "source": "from the clean shadow model (clean_v3, 00:05 inputs; results/shadow_makerfix pred_clean); never the published ranking",
           "label": lab, "p_clear_leader": round(p2, 3), "cutoff": r2["cutoff"],
           "features": {k: round(float(x), 3) for k, x in f2.items()},
           "text": st["text_" + lab], "validated_rates": st["validated_month_forward"][lab],
           "eval": st["eval"], "picks_rule": "confidence_v1 pick_models (clean), unchanged", "picks": []}
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
    print(json.dumps({k: out[k] for k in ("day", "launches", "label", "p_clear_leader")}))


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
        rows.append({"day": d, "label": c.get("label"), "h3": hit(3), "h5": hit(5), "h10": hit(10) if len(t) > 10 else None,
                     "p1t3": float(ids[0] in t[:3])})
    X = pd.DataFrame(rows)
    out = {"source": "clean shadow model, confidence_v2 label (clear_leader / open_field), live days scored forward", "applies_to": "clean shadow model",
           "n_days": int(len(X)), "by_label": {}, "days": rows}
    if len(X):
        out["by_label"] = {lab: {"days": int(len(g)), "p1_top3": round(float(g.p1t3.mean()), 3), "p1_top3_count": f"{int(g.p1t3.sum())} of {len(g)}",
                                 "top3_hits": round(float(g.h3.mean()), 2), "top5_hits": round(float(g.h5.mean()), 2)} for lab, g in X.dropna(subset=["label"]).groupby("label")}
    p = os.path.join(HERE, "results", "web", "confidence_scoreboard.json"); json.dump(out, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/confidence_scoreboard.json"], check=True)
    print(json.dumps(out["by_label"]))


if __name__ == "__main__":
    score() if sys.argv[1] == "score" else main(sys.argv[1])
