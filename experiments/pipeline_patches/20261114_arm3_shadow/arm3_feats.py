"""Arm 3 = arm 2 + the A + B + C 00:05 feature block (orchestrator 13:57Z Nov 14; replicated top 10 +1.9 [+0.9, +2.8] on 183 days,
pre-registered secondary top 3 not replicated). UNDEPLOYED: a shadow column pred_arm3 until Shreyas's direct word.
  A  within the day's line-up (at 00:05: the 00:05 line-up): same-topic count / share, max topic share, max / mean / top-3 bge-small
     cosine to the other launches, same-topic launches with more hunter followers / a higher hunter record, max cosine to a launch with
     more hunter followers, hunter-follower share inside the topic.
  B  launches on days <= d-2 (settled labels), 365-day window: nearest cosine (90 / 365 days), count cosine > 0.85, 10 nearest:
     mean log-votes, top-10 rate, similarity-weighted log-votes, mean log-votes minus the window mean.
  C  days <= d-2: same normalised name or same non-hosting domain: flag, count, days since, previous log-votes, best previous rank.
Embedding model pinned: BAAI/bge-small-en-v1.5 @ revision 5c38ec7c405ec4b44b94cc5a9bb96e735b38267a, CPU, normalised.
Text = "name. tagline. description[:400]. topic, topic".  Counts / ids only; no people.
API:  embed(texts) -> (n, 384) | add_feats(df, E, norm="plain") -> (df with NEW columns, NEW) | predict_arm3(day, base_pred) -> see below.
Fallback rule (production): if the model or the embeddings fail, the caller keeps arm 2's forecast unchanged (predict_arm3 raises; the
caller catches and writes pred_arm3 = NaN with the reason)."""
import os, re
from collections import defaultdict
import numpy as np, pandas as pd
MODEL, REV = "BAAI/bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
HOST = re.compile(r"(github\.(io|com)|vercel\.app|netlify\.app|apple\.com|google\.com|chromewebstore|notion\.(so|site)|framer\.(app|website)|webflow\.io|"
                  r"producthunt\.com|youtube\.com|x\.com|twitter\.com|linkedin\.com|medium\.com|substack\.com|gumroad\.com|figma\.com|huggingface\.co|"
                  r"pages\.dev|carrd\.co|bubbleapps\.io|replit\.app|lovable\.app|hugedomains\.com|dynadot\.com)")
_M = {}


def embed(texts, batch_size=64):
    if "m" not in _M:
        from sentence_transformers import SentenceTransformer
        _M["m"] = SentenceTransformer(MODEL, revision=REV, device="cpu")
    return np.asarray(_M["m"].encode(list(texts), batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)


def text_of(df):
    return (df.name.astype(str) + ". " + df.tagline.fillna("").astype(str) + ". " + df.description.fillna("").astype(str).str[:400] + ". "
            + df.topics.map(lambda t: ", ".join(t) if isinstance(t, (list, tuple, np.ndarray)) else "")).tolist()


def norm_name(n, mode="plain"):
    n = str(n).lower()
    if mode == "strong":   # the subagent's rule: cut at ':' '-' '|' '(' and drop ai / app / hq / io / version tokens
        n = re.split(r"[:\-–—|(]", n)[0]; n = re.sub(r"\b(ai|app|hq|io|v\d+|\d+(\.\d+)?)\b", " ", n)
    n = re.sub(r"[^a-z0-9]", "", n)
    return n if len(n) >= 3 else ""


def a_feats(idx, E, tops, hf, hr):
    """A for the launches idx (one day's line-up as given). Returns {row: {feature: value}}."""
    out = {}; n = len(idx); S = E[idx] @ E[idx].T; np.fill_diagonal(S, np.nan); cnt = defaultdict(int)
    for t in tops:
        for x in t: cnt[x] += 1
    for a, i in enumerate(idx):
        same = [b for b in range(n) if b != a and tops[a] & tops[b]]; s = S[a][~np.isnan(S[a])]
        st = [b for b in range(n) if b != a and hf[idx[b]] > hf[i]]
        out[i] = {"A_same_n": len(same), "A_same_share": len(same) / max(n - 1, 1), "A_topic_max_share": max([cnt[x] / n for x in tops[a]] or [0]),
                  "A_cos_max": float(np.max(s)) if len(s) else 0.0, "A_cos_mean": float(np.mean(s)) if len(s) else 0.0,
                  "A_cos_top3": float(np.mean(np.sort(s)[-3:])) if len(s) else 0.0,
                  "A_same_strong_fol": int(sum(hf[idx[b]] > hf[i] for b in same)), "A_same_strong_rec": int(sum(hr[idx[b]] > hr[i] for b in same)),
                  "A_cos_to_stronger": float(np.nanmax(S[a][st])) if st else 0.0, "A_fol_pct_in_topic": float(np.mean([hf[idx[b]] <= hf[i] for b in same + [a]]))}
    return out


def add_feats(df, E, norm="plain", line_up=None):
    """df: one row per launch with day, name, topics, ph_hunter_followers, hist_hunter_rel, votes, dailyRank, domain (optional);
    E: embeddings aligned with df rows (positional). line_up: optional boolean mask; for days where it is set, A is computed over the
    masked rows only (the 00:05 line-up). Labels (votes, dailyRank) are read only from days <= d-2. Returns (df copy, NEW columns)."""
    df = df.reset_index(drop=True).copy(); E = np.asarray(E)
    tops = [set(t) if isinstance(t, (list, tuple, np.ndarray)) else set() for t in df.topics]
    hf = df.ph_hunter_followers.fillna(-1).values; hr = df.hist_hunter_rel.fillna(-9).values
    A = {}
    for d, g in df.groupby("day"):
        ix = g.index.values
        if line_up is not None and line_up[ix].any(): ix = ix[line_up[ix]]
        A.update(a_feats(ix, E, [tops[i] for i in ix], hf, hr))
    AC = list(next(iter(A.values())).keys())
    for c in AC: df[c] = [A.get(i, {}).get(c, np.nan) for i in range(len(df))]
    dt = pd.to_datetime(df.day); logv = np.log1p(pd.to_numeric(df.votes, errors="coerce")).values; rk = pd.to_numeric(df.dailyRank, errors="coerce").values
    key = [norm_name(x, norm) for x in df.name]; dom = df.domain.fillna("").astype(str).values if "domain" in df else np.array([""] * len(df))
    BY = defaultdict(list)
    for j in range(len(df)):
        if key[j]: BY[("n", key[j])].append(j)
        if dom[j] and not HOST.search(dom[j]): BY[("d", dom[j])].append(j)
    BC = {}
    for d in sorted(df.day.unique()):
        cur = df.index[df.day == d].values; dd = pd.Timestamp(d)
        past = df.index[(dt <= dd - pd.Timedelta(days=2)) & (dt > dd - pd.Timedelta(days=365)) & np.isfinite(logv)].values
        if len(past):
            S = E[cur] @ E[past].T; wm = np.nanmean(logv[past]); m90 = (dt[past] > dd - pd.Timedelta(days=90)).values
        for a, i in enumerate(cur):
            o = {}
            if len(past):
                s = S[a]; nn = np.argsort(-s)[:10]; w = np.clip(s[nn], 0, None)
                o.update({"B_nn365": float(s.max()), "B_nn90": float(s[m90].max()) if m90.any() else 0.0, "B_n085": int((s > 0.85).sum()),
                          "B_nn10_logv": float(np.nanmean(logv[past[nn]])), "B_nn10_top10": float(np.nanmean(rk[past[nn]] <= 10)),
                          "B_nn10_wlogv": float(np.nansum(w * logv[past[nn]]) / (w.sum() or 1)), "B_nn10_rel": float(np.nanmean(logv[past[nn]]) - wm)})
            cand = set(BY.get(("n", key[i]), [])) | (set(BY.get(("d", dom[i]), [])) if dom[i] and not HOST.search(dom[i]) else set())
            prv = sorted([j for j in cand if dt[j] <= dd - pd.Timedelta(days=2)], key=lambda j: dt[j])
            o.update({"C_prev": int(bool(prv)), "C_prev_n": len(prv), "C_days_since": float((dd - dt[prv[-1]]).days) if prv else np.nan,
                      "C_prev_logv": float(logv[prv[-1]]) if prv else np.nan, "C_prev_best_rank": float(np.nanmin(rk[prv])) if prv and np.isfinite(rk[prv]).any() else np.nan})
            BC[i] = o
    BCC = ["B_n085", "B_nn10_logv", "B_nn10_rel", "B_nn10_top10", "B_nn10_wlogv", "B_nn365", "B_nn90", "C_days_since", "C_prev", "C_prev_best_rank", "C_prev_logv", "C_prev_n"]
    for c in BCC: df[c] = [BC.get(i, {}).get(c, np.nan) for i in range(len(df))]
    return df, AC + BCC
