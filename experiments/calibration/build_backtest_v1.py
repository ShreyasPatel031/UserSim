"""Backtest calibration set v1 (held data only; no new Product Hunt requests).

Builds, for every featured launch with a final daily rank in a window of PT days:
  launches.jsonl, comments.jsonl, cohort.jsonl, predictions.jsonl, sample_for_plugin.json
from files already in gs://usersim-bakeoff-347838016394/usersim_sim/ (copied to a local DATA dir first, see fetch()).

Privacy: no PH usernames or person ids are written. Comment text has @handles replaced by "@user"; people appear only as
segment counts, and every segment cell under 20 people is folded into "other".

Usage:
  python experiments/calibration/build_backtest_v1.py fetch DATA            # gsutil copies of the inputs (about 1 GB)
  python experiments/calibration/build_backtest_v1.py build DATA OUT [--start 2026-10-22 --end 2026-11-20]
"""
import collections, glob, gzip, html, json, os, re, statistics, subprocess, sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

B = "gs://usersim-bakeoff-347838016394/usersim_sim"
MIN_CELL = 20


def fetch(D, start="2026-10-22", end="2026-11-20"):
    def sh(cmd):
        print(cmd, flush=True); subprocess.run(cmd, shell=True, check=False)
    for sub in ["launches", "days", "wc", "explain", "f0005", "pred", "store", "seg", "daily", "pal"]:
        os.makedirs(f"{D}/{sub}", exist_ok=True)
    sh(f"gsutil -m -q cp '{B}/tables/launches/*.parquet' {D}/launches/")
    sh(f"gsutil -m -q cp '{B}/tables/comments/*.parquet' {D}/wc/")
    sh(f"gsutil -m -q cp '{B}/raw/store/days/2026-1*.json' {D}/days/")
    sh(f"gsutil -m -q cp '{B}/results/web/explain/*.json' {D}/explain/")
    sh(f"gsutil -m -q cp '{B}/results/web/forecast_0005/*.json' {D}/f0005/")
    sh(f"gsutil -m -q cp '{B}/results/web/predictions/*.json' {D}/pred/")
    sh(f"gsutil -m -q cp {B}/raw/population/store_v3/persons.parquet {B}/raw/population/store_v3/events.parquet {D}/store/")
    sh(f"gsutil -q cp {B}/raw/sites_ph.jsonl {D}/sites_ph.jsonl")
    sh(f"gsutil -q cp {B}/raw/ph_alternatives/similar_products_all.jsonl {D}/alts.jsonl")
    sh(f"gsutil -q cp {B}/raw/ph_predict_data/competitors.json {D}/competitors.json")
    for day in days_between(start, end):
        sh(f"gsutil -q cp {B}/raw/daily/{day}/sites_0005.json {D}/daily/{day}_sites_0005.json")
        sh(f"gsutil -q cp {B}/raw/ph_at_launch/{day}/products.jsonl {D}/daily/{day}_products.jsonl")
        for k in ["api_comments", "api_replies"]:
            os.makedirs(f"{D}/pal/{day}/{k}", exist_ok=True)
            sh(f"gsutil -m -q rsync {B}/raw/ph_at_launch/{day}/{k} {D}/pal/{day}/{k}")
        os.makedirs(f"{D}/pal/{day}/live", exist_ok=True)
        sh(f"gsutil -q cp {B}/raw/ph_at_launch/{day}/live/comments_ts.jsonl {D}/pal/{day}/live/")
        sh(f"gsutil -q cp {B}/raw/ph_at_launch/{day}/api_teams.jsonl {D}/pal/{day}/")
    for c in segment_cuts_available(start, end):
        sh(f"gsutil -q cp {B}/tmp/e5/private/segments/{c}.parquet {D}/seg/priv_{c}.parquet")
        sh(f"gsutil -q cp {B}/results/web/segments/{c}.json {D}/seg/pub_{c}.json")


def days_between(a, b):
    import datetime as dt
    d, e = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    while d <= e:
        yield d.isoformat(); d += dt.timedelta(days=1)


def segment_cuts_available(start, end):
    out = subprocess.run(f"gsutil ls {B}/tmp/e5/private/segments/", shell=True, capture_output=True, text=True).stdout
    return sorted(set(re.findall(r"/(\d{4}-\d{2}-\d{2})\.parquet", out)))


# ---------- helpers ----------
TRACK = re.compile(r"^(utm_.*|ref|ref_src|via|source|fbclid|gclid)$", re.I)


def strip_url(u):
    if not u:
        return u
    try:
        p = urlsplit(u)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACK.match(k)]
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))
    except Exception:
        return u


BLOG_HOSTS = ("medium.com", "substack.com", "dev.to", "hashnode", "blogspot.", "wordpress.com", "notion.site", "notion.so",
              "ghost.io", "beehiiv.com", "linkedin.com", "x.com", "twitter.com", "youtube.com", "youtu.be", "reddit.com")


def url_kind(u, parked=False):
    if not u:
        return "unresolved"
    h = (urlsplit(u).netloc or "").lower()
    path = (urlsplit(u).path or "").lower()
    if "producthunt.com" in h:
        return "unresolved"
    if parked:
        return "parked_domain"
    if h.endswith("apps.apple.com") or h.endswith("itunes.apple.com") or h.endswith("testflight.apple.com"):
        return "app_store"
    if h.endswith("play.google.com"):
        return "play_store"
    if "chromewebstore.google.com" in h or "chrome.google.com" in h or "addons.mozilla.org" in h or "marketplace.visualstudio.com" in h:
        return "extension_store"
    if any(b in h for b in BLOG_HOSTS) or re.search(r"/(blog|posts?|news|articles?|changelog)/", path + "/") and path.count("/") >= 2:
        return "blog_or_post"
    if h.endswith("github.com") or h.endswith("gitlab.com") or h.endswith("huggingface.co"):
        return "code_repo"
    if h.endswith("apps.microsoft.com") or h.endswith("microsoft.com") and "/store/" in path:
        return "app_store"
    return "web"


WEB_TESTABLE = {"web", "code_repo"}

CAPTURE_NOTE = {
    **{d: "warehouse tables/comments: text with date only, no comment ids, no reply links" for d in ("2026-10-22", "2026-10-23", "2026-10-24")},
    **{d: "no comment text held" for d in ("2026-10-25", "2026-10-26", "2026-11-05")},
    **{d: "first 20 top-level comments per launch only (API page of 20), no replies" for d in
       ("2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-09")},
    **{d: "partial: API capture incomplete that day" for d in ("2026-11-06", "2026-11-07")},
}


def norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()

TAG = re.compile(r"<[^>]+>")


def _mask(m):
    tok = m.group(0)
    pre = m.string[m.start() - 1] if m.start() > 0 else " "
    if re.match(r"\w", pre) and re.search(r"\.[A-Za-z]{2,}$", tok):   # an e-mail address, not a handle
        return tok
    return "@user"


def clean_text(b, mask_names=()):
    if not b:
        return ""
    t = b
    for _ in range(2):   # some bodies hold escaped HTML: unescape, then strip, twice
        t = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", t)
        t = html.unescape(TAG.sub("", t))
        t = re.sub(r"<(a|p|span|img|br|div|strong|em|ul|ol|li)\b[^>]*$", "", t)   # a tag cut off at the end of a stored body
    t = re.sub(r"@[A-Za-z0-9_][A-Za-z0-9_.-]*", _mask, t)
    for n in mask_names:   # makers' PH usernames that also appear as GitHub/other handles in the text
        t = re.sub(r"(?i)(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])", "[maker]", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def jl(path):
    out = []
    try:
        op = gzip.open if path.endswith(".gz") else open
        with op(path, "rt") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try: out.append(json.loads(line))
                    except Exception: pass
    except FileNotFoundError:
        pass
    return out


def jload(path, default=None):
    try:
        return json.load(open(path))
    except Exception:
        return default


def none_if(v):
    if v in (None, "None", "", "null") or (isinstance(v, float) and v != v):
        return None
    return v


# ---------- build ----------
def build(D, OUT, start, end):
    import duckdb
    os.makedirs(OUT, exist_ok=True)
    con = duckdb.connect()
    days = list(days_between(start, end))

    # 1. launches: newest warehouse row per id with a daily rank
    rows = con.sql(f"""
        select * exclude(rn) from (
          select *, row_number() over (partition by id order by updated_at desc) rn
          from read_parquet('{D}/launches/*.parquet', union_by_name=true)
          where day between '{start}' and '{end}')
        where rn = 1 and daily_rank > 0 order by day, daily_rank""").fetchall()
    cols = [c[0] for c in con.sql(f"describe select * from read_parquet('{D}/launches/*.parquet', union_by_name=true)").fetchall()]
    L = [dict(zip(cols, r)) for r in rows]
    ids = {x["id"] for x in L}

    dayfile = {}
    for day in days:
        for p in jload(f"{D}/days/{day}.json", []) or []:
            dayfile[str(p["id"])] = p

    # makers (ids, usernames) per launch, for the maker flag only (never written out)
    maker_ids, maker_names = collections.defaultdict(set), collections.defaultdict(set)
    for i, p in dayfile.items():
        for m in p.get("makers") or []:
            if m.get("id"): maker_ids[i].add(str(m["id"]))
            if m.get("username") and m["username"] != "[REDACTED]": maker_names[i].add(m["username"].lower())
    for day in days:
        for r in jl(f"{D}/pal/{day}/api_teams.jsonl"):
            if r.get("maker_id"): maker_ids[str(r.get("post_id"))].add(str(r["maker_id"]))
    for x in L:
        try:
            for u in json.loads(x.get("makers") or "[]"):
                if u and u != "[REDACTED]": maker_names[x["id"]].add(u.lower())
        except Exception:
            pass

    # resolved URLs
    url = {}
    sp = collections.defaultdict(list)
    for r in jl(f"{D}/sites_ph.jsonl"):
        sp[str(r.get("id"))].append(r)
    for i, rs in sp.items():
        good = [r for r in rs if r.get("url") and "producthunt.com" not in r["url"]]
        if good:
            r = sorted(good, key=lambda r: (r.get("status") == 200, -(r.get("status") or 0)))[-1]
            url[i] = {"url": r["url"], "source": "raw/sites_ph.jsonl", "http_status": r.get("status"), "parked": bool(r.get("parked"))}
    for day in days:
        for r in jl(f"{D}/daily/{day}_products.jsonl"):
            w = (r.get("socials") or {}).get("websiteUrl")
            for i in r.get("launch_ids") or []:
                if w and str(i) not in url:
                    url[str(i)] = {"url": w, "source": f"raw/ph_at_launch/{day}/products.jsonl (socials.websiteUrl)", "http_status": None, "parked": False}
        s = jload(f"{D}/daily/{day}_sites_0005.json") or jload(f"{D}/daily/{day}/sites_0005.json")
        for i, r in ((s or {}).get("launches") or {}).items():
            if r.get("final_url") and "producthunt.com" not in r["final_url"]:
                url[str(i)] = {"url": r["final_url"], "source": f"raw/daily/{day}/sites_0005.json", "http_status": r.get("status"), "parked": False}

    # competitors
    alts = {}
    for r in jl(f"{D}/alts.jsonl"):
        alts[str(r.get("launch_id"))] = r
    gcomp = jload(f"{D}/competitors.json", {}) or {}
    explain = {}
    for f in sorted(glob.glob(f"{D}/explain/*.json")):
        d = jload(f)
        if d: explain[d["day"]] = d

    # forecasts
    f0005 = {}
    for f in sorted(glob.glob(f"{D}/f0005/*.json")):
        d = jload(f)
        if d: f0005[d["day"]] = d
    pub = {}
    for f in sorted(glob.glob(f"{D}/pred/*_0005.json")) + sorted(glob.glob(f"{D}/pred/*_prereveal.json")):
        d = jload(f)
        if d and d.get("day"): pub[(d["day"], d.get("kind"))] = d

    # 2. comments
    com = collections.defaultdict(dict)   # launch -> comment_id -> rec
    def add(lid, cid, rec):
        if lid not in ids: return
        old = com[lid].get(cid)
        if old is None or (rec.get("_seen") or "") >= (old.get("_seen") or ""):
            if old:
                for k in ("is_maker_flag", "is_hunter_flag"):
                    if rec.get(k) is None: rec[k] = old.get(k)
            com[lid][cid] = rec
    sources_by_launch = collections.defaultdict(set)
    for day in days:
        for k in ["api_comments", "api_replies"]:
            for f in sorted(glob.glob(f"{D}/pal/{day}/{k}/*.jsonl")):
                for r in jl(f):
                    lid, cid = str(r.get("post_id")), str(r.get("comment_id"))
                    add(lid, cid, {"_seen": r.get("snapshot_at"), "created_at": r.get("createdAt"), "ts_quality": "exact",
                                   "parent_id": none_if(r.get("parentId")), "votes": none_if(r.get("votesCount")),
                                   "uid": str(r.get("commenter_user_id")), "body": r.get("body"),
                                   "is_maker_flag": None, "is_hunter_flag": None})
                    sources_by_launch[lid].add(f"raw/ph_at_launch/<day>/{k}")
        for r in jl(f"{D}/pal/{day}/live/comments_ts.jsonl"):
            lid, cid = str(r.get("launch_id")), str(r.get("comment_id"))
            im, ih = none_if(r.get("is_maker")), none_if(r.get("is_hunter"))
            add(lid, cid, {"_seen": r.get("fetched_at"), "created_at": r.get("created_at"), "ts_quality": "exact",
                           "parent_id": none_if(r.get("parent_id")), "votes": none_if(r.get("votes_at_fetch")),
                           "uid": str(r.get("commenter_user_id") or r.get("user_id")), "body": r.get("body"),
                           "is_maker_flag": im, "is_hunter_flag": ih})
            sources_by_launch[lid].add("raw/ph_at_launch/<day>/live/comments_ts.jsonl")
    # warehouse comments: text only for the oldest days (no comment id, date only)
    wrows = con.sql(f"""select launch_id, person, date, text, max(updated_at) u from read_parquet('{D}/wc/*.parquet', union_by_name=true)
                        where text is not null group by all""").fetchall()
    for lid, person, date, text, u in wrows:
        lid = str(lid)
        if lid not in ids or com.get(lid) and any(not k.startswith("wh:") for k in com[lid]): continue
        cid = "wh:" + str(abs(hash((person, date, text))) % 10**12)
        add(lid, cid, {"_seen": u, "created_at": date, "ts_quality": "day", "parent_id": None, "votes": None, "uid": None,
                       "uname": (person or "").lower(), "body": text, "is_maker_flag": None, "is_hunter_flag": None})
        sources_by_launch[lid].add("tables/comments (warehouse; date only, no comment id)")

    # 3. cohort: held people
    persons = con.sql(f"select person_id, ph_user_id, complete from '{D}/store/persons.parquet'").fetchall()
    uid2pid = {str(u): p for p, u, c in persons if u}
    complete = {p for p, u, c in persons if c}
    idlist = ",".join(f"'{i}'" for i in ids)
    upv = collections.defaultdict(set)
    for pid, t in con.sql(f"select distinct person_id, target_id from '{D}/store/events.parquet' where kind='upvote' and target_id in ({idlist})").fetchall():
        if pid in complete: upv[t].add(pid)
    cmt = collections.defaultdict(set)
    for pid, t in con.sql(f"select distinct person_id, target_id from '{D}/store/events.parquet' where kind='comment' and target_id in ({idlist})").fetchall():
        cmt[t].add(pid)
    for lid, cs in com.items():
        for c in cs.values():
            if c.get("uid") in uid2pid: cmt[lid].add(uid2pid[c["uid"]])

    cuts = {}
    for f in sorted(glob.glob(f"{D}/seg/priv_*.parquet")):
        c = re.search(r"priv_(.+)\.parquet", f).group(1)
        pubj = jload(f"{D}/seg/pub_{c}.json", {})
        gname = {g["id"]: g["name"] for g in pubj.get("groups", [])}
        sname = {s["id"]: s["name"] for g in pubj.get("groups", []) for s in g.get("subgroups", [])}
        m = {}
        for pid, g, sg in con.sql(f"select person_id, \"group\", subgroup from '{f}'").fetchall():
            gn = gname.get(g, f"group {g}")
            sub = sname.get(str(sg))
            m[pid] = (gn, f"{gn} / {sub}" if sub else gn)
        cuts[c] = m
    latest_cut = max(cuts) if cuts else None
    explain_cut = {}
    for day, d in explain.items():
        cs = re.findall(r'segments_cut": "([0-9-]+)', json.dumps(d))
        if cs: explain_cut[day] = collections.Counter(cs).most_common(1)[0][0]

    def seg_counts(people, cut, level):
        m = cuts[cut]; cnt = collections.Counter()
        for p in people:
            cnt[m[p][level] if p in m else "not segmented"] += 1
        out, other = {}, 0
        for k, v in cnt.most_common():
            if v >= MIN_CELL and k != "not segmented": out[k] = v
            else: other += v
        if other: out["other"] = other
        return out

    # ---- write ----
    fl = open(f"{OUT}/launches.jsonl", "w"); fc = open(f"{OUT}/comments.jsonl", "w")
    fk = open(f"{OUT}/cohort.jsonl", "w"); fp = open(f"{OUT}/predictions.jsonl", "w")
    summary = []
    for x in L:
        lid, day = x["id"], x["day"]
        dfp = dayfile.get(lid, {})
        u = url.get(lid)
        if u:
            purl, usrc, parked = strip_url(u["url"]), u["source"], u["parked"]
        else:
            purl, usrc, parked = strip_url(dfp.get("website")), "website field (PH redirect link, unresolved)", False
        kind = url_kind(purl if u else None, parked)
        # competitor
        comp_all, main = [], None
        a = alts.get(lid)
        if a and a.get("similar_products"):
            comp_all.append({"source": "PH 'Similar Products' (raw/ph_alternatives/similar_products_all.jsonl, read 2026-11-01)",
                             "items": [{"name": s.get("name"), "tagline": s.get("tagline")} for s in a["similar_products"][:5]]})
        if gcomp.get(lid):
            comp_all.append({"source": "raw/ph_predict_data/competitors.json",
                             "items": [{"name": s.get("name"), "domain": s.get("domain")} for s in gcomp[lid][:5]]})
        ex = (explain.get(day) or {}).get("launches", {}).get(lid) or {}
        exc = ex.get("competitors") if isinstance(ex.get("competitors"), dict) else None
        if exc and exc.get("items"):
            comp_all.append({"source": f"E5 explain results/web/explain/{day}.json (similar earlier PH launches by embedding)",
                             "items": [{"name": s.get("name"), "launch_date": s.get("launch_date"), "final_daily_rank": s.get("final_daily_rank"),
                                        "similarity": s.get("similarity")} for s in exc["items"][:5]]})
        def own(nm):  # the launch's own product or an earlier launch of it is not a competitor
            a_, b_ = norm(nm), norm(x["name"])
            return bool(a_) and bool(b_) and (a_ in b_ or b_ in a_ or a_.split()[0] == b_.split()[0])
        for c0 in comp_all:
            it = next((i for i in c0["items"] if i.get("name") and not own(i["name"])), None)
            if it:
                main = {"name": it.get("name"), "url": ("https://" + it["domain"]) if it.get("domain") else None, "source": c0["source"]}
                break
        # comments
        cs = com.get(lid, {})
        clist = []
        for cid, c in sorted(cs.items(), key=lambda kv: str(kv[1].get("created_at") or "")):
            is_maker = bool(c.get("is_maker_flag")) or (c.get("uid") in maker_ids.get(lid, set())) or \
                       (bool(c.get("uname")) and c.get("uname") in maker_names.get(lid, set()))
            role = "maker" if is_maker else ("hunter" if c.get("is_hunter_flag") else "non_maker")
            txt = clean_text(c.get("body"), [n for n in maker_names.get(lid, set()) if len(n) >= 3])
            if not txt: continue
            clist.append({"comment_id": None if cid.startswith("wh:") else cid, "created_at": c.get("created_at"), "ts_quality": c.get("ts_quality"),
                          "is_reply": c.get("parent_id") is not None, "parent_id": c.get("parent_id"),
                          "is_maker": is_maker, "role": role, "votes": int(float(c["votes"])) if c.get("votes") not in (None, "None") else None,
                          "text": txt})
        n_ph = none_if(dfp.get("commentsCount"))
        n_ph = int(n_ph) if n_ph is not None else None
        n_ph_raw = n_ph
        if n_ph is not None and len(clist) > n_ph: n_ph = len(clist)  # day file read before the day closed
        n_nonmaker = sum(1 for c in clist if not c["is_maker"])
        # cohort
        backers = upv.get(lid, set()); commenters = cmt.get(lid, set())
        votes = int(x["votes"]) if x.get("votes") is not None else None
        cov = round(len(backers) / votes, 4) if votes else None
        coh = {"day": day, "launch_id": lid, "name": x["name"], "final_daily_rank": int(x["daily_rank"]), "votes": votes,
               "n_held_backers": len(backers), "coverage": cov,
               "n_held_commenters": len(commenters), "n_held_commenters_complete": len(commenters & complete),
               "segments_cut": latest_cut,
               "backers_by_group": seg_counts(backers, latest_cut, 0) if latest_cut else None,
               "backers_by_segment": seg_counts(backers, latest_cut, 1) if latest_cut else None,
               "commenters_by_group": seg_counts(commenters, latest_cut, 0) if latest_cut else None,
               "commenters_by_segment": seg_counts(commenters, latest_cut, 1) if latest_cut else None}
        ec = explain_cut.get(day)
        if ec and ec in cuts and ec != latest_cut:
            coh["explain_segments_cut"] = ec
            coh["backers_by_segment_explain_cut"] = seg_counts(backers, ec, 1)
            coh["backers_by_group_explain_cut"] = seg_counts(backers, ec, 0)
        elif ec:
            coh["explain_segments_cut"] = ec
        # predictions
        fr = None
        P = pub.get((day, "0005"))
        if P:
            r = next((r for r in P.get("ranking", []) if str(r.get("id")) == lid), None)
            fr = {"predicted_rank": r["rank"] if r else None, "n_ranked": len(P.get("ranking", [])), "model": P.get("model"),
                  "source": f"results/web/predictions/{day}_0005.json", "written_at": P.get("written_at"),
                  "frozen_before_reveal": (P.get("written_at") or "9") < f"{day}T12:00"}
        elif day in f0005:
            F = f0005[day]
            r = next((r for r in F.get("forecast", []) if str(r.get("id")) == lid), None)
            run = F.get("run_updated_at") or ""
            fr = {"predicted_rank": r["predicted_rank"] if r else None, "n_ranked": len(F.get("forecast", [])),
                  "model": "then-published 00:05 line (pipeline forecast; arm 2 era before Nov 17)",
                  "source": f"results/web/forecast_0005/{day}.json", "written_at": run,
                  "frozen_before_reveal": run.replace("Z", "") < f"{day}T12:00"}
        pr = None
        PR = pub.get((day, "prereveal"))
        if PR:
            r = next((r for r in PR.get("ranking", []) if str(r.get("id")) == lid), None)
            pr = {"predicted_rank": r["rank"] if r else None, "model": PR.get("model"), "written_at": PR.get("written_at"),
                  "source": f"results/web/predictions/{day}_prereveal.json"}
        exw = ex.get("who") if isinstance(ex.get("who"), dict) else None
        exs = ex.get("say") if isinstance(ex.get("say"), dict) else None
        exp = None
        if exw or exs or exc:
            exp = {"source": f"results/web/explain/{day}.json", "written_at": explain[day].get("written_at"), "segments_cut": ec,
                   "who": None if not exw else {
                       "expected_held_votes": exw.get("expected_held_votes"),
                       "segments": exw.get("segments"),
                       "segments_by_lift_top200": exw.get("segments_by_lift"),
                       "groups_expected": (exw.get("groups_expected") or {}).get("groups"),
                       "hunter_past_backers_segments_by_lift": ((exw.get("hunter_past_backers") or {}).get("segments_by_lift") or [])[:8],
                       "what_likely_backers_upvote": exw.get("what_likely_backers_upvote")},
                   "say": None if not exs else {k: exs.get(k) for k in ("reactions", "top_concerns", "top_questions", "predicted_at")},
                   "persona_panel": None if not exs else [{k: i.get(k) for k in ("segment", "n_people", "reaction", "concern", "question", "interest")}
                                                         for i in (exs.get("persona_panel") or {}).get("items", [])] if isinstance(exs.get("persona_panel"), dict) else None,
                   "competitors": None if not exc else exc.get("items")}
        rec = {"day": day, "launch_id": lid, "name": x["name"], "tagline": x.get("tagline"),
               "product_url": purl, "product_url_source": usrc, "url_kind": kind, "web_testable": kind in WEB_TESTABLE,
               "final_daily_rank": int(x["daily_rank"]), "votes": votes, "n_comments": n_ph, "n_comments_held": len(clist),
               "n_comments_held_non_maker": n_nonmaker,
               "main_competitor": main, "competitors": comp_all or None,
               "topics": json.loads(x["topics"]) if x.get("topics") and x["topics"].startswith("[") else x.get("topics"),
               "outcome_source": "warehouse tables/launches (newest row per launch)", "outcome_updated_at": x.get("updated_at")}
        fl.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fc.write(json.dumps({"day": day, "launch_id": lid, "name": x["name"], "n_comments_ph": n_ph, "n_comments_ph_day_file": n_ph_raw,
                             "n_comments_held": len(clist), "capture_note": CAPTURE_NOTE.get(day, "full API capture (top-level and replies)"),
                             "sources": sorted(sources_by_launch.get(lid, [])),
                             "comment_themes": None,
                             "comment_themes_source": "not held: no E5 or PH-agent theme labels exist for this launch's own comments (E5 explain themes describe competitor launches; tables/judge_labels covers older launches only)",
                             "comments": clist}, ensure_ascii=False) + "\n")
        fk.write(json.dumps(coh, ensure_ascii=False) + "\n")
        fp.write(json.dumps({"day": day, "launch_id": lid, "name": x["name"], "final_daily_rank": int(x["daily_rank"]),
                             "forecast_0005": fr, "forecast_prereveal_0345": pr,
                             "explain_frozen": exp is not None and exw is not None,
                             "explain": exp}, ensure_ascii=False) + "\n")
        summary.append({**rec, "coverage": cov, "n_held_backers": len(backers), "has_explain": exp is not None and exw is not None})
    for f in (fl, fc, fk, fp): f.close()

    # 5. stratified sample for the plugin
    bands = [("1-3", 1, 3, 13), ("4-10", 4, 10, 14), ("11+", 11, 10**6, 13)]
    sample = []
    for bname, lo, hi, n in bands:
        pool = [s for s in summary if s["web_testable"] and lo <= s["final_daily_rank"] <= hi]
        nm = lambda s: s["n_comments_held_non_maker"] or 0
        key = lambda s: (2 if nm(s) >= 20 else 1 if nm(s) >= 8 else 0, min(s["coverage"] or 0, 1.0), nm(s))
        ranked = sorted(pool, key=key, reverse=True)
        picked, per_day = [], collections.Counter()
        for tier in (2, 1, 0):   # comment tier first; within a tier best first, at most `cap` per day, raise cap only when needed
            tp = [s for s in ranked if key(s)[0] == tier]
            cap = 1
            while len(picked) < n and any(s not in picked for s in tp):
                for s in tp:
                    if len(picked) >= n: break
                    if s not in picked and per_day[s["day"]] < cap:
                        picked.append(s); per_day[s["day"]] += 1
                cap += 1
        for s in picked:
            sample.append({"rank_band": bname, "day": s["day"], "rank": s["final_daily_rank"], "name": s["name"], "product_url": s["product_url"],
                           "competitor": (s["main_competitor"] or {}).get("name"), "competitor_url": (s["main_competitor"] or {}).get("url"),
                           "competitor_source": (s["main_competitor"] or {}).get("source"),
                           "launch_id": s["launch_id"], "tagline": s["tagline"], "votes": s["votes"], "n_comments_held": s["n_comments_held"],
                           "n_comments_held_non_maker": s["n_comments_held_non_maker"], "n_held_backers": s["n_held_backers"],
                           "coverage": s["coverage"], "has_explain_prediction": s["has_explain"], "url_kind": s["url_kind"]})
    sample.sort(key=lambda s: (s["day"], s["rank"]))
    json.dump({"built_from": "launches.jsonl (web_testable only)", "rule": "rank bands 1-3 / 4-10 / 11+ (13/14/13), round-robin over days; within a band prefer >= 20 held non-maker comments, then highest held-backer coverage",
               "n": len(sample), "launches": sample}, open(f"{OUT}/sample_for_plugin.json", "w"), ensure_ascii=False, indent=1)

    # stats
    covs = [s["coverage"] for s in summary if s["coverage"] is not None]
    st = {"window": [start, end], "launches": len(summary), "days": len({s["day"] for s in summary}),
          "web_testable": sum(s["web_testable"] for s in summary), "url_kind": collections.Counter(s["url_kind"] for s in summary),
          "url_resolved": sum(1 for s in summary if s["url_kind"] != "unresolved"),
          "with_competitor": sum(1 for s in summary if s["main_competitor"]),
          "comments_held": sum(s["n_comments_held"] for s in summary),
          "launches_with_comments": sum(1 for s in summary if s["n_comments_held"]),
          "launches_with_20plus_non_maker_comments": sum(1 for s in summary if s["n_comments_held_non_maker"] >= 20),
          "days_without_comment_text": sorted({s["day"] for s in summary} - {s["day"] for s in summary if s["n_comments_held"]}),
          "launches_with_forecast_0005": sum(1 for l in open(f"{OUT}/predictions.jsonl") if json.loads(l)["forecast_0005"]),
          "days_without_forecast_0005": sorted({s["day"] for s in summary} - {json.loads(l)["day"] for l in open(f"{OUT}/predictions.jsonl") if json.loads(l)["forecast_0005"]}),
          "launches_with_explain_prediction": sum(s["has_explain"] for s in summary),
          "explain_prediction_days": sorted({s["day"] for s in summary if s["has_explain"]}),
          "median_coverage": statistics.median(covs) if covs else None,
          "median_n_held_backers": statistics.median([s["n_held_backers"] for s in summary]),
          "segments_cut": latest_cut, "sample_n": len(sample),
          "sample_bands": collections.Counter(s["rank_band"] for s in sample), "sample_days": len({s["day"] for s in sample})}
    json.dump(st, open(f"{OUT}/build_stats.json", "w"), indent=1, default=str)
    print(json.dumps(st, indent=1, default=str))


if __name__ == "__main__":
    a = sys.argv[1:]
    start = a[a.index("--start") + 1] if "--start" in a else "2026-10-22"
    end = a[a.index("--end") + 1] if "--end" in a else "2026-11-20"
    if a[0] == "fetch":
        fetch(a[1], start, end)
    else:
        build(a[1], a[2], start, end)
