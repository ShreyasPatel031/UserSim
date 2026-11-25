"""CEILING-1: every reaction metric on a "fraction of the human ceiling" scale.

  python -m simharness.ceiling1 launch --work W --sim-dir SIM [--resamples 20] [--max-launches N] [--budget 4.0]
  python -m simharness.ceiling1 person --work W --point1 P1_WIP [--budget 1.0]
  python -m simharness.ceiling1 table  --work W --out-dir simharness/bench_v0/ceiling1 [--sync gs://...]

Launch level (E5's frozen consensus-theme scorer, commit bfbed0a3 / forward_says.py: TRUTH and CT extracted 3 times,
a Gemini merge keeps themes in >= 2 of 3; JUDGE and CJ score a candidate list; Gemini 2.5 Flash, temperature 0):
for launches of Nov 15-24 with >= 10 real non-team commenters (official API live capture; team = hunter and makers from
the 00:05 line-up; comments > 25 characters, @handles removed), the commenters are split at random into halves A / B
(R resamples, every comment of a person in the same half). Themes are built from half B only. Scored against them:
  human ceiling   half A's comments as the candidate list
  deployed panel  persona panel + person-built comments (explain say.person_built_panel where it exists, else the
                  Nov 25 re-generation results/calibration/<day>/what_panel/person_built_flash_deployed15.json)
  persona only    the persona panel
One judge run per resample (resamples average the judge noise). Fraction of ceiling = arm / ceiling per launch, mean
over resamples; launch-bootstrap intervals.

Person level (POINT-1 rows, "same point" content judge, Claude Opus 5.5, 2 runs): existing arms A0 (Flash + launch
block) and the other-commenter reference, plus a stronger ceiling: the same person's own earlier comment on the most
similar launch they commented on before D (bge-small embedding of name + tagline + description).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import html
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

import numpy as np
import pandas as pd

RNG = np.random.default_rng(0)
_lk = threading.Lock()
USAGE = {"in": 0, "out": 0, "calls": 0}
_tok = {"t": "", "at": 0}
URL = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"


def usd():
    return USAGE["in"] / 1e6 * 0.30 + USAGE["out"] / 1e6 * 2.50


def _token():
    with _lk:
        if time.time() - _tok["at"] > 1800:
            _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
            _tok["at"] = time.time()
        return _tok["t"]


def gemini(prompt, max_tokens):
    """Same request as E5's llm.gemini_call: temperature 0, JSON, no thinking budget; usage from usage_metadata."""
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    for i in range(6):
        try:
            req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r)
                u = j.get("usageMetadata", {})
                with _lk:
                    USAGE["in"] += u.get("promptTokenCount", 0)
                    USAGE["out"] += u.get("candidatesTokenCount", 0)
                    USAGE["calls"] += 1
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e:  # noqa: BLE001
            if "403" in str(e):
                raise
            time.sleep(4 * (i + 1))
    return ""


def g(p, mt):
    try:
        return json.loads(gemini(p, mt))
    except Exception:  # noqa: BLE001
        return None


def boot(x, B=4000):
    x = np.array([v for v in x if v is not None and not np.isnan(v)], float)
    if len(x) < 2:
        return {"mean": round(float(x.mean()), 4) if len(x) else None, "lo": None, "hi": None, "n": int(len(x))}
    m = RNG.choice(x, (B, len(x))).mean(1)
    return {"mean": round(float(x.mean()), 4), "lo": round(float(np.percentile(m, 2.5)), 4), "hi": round(float(np.percentile(m, 97.5)), 4), "n": int(len(x))}


# ------------------------------------------------------------------ E5's frozen prompts
def prompts(sim_dir):
    RE = open(os.path.join(sim_dir, "reactions_eval.py")).read()
    CE = open(os.path.join(sim_dir, "complaints_eval.py")).read()
    FS = open(os.path.join(sim_dir, "forward_says.py")).read()
    P = {"TRUTH": re.search(r'TRUTH = """(.*?)"""', RE, re.S).group(1), "JUDGE": re.search(r'JUDGE = """(.*?)"""', RE, re.S).group(1),
         "CT": re.search(r'CT = """(.*?)"""', CE, re.S).group(1), "CJ": re.search(r'CJ = """(.*?)"""', CE, re.S).group(1),
         "CONS": re.search(r'CONS = """(.*?)"""', FS, re.S).group(1)}
    return P


def truth_for(P, c):
    """forward_says.truth_for, unchanged except it takes the comment block directly."""
    ex_t = [[{"theme": str(t.get("theme", "")), "n": max(1, int(t.get("n_comments", 1) or 1))} for t in ((g(P["TRUTH"].format(c=c), 2000) or {}).get("themes") or [])
             if isinstance(t, dict) and t.get("theme")][:8] for _ in range(3)]
    ex_c = [[str(t) for t in ((g(P["CT"].format(c=c), 1200) or {}).get("themes") or [])][:6] for _ in range(3)]
    lt = "\n".join(f"Extraction {i + 1}:\n" + "\n".join(f"- {t['theme']} (comments: {t['n']})" for t in e) for i, e in enumerate(ex_t))
    th = [{"theme": str(t.get("theme")), "n": max(1, int(t.get("n_comments", 1) or 1))}
          for t in ((g(P["CONS"].format(k=3, nfield=" and the median number of comments across the extractions that list it", shape='{"theme": "...", "n_comments": N}', lists=lt), 1500) or {}).get("themes") or [])
          if isinstance(t, dict) and t.get("theme")][:8]
    lc = "\n".join(f"Extraction {i + 1}:\n" + "\n".join(f"- {t}" for t in e) for i, e in enumerate(ex_c))
    ct = [str(t.get("theme") if isinstance(t, dict) else t) for t in ((g(P["CONS"].format(k=3, nfield="", shape='{"theme": "..."}', lists=lc), 1200) or {}).get("themes") or [])][:6] if any(ex_c) else []
    return th, ct


def judge(P, th, ct, cand):
    Bt = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(cand))
    r = {}
    j = g(P["JUDGE"].format(a="\n".join(f"{i + 1}. {t['theme']}" for i, t in enumerate(th)), b=Bt), 900) if th else None
    if j and len(j.get("a_covered", [])) == len(th):
        ac = np.array([bool(v) for v in j["a_covered"]])
        w = np.array([t["n"] for t in th], float)
        r.update({"recall": float(ac.mean()), "recall_w": float((ac * w).sum() / w.sum()),
                  "precision": float(np.mean([bool(v) for v in j.get("b_present", [])[:len(cand)]]))})
    if ct:
        j2 = g(P["CJ"].format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(ct)), b=Bt), 1200)
        if j2 and len(j2.get("a_covered", [])) == len(ct):
            r["complaint_recall"] = float(np.mean([bool(v) for v in j2["a_covered"]]))
    return r


# ------------------------------------------------------------------ data
clean = lambda b: re.sub(r"@[A-Za-z0-9_]{2,}", "", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b or "")))).strip()


def real_comments(W, d):
    rows = []
    for f in glob.glob(f"{W}/raw/{d}/api/*.jsonl"):
        for l in open(f):
            if l.strip():
                x = json.loads(l)
                rows.append((str(x["post_id"]), str(x["comment_id"]), str(x.get("commenter_user_id")), x.get("createdAt"), x.get("snapshot_at"), x.get("body") or ""))
    f = f"{W}/raw/{d}/comments_ts.jsonl"
    if os.path.exists(f):
        for l in open(f):
            if l.strip():
                x = json.loads(l)
                rows.append((str(x["launch_id"]), str(x["comment_id"]), str(x.get("commenter_user_id")), x.get("created_at"), x.get("snapshot_ts"), x.get("body") or ""))
    C = pd.DataFrame(rows, columns=["post", "cid", "uid", "created", "snap", "body"]).sort_values("snap").drop_duplicates("cid", keep="last")
    T0 = {str(x["id"]): x for x in json.load(open(f"{W}/raw/{d}/today_0005.json"))}
    team = {i: {str((x.get("user") or {}).get("id"))} | {str(m.get("id")) for m in (x.get("makers") or [])} for i, x in T0.items()}
    C["team"] = [u in team.get(p, set()) for p, u in zip(C.post, C.uid)]
    C["text"] = C.body.map(clean)
    return C[~C.team & (C.text.str.len() > 25)], T0


def arms_for(W, d, T0):
    ex = json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/results/web/explain/{d}.json"], capture_output=True).stdout or b"{}").get("launches", {})
    pb15 = json.load(open(f"{W}/raw/{d}/pb15.json"))["launches"] if os.path.exists(f"{W}/raw/{d}/pb15.json") else {}
    slug = {i: str(x.get("slug")) for i, x in T0.items()}
    out = {}
    for lid, L in ex.items():
        say = L.get("say") or {}
        pan = (say.get("persona_panel") or {}).get("items") or []
        persona = [f"{x.get('reaction', '')} Concern: {x.get('concern', '')} Question: {x.get('question', '')}" for x in pan]
        pbp = say.get("person_built_panel") or {}
        if pbp.get("comments"):
            pb, src = [str(x)[:300] for x in pbp["comments"] if str(x).strip()], ("explain, launch block" if (pbp.get("launch_block") or {}).get("maker_comment_present") else "explain")
        else:
            pb, src = [str(x)[:300] for x in (pb15.get(slug.get(lid)) or []) if str(x).strip()], "Nov 25 re-generation (no launch block)"
        out[str(lid)] = {"persona": persona, "deployed": persona + pb, "pb_source": src if pb else None}
    return out


# ------------------------------------------------------------------ launch level
def cmd_launch(a):
    P = prompts(a.sim_dir)
    W = a.work
    cands = []
    for d in sorted(os.listdir(f"{W}/raw")):
        C, T0 = real_comments(W, d)
        arms = arms_for(W, d, T0)
        for lid, g_ in C.groupby("post"):
            if g_.uid.nunique() >= 10 and lid in arms and arms[lid]["persona"]:
                cands.append((d, lid, g_, arms[lid]))
    print("eligible launches", len(cands), flush=True)
    order = RNG.permutation(len(cands))
    cands = [cands[i] for i in order][: a.max_launches]
    out_rows = []
    path = f"{W}/launch_rows.jsonl"
    done = set()
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            out_rows.append(r)
            done.add((r["day"], r["id"], r["resample"]))
    fo = open(path, "a")
    for d, lid, g_, arms in cands:
        users = sorted(g_.uid.unique())
        jobs = []
        for k in range(a.resamples):
            if (d, lid, k) in done:
                continue
            rng = np.random.default_rng(int(lid) * 100 + k)
            perm = rng.permutation(users)
            A, Bh = set(perm[: len(users) // 2]), set(perm[len(users) // 2:])
            ca = g_[g_.uid.isin(A)].sort_values("created").text.tolist()
            cb = g_[g_.uid.isin(Bh)].sort_values("created").text.tolist()
            jobs.append((k, ca, cb))

        def one(job):
            k, ca, cb = job
            th, ct = truth_for(P, "\n".join(f"- {t[:500]}" for t in cb))
            r = {"day": d, "id": lid, "resample": k, "n_commenters": len(users), "n_a": len(ca), "n_b": len(cb),
                 "n_themes": len(th), "n_complaints": len(ct), "pb_source": arms["pb_source"]}
            for arm, cand in (("ceiling_half_a", [x[:300] for x in ca]), ("deployed", arms["deployed"]), ("persona", arms["persona"])):
                for m, v in judge(P, th, ct, cand).items():
                    r[f"{arm}:{m}"] = v
            return r
        if usd() >= a.budget:
            print("budget reached", round(usd(), 3), flush=True)
            break
        with cf.ThreadPoolExecutor(10) as ex:
            for r in ex.map(one, jobs):
                fo.write(json.dumps(r) + "\n")
                fo.flush()
                out_rows.append(r)
        print(d, lid, len(users), "usd", round(usd(), 3), "calls", USAGE["calls"], flush=True)
    json.dump({"usd": round(usd(), 4), "calls": USAGE["calls"], "tokens_in": USAGE["in"], "tokens_out": USAGE["out"]}, open(f"{W}/launch_spend.json", "w"))


def launch_table(W):
    R = pd.DataFrame([json.loads(l) for l in open(f"{W}/launch_rows.jsonl")])
    out = {"launches": int(R.id.nunique()), "days": int(R.day.nunique()), "resamples_per_launch": float(R.groupby("id").size().mean()),
           "median_commenters": float(R.groupby("id").n_commenters.first().median()), "pb_source": R.groupby("id").pb_source.first().value_counts().to_dict(),
           "metrics": {}}
    for m in ("recall", "recall_w", "precision", "complaint_recall"):
        per = R.groupby("id").agg(**{arm: (f"{arm}:{m}", "mean") for arm in ("ceiling_half_a", "deployed", "persona") if f"{arm}:{m}" in R})
        row = {arm: boot(per[arm] * 100) for arm in per}
        for arm in ("deployed", "persona"):
            if arm in per:
                f = (per[arm] / per["ceiling_half_a"]).replace([np.inf], np.nan)
                row[f"{arm}_fraction_of_ceiling"] = boot(f[per["ceiling_half_a"] > 0])
                row[f"{arm}_minus_ceiling_points"] = boot((per[arm] - per["ceiling_half_a"]) * 100)
        out["metrics"][m] = row
    return out


# ------------------------------------------------------------------ person level
def cmd_person(a):
    """Stronger person-level ceiling: the same person's own comment on the most similar launch they commented on before D
    (bge-small embedding of name + tagline + description; comments written before D starts), judged by the POINT-1
    same-point judge (Claude Opus 5.5, 2 runs, majority; a 1-1 split counts as not the same point, as in POINT-1)."""
    from simharness.bench import Benchmark, day_ord, scrub, _day_bounds_utc
    from simharness.content_judge import ContentJudge
    from sentence_transformers import SentenceTransformer
    dirs = sorted(d for d in glob.glob(os.path.join(a.forward_root, "20*")) if os.path.exists(f"{d}/comments.parquet"))
    b = Benchmark(a.bench, overlays=dirs)
    R = pd.read_parquet(os.path.join(a.point1, "rows.parquet"))
    it = b.items.set_index("item_idx")
    txt = lambda i: f"{it.loc[i, 'title']}. {it.loc[i, 'summary']}. {str(it.loc[i, 'description'] or '')[:400]}"
    C = b.comments.copy()
    C["ts"] = pd.to_datetime(C["ts"], utc=True)
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    need = sorted(set(R.item_idx) | set(C[C.person_idx.isin(set(R.person_idx))].item_idx))
    E = dict(zip(need, m.encode([txt(i) for i in need], batch_size=128, normalize_embeddings=True)))
    own, sims, n_prev = [], [], []
    for r in R.itertuples():
        o = day_ord(r.day)
        start, _ = _day_bounds_utc(r.day, "America/Los_Angeles")
        h = C[(C.person_idx == r.person_idx) & (C.day_ord < o) & (C.ts.isna() | (C.ts < start)) & (C.item_idx != r.item_idx)]
        n_prev.append(len(h))
        if not len(h):
            own.append(None); sims.append(np.nan); continue
        sc = np.array([float(E[r.item_idx] @ E[i]) for i in h.item_idx])
        k = int(np.argmax(sc))
        own.append(scrub(" ".join(str(h.text.iloc[k]).split()))[:500]); sims.append(sc[k])
    R["own_similar_comment"], R["own_similar_sim"], R["n_prev_comments"] = own, sims, n_prev
    P = pd.DataFrame([{"pair_id": i, "launch": f"{it.loc[r.item_idx, 'title']} — {it.loc[r.item_idx, 'summary']}",
                       "real": scrub(" ".join(str(r.text).split()))[:500], "cand": r.own_similar_comment}
                      for i, r in enumerate(R.itertuples()) if isinstance(r.own_similar_comment, str) and r.own_similar_comment.strip()])
    j = ContentJudge(a.project, runs=2, cap_usd=a.budget)
    L = j.label(P)
    g = L.groupby("pair_id")["same_point"].agg(["sum", "size"])
    maj = (g["sum"] * 2 > g["size"]).astype(int)
    R["own_similar_same_point"] = [int(maj.get(i, 0)) if i in set(P.pair_id) else np.nan for i in range(len(R))]
    R["own_similar_tie"] = [bool((g["size"].get(i, 0) == 2) and (g["sum"].get(i, 0) == 1)) for i in range(len(R))]
    os.makedirs(a.work, exist_ok=True)
    R.drop(columns=["history", "launch_block"], errors="ignore").to_parquet(os.path.join(a.work, "person_rows.parquet"), index=False)
    L.to_parquet(os.path.join(a.work, "person_judge_runs.parquet"), index=False)
    json.dump({"judge_usd": round(j.usd, 4), "pairs": int(len(P)), "rows": int(len(R))}, open(os.path.join(a.work, "person_spend.json"), "w"))
    print("judge usd", round(j.usd, 3), "pairs", len(P))


def person_table(W, point1_dir):
    R = pd.read_parquet(os.path.join(W, "person_rows.parquet"))
    S = pd.read_parquet(os.path.join(point1_dir, "row_scores.parquet"))
    out = {"rows": int(len(R)), "rows_with_earlier_own_comment": int(R.own_similar_same_point.notna().sum()),
           "median_similarity_of_chosen_launch": round(float(R.own_similar_sim.median()), 3), "by_day": {}}

    def day_boot(df, col):
        days = sorted(df.day.unique())
        est = float(df[col].mean()) * 100
        vals = []
        for _ in range(2000):
            pick = RNG.choice(days, len(days))
            x = pd.concat([df[df.day == d] for d in pick])[col]
            vals.append(float(x.mean()) * 100)
        return {"mean": round(est, 2), "lo": round(float(np.percentile(vals, 2.5)), 2), "hi": round(float(np.percentile(vals, 97.5)), 2), "n": int(len(df))}
    arms = {}
    for arm in ("A0", "ref_other_commenter"):
        x = S[S.arm == arm][["row", "day", "same_point"]].rename(columns={"same_point": "sp"})
        arms[arm] = x
    own = pd.DataFrame({"row": range(len(R)), "day": R.day, "sp": R.own_similar_same_point}).dropna()
    arms["own_similar_comment"] = own
    out["same_point_all_rows"] = {k: day_boot(v, "sp") for k, v in arms.items()}
    rows_own = set(own.row)
    out["same_point_rows_with_own_comment"] = {k: day_boot(v[v.row.isin(rows_own)], "sp") for k, v in arms.items()}
    o = arms["own_similar_comment"].set_index("row").sp
    a0 = arms["A0"].set_index("row").sp
    rf = arms["ref_other_commenter"].set_index("row").sp
    common = sorted(rows_own & set(a0.index))
    out["A0_fraction_of_ceilings_on_common_rows"] = {
        "A0": round(float(a0[common].mean()) * 100, 2), "other_commenter": round(float(rf.reindex(common).mean()) * 100, 2),
        "own_similar_comment": round(float(o[common].mean()) * 100, 2), "n": len(common),
        "A0_over_other_commenter": round(float(a0[common].mean() / max(rf.reindex(common).mean(), 1e-9)), 3),
        "A0_over_own_similar": round(float(a0[common].mean() / max(o[common].mean(), 1e-9)), 3)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("launch")
    l.add_argument("--work", required=True)
    l.add_argument("--sim-dir", required=True)
    l.add_argument("--resamples", type=int, default=20)
    l.add_argument("--max-launches", type=int, default=1000)
    l.add_argument("--budget", type=float, default=4.0)
    pp = sub.add_parser("person")
    pp.add_argument("--work", required=True)
    pp.add_argument("--bench", required=True)
    pp.add_argument("--forward-root", required=True)
    pp.add_argument("--point1", required=True)
    pp.add_argument("--project", default="project-amer-scs-sandbox")
    pp.add_argument("--budget", type=float, default=1.0)
    t = sub.add_parser("table")
    t.add_argument("--work", required=True)
    t.add_argument("--point1", required=True)
    t.add_argument("--out-dir", required=True)
    t.add_argument("--sync")
    a = ap.parse_args(argv)
    if a.cmd == "launch":
        cmd_launch(a)
    elif a.cmd == "person":
        cmd_person(a)
    elif a.cmd == "table":
        res = {"version": "ceiling1_v1", "launch_level": launch_table(a.work), "person_level": person_table(a.work, a.point1),
               "spend": {"launch": json.load(open(f"{a.work}/launch_spend.json")), "person": json.load(open(f"{a.work}/person_spend.json"))}}
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(f"{a.out_dir}/ceiling1.json", "w"), indent=1)
        if a.sync:
            subprocess.run(["gsutil", "-q", "cp", f"{a.out_dir}/ceiling1.json", a.sync + "/ceiling1.json"], check=False)
        print(json.dumps(res, indent=1)[:8000])


if __name__ == "__main__":
    main()
