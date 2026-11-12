"""Score one page read + raw HTML with the band v2 models frozen from band_facts.py (FREEZE=...; trained on launches <= Aug 31).
Same features as the test: B0 d_both score, 37 page facts, retrieval of the 30 nearest launches strictly before the day (run 1 sklearn,
run 2 pure-python TF-IDF), topic prior of months strictly before. Returns raw scores and percentiles vs the frozen OOF cuts."""
import math, re
from collections import Counter
import numpy as np, pandas as pd
from scipy import sparse

tok = lambda t: re.findall(r"\b[a-z0-9]+\b", t)
W = lambda p: re.compile(p, re.I)
TW = {"w_pricing": W(r"\bpricing\b|\bplans?\b|/mo\b|per month|\$\d"), "w_free": W(r"\bfree\b"), "w_trial": W(r"free trial|\btrial\b"),
      "w_opensource": W(r"open[- ]source|\bMIT license|apache 2"), "w_api": W(r"\bAPI\b|\bSDK\b"), "w_docs": W(r"\bdocs\b|documentation"),
      "w_login": W(r"\blog ?in\b|\bsign ?in\b"), "w_signup": W(r"sign ?up|get started|start for free"), "w_demo": W(r"book a demo|request a demo|schedule a demo|talk to sales|contact sales"),
      "w_enterprise": W(r"\benterprise\b|\bSOC ?2\b|\bSSO\b|\bGDPR\b"), "w_testimonial": W(r"testimonial|what (our )?(customers|users) say|loved by|trusted by|used by"),
      "w_logos": W(r"trusted by|backed by|as seen (on|in)|featured (in|on)"), "w_ai": W(r"\bAI\b|artificial intelligence"), "w_agent": W(r"\bagents?\b|agentic"),
      "w_llm": W(r"\bLLMs?\b|\bGPT|\bClaude\b|\bGemini\b|\bMCP\b"), "w_b2b": W(r"\bteams?\b|\bbusiness(es)?\b|\bB2B\b|\bcompan(y|ies)\b|\bworkflows?\b|\bcustomers\b|\bROI\b"),
      "w_consumer": W(r"\byour life\b|\bfamily\b|\bfriends\b|\bfun\b|\bhabits?\b|\bpersonal\b"), "w_waitlist": W(r"waitlist|wait list|coming soon|early access"),
      "w_download": W(r"\bdownload\b"), "w_mac": W(r"\bmacOS\b|\bMac\b"), "w_chrome": W(r"chrome extension|add to chrome"), "w_yc": W(r"Y ?Combinator|\bYC\b")}
LEAK = re.compile(r"(?i)product\s*hunt|product of the (day|week|month)|#\s*1\s*product|upvote")


def terms(n, t, d, tp):
    w = tok((f"{n}. {t}. {d} " + " ".join(tp)).lower()); return w + [a + " " + b for a, b in zip(w, w[1:])]


def tfidf(T, idf):
    ix = {t: k for k, t in enumerate(idf)}; data, ri, ci = [], [], []
    for r, ts in enumerate(T):
        c = Counter(t for t in ts if t in ix); x = {t: (1 + math.log(v)) * idf[t] for t, v in c.items()}; nm = math.sqrt(sum(v * v for v in x.values())) or 1.0
        for t, v in x.items(): data.append(v / nm); ri.append(r); ci.append(ix[t])
    return sparse.csr_matrix((data, (ri, ci)), shape=(len(T), len(idf)))


def facts(text, h):
    t = LEAK.sub(" ", text or ""); words = re.findall(r"[A-Za-z']+", t); nw = max(len(words), 1)
    we = sum(w.lower() in ("we", "our", "us", "we're", "we've") for w in words); ii = sum(w in ("I", "I'm", "I've", "my") for w in words)
    d = {"f_len": np.log1p(len(t)), "f_words": np.log1p(nw), "f_we": we / nw * 100, "f_i": ii / nw * 100, "f_nonascii": sum(ord(c) > 127 for c in t[:3000]) / max(len(t[:3000]), 1)}
    if h:
        hl = h.lower(); lang = (re.search(r'<html[^>]*\blang=["\']?([a-zA-Z]{2})', h) or [None, ""])[1].lower()
        d |= {"f_h1": len(re.findall(r"<h1\b", hl)), "f_h2": len(re.findall(r"<h[23]\b", hl)), "f_links": np.log1p(len(re.findall(r'href=["\']([^"\'#]+)["\']', h, re.I)[:400])),
              "f_appstore": int("apps.apple.com" in hl or "itunes.apple.com" in hl), "f_play": int("play.google.com" in hl), "f_github": int("github.com/" in hl),
              "f_social": sum(int(s in hl) for s in ("twitter.com/", "x.com/", "linkedin.com/", "discord.gg", "discord.com/invite", "youtube.com/", "instagram.com/", "tiktok.com/", "reddit.com/")),
              "f_lang_en": int(lang in ("", "en")), "f_img": np.log1p(hl.count("<img")), "f_form": int("<form" in hl)}
    for k, r in TW.items(): d[k] = int(bool(r.search(t)))
    return d


def score(F, read, html, day):
    VOC = F["VOCAB"]; L = F["L"]
    n, t = read.get("name") or "", read.get("tagline") or ""; ex = LEAK.sub(" ", read.get("page_excerpt") or ""); d = (read.get("summary") or "") + " " + ex[:1500]
    tp = [x for x in (read.get("topics") or []) if x in VOC][:4] or ["Productivity"]
    idf, mu0, sd0, m0 = F["b0"]
    De = np.array([[float(q in tp) for q in VOC] + [math.log1p(len(d)), math.log1p(len(t)), float(len(tp))]])
    b0 = float(m0.predict(sparse.hstack([tfidf([terms(n, t, d, tp)], idf), sparse.csr_matrix((De - mu0) / sd0), sparse.csr_matrix([[1.0]])]).tocsr())[0])
    fx = facts(ex, html); E = L[L.day < day]
    if F["retr"] == "sklearn": Q = F["vec"].transform([n + ". " + t + ". " + d]); P = F["vec"].transform(E.phtext)
    else:
        Q = tfidf([terms(n, t, d, [])], F["ridf"]); P = tfidf([terms(a or "", b or "", c or "", []) for a, b, c in zip(E.name, E.tagline, E.description)], F["ridf"])
    s = (Q @ P.T).toarray()[0]; o = np.argsort(-s)[:30]; w = np.clip(s[o], 1e-4, None); rp, y = E.rp.values[o], E.y.values[o]
    rr = [rp.mean(), (w * rp).sum() / w.sum(), (w * y).sum() / w.sum(), s[o].mean(), s[o[0]]]
    G = L[L.day < day[:7] + "-01"]; gm = G.rp.mean(); c, s_ = Counter(), Counter()
    for tps, r in zip(G.ptop, G.rp):
        for q in tps: c[q] += 1; s_[q] += r
    topic = float(np.mean([(s_[q] + 20 * gm) / (c[q] + 20) if q in c else gm for q in tp]))
    blocks = {"facts": [fx.get(k, np.nan) for k in F["FCOLS"]], "retr30": rr, "topic": [topic]}
    out = {"b0": b0, "b0_pct": int(sum(1 for x in F["b0_oof_cuts"] if x < b0))}
    for v, M in F["models"].items():
        x = np.array(sum((blocks[b] for b in M["blocks"]), []) + [b0], float); z = np.nan_to_num((x - M["mu"]) / M["sd"])
        sc = float(M["ridge"].predict(z[None])[0]); out[v] = {"score": sc, "pct": int(sum(1 for q in M["oof_cuts"] if q < sc))}
    return out
