"""people_v2 builder, revision 3: applies the fix list in docs/PEOPLE_V2_REVIEW.md to PR #142's build_v2.py.

Run from a directory that holds the inputs (same layout as build_v2.py; paths are relative to --root):
    raw/ph_profiles.jsonl.gz  raw/ph_profiles_rest.jsonl.gz  raw/ph_profiles2.jsonl.gz
    raw/ph_profiles2_refetch/profiles.jsonl.gz   (the Nov 2 re-fetch; status 200 rows are used)
    raw/profile_tabs.jsonl.gz  raw/x_people.jsonl.gz  raw/x_posts.jsonl.gz
    li/li_search.jsonl  li/li_search_retry.jsonl  li/li_apify.jsonl
    t/people.parquet    ev/*.parquet   (tables/events)
    python build_v3.py --root work --out v2b        # writes work/v2b/{persons,handles,profiles,events}.parquet + build_report.json

Changes against build_v2.py (numbers refer to the fix list):
 1. Re-fetch rows (status 200, numeric user_id, name) replace every legacy/poisoned PH row. 404 users are marked gone (kept as
    persons, because their events are real history, but flagged and without a profile); other failures are marked retry_pending.
 2. persons = union of events, all profile captures and v1 people, with has_profile / gone / retry_pending / in_events (fixes the 541 orphans).
 3. v1 `segments` are NOT carried over (they were built from poisoned LinkedIn text). Rebuild from the re-fetch before use.
 4. Own handles come only from links whose `kind` matches the platform; the first-listed link is primary (not alphabetical), later ones
    get confidence 0.5; an X handle claimed by several people is demoted to 0.5 for all of them and their posts are not attributed.
 5. observed_on is the row's own fetched_at; where that is unknown it is null with observed_on_quality='unknown', never the build date.
 6. ph_user_id keeps numeric ids only (legacy UUIDs become null); every PH profile records parser_version.
Not done here, needs a human or a model: personal-vs-company labelling of X handles (see x_handle_audit_100.csv) and rebuilding segments.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import difflib
import glob
import gzip
import json
import os
import re
from urllib.parse import unquote, urlparse

import pandas as pd

NOW = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
POISON_ID = {"606339", "109827"}
POISON_NAMES = {"Wispr Flow", "Lovable"}
KIND_PLAT = {"twitter": "x", "linkedin": "linkedin", "github": "github"}
MISSING: list[str] = []


def jl(fn):
    if not os.path.exists(fn):
        MISSING.append(fn)
        return
    op = gzip.open if fn.endswith(".gz") else open
    for line in op(fn, "rt"):
        try:
            yield json.loads(line)
        except ValueError:
            pass


def slug(url, plat):
    if not url:
        return None
    try:
        p = urlparse(url if "://" in url else "https://" + url)
    except Exception:  # noqa: BLE001
        return None
    parts = [x for x in unquote(p.path).split("/") if x]
    h = p.netloc.lower()
    if plat == "x":
        if not any(d in h for d in ("twitter.com", "x.com")) or not parts:
            return None
        s = parts[0].lstrip("@").lower()
        return s if re.fullmatch(r"[a-z0-9_]{1,15}", s) and s not in ("intent", "share", "home", "i", "search", "hashtag") else None
    if plat == "linkedin":
        if "linkedin.com" not in h or len(parts) < 2 or parts[0] not in ("in", "pub"):
            return None
        return parts[1].lower()
    if plat == "github":
        if "github.com" not in h or not parts:
            return None
        return parts[0].lower()
    return None


def norm(s):
    return " ".join(re.findall(r"[a-z]+", (s or "").lower()))


def namesim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    tok = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return round(max(difflib.SequenceMatcher(None, a, b).ratio(), tok), 3)


def day(v):
    return str(v)[:10] if v else None


def numeric_id(v):
    s = str(v) if v is not None else ""
    return s if s.isdigit() else None


def main(root: str, out: str) -> dict:
    os.chdir(root)
    os.makedirs(out, exist_ok=True)
    R = "raw/"
    # ---- PH raw
    old, p2 = {}, {}
    for fn in (R + "ph_profiles.jsonl.gz", R + "ph_profiles_rest.jsonl.gz"):
        for r in jl(fn):
            if r.get("username"):
                old[r["username"]] = r
    for r in jl(R + "ph_profiles2.jsonl.gz"):
        if r.get("username"):
            p2[r["username"]] = r
    rf, gone, retry = {}, set(), set()  # fix 1
    for r in jl(R + "ph_profiles2_refetch/profiles.jsonl.gz"):
        u = r.get("username")
        if not u:
            continue
        if str(r.get("status")) == "200" and numeric_id(r.get("user_id")) and r.get("name") and r.get("name") not in POISON_NAMES:
            rf[u] = r
        elif str(r.get("status")) == "404":
            gone.add(u)
        else:
            retry.add(u)
    tabs = {r["username"]: r for r in jl(R + "profile_tabs.jsonl.gz") if r.get("username")}
    v1 = pd.read_parquet("t/people.parquet").set_index("person")
    E = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob("ev/*.parquet"))]).drop_duplicates(["person", "launch_id", "date", "kind"])
    event_users = set(E.person.astype(str))
    users = sorted(set(old) | set(p2) | set(rf) | gone | retry | set(v1.index) | event_users)  # fix 2
    X = {}
    for r in jl(R + "x_people.jsonl.gz"):
        if r.get("handle"):
            X[r["handle"].lower()] = r
    XP = collections.defaultdict(list)
    for r in jl(R + "x_posts.jsonl.gz"):
        for p in (r.get("posts") or []):
            XP[(p.get("author") or r.get("handle") or "").lower()].append(p)
    for h, r in X.items():
        for p in (r.get("posts") or []):
            XP[(p.get("author") or h).lower()].append(p)
    LS = {}
    for fn in ("li/li_search.jsonl", "li/li_search_retry.jsonl"):
        for r in jl(fn):
            if r.get("username"):
                LS[r["username"]] = r
    LA = {}
    for r in jl("li/li_apify.jsonl"):
        if r.get("u") and r.get("profile"):
            LA[r["u"]] = r["profile"]

    persons, handles, profiles = [], [], []
    stats = collections.Counter()

    def H(pid, plat, h, url, src, conf, note=None, obs=None):
        handles.append(dict(person_id=pid, platform=plat, handle=h, url=url, source=src, confidence=conf, note=note,
                            observed_on=obs, observed_on_quality="fetched" if obs else "unknown"))

    for u in users:
        pid = "ph:" + u
        o = old.get(u, {})
        g = rf.get(u) or p2.get(u)  # fixed-parser row, if any
        parser = "refetch-2026-11" if u in rf else ("ph_profiles2" if u in p2 else ("legacy" if o else None))
        base = g or o
        poisoned = (not g) and bool(o) and (o.get("user_id") in POISON_ID or o.get("name") in POISON_NAMES)
        ph_name = None if poisoned else base.get("name")
        ph_uid = None if poisoned else numeric_id(base.get("user_id"))  # fix 6: legacy UUIDs -> null
        obs = day(g.get("fetched_at") or g.get("observed_on")) if (u in rf and g) else None  # fix 5
        has_profile = bool(base) and u not in gone
        links, seen = [], set()
        for l in (base.get("links") or []) + (o.get("links") or []):
            k = (l.get("kind"), l.get("url"))
            if l.get("url") and k not in seen:
                seen.add(k)
                links.append(l)
        H(pid, "producthunt", u, f"https://www.producthunt.com/@{u}", "ph_username", 1.0, obs=obs)
        own = {"x": [], "linkedin": [], "github": []}  # fix 4: kind must match the platform; page order kept
        for l in links:
            k, url = l.get("kind"), l["url"]
            plat = KIND_PLAT.get(k)
            if plat:
                s = slug(url, plat)
                if s and s not in own[plat]:
                    own[plat].append(s)
            else:
                H(pid, k, None, url, "ph_self_link", 0.95, obs=obs)
        base_url = {"x": "https://x.com/", "linkedin": "https://www.linkedin.com/in/", "github": "https://github.com/"}
        for plat in own:
            for i, s in enumerate(own[plat]):
                if i == 0:
                    H(pid, plat, s, base_url[plat] + s, "ph_self_link", 0.95, obs=obs)
                else:
                    H(pid, plat, s, base_url[plat] + s, "ph_self_link_extra", 0.5, "not the first listed link of this kind", obs)
                    stats["extra_self_link_demoted"] += 1
        tw = base.get("twitter") or (v1.loc[u, "twitter"] if u in v1.index else None)
        tw = tw.lower().lstrip("@") if isinstance(tw, str) and tw else None
        if tw and tw not in own["x"]:
            if own["x"]:
                H(pid, "x", tw, "https://x.com/" + tw, "ph_twitter_field", 0.2, "conflicts with self link; not used", obs)
                stats["x_field_conflict"] += 1
            else:
                H(pid, "x", tw, "https://x.com/" + tw, "ph_twitter_field", 0.8, obs=obs)
        x_primary = own["x"][0] if own["x"] else tw
        xname = None
        if x_primary and x_primary in X and X[x_primary].get("profile"):
            xp = X[x_primary]["profile"]
            xname = xp.get("name")
            profiles.append(dict(person_id=pid, platform="x", handle=x_primary, observed_on=None, observed_on_quality="unknown",
                                 source="raw/x_people", name=xp.get("name"), bio=xp.get("description"), location=xp.get("location") or None,
                                 website=xp.get("website"), joined=xp.get("joined"), followers=xp.get("followers"), following=xp.get("following"),
                                 post_count=xp.get("tweets"), likes_count=xp.get("likes"), media_count=xp.get("media_count"),
                                 verified=bool((xp.get("verification") or {}).get("verified")), protected=xp.get("protected"), extra=None))
        # LinkedIn (logic unchanged from build_v2: only self-link-confirmed or high-similarity, non-poisoned-query rows)
        li_slug = li_conf = li_src = li_row = None
        ref = [n for n in (ph_name, xname) if n]
        ls = LS.get(u)
        if ls and ls.get("found") and ls.get("url"):
            s = slug(ls["url"], "linkedin")
            if s and s in own["linkedin"]:
                li_slug, li_conf, li_src, li_row = s, 0.95, "li_search_url_matches_self_link", ls
            else:
                sc = max([namesim(ls.get("name"), n) for n in ref] + [0])
                if sc >= 0.85 and ls.get("ph_name") not in POISON_NAMES:
                    li_slug, li_conf, li_src, li_row = s, round(0.6 * sc, 3), "li_search_name_match", ls
                    H(pid, "linkedin", s, ls["url"], "li_search_name_match", round(0.6 * sc, 3), f"name_sim={sc}")
                else:
                    stats["li_search_rejected"] += 1
        if not li_slug and own["linkedin"]:
            li_slug, li_conf, li_src = own["linkedin"][0], 0.95, "ph_self_link"
        la = LA.get(u)
        if la and (la.get("publicIdentifier") or "").lower() in set(own["linkedin"]) | ({li_slug} if li_slug else set()):
            cp = la.get("currentPosition") or [{}]
            cp = cp[0] if cp else {}
            profiles.append(dict(person_id=pid, platform="linkedin", handle=(la.get("publicIdentifier") or "").lower(), observed_on=None,
                                 observed_on_quality="unknown", source="raw/li_apify",
                                 name=" ".join(x for x in (la.get("firstName"), la.get("lastName")) if x), bio=la.get("about"),
                                 location=(la.get("location") or {}).get("linkedinText"), website=json.dumps(la.get("websites")),
                                 joined=la.get("registeredAt"), followers=la.get("followerCount"), following=None, post_count=None,
                                 likes_count=None, media_count=None, verified=la.get("verified"), protected=None,
                                 extra=json.dumps(dict(headline=la.get("headline"), company=cp.get("companyName"), connections=la.get("connectionsCount"),
                                                       top_skills=la.get("topSkills"), experience=la.get("experience"), education=la.get("education")), default=str)))
        elif li_row:
            tainted = li_row.get("ph_name") in POISON_NAMES or ("wispr" in str(li_row.get("headline")).lower() and
                                                               "wispr" not in (str(base.get("headline")) + str(base.get("about"))).lower())
            profiles.append(dict(person_id=pid, platform="linkedin", handle=li_slug, observed_on=None, observed_on_quality="unknown", source=li_src,
                                 name=None if li_row.get("name") in POISON_NAMES else li_row.get("name"), bio=None,
                                 location=None if li_row.get("ph_name") in POISON_NAMES else li_row.get("location"), website=None, joined=None,
                                 followers=None, following=None, post_count=None, likes_count=None, media_count=None, verified=None, protected=None,
                                 extra=json.dumps(dict(headline=None, company=None, role=None, education=None, confidence=li_conf,
                                                       text_dropped="search query used poisoned PH name") if tainted else
                                                  dict(headline=li_row.get("headline"), company=li_row.get("company"), role=li_row.get("role"),
                                                       education=li_row.get("education"), confidence=li_conf))))
        # PH profile row (only when there is a capture)
        v = v1.loc[u] if u in v1.index else None
        t = tabs.get(u, {})
        fixed = bool(g)

        def g2(k):
            return g.get(k) if g else None
        if has_profile:
            profiles.append(dict(
                person_id=pid, platform="producthunt", handle=u, observed_on=obs, observed_on_quality="fetched" if obs else "unknown",
                source={"refetch-2026-11": "raw/ph_profiles2_refetch", "ph_profiles2": "raw/ph_profiles2"}.get(parser, "raw/ph_profiles(+rest)"),
                name=ph_name, bio=base.get("about") or (v["about"] if v is not None else None), location=None, website=None,
                joined=g2("joined") or (v["joined"] if v is not None else None), followers=base.get("followers"), following=base.get("followings"),
                post_count=None, likes_count=None, media_count=None, verified=g2("verified"), protected=None,
                extra=json.dumps(dict(parser_version=parser, ph_user_id=ph_uid, headline=base.get("headline"), is_maker=base.get("is_maker"),
                                      upvotes_total=g2("upvotes_total") if fixed else (None if v is None else v["upvotes_total"]),
                                      products_made=g2("products_made"), hunted=g2("hunted"), collections=g2("collections"),
                                      reviews_count=g2("reviews_count"), stacks_count=g2("stacks_count"), visit_streak_days=g2("visit_streak_days"),
                                      community_rank_year=g2("community_rank_year"), current_product=g2("current_product"),
                                      badges_total=g2("badges_total"), badges=base.get("badges"), voted_recent=base.get("voted_recent"),
                                      stacks=t.get("stacks"), reviews=t.get("reviews")), default=str)))  # fix 3: no v1 segments
        persons.append(dict(person_id=pid, display_name=ph_name or xname, ph_username=u,
                            ph_name_poisoned_in_v1=bool(poisoned or (u in LS and LS[u].get("ph_name") in POISON_NAMES)),
                            has_profile=has_profile, gone=u in gone, retry_pending=u in retry, in_events=u in event_users,
                            profile_parser=parser, first_seen=(None if v is None else v["first_seen"]), built_at=NOW))

    P = pd.DataFrame(persons)
    Hd = pd.DataFrame(handles).drop_duplicates(["person_id", "platform", "handle", "url", "source"])
    Pr = pd.DataFrame(profiles)
    # fix 4: a handle several people claim at >=0.8 is not attributable to any one of them
    hx = Hd[(Hd.platform == "x") & (Hd.confidence >= 0.8)]
    counts = hx.groupby("handle").person_id.nunique()
    shared = set(counts[counts > 1].index)
    m = (Hd.platform == "x") & (Hd.confidence >= 0.8) & Hd.handle.isin(shared)
    stats["shared_x_handle_rows_demoted"] = int(m.sum())
    Hd.loc[m, "note"] = "handle shared by several people; not attributed"
    Hd.loc[m, "confidence"] = 0.5
    if len(Pr):
        drop = (Pr.platform == "x") & Pr.handle.isin(shared)
        Pr = Pr[~drop]
    for c in ["followers", "following", "post_count", "likes_count", "media_count"]:
        Pr[c] = pd.to_numeric(Pr[c], errors="coerce")
    for c in ["name", "bio", "location", "website", "extra", "handle"]:
        Pr[c] = Pr[c].map(lambda x: x if (x is None or isinstance(x, str)) else json.dumps(x, default=str))
    for c in ["verified", "protected"]:
        Pr[c] = Pr[c].astype("boolean")
    Pr["joined"] = Pr["joined"].astype("string")
    P["first_seen"] = P["first_seen"].astype("string")
    # ---- events
    ev = pd.DataFrame(dict(person_id="ph:" + E.person.astype(str), platform="producthunt", event_id=None, ts=E.date.astype(str),
                           ts_quality=E.date_quality.map({"exact": "exact", "launch_day": "day"}).fillna(E.date_quality), kind=E.kind,
                           target_id=E.launch_id.astype(str), text=None, metrics=None, source="tables/events"))
    xh = Hd[(Hd.platform == "x") & (Hd.confidence >= 0.8)][["person_id", "handle"]].drop_duplicates("handle")
    h2p = dict(zip(xh.handle, xh.person_id))
    xr, seenp = [], set()
    for h, ps in XP.items():
        if h not in h2p:
            continue
        for p in ps:
            key = p.get("id") or (h, p.get("created_at"), str(p.get("text"))[:40])
            if key in seenp:
                continue
            seenp.add(key)
            ca = str(p.get("created_at"))
            xr.append(dict(person_id=h2p[h], platform="x", event_id=None if p.get("id") is None else str(p.get("id")), ts=ca,
                           ts_quality="exact" if "T" in ca else "day", kind="post", target_id=None, text=p.get("text"),
                           metrics=json.dumps({k: p.get(k) for k in ("likes", "reposts", "replies", "quotes", "views", "bookmarks")}),
                           source="raw/x_posts+x_people"))
    ev = pd.concat([ev, pd.DataFrame(xr)], ignore_index=True)
    ev["event_id"] = ev["event_id"].astype("string")
    for name, df in (("persons", P), ("handles", Hd), ("profiles", Pr), ("events", ev)):
        df.to_parquet(f"{out}/{name}.parquet", index=False)
    report = dict(rows=dict(persons=len(P), handles=len(Hd), profiles=len(Pr), events=len(ev)), refetch=dict(used=len(rf), gone=len(gone), retry=len(retry)),
                  persons_with_events_only=int(((~P.has_profile) & P.in_events).sum()), stats=dict(stats), missing_inputs=sorted(set(MISSING)),
                  segments="dropped (not carried over from v1)", built_at=NOW)
    json.dump(report, open(f"{out}/build_report.json", "w"), indent=1)
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="v2b")
    a = ap.parse_args()
    main(a.root, a.out)
