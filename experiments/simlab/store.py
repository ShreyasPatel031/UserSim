"""Data store: three tables every experiment reads, built once from the raw files in experiments/ph_predict/data.

  people.parquet   one row per real person: profile, segments, LinkedIn/X lines, follows (as JSON lists).
                   Undated facts (segments, LinkedIn, X, follows) are what is true now; the column `undated` lists them
                   so experiments can see which inputs could include the future.
  items.parquet    one row per launch: id, day, name, tagline, description, topics, poster, makers, outcomes
                   (dailyRank / weeklyRank / monthlyRank / votes) kept in separate columns prefixed `out_`.
  events.parquet   one row per dated action: person, item id, date, kind (comment | upvote). Upvote dates are the
                   launch day (a profile lists recent upvotes without their time).
usage: python -m simlab.store   (from experiments/)   -> experiments/simlab/data/*.parquet"""
import ast, glob, gzip, json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(os.path.dirname(HERE), "ph_predict", "data")
OUT = os.path.join(HERE, os.environ.get("SIMLAB_DATA", "data"))  # data_v2 = store rebuilt with fuller upvote histories
UNDATED = ["seg", "li_headline", "li_company", "li_location", "x_bio", "x_followers", "follows"]


def jl(path):
    op = gzip.open if path.endswith(".gz") else open
    if not os.path.exists(path):
        return
    with op(path, "rt") as f:
        for l in f:
            try:
                yield json.loads(l)
            except ValueError:
                pass


def lit(x):
    return x if isinstance(x, (list, dict)) else (ast.literal_eval(x) if x and x != "None" else [])


def build_people():
    P = {}
    for f in ("ph_profiles_rest", "ph_profiles2"):
        for p in jl(f"{RAW}/{f}.jsonl.gz"):
            P[p["username"]] = {"person": p["username"], "headline": p.get("headline"), "about": (p.get("about") or "")[:500],
                                "twitter": p.get("twitter"), "joined": (p.get("joined") or "")[:10],
                                "followers": int(p.get("followers") or 0), "followings": int(p.get("followings") or 0),
                                "is_maker": p.get("is_maker") in (True, "True"), "voted_recent": lit(p.get("voted_recent"))}
    for f in ("ph_tabs_rest", "profile_tabs"):
        for t in jl(f"{RAW}/{f}.jsonl.gz"):
            if t["username"] in P:
                P[t["username"]]["stacks"] = [[s.get("name") or s.get("slug"), (s.get("added") or "")[:10]] for s in lit(t.get("stacks"))]
                P[t["username"]]["reviews"] = [[r.get("product_name") or r.get("product_slug"), r.get("rating"), (r.get("created") or "")[:10]]
                                               for r in lit(t.get("reviews"))]
    for r in jl(f"{RAW}/segments2.jsonl"):
        if r["username"] in P and r.get("labels"):
            P[r["username"]]["seg"] = r["labels"]
    for f in ("li_search.jsonl", "li_search_retry.jsonl"):
        for r in jl(f"{RAW}/{f}"):
            if r.get("found") and r["username"] in P:
                P[r["username"]].update(li_headline=r.get("headline"), li_company=r.get("company"), li_location=r.get("location"))
    X = {}
    for f in ("x_people", "commenter_x"):
        for r in jl(f"{RAW}/{f}.jsonl.gz"):
            if r.get("profile"):
                X[r["handle"].lower()] = r["profile"]
    for u, p in P.items():
        x = X.get((p.get("twitter") or "").lower())
        if x:
            p.update(x_bio=(x.get("description") or "")[:300], x_followers=x.get("followers"))
    # more upvotes: the Upvotes tab's first page (20) and browser-scrolled histories (~6 months), merged, newest first
    extra = {}
    for f in ("upvotes_pages.jsonl.gz", "scroll_upvotes.jsonl.gz", "scroll_sample.jsonl.gz", "scroll_full.jsonl.gz"):
        for r in jl(f"{RAW}/{f}"):
            if r.get("upvotes"):
                extra.setdefault(r["username"], []).extend(r["upvotes"])
            if r.get("votes_total") is not None and r["username"] in P:
                P[r["username"]]["upvotes_total"] = r["votes_total"]
    for u, ids in extra.items():
        if u in P:
            P[u]["voted_recent"] = list(dict.fromkeys(P[u]["voted_recent"] + ids))
    for r in jl(f"{RAW}/ph_following.jsonl.gz"):
        if r["username"] in P:
            P[r["username"]]["follows"] = [u for u, _ in r.get("following") or []]
    df = pd.DataFrame(P.values())
    for c in ("headline", "li_headline", "li_company", "li_location", "x_bio", "twitter"):  # LLM output can be a list
        df[c] = df[c].apply(lambda v: ", ".join(map(str, v)) if isinstance(v, list) else (None if v is None or v != v else str(v)))
    df["x_followers"] = pd.to_numeric(df.x_followers, errors="coerce")
    for c in ("voted_recent", "stacks", "reviews", "seg", "follows"):
        df[c] = df[c].apply(lambda v: json.dumps(v) if isinstance(v, (list, dict)) else None)
    return df


def build_items():
    rows = []
    for fn in sorted(glob.glob(f"{RAW}/days/*.json")):
        day = os.path.basename(fn)[:10]
        for p in json.load(open(fn)):
            rows.append({"id": p["id"], "slug": p["slug"], "day": day, "name": p["name"], "tagline": p["tagline"],
                         "description": p.get("description") or "",
                         "topics": json.dumps([e["node"]["name"] for e in p["topics"]["edges"]]),
                         "poster": (p.get("user") or {}).get("username"),
                         "makers": json.dumps([m["username"] for m in p.get("makers") or []]),
                         "out_dailyRank": p.get("dailyRank"), "out_weeklyRank": p.get("weeklyRank"),
                         "out_monthlyRank": p.get("monthlyRank"), "out_votes": p.get("votesCount")})
    df = pd.DataFrame(rows).drop_duplicates("id")
    for c in ("out_dailyRank", "out_weeklyRank", "out_monthlyRank", "out_votes"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_events(items, people):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ph_predict"))
    import commenters as K
    slug2 = dict(zip(items.slug, zip(items.id, items.day)))
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in items.itertuples()}
    ev = []
    for slug, v in K.load_comments().items():
        if slug not in slug2:
            continue
        iid, _ = slug2[slug]
        for c in v["rows"]:
            u = c["username"]
            if u and u != "[REDACTED]" and u not in team[iid]:
                ev.append((u, iid, (c["created"] or "")[:10], "comment"))
    day_of = dict(zip(items.id, items.day))
    for r in people.itertuples():
        for iid in json.loads(r.voted_recent or "[]"):
            if iid in day_of:
                ev.append((r.person, iid, day_of[iid], "upvote"))
    return pd.DataFrame(ev, columns=["person", "item", "date", "kind"]).drop_duplicates()


def main():
    os.makedirs(OUT, exist_ok=True)
    people = build_people(); items = build_items(); events = build_events(items, people)
    people.to_parquet(f"{OUT}/people.parquet"); items.to_parquet(f"{OUT}/items.parquet"); events.to_parquet(f"{OUT}/events.parquet")
    json.dump({"undated_people_columns": UNDATED}, open(f"{OUT}/meta.json", "w"))
    print("people", len(people), "items", len(items), "events", len(events), events.kind.value_counts().to_dict())


def load():
    """(people, items, events) DataFrames."""
    return tuple(pd.read_parquet(f"{OUT}/{t}.parquet") for t in ("people", "items", "events"))


if __name__ == "__main__":
    main()
