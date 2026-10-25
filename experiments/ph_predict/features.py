"""One row per featured launch. Labels: votes, dailyRank, weeklyRank, monthlyRank, comments (never features).
Feature columns are prefixed by source so ablations can drop a whole source:
  ph_     Product Hunt audience/metadata (hunter, makers, media, topics, day context)
  txt_    pitch text (name, tagline, description) — handled as TF-IDF inside the model
  web_    launch-day website (Wayback snapshot day before launch, else live site)
  dom_    domain/age (RDAP registration, Wayback first capture)
  x_      X/Twitter audience of hunter + makers
  hn_     Hacker News mentions of the domain before launch
  comp_   competitors: how similar earlier PH launches did (computed from strictly earlier days)
  llm_    LLM judgements (pitch only / with website)
  hist_   track record of the hunter and makers on earlier PH launches"""
import datetime as dt, glob, json, math, os, re
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _jl(name, key="key"):
    f = f"{D}/{name}"
    return {r[key]: r for r in map(json.loads, open(f))} if os.path.exists(f) else {}


def domain(url):
    h = re.sub(r"^https?://", "", url or "").split("/")[0].split(":")[0].lower()
    return h[4:] if h.startswith("www.") else h


def _days(a, b):
    try:
        return (pd.Timestamp(a).tz_localize(None) - pd.Timestamp(b).tz_localize(None)).days
    except Exception:  # noqa: BLE001
        return np.nan


def _ts(s):
    try:
        return pd.Timestamp(s).tz_localize(None) if pd.Timestamp(s).tzinfo is None else pd.Timestamp(s).tz_convert(None)
    except Exception:  # noqa: BLE001
        return pd.NaT


BADGE = re.compile(r"(?is)<a[^>]*producthunt\.com[^>]*>.*?</a>|<img[^>]*producthunt[^>]*>|<iframe[^>]*producthunt[^>]*>")
LEAK_WORDS = re.compile(r"(?i)product\s*hunt|product of the (day|week|month)|#\s*1\s*product|upvote")


def site_text(html):
    html = BADGE.sub(" ", html or "")
    html = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()
    return LEAK_WORDS.sub(" ", t)


def web_feats(rec):
    html = rec.get("html") or ""
    low = html.lower()
    txt = site_text(html)
    f = {
        "web_src_wayback": float(rec.get("src") == "wayback"),
        "web_src_live": float(rec.get("src") == "live"),
        "web_dead": float(not html),
        "web_html_kb": len(html) / 1000,
        "web_text_words": len(txt.split()),
        "web_n_links": low.count("<a "),
        "web_n_img": low.count("<img"),
        "web_has_pricing": float(bool(re.search(r"pricing|/month|per month|\$\d", low))),
        "web_has_free": float("free trial" in low or "get started for free" in low or "free forever" in low),
        "web_has_github": float("github.com/" in low),
        "web_has_discord": float("discord.gg" in low or "discord.com/invite" in low),
        "web_has_testimonials": float(bool(re.search(r"trusted by|testimonial|loved by|what our (users|customers)", low))),
        "web_has_waitlist": float("waitlist" in low or "join the wait" in low),
        "web_has_appstore": float("apps.apple.com" in low or "play.google.com" in low),
        "web_has_chrome": float("chromewebstore" in low or "chrome.google.com/webstore" in low),
        "web_has_video": float("<video" in low or "youtube.com/embed" in low or "vimeo" in low),
        "web_framer": float("framer" in low), "web_webflow": float("webflow" in low),
        "web_nextjs": float("__next" in low or "_next/static" in low), "web_wix": float("wix.com" in low),
        "web_has_blog": float("/blog" in low), "web_has_docs": float("/docs" in low),
        "web_has_login": float(bool(re.search(r">\s*(log ?in|sign ?in)\s*<", low))),
    }
    return f, txt


def build(include_today=False):
    rows, sites = [], _jl("sites.jsonl", "id")
    sites.update(_jl("sites_today.jsonl", "id"))
    xs, rd, hn = _jl("ext_x.jsonl"), _jl("ext_rdap.jsonl"), _jl("ext_hn.jsonl")
    llm = _jl("llm.jsonl", "id")
    wbav = _jl("ext_wb.jsonl")
    cmf = json.load(open(f"{D}/cm_features.json")) if os.path.exists(f"{D}/cm_features.json") else {}
    audf = json.load(open(f"{D}/aud_features.json")) if os.path.exists(f"{D}/aud_features.json") else {}
    import external as E
    files = sorted(glob.glob(f"{D}/days/*.json")) + (sorted(glob.glob(f"{D}/today/*.json")) if include_today else [])
    for fn in files:
        day = os.path.basename(fn)[:10]
        is_today = "/today/" in fn
        posts = json.load(open(fn))
        for p in posts:
            t = _ts(p["featuredAt"] or p["createdAt"])
            mk = p.get("makers") or []
            hunter = p.get("user") or {}
            topics = [e["node"]["name"] for e in p["topics"]["edges"]]
            r = {"id": p["id"], "day": day, "name": p["name"], "tagline": p["tagline"] or "",
                 "description": p.get("description") or "", "topics": topics,
                 "votes": p["votesCount"], "comments": p["commentsCount"], "dailyRank": p["dailyRank"],
                 "weeklyRank": p["weeklyRank"], "monthlyRank": p["monthlyRank"],
                 "hunter_id": hunter.get("id"), "maker_ids": [m["id"] for m in mk], "is_today": is_today}
            if is_today:  # results not final: never a label, never history
                r.update(votes=np.nan, comments=np.nan, dailyRank=np.nan, weeklyRank=np.nan, monthlyRank=np.nan)
            mf = [m.get("followersCount") or 0 for m in mk]
            r.update({
                "ph_hunter_followers": math.log1p(hunter.get("followersCount") or 0),
                "ph_maker_max_followers": math.log1p(max(mf, default=0)),
                "ph_maker_sum_followers": math.log1p(sum(mf)),
                "ph_n_makers": len(mk),
                "ph_self_hunted": float(hunter.get("id") in {m["id"] for m in mk}),
                "ph_hunter_age_d": _days(t, hunter.get("createdAt")),
                "ph_maker_max_age_d": max([_days(t, m.get("createdAt")) for m in mk] or [np.nan]),
                "ph_maker_min_age_d": min([_days(t, m.get("createdAt")) for m in mk] or [np.nan]),
                "ph_n_makers_new": sum(_days(t, m.get("createdAt")) < 30 for m in mk),
                "ph_n_media": len(p.get("media") or []),
                "ph_has_video": float(any(m["type"] == "video" for m in p.get("media") or [])),
                "ph_n_topics": len(topics), "ph_weekday": t.weekday(), "ph_day_n_launches": len(posts),
                "ph_month": t.month,
                "ph_desc_len": len(r["description"]), "ph_tagline_len": len(r["tagline"]),
                "ph_name_len": len(p["name"]),
                "ph_maker_has_headline": float(any(m.get("headline") for m in mk)),
            })
            # X audience
            tw = [hunter.get("twitterUsername")] + [m.get("twitterUsername") for m in mk]
            xf = [xs.get((u or "").strip().lstrip("@"), {}) for u in tw]
            fol = [x.get("followers") or 0 for x in xf[1:]]
            r.update({"x_hunter_followers": math.log1p(xf[0].get("followers") or 0),
                      "x_maker_max_followers": math.log1p(max(fol, default=0)),
                      "x_maker_sum_followers": math.log1p(sum(fol)),
                      "x_n_makers_with_x": sum(1 for u in tw[1:] if u),
                      "x_any_verified": float(any(x.get("verified") for x in xf))})
            s = sites.get(p["id"], {})
            dom = domain(s.get("url"))
            r["domain"] = dom
            wf, txt = web_feats(s)
            r.update(wf)
            r["web_text"] = txt[:6000]
            tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
            reg = rd.get(dom, {}).get("registered")
            r.update({
                "dom_has_site": float(bool(dom)),
                "dom_age_d": _days(t, reg) if reg else np.nan,
                "dom_tld_ai": float(tld == "ai"), "dom_tld_com": float(tld == "com"),
                "dom_tld_io": float(tld == "io"), "dom_tld_app": float(tld == "app"), "dom_tld_dev": float(tld == "dev"),
                "dom_subpath": float(bool(re.sub(r"^https?://[^/]+/?", "", s.get("url") or "").strip("/"))),
                "dom_wb_captures": math.log1p(s.get("wb_n_before") or 0),
                "dom_wb_first_age_d": _days(t, pd.Timestamp(s["wb_first"][:8])) if s.get("wb_first") else np.nan,
                "dom_github_hosted": float("github.com" in dom or "github.io" in dom),
                "dom_apple_hosted": float("apple.com" in dom), "dom_chrome_hosted": float("chrome" in dom),
            })
            xh = E.site_handles(s.get("html"))[0]
            cx = xs.get(xh, {}) if xh else {}
            r["x_company_followers"] = math.log1p(cx.get("followers") or 0) if xh else np.nan
            r["x_company_has_x"] = float(bool(xh))
            eve = (pd.Timestamp(day) - pd.Timedelta(days=1)).strftime("%Y%m%d")
            w = wbav.get(f"{dom}|{eve}", {})
            r["dom_wb_has_before"] = float(bool(w.get("wb_ts"))) if w else np.nan
            r["dom_wb_snap_age_d"] = _days(t, pd.Timestamp(w["wb_ts"][:8])) if w.get("wb_ts") else np.nan
            h = hn.get(f"{dom}|{day}", {})
            r.update({"hn_n": math.log1p(h.get("hn_n") or 0), "hn_points": math.log1p(h.get("hn_points") or 0),
                      "hn_comments": math.log1p(h.get("hn_comments") or 0)})
            l = llm.get(p["id"], {})
            for k, v in l.items():
                if k.startswith("llm_"):
                    r[k] = v
            r.update(cmf.get(p["id"], {}))  # cm_: commenter network (commenters.py), pre-launch comments only
            r.update(audf.get(p["id"], {}))  # aud_: predicted audience from people's history (audience.py)
            rows.append(r)
    df = pd.DataFrame(rows)
    df = add_history(df)
    df["ph_hunter_n_same_day"] = df.groupby(["day", "hunter_id"]).id.transform("count")
    for c in ["ph_hunter_followers", "ph_hunter_age_d", "ph_n_makers", "ph_n_media", "x_hunter_followers",
              "x_maker_max_followers", "x_company_followers", "hist_hunter_rel", "hist_maker_rel_max",
              "dom_age_d", "web_text_words"]:
        df[c.split("_")[0] + "_dayrank_" + c] = df.groupby("day")[c].rank(pct=True)
    df["week"] = pd.to_datetime(df.day).dt.strftime("%G-W%V")
    df["mon"] = df.day.str[:7]
    df["logv"] = np.log1p(df.votes)
    return df


def add_history(df):
    """hist_: how the hunter's and makers' EARLIER launches did (other launches only; strictly earlier days, so
    it is known before launch). rel = log votes minus that day's mean; top5 = finished top 5 that day."""
    df = df.sort_values("day").reset_index(drop=True)
    df["_rel"] = np.log1p(df.votes) - df.groupby("day").votes.transform(lambda v: np.log1p(v).mean())
    df["_top5"] = (df.dailyRank <= 5).astype(float)
    H, Mk = {}, {}
    feats = []
    for day, g in df.groupby("day", sort=True):
        for _, r in g.iterrows():
            h = H.get(r.hunter_id, [])
            ms = [x for m in r.maker_ids for x in Mk.get(m, [])]
            feats.append({
                "hist_hunter_n": len(h), "hist_hunter_rel": np.mean([x[0] for x in h]) if h else np.nan,
                "hist_hunter_top5": np.mean([x[1] for x in h]) if h else np.nan,
                "hist_maker_n": len(ms), "hist_maker_rel_max": max([x[0] for x in ms]) if ms else np.nan,
                "hist_maker_top5": np.mean([x[1] for x in ms]) if ms else np.nan})
        for _, r in g.iterrows():  # add today's results only after the whole day is featurised
            H.setdefault(r.hunter_id, []).append((r._rel, r._top5))
            for m in set(r.maker_ids):
                Mk.setdefault(m, []).append((r._rel, r._top5))
    return pd.concat([df, pd.DataFrame(feats, index=df.index)], axis=1).drop(columns=["_rel", "_top5"])
