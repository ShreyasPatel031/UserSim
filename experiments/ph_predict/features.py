"""One row per featured launch: labels plus feature groups, each group one data source.

Never used as features: the launch's own votes, comments, reviews or ranks (they are the labels). Everything
historical (maker / hunter track record, topic and look-alike history) only looks at launches on earlier days.

Groups:
  launch   PH listing as submitted: topics, tagline/description, media, links, launch hour, weekday, day's field size
  people   hunter and makers: account age, self-hunt, Twitter linked, headline words
  followers  hunter and maker follower counts -- TODAY's counts, so they include followers won by the launch itself
           (possible leak); reported separately and left out of the headline model
  history  makers' and hunter's earlier launches in the data, topic track record, look-alike earlier launches
  site     the homepage (Apify crawl): domain, size, social proof / pricing / open-source words
  llm      Gemini's read of the listing + homepage (llm_scores.py)
  hn       Hacker News stories linking the domain before launch day (external.py)
  domain   age of the product's domain on launch day (RDAP, external.py)
  github   GitHub-hosted products: stars before launch day, repo age (external.py)
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
PT = ZoneInfo("America/Los_Angeles")
TOP_TOPICS = 40
SITE_WORDS = {
    "w_pricing": r"\bpricing\b|\bper month\b|/mo\b|\bplans?\b",
    "w_free": r"\bfree\b",
    "w_open_source": r"open[- ]source|github",
    "w_social_proof": r"trusted by|used by|loved by|customers|teams at|companies",
    "w_testimonial": r"testimonial|what (our )?(users|customers) say|★|stars?\b",
    "w_backed": r"backed by|y ?combinator|\byc\b|seed|series [ab]|investors?",
    "w_ai": r"\bai\b|\bagent|\bllm|gpt|claude|gemini",
    "w_waitlist": r"waitlist|join the list|early access|coming soon",
    "w_download": r"download|app store|google play|chrome extension|for mac",
    "w_api": r"\bapi\b|\bsdk\b|developers?",
    "w_enterprise": r"enterprise|soc ?2|gdpr|security",
}
LISTING_WORDS = {"t_ai": r"\bai\b|agent|llm|gpt", "t_open_source": r"open[- ]source", "t_free": r"\bfree\b",
                 "t_mac": r"\bmac(?:os)?\b", "t_chrome": r"chrome|extension", "t_api": r"\bapi\b|\bsdk\b|mcp"}
PH_LEAK = re.compile(r"[^.]*(product ?hunt|product of the (day|week|month)|#\s?1 product)[^.]*\.?", re.I)


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(PT) if s else None


def load_posts() -> pd.DataFrame:
    rows = []
    for f in sorted((CACHE / "ph_days").glob("*.json")):
        day = json.loads(f.read_text())
        n_featured = len(day["edges"])
        # Ranks are final only if fetched after the PT day closed (live days are collected mid-day).
        closed = datetime.fromisoformat(day["fetched_at"]) >= datetime.fromisoformat(day["day"]).replace(
            tzinfo=PT) + pd.Timedelta(days=1)
        for e in day["edges"]:
            n = e["node"]
            t = _ts(n["featuredAt"] or n["createdAt"])
            created = _ts(n["createdAt"])
            topics = [x["node"]["name"] for x in n["topics"]["edges"]]
            makers = n.get("makers") or []
            hunter = n.get("user") or {}
            rows.append({
                "id": n["id"], "name": n["name"], "slug": n["slug"], "day": day["day"], "complete": closed, "tagline": n["tagline"] or "",
                "description": n["description"] or "", "topics": topics, "website": n["website"],
                "dailyRank": n["dailyRank"], "weeklyRank": n["weeklyRank"], "monthlyRank": n["monthlyRank"],
                "votes": n["votesCount"],
                "hour": created.hour + created.minute / 60 if created else np.nan,
                "weekday": t.weekday(), "scheduled": int(bool(n.get("scheduledAt"))), "n_featured_day": n_featured,
                "n_media": len(n.get("media") or []),
                "has_video": int(any((m.get("videoUrl") or m.get("type") == "video") for m in n.get("media") or [])),
                "links": [l["type"] for l in n.get("productLinks") or []],
                "hunter": hunter.get("username"), "hunter_followers": hunter.get("followersCount"),
                "hunter_created": hunter.get("createdAt"), "hunter_twitter": int(bool(hunter.get("twitterUsername"))),
                "makers": [m.get("username") for m in makers],
                "maker_followers": [m.get("followersCount") or 0 for m in makers],
                "maker_created": [m.get("createdAt") for m in makers],
                "maker_twitter": sum(bool(m.get("twitterUsername")) for m in makers),
                "maker_headlines": " | ".join(m.get("headline") or "" for m in makers)})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df.day)
    # PH weekly leaderboard weeks run Monday-Sunday; monthly by calendar month.
    df["week"] = (df.date - pd.to_timedelta(df.date.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    df["month"] = df.date.dt.strftime("%Y-%m")
    # The API returns each day in PH's ranking order; shuffle so ties in any score can't be broken by the answer.
    return df.drop_duplicates("id").sample(frac=1, random_state=0).reset_index(drop=True)


def launch_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["launch_hour"] = df.hour
    f["launch_weekday"] = df.weekday
    f["launch_weekend"] = (df.weekday >= 5).astype(int)
    f["launch_scheduled"] = df.scheduled
    f["launch_n_featured_day"] = df.n_featured_day
    f["launch_n_topics"] = df.topics.str.len()
    f["launch_tagline_words"] = df.tagline.str.split().str.len()
    f["launch_desc_words"] = df.description.str.split().str.len()
    f["launch_n_media"] = df.n_media
    f["launch_has_video"] = df.has_video
    f["launch_n_links"] = df.links.str.len()
    for t in ("Github", "Twitter", "App Store", "Play Store", "Website"):
        f[f"launch_link_{t.lower().replace(' ', '_')}"] = df.links.apply(lambda ls, t=t: int(t in ls))
    text = (df.name + " " + df.tagline + " " + df.description).str.lower()
    for k, rx in LISTING_WORDS.items():
        f[f"launch_{k}"] = text.str.contains(rx, regex=True).astype(int)
    common = pd.Series([t for ts in df.topics for t in ts]).value_counts().index[:TOP_TOPICS]
    for t in common:
        f["launch_topic_" + re.sub(r"\W+", "_", t.lower()).strip("_")] = df.topics.apply(lambda ts, t=t: int(t in ts))
    return f


def _age_days(created: str | None, day: pd.Timestamp) -> float:
    return (day.tz_localize(PT) - _ts(created)).days if created else np.nan


def people_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["people_n_makers"] = df.makers.str.len()
    f["people_self_hunted"] = [int(h in ms) for h, ms in zip(df.hunter, df.makers)]
    f["people_hunter_age_days"] = [_age_days(c, d) for c, d in zip(df.hunter_created, df.date)]
    f["people_maker_age_max_days"] = [max([_age_days(c, d) for c in cs if c] or [np.nan]) for cs, d in
                                      zip(df.maker_created, df.date)]
    f["people_maker_twitter"] = df.maker_twitter
    f["people_hunter_twitter"] = df.hunter_twitter
    h = df.maker_headlines.str.lower()
    f["people_founder_headline"] = h.str.contains(r"founder|ceo", regex=True).astype(int)
    f["people_yc_headline"] = h.str.contains(r"\byc\b|y combinator|\(s2\d|\(w2\d|\(f2\d|\(x2\d", regex=True).astype(int)
    return f


def follower_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["followers_hunter_log"] = np.log1p(df.hunter_followers.fillna(0))
    f["followers_maker_max_log"] = df.maker_followers.apply(lambda x: math.log1p(max(x) if x else 0))
    f["followers_maker_sum_log"] = df.maker_followers.apply(lambda x: math.log1p(sum(x)))
    return f


def history_features(df: pd.DataFrame) -> pd.DataFrame:
    """Track records from earlier days only (strictly before the launch's day)."""
    f = pd.DataFrame(index=df.index, dtype=float)
    order = df.sort_values("date").index
    person_hist: dict[str, list[tuple[pd.Timestamp, int]]] = defaultdict(list)
    topic_hist: dict[str, list[tuple[pd.Timestamp, int]]] = defaultdict(list)
    cols = defaultdict(dict)
    for day, idx in df.loc[order].groupby("date", sort=True).groups.items():
        for i in idx:  # read history before writing this day's results
            r = df.loc[i]
            people = set(r.makers) | {r.hunter}
            m_prev = [x for p in r.makers for x in person_hist.get(p, [])]
            h_prev = person_hist.get(r.hunter, [])
            cols["hist_maker_prior_launches"][i] = len(m_prev)
            cols["hist_maker_prior_top10_rate"][i] = np.mean([x[1] <= 10 for x in m_prev]) if m_prev else np.nan
            cols["hist_maker_prior_best_rank"][i] = min(x[1] for x in m_prev) if m_prev else np.nan
            cols["hist_hunter_prior_hunts"][i] = len(h_prev)
            cols["hist_hunter_prior_top10_rate"][i] = np.mean([x[1] <= 10 for x in h_prev]) if h_prev else np.nan
            t_rates = []
            for t in r.topics:
                recent = [x[1] for x in topic_hist.get(t, []) if (day - x[0]).days <= 60]
                if len(recent) >= 5:
                    t_rates.append(np.mean([x <= 10 for x in recent]))
            cols["hist_topic_top10_rate_max"][i] = max(t_rates) if t_rates else np.nan
            cols["hist_topic_top10_rate_mean"][i] = np.mean(t_rates) if t_rates else np.nan
            del people
        for i in idx:
            r = df.loc[i]
            rank = r.dailyRank if pd.notna(r.dailyRank) else 999
            for p in set(r.makers) | {r.hunter}:
                if p:
                    person_hist[p].append((day, rank))
            for t in r.topics:
                topic_hist[t].append((day, rank))
    for c, vals in cols.items():
        f[c] = pd.Series(vals)
    f["hist_maker_is_repeat"] = (f.hist_maker_prior_launches > 0).astype(int)
    f = f.join(lookalike_features(df))
    return f


def lookalike_features(df: pd.DataFrame, k: int = 20) -> pd.DataFrame:
    """Competitors on PH: the k most similar earlier launches (TF-IDF on name + tagline + description + topics)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    text = df.tagline + " " + df.description + " " + df.topics.str.join(" ")
    X = TfidfVectorizer(min_df=2, max_features=30000, ngram_range=(1, 2), stop_words="english").fit_transform(text)
    top10 = (df.dailyRank.fillna(999) <= 10).to_numpy()
    top3 = (df.dailyRank.fillna(999) <= 3).to_numpy()
    dates = df.date.to_numpy()
    out = np.full((len(df), 3), np.nan)
    sims = (X @ X.T).tocsr()
    for i in range(len(df)):
        row = sims.getrow(i)
        js, vs = row.indices, row.data
        keep = dates[js] < dates[i]
        js, vs = js[keep], vs[keep]
        if len(js) < 5:
            continue
        o = np.argsort(-vs)[:k]
        js, vs = js[o], vs[o]
        out[i] = [top10[js].mean(), top3[js].mean(), vs.mean()]
    return pd.DataFrame(out, index=df.index, columns=["hist_lookalike_top10_rate", "hist_lookalike_top3_rate",
                                                      "hist_lookalike_similarity"])


def site_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index, dtype=float)
    web = {}
    for p in (CACHE / "web").glob("*.json"):
        web[p.stem] = json.loads(p.read_text())
    rows = []
    for pid in df.id:
        w = web.get(pid)
        if not w:
            rows.append({"site_crawled": np.nan})
            continue
        text = PH_LEAK.sub(" ", w.get("text") or "")
        url = (w.get("loaded_url") or "").lower()
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        r = {"site_crawled": 1, "site_ok": int(w.get("status") == 200), "site_words_log": math.log1p(len(text.split())),
             "site_tld_ai": int(host.endswith(".ai")), "site_tld_com": int(host.endswith(".com")),
             "site_tld_io": int(host.endswith(".io") or host.endswith(".dev")),
             "site_is_github": int("github.com" in host), "site_is_appstore": int("apps.apple.com" in host),
             "site_is_subdomain": int(host.count(".") >= 2), "site_en": int((w.get("language") or "en") == "en"),
             "site_title_words": len((w.get("title") or "").split())}
        low = text.lower()
        for k, rx in SITE_WORDS.items():
            r["site_" + k] = len(re.findall(rx, low))
        rows.append(r)
    return pd.DataFrame(rows, index=df.index)


def optional(name: str, df: pd.DataFrame) -> pd.DataFrame:
    path = CACHE / f"{name}.jsonl"
    if not path.exists():
        return pd.DataFrame(index=df.index)
    recs = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        recs[r.pop("id")] = r
    return pd.DataFrame([{f"{name}_{k}": v for k, v in recs.get(pid, {}).items()} for pid in df.id], index=df.index)


def build() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, list[str]]]:
    df = load_posts()
    parts = {"launch": launch_features(df), "people": people_features(df), "followers": follower_features(df),
             "history": history_features(df),
             "site": site_features(df), "llm": optional("llm", df), "hn": optional("hn", df), "domain": optional("domain", df),
             "github": optional("github", df)}
    groups = {g: list(p.columns) for g, p in parts.items()}
    X = pd.concat(parts.values(), axis=1).apply(pd.to_numeric, errors="coerce")
    return df, X, groups


if __name__ == "__main__":
    df, X, groups = build()
    print(len(df), "launches,", X.shape[1], "features:", {g: len(c) for g, c in groups.items()})
