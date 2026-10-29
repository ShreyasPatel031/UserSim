"""Does Gemini's reading of a launch page predict its real comments? Scores page_score.py predictions against the
labelled real comments (comment_label.py), each against a baseline that knows nothing about the page:
  mix          predicted share of each comment kind vs real share (rank correlation across launches; error vs the
               average mix of earlier launches)
  competitors  products Gemini expects visitors to compare it to vs products real commenters named
  questions    Gemini's 3 likely questions vs real question comments (meaning similarity), against the questions
               predicted for a random other launch with the same first topic
usage: python eval_comments.py -> results/eval_comments.json"""
import json, os, random, re, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pipeline import warehouse as W

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
KINDS = ["question", "bug", "pricing", "comparison", "privacy", "confusion", "praise", "other"]
norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())


def load():
    con = W.connect(do_sync=False)
    C = con.execute("SELECT launch_id, person, text FROM comments WHERE text IS NOT NULL").df()
    C["key"] = C.launch_id + "|" + C.person + "|" + C.text.str[:40]
    L = pd.DataFrame([json.loads(l) for l in open(f"{D}/comment_labels.jsonl")]).drop_duplicates("key")
    C = C.merge(L, on="key")
    P = {r["id"]: r for r in map(json.loads, open(f"{D}/page_scores.jsonl"))}
    top = dict(con.execute("SELECT id, json_extract_string(topics, '$[0]') FROM launches").fetchall())
    day = dict(con.execute("SELECT id, day FROM launches").fetchall())
    return C, P, top, day


def main():
    C, P, top, day = load()
    C = C[C.launch_id.isin(P)]
    G = {lid: g for lid, g in C.groupby("launch_id") if len(g) >= 5}
    out = {"launches": len(G), "comments": int(sum(len(g) for g in G.values()))}
    # mix
    real = pd.DataFrame({lid: g.kind.value_counts(normalize=True).reindex(KINDS).fillna(0) for lid, g in G.items()}).T
    pred = pd.DataFrame({lid: pd.Series((P[lid]["result"].get("comment_mix") or {})).reindex(KINDS).astype(float) for lid in G}).T
    real["day"] = real.index.map(day)
    mix = {}
    for k in KINDS:
        prior = real.sort_values("day")[k].expanding().mean().shift(1)     # earlier launches' average share: the baseline
        ok = pred[k].notna() & prior.reindex(pred.index).notna()
        mix[k] = {"real_mean": round(real[k].mean(), 3), "rank_corr": round(spearmanr(pred[k][ok], real[k][ok]).correlation, 3),
                  "error_pred": round((pred[k][ok] - real[k][ok]).abs().mean(), 3),
                  "error_baseline": round((prior.reindex(pred.index)[ok] - real[k][ok]).abs().mean(), 3)}
    out["mix"] = mix
    # competitors
    by_top = {}
    for lid in G:
        by_top.setdefault(top.get(lid), []).append(lid)
    rng = random.Random(0)
    hit, hit_b, n = 0, 0, 0
    for lid, g in G.items():
        named = {norm(x) for xs in g.named for x in xs if norm(x)}
        if not named:
            continue
        other = rng.choice([x for x in by_top[top.get(lid)] if x != lid] or [lid])
        f = lambda c: {norm(x) for x in (P[c]["result"].get("competitors") or []) if norm(x)}
        match = lambda pr: any(a in b or b in a for a in pr for b in named)
        n += 1; hit += match(f(lid)); hit_b += match(f(other))
    out["competitors"] = {"launches_with_named_products": n, "predicted_hits_one": round(hit / max(n, 1), 3),
                          "baseline_same_topic_other_launch": round(hit_b / max(n, 1), 3)}
    # questions
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    clean = lambda t: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))[:300]
    rows = []
    for lid, g in G.items():
        q = [clean(t) for t in g[g.kind == "question"].text]
        if not q:
            continue
        other = rng.choice([x for x in by_top[top.get(lid)] if x != lid] or [lid])
        rows.append((q, P[lid]["result"].get("questions") or [], P[other]["result"].get("questions") or []))
    best, best_b = [], []
    for q, pq, bq in rows:
        if not pq or not bq:
            continue
        E = m.encode(q + pq + bq, normalize_embeddings=True, batch_size=64)
        Q, A, B = E[:len(q)], E[len(q):len(q) + len(pq)], E[len(q) + len(pq):]
        best += list((Q @ A.T).max(1)); best_b += list((Q @ B.T).max(1))
    best, best_b = np.array(best), np.array(best_b)
    out["questions"] = {"real_questions": len(best), "mean_best_similarity": round(float(best.mean()), 3),
                        "baseline": round(float(best_b.mean()), 3),
                        "share_close_0.8": round(float((best > 0.8).mean()), 3), "baseline_share_close_0.8": round(float((best_b > 0.8).mean()), 3)}
    json.dump(out, open("results/eval_comments.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
