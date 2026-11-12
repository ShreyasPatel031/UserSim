"""Reference scorer for launch_band_page_v2 (pure python + numpy; no sklearn). The website can copy this as is.
    bundle = json.load(open("launch_band_page_v2.json")); pool = np.load("launch_band_page_v2_pool.npz")
    out = score_v2(bundle, pool, read, raw_html)   # read: the site's page read (name, tagline, summary, page_excerpt, topics)
returns {"score", "percentile", "band": [p10, p50, p90]}. raw_html may be "" (the HTML facts then take the training means)."""
import html as _html, math, re
from collections import Counter
import numpy as np

LEAK = re.compile(r"(?i)product\s*hunt|product of the (day|week|month)|#\s*1\s*product|upvote")
tok = lambda t: re.findall(r"\b[a-z0-9]+\b", t)


def terms(n, t, d, tp):
    w = tok((f"{n}. {t}. {d} " + " ".join(tp)).lower()); return w + [a + " " + b for a, b in zip(w, w[1:])]


def tfidf_vec(ts, idf):
    c = Counter(t for t in ts if t in idf); x = {t: (1 + math.log(v)) * idf[t] for t, v in c.items()}; nm = math.sqrt(sum(v * v for v in x.values())) or 1.0
    return {t: v / nm for t, v in x.items()}


def b0_score(lb, n, t, d, tp):   # identical to try_sim._band_score
    x = tfidf_vec(terms(n, t, d, tp), {k: v[0] for k, v in lb["vocab"].items()})
    s = lb["intercept"] + sum(lb["vocab"][k][1] * v for k, v in x.items())
    dn = [1.0 if q in tp else 0.0 for q in lb["topics_order"]] + [math.log1p(len(d)), math.log1p(len(t)), float(len(tp))]
    return s + sum(c * (v - m) / (sd or 1.0) for v, m, sd, c in zip(dn, lb["dense_mean"], lb["dense_sd"], lb["dense_coef"]))


def facts(bundle, text, h):
    t = LEAK.sub(" ", text or ""); words = re.findall(r"[A-Za-z']+", t); nw = max(len(words), 1)
    we = sum(w.lower() in ("we", "our", "us", "we're", "we've") for w in words); ii = sum(w in ("I", "I'm", "I've", "my") for w in words)
    d = {"f_len": math.log1p(len(t)), "f_words": math.log1p(nw), "f_we": we / nw * 100, "f_i": ii / nw * 100, "f_nonascii": sum(ord(c) > 127 for c in t[:3000]) / max(len(t[:3000]), 1)}
    if h:
        hl = h.lower(); m = re.search(r'<html[^>]*\blang=["\']?([a-zA-Z]{2})', h); lang = m.group(1).lower() if m else ""
        d |= {"f_h1": len(re.findall(r"<h1\b", hl)), "f_h2": len(re.findall(r"<h[23]\b", hl)), "f_links": math.log1p(len(re.findall(r'href=["\']([^"\'#]+)["\']', h, re.I)[:400])),
              "f_appstore": int("apps.apple.com" in hl or "itunes.apple.com" in hl), "f_play": int("play.google.com" in hl), "f_github": int("github.com/" in hl),
              "f_social": sum(int(s in hl) for s in ("twitter.com/", "x.com/", "linkedin.com/", "discord.gg", "discord.com/invite", "youtube.com/", "instagram.com/", "tiktok.com/", "reddit.com/")),
              "f_lang_en": int(lang in ("", "en")), "f_img": math.log1p(hl.count("<img")), "f_form": int("<form" in hl)}
    for k, p in bundle["word_facts"].items(): d[k] = int(bool(re.search(p, t, re.I)))
    return d


def retrieval(bundle, pool, n, t, d, k=30):
    q = tfidf_vec(terms(n, t, d, []), bundle["retrieval_idf"])
    if not q: return [float("nan")] * 5
    ix = bundle["retrieval_index"]; qv = np.zeros(len(ix), np.float32)
    for term, v in q.items(): qv[ix[term]] = v
    indptr, indices, data = pool["indptr"], pool["indices"], pool["data"].astype(np.float32)
    s = np.zeros(len(indptr) - 1, np.float32); np.add.at(s, np.repeat(np.arange(len(indptr) - 1), np.diff(indptr)), data * qv[indices])
    o = np.argsort(-s)[:k]; w = np.clip(s[o], 1e-4, None); rp, y = pool["rp"].astype(float)[o], pool["y"].astype(float)[o]
    return [rp.mean(), (w * rp).sum() / w.sum(), (w * y).sum() / w.sum(), float(s[o].mean()), float(s[o[0]])]


def score_v2(bundle, pool, read, raw_html=""):
    n, t = read.get("name") or "", read.get("tagline") or ""; excerpt = LEAK.sub(" ", read.get("page_excerpt") or "")
    d = (read.get("summary") or "") + " " + excerpt[:1500]; tp = [x for x in (read.get("topics") or []) if x in bundle["b0"]["topics_order"]][:4] or ["Productivity"]
    f = facts(bundle, excerpt, raw_html); tpri = bundle["topic_prior"]; r = retrieval(bundle, pool, n, t, d)
    x = [f.get(c, float("nan")) for c in bundle["facts"]] + r + [float(np.mean([tpri.get(q, tpri["_global"]) for q in tp]))] + [b0_score(bundle["b0"], n, t, d, tp)]
    st = bundle["stack"]; z = [(v - m) / s if v == v else 0.0 for v, m, s in zip(x, st["mu"], st["sd"])]
    sc = st["intercept"] + sum(c * v for c, v in zip(st["coef"], z)); p = sum(1 for c in bundle["score_percentile_cuts"] if c < sc)
    return {"score": sc, "percentile": p, "band": bundle["bands"][min(9, p // 10)]["daily_rank_p10_p50_p90"]}
