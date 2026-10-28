"""One-time cleaned load of everything collected so far into the warehouse (pipeline/warehouse.py).
Cleaning: ids as strings, dates ISO (YYYY-MM-DD), the [REDACTED] user and makers' comments on their own launches dropped,
duplicates removed, undated facts marked (follows: observed_on = the day the list was read).
fetch_state records, per person and source, when we last fetched and how far back we got, so the daily pipeline
fetches only what is new (pipeline/incremental.py).
usage: python -m pipeline.build_initial"""
import datetime as dt, glob, gzip, json, os, re
import numpy as np, pandas as pd
from . import warehouse as W

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PH = os.path.join(EXP, "ph_predict"); RAW = os.path.join(PH, "data"); SIM = os.path.join(EXP, "simlab")


def mdate(path):
    return dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).strftime("%Y-%m-%d")


def jl(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        for l in f:
            try:
                yield json.loads(l)
            except ValueError:
                continue


def people_launches_events():
    P = pd.read_parquet(f"{SIM}/data_v2/people.parquet"); I = pd.read_parquet(f"{SIM}/data_v2/items.parquet")
    E = pd.read_parquet(f"{SIM}/data_v2/events.parquet")
    P = P[P.person.notna() & (P.person != "[REDACTED]")].drop_duplicates("person")
    first = E.groupby("person").date.min()
    people = pd.DataFrame({
        "person": P.person, "headline": P.headline, "about": P.about, "twitter": P.twitter, "joined": P.joined,
        "ph_followers": P.followers, "ph_followings": P.followings, "is_maker": P.is_maker, "upvotes_total": P.upvotes_total,
        "li_headline": P.li_headline, "li_company": P.li_company, "li_location": P.li_location, "x_bio": P.x_bio,
        "x_followers": P.x_followers, "segments": P.seg, "stacks": P.stacks, "reviews": P.reviews,
        "first_seen": P.person.map(first)})
    launches = pd.DataFrame({
        "id": I.id.astype(str), "slug": I.slug, "day": I.day, "name": I.name, "tagline": I.tagline, "description": I.description,
        "topics": I.topics, "poster": I.poster, "makers": I.makers, "daily_rank": I.out_dailyRank, "weekly_rank": I.out_weeklyRank,
        "monthly_rank": I.out_monthlyRank, "votes": I.out_votes})
    launches["outcome_final"] = launches.day < (dt.date.today() - dt.timedelta(days=31)).isoformat()   # monthly rank settled
    E = E[E.person.isin(set(people.person))].drop_duplicates()
    events = pd.DataFrame({"person": E.person, "launch_id": E.item.astype(str), "date": E.date, "kind": E.kind,
                           "date_quality": np.where(E.kind == "upvote", "launch_day", "exact")})
    follows = []
    for u, f in zip(P.person, P.follows):
        for m in (json.loads(f) if isinstance(f, str) else []):
            follows.append((u, m))
    follows = pd.DataFrame(follows, columns=["person", "followee"]).drop_duplicates()
    follows["observed_on"] = mdate(f"{RAW}/ph_following.jsonl.gz")
    return people, launches, events, follows


def comments(launches):
    C = pd.read_parquet(f"{SIM}/data/comment_text.parquet")
    sid = dict(zip(launches.slug, launches.id))
    C = C[C.person.notna() & (C.person != "[REDACTED]")]
    out = pd.DataFrame({"person": C.person, "launch_id": C.slug.map(sid), "slug": C.slug, "date": C.date, "text": C.text})
    return out.dropna(subset=["launch_id"]).drop_duplicates()


def fetch_state(people):
    """When we last fetched each source per person, and how far back the upvote history goes."""
    rows = []
    known = set(people.person)
    def add(path, src, key="username", extra=None):
        on = mdate(path)
        for r in jl(path):
            u = r.get(key)
            if u in known:
                row = {"person": u, "source": src, "last_fetched": on, "status": r.get("status", 200)}
                if extra:
                    row.update(extra(r))
                rows.append(row)
    up = lambda r: {"items": len(r.get("upvotes") or []) if isinstance(r.get("upvotes"), list) else r.get("upvotes"),
                    "newest_item": (r["upvotes"][0] if isinstance(r.get("upvotes"), list) and r["upvotes"] else None),
                    "complete": not r.get("has_more", True) if "has_more" in r else None}
    add(f"{RAW}/upvotes_pages.jsonl.gz", "upvotes_page1", extra=up)
    for f, cut in (("scroll_upvotes.jsonl.gz", None), ("scroll_sample.jsonl.gz", None), ("scroll_full.jsonl.gz", None),
                   ("scroll_left.jsonl.gz", "2026-09-01")):
        add(f"{RAW}/{f}", "upvotes_scroll", extra=lambda r, cut=cut: {**up(r), "complete": None, "back_to": cut})
    add(f"{RAW}/ph_following.jsonl.gz", "follows", extra=lambda r: {"items": len(r.get("following") or []),
                                                                     "complete": not r.get("has_more", False)})
    for f in ("ph_profiles.jsonl.gz", "ph_profiles2.jsonl.gz", "ph_profiles_rest.jsonl.gz"):
        add(f"{RAW}/{f}", "profile")
    for f in ("profile_tabs.jsonl.gz", "ph_tabs_rest.jsonl.gz"):
        add(f"{RAW}/{f}", "profile_tabs")
    add(f"{RAW}/sample_tabs.jsonl", "activity_tabs")
    add(f"{RAW}/li_apify.jsonl", "linkedin", key="u")
    add(f"{RAW}/segments2.jsonl", "segments")
    S = pd.DataFrame(rows)
    S["items"] = pd.to_numeric(S.get("items"), errors="coerce")
    # several files per source: keep the latest successful fetch, and the deepest history
    S = S.sort_values(["person", "source", "last_fetched", "items"]).groupby(["person", "source"], as_index=False).last()
    return S


def launch_state(launches):
    import sys
    sys.path.insert(0, PH)
    import commenters as K
    on = max(mdate(f) for f in glob.glob(f"{RAW}/comments/page*.jsonl.gz"))
    rows = [{"slug": slug, "source": "comments", "last_fetched": on, "items": len(v["rows"])} for slug, v in K.load_comments().items()]
    S = pd.DataFrame(rows).drop_duplicates()
    sid = dict(zip(launches.slug, launches.id))
    S["launch_id"] = S.slug.map(sid)
    for f in ("sites.jsonl", "sites_today.jsonl"):
        p = f"{RAW}/{f}"
        if os.path.exists(p):
            on = mdate(p)
            S = pd.concat([S, pd.DataFrame([{"launch_id": str(r.get("id")), "source": "site", "last_fetched": on} for r in jl(p) if r.get("id")])])
    return S.dropna(subset=["launch_id"]).drop_duplicates(["launch_id", "source"])


def forecasts():
    rows = []
    for fn in sorted(glob.glob(f"{PH}/results/forecast_20[0-9][0-9]-[0-9][0-9]-[0-9][0-9].md")):
        d = re.search(r"forecast_(\d{4}-\d\d-\d\d)", fn).group(1)
        today = f"{RAW}/today/{d}.json"
        name2id = {p["name"].strip(): str(p["id"]) for p in json.load(open(today))} if os.path.exists(today) else {}
        for l in open(fn):
            m = re.match(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|", l)
            if m:
                rows.append({"forecast_date": d, "model": "launch_model", "predicted_rank": int(m.group(1)),
                             "name": m.group(2), "launch_id": name2id.get(m.group(2).strip()), "made_on": mdate(fn)})
    return pd.DataFrame(rows)


def backtests():
    rows = []
    for fn in glob.glob(f"{PH}/results/robust_*.csv"):
        try:
            d = pd.read_csv(fn, index_col=0)
        except Exception:  # noqa: BLE001
            continue
        for lst, r in d.iterrows():
            for c in d.columns:
                if c.startswith("gain ") or c.startswith("better/worse") or not isinstance(r[c], (int, float, np.floating)):
                    continue
                rows.append({"run_file": os.path.basename(fn), "run_on": mdate(fn), "variant": c, "list": lst,
                             "recall": float(r[c]), "seeds": 5, "months": "2026-03..2026-10"})
    return pd.DataFrame(rows)


def spend():
    rows = [json.loads(l) for l in open(f"{SIM}/spend.jsonl")]
    S = pd.DataFrame(rows).rename(columns={"t": "step"})
    S["logged_on"] = mdate(f"{SIM}/spend.jsonl")
    return S


def persona_ratings():
    rows = []
    for f, design in (("taste_v3_ratings.jsonl", "rate_comments_flash"), ("taste_best4_full.jsonl", "rate_best4_flash"),
                      ("taste_ratings.jsonl", "rate_profile_flash"), ("taste_v2_ratings.jsonl", "rate_pastchoices_flash")):
        p = f"{SIM}/cache/{f}"
        if os.path.exists(p):
            for r in jl(p):
                for i, v in r["ratings"].items():
                    rows.append((r["person"], r["day"], str(i), design, float(v)))
    for r in jl(f"{SIM}/cache/persona_lab.jsonl"):
        if r["kind"] == "rate" and r["value"]:
            for i, v in r["value"].items():
                rows.append((r["person"], r["key"], str(i), f"rate_comments_{r['model']}", float(v)))
    return pd.DataFrame(rows, columns=["person", "day", "launch_id", "design", "rating"]).drop_duplicates()


def main():
    people, launches, events, follows = people_launches_events()
    tables = {"people": people, "launches": launches, "events": events, "follows": follows, "comments": comments(launches),
              "fetch_state": fetch_state(people), "launch_state": launch_state(launches), "forecasts": forecasts(),
              "backtests": backtests(), "spend": spend(), "persona_ratings": persona_ratings()}
    for name, df in tables.items():
        W.write(name, df, part="initial-2026-10-28")
        print(f"{name:16s} {len(df):>9,} rows  {list(df.columns)}", flush=True)


if __name__ == "__main__":
    main()
