"""Website score guard (Shreyas via orchestrator 09:41Z Nov 21): the public site's forecast score must not drop sharply.
The site's score = the LIVE rows of E5's track record (tmp/e5/website/track_record_v1.json, read by mvp/ph_site/live.py
accuracy()): top 3 / 5 / 10 hits % of the published 03:45 PT before-reveal line (the 80-90 figure) and of the published
00:05 PT line. Daily: for each line and k, rolling 7-day mean vs 30-day mean (calendar windows ending at the line's last
scored live day). ALERT when the 7-day value is more than 5 points below the 30-day value, with a first diagnosis:
  - model / fallback changes (track-record model field; 00:05 published_model per day);
  - 00:05 arm-3 inputs (raw/daily/<d>/arm3_input_nulls_<d>.json, arm3_inputs_<d>.parquet): null-rate changes > 0.10 and the
    largest shifts of the per-day input median, in units of the earlier days' spread (person-derived groups hist_/A_/B_/C_
    flagged: the store refresh coverage jump changes them).
usage: python score_guard.py  -> appends results/score_guard.jsonl; prints one JSON line; exit 0 (status "ALERT" in the line)."""
import json, os, subprocess, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "results", "score_guard.jsonl")
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
DROP = 5.0; KS = (3, 5, 10)
PERSON = ("hist_", "A_", "B_", "C_", "ph_hunter_n_same_day")


def windows(rows):
    """rows: scored live rows of one line. Returns (last day, {k: (mean7, n7, mean30, n30)})."""
    df = pd.DataFrame(rows); df["day"] = pd.to_datetime(df.day); L = df.day.max()
    w7, w30 = df[df.day > L - pd.Timedelta(days=7)], df[df.day > L - pd.Timedelta(days=30)]
    m = lambda w, k: round(float((100 * w[f"hits_top{k}"] / k).mean()), 1) if len(w) else None
    return L.strftime("%Y-%m-%d"), {k: (m(w7, k), len(w7), m(w30, k), len(w30)) for k in KS}


def inputs_diag(days7, days_prior):
    """00:05 arm-3 input drift: null-rate moves and median shifts, recent window vs earlier days."""
    def nulls(d):
        s = cat(f"{B}/raw/daily/{d}/arm3_input_nulls_{d}.json")
        return json.loads(s).get("null_rate", {}) if s else None
    def med(d):
        p = tempfile.mkdtemp() + "/a.parquet"
        if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/arm3_inputs_{d}.parquet", p], capture_output=True).returncode: return None
        A = pd.read_parquet(p).drop(columns=["id"], errors="ignore"); A = A.apply(pd.to_numeric, errors="coerce"); return A.median()
    N7, N0 = [x for x in map(nulls, days7) if x], [x for x in map(nulls, days_prior) if x]
    out = {"days_with_inputs": {"recent": len(N7), "earlier": len(N0)}}
    if N7 and N0:
        n7, n0 = pd.DataFrame(N7).mean(), pd.DataFrame(N0).mean()
        mv = (n7 - n0).dropna(); mv = mv[mv.abs() > 0.10].sort_values()
        out["null_rate_moves"] = {c: [round(float(n0[c]), 2), round(float(n7[c]), 2)] for c in mv.index}
    M7, M0 = [x for x in map(med, days7) if x is not None], [x for x in map(med, days_prior) if x is not None]
    if M7 and len(M0) >= 3:
        m7, m0 = pd.DataFrame(M7).mean(), pd.DataFrame(M0)
        z = ((m7 - m0.mean()) / m0.std(ddof=1).replace(0, np.nan)).dropna()
        top = z.abs().sort_values(ascending=False).head(6).index
        out["largest_median_shifts_sd"] = {c: round(float(z[c]), 1) for c in top}
        out["person_derived_among_them"] = [c for c in top if c.startswith(PERSON)]
    elif M7:
        out["median_shift"] = f"too few earlier days with inputs ({len(M0)}); arm3_inputs files start Nov 17"
    return out


def model_diag(line, rows, days7):
    df = pd.DataFrame(rows); recent = df[df.day.isin(days7)]; earlier = df[~df.day.isin(days7)]
    cnt = lambda w: {str(k): int(v) for k, v in pd.Series([str(r.get("model")) + (" | fallback " + str(r["fallback_used"]) if r.get("fallback_used") else "")
                                                         for r in w.to_dict("records")]).value_counts().items()} if len(w) else {}
    out = {"recent_models": cnt(recent), "earlier_models": cnt(earlier)}
    if line == "00:05 PT":
        pm = {}
        for d in days7:
            p = tempfile.mkdtemp() + "/f.parquet"
            if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p], capture_output=True).returncode: continue
            F = pd.read_parquet(p, columns=None); pm[d] = str(F.get("published_model", pd.Series(["?"])).iloc[0])
        out["published_model_by_day"] = pm
    return out


def main():
    t = json.loads(cat(f"{B}/tmp/e5/website/track_record_v1.json") or "{}")
    res = {"checked_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "track_record_written_at": t.get("written_at"),
           "rule": f"ALERT if 7-day mean < 30-day mean - {DROP} on any of top 3/5/10, per published line (live rows only)", "lines": {}}
    alert = []
    for line in ("03:45 PT", "00:05 PT"):
        rows = [r for r in t.get("days", []) if r.get("prediction") == line and r.get("flag") == "live" and r.get("status") == "scored"]
        if not rows: res["lines"][line] = "no live rows"; continue
        L, w = windows(rows)
        v = {f"top{k}": {"7d": a, "n7": b, "30d": c, "n30": d, "gap": (round(a - c, 1) if a is not None and c is not None else None)} for k, (a, b, c, d) in w.items()}
        bad = [k for k in v if v[k]["gap"] is not None and v[k]["gap"] < -DROP]
        res["lines"][line] = {"last_scored_day": L, "windows": v, "breach": bad}
        if bad:
            Ld = pd.Timestamp(L); days7 = [(Ld - pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
            prior = sorted({r["day"] for r in rows if r["day"] not in days7})
            res["lines"][line]["diagnosis"] = {"models": model_diag(line, rows, days7), "inputs_0005": inputs_diag(days7, prior)}
            alert.append(f"{line} {','.join(bad)}")
    res["status"] = ("ALERT: " + "; ".join(alert)) if alert else "ok"
    open(OUT, "a").write(json.dumps(res, default=str) + "\n")
    print(json.dumps({"status": res["status"], **{ln: (v if isinstance(v, str) else {k: [x["7d"], x["30d"], x["n7"], x["n30"]] for k, x in v["windows"].items()})
                                                    for ln, v in res["lines"].items()}}))


if __name__ == "__main__":
    main()
