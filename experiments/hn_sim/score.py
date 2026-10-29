"""Score the pilot arms against what real commenters wrote.

- Real issues: the judge's points for every non-maker top-level comment (kind 'other' = off-topic, left out), merged
  into distinct issues per post.
- Simulated comments get the same labelling prompt (judge.label_one) as real ones.
- Matching uses the complaint-recall judge from experiments/staged_context/human_mode.py (JUDGE_SIDE: 2 = same
  specific point, 1 = same area, 0 = different; a match is a 2), worded for comment points. The judge never sees
  which arm wrote the points.
- recall = share of a post's distinct real issues matched by any of the arm's points; precision = share of the arm's
  points that match any real issue. Per person: does twin k's comment match its own real person's points (A) more
  often than shuffled twin k's (D)?
95% intervals: bootstrap over posts (paired differences).

    python score.py <post_id> ...
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import arms as A
import judge as J
import llm
import store as S

MERGE = """These are the points readers made in top-level comments on the Show HN post "{title}".
{points}
Merge them into the distinct issues readers raised (same specific point = one issue). Keep each issue specific.
Return {{"issues": [{{"issue": "<under 15 words>", "kind": "...", "ids": ["p1", ...]}}]}}"""

MATCH = """Readers of a Show HN product posted comments. Compare predicted comment points with the real readers' points.
Score each (predicted, actual) pair 2 = same specific point, 1 = same general area but vaguer, 0 = different.
Predicted points:
{pp}
Real readers' points:
{ap}
Return {{"pairs": [{{"pred": "P1", "act": "A1", "score": 2}}]}} listing only pairs scoring 1 or 2."""

ARMS = ["A_twin", "B_generic", "C_page", "D_shuffled"]


def pts(js: str) -> list[dict]:
    return [p for p in json.loads(js) if p.get("kind") != "other"]


def real_issues(post: dict, labels: pd.DataFrame) -> list[dict]:
    rows = [(r.comment_id, r.author, p) for r in labels.itertuples() for p in pts(r.points)]
    lines = "\n".join(f"p{i + 1}: [{p['kind']}] {p['point']}" for i, (_, _, p) in enumerate(rows))
    j = llm.call("merge_issues", MERGE.format(title=post["title"], points=lines), model=llm.FLASH, thinking=1024,
                 max_tokens=16000)
    out = []
    for it in j.get("issues") or []:
        idx = [int(str(x).lstrip("p")) - 1 for x in it.get("ids") or [] if str(x).lstrip("p").isdigit()]
        out.append({"issue": it.get("issue"), "kind": it.get("kind"),
                    "authors": sorted({rows[i][1] for i in idx if 0 <= i < len(rows)})})
    return out


def match(pred: list[str], act: list[str]) -> list[tuple[int, int]]:
    if not pred or not act:
        return []
    fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs))  # noqa: E731
    j = llm.call("match_judge", MATCH.format(pp=fmt(pred, "P"), ap=fmt(act, "A")), model=llm.FLASH, thinking=512,
                 system="You are a strict evaluator. Return JSON only.", max_tokens=8192)
    out = []
    for m in j.get("pairs") or []:
        try:
            if isinstance(m, dict) and m.get("score") == 2:
                out.append((int(str(m["pred"]).lstrip("P")) - 1, int(str(m["act"]).lstrip("A")) - 1))
        except (KeyError, ValueError):
            continue
    return out


def boot(d: np.ndarray, n: int = 10000) -> tuple[float, float, float]:
    rng = np.random.default_rng(0)
    m = rng.choice(d, (n, len(d))).mean(1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main(ids: list[int]) -> pd.DataFrame:
    allp = S.read("hn_posts").drop_duplicates("post_id").set_index("post_id")
    L = S.read("judge_labels").drop_duplicates(["source", "comment_id"])
    C = S.read("sim_comments")
    C = C[C.post_id.isin(ids)].drop_duplicates(["post_id", "arm", "slot"], keep="last")
    # label simulated comments with the same prompt as real ones
    with ThreadPoolExecutor(32) as ex:
        labs = list(ex.map(lambda r: J.label_one(dict(allp.loc[r["post_id"]], post_id=r["post_id"]), r["comment"]),
                           C.to_dict("records")))
    C = C.assign(points=[x["points"] for x in labs], kind=[x["kind"] for x in labs])
    S.write("judge_labels", C.assign(source="sim", judge=llm.FLASH, prompt="label_v1", labelled_on=S.now())[
        ["source", "post_id", "arm", "slot", "person", "judge", "prompt", "kind", "points", "labelled_on"]])
    rows, per = [], []

    def post_score(pid):
        post = dict(allp.loc[pid], post_id=pid)
        lab = L[(L.source == "real") & (L.post_id == pid)]
        issues = real_issues(post, lab)
        five = set(A.pick_people(post))
        out, pp = [], []
        for arm in ARMS:
            g = C[(C.post_id == pid) & (C.arm == arm)].sort_values("slot")
            sp = [p["point"] for js in g.points for p in pts(js)]
            for scope, R in (("all", issues), ("five", [i for i in issues if five & set(i["authors"])])):
                m = match(sp, [i["issue"] for i in R])
                out.append({"post_id": pid, "arm": arm, "scope": scope, "n_real": len(R), "n_sim": len(sp),
                            "recall": len({a for _, a in m}) / len(R) if R else np.nan,
                            "precision": len({p for p, _ in m}) / len(sp) if sp else 0.0})
        # per person: slot k's comment vs real person k's own points (A twin of k vs D shuffled slot k)
        people = A.pick_people(post)
        for k, person in enumerate(people):
            own = [p["point"] for js in lab[lab.author == person].points for p in pts(js)]
            for arm in ("A_twin", "D_shuffled"):
                g = C[(C.post_id == pid) & (C.arm == arm) & (C.slot == k)]
                sp = [p["point"] for js in g.points for p in pts(js)]
                pp.append({"post_id": pid, "slot": k, "arm": arm, "match": float(bool(match(sp, own))) if own and sp else np.nan})
        return out, pp, issues
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(post_score, ids))
    for o, pp, _ in res:
        rows += o
        per += pp
    D, P = pd.DataFrame(rows), pd.DataFrame(per)
    S.write("hn_scores", D.assign(kind="post_arm", scored_on=S.now()))
    S.write("hn_scores", P.assign(kind="per_person", scored_on=S.now()))
    usd = llm.flush_spend("hn_pilot_score", f"{len(ids)} posts scored")
    print(f"scoring ${usd:.3f}; real distinct issues per post: {np.mean([len(x[2]) for x in res]):.1f}")
    for scope in ("all", "five"):
        t = D[D.scope == scope].pivot_table(index="post_id", columns="arm", values=["recall", "precision"])
        print(f"\n== scope {scope}: mean over {len(t)} posts")
        print(t.mean().unstack(0).round(3).to_string())
        for b in ("B_generic", "C_page", "D_shuffled"):
            d = (t["recall"]["A_twin"] - t["recall"][b]).dropna().to_numpy()
            m, lo, hi = boot(d)
            print(f"recall A - {b}: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), A better on {(d > 0).sum()}/{len(d)}")
    pt = P.pivot_table(index=["post_id", "slot"], columns="arm", values="match").dropna()
    d = (pt["A_twin"] - pt["D_shuffled"]).groupby(level=0).mean().to_numpy()
    m, lo, hi = boot(d)
    print(f"\nper person match: A {pt['A_twin'].mean():.3f} vs D {pt['D_shuffled'].mean():.3f}; "
          f"A - D {m:+.3f} (95% CI over posts {lo:+.3f} to {hi:+.3f}), n={len(pt)} people")
    return D


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]])
