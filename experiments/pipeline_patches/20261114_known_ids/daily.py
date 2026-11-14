"""The daily pipeline (runs on usersim-pipeline, started at 00:05 Pacific by a schedule; shuts itself down after).
Steps, each logged to the warehouse's pipeline_runs (items, bytes, dollars, seconds) and spend:
  1 launches   today's featured launches (Product Hunt API, free)
  2 forecast   today's ranking before any results (the launch model) -> forecasts
  3 ranks      refresh outcomes of the last 31 days (daily / weekly / monthly ranks settle late; API, free) -> launches
  4 comments   yesterday's launches, once (fetch ladder: direct first) -> comments, events; new commenters found
  5 people     new commenters: upvotes + following page 1, once; known active people: upvotes page 1 when stale or they
               commented since; follow lists weekly (Mondays) -> events, follows, fetch_state, people
  6 personas   today's line-up rated by each active person's comment persona (Gemini Flash-Lite) -> persona_ratings
  7 score      yesterday's forecast against its final daily ranks -> daily_scores
  8 earlyshock the early-vote shock backtest (ph_predict/early_shock.py) once 14 clean days exist -> backtests
  9 raw        today's raw files copied to the bucket (raw/<source>/<date>/)
usage: python -m pipeline.daily [YYYY-MM-DD] [--only step,step] [--dry-run]   (date = Pacific day; default today)"""
import datetime as dt, gzip, json, os, subprocess, sys, time
import pandas as pd
from collections import defaultdict
from . import warehouse as W, fetch as F, incremental as INC

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PH = os.path.join(EXP, "ph_predict"); RAW = os.path.join(PH, "data")
sys.path.insert(0, PH)
PERSONA_CAP = int(os.environ.get("PERSONA_CAP", "6000"))      # person-days rated per day (cost cap: ~$0.80)
PERSON_CAP = int(os.environ.get("PERSON_CAP", "8000"))        # pages per day for people (cost cap: ~$2.40)
RUNS = []
VM_USD_PER_HOUR = 0.134      # e2-standard-4 on demand, us-central1 (the pipeline machine)
BOOT_SECONDS = 180           # boot, wait, upload and shutdown around the steps


def pacific_today():
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def step(name):
    def deco(fn):
        def run(d, con, dry):
            t0 = time.time(); rec = {"run_date": d, "step": name, "status": "ok", "items": 0, "bytes": 0, "usd": 0.0}
            try:
                out = fn(d, con, dry) or {}
                rec.update({k: out[k] for k in ("items", "bytes", "usd", "status") if k in out})
            except Exception as e:  # noqa: BLE001
                rec.update(status=f"error: {str(e)[:300]}")
            rec["seconds"] = round(time.time() - t0, 1); RUNS.append(rec)
            print(json.dumps(rec), flush=True)
        run.__name__ = name
        return run
    return deco


def day_rows(d):
    nodes = json.load(open(f"{RAW}/days/{d}.json")) if os.path.exists(f"{RAW}/days/{d}.json") else \
        json.load(open(f"{RAW}/today/{d}.json"))
    return pd.DataFrame([{
        "id": str(p["id"]), "slug": p["slug"], "day": d, "name": p["name"], "tagline": p.get("tagline"),
        "description": p.get("description") or "", "topics": json.dumps([e["node"]["name"] for e in p["topics"]["edges"]]),
        "poster": (p.get("user") or {}).get("username"), "makers": json.dumps([m["username"] for m in p.get("makers") or []]),
        "daily_rank": p.get("dailyRank"), "weekly_rank": p.get("weeklyRank"), "monthly_rank": p.get("monthlyRank"),
        "votes": p.get("votesCount"),
        "outcome_final": d < (dt.date.fromisoformat(pacific_today()) - dt.timedelta(days=31)).isoformat()} for p in nodes])


@step("launches")
def s_launches(d, con, dry):
    subprocess.run(["python3", "today.py", d], cwd=PH, check=True)
    L = day_rows(d); L[["daily_rank", "weekly_rank", "monthly_rank", "votes"]] = None   # not final: never stored as outcomes
    if not dry:
        W.write("launches", L)
    if not dry and len(L):   # the trigger Data Feeder's at-launch capture watches (~00:06 PT; <d>.json itself lands ~00:30)
        r = subprocess.run(["gsutil", "-q", "cp", f"{RAW}/today/{d}.json", f"{W.BUCKET}/raw/daily/{d}/today_0005.json"], check=False)
        if r.returncode:
            return {"items": len(L), "status": "failed: today_0005.json upload"}
    return {"items": len(L), **({} if len(L) else {"status": "failed: 0 launches fetched for today"})}


def snap_fields(t, tagline=None):
    """This product's fields on its page (the page also lists other products: anchor on the one launching today)."""
    import re
    m = re.search(r'"launchingToday":true\},"tagline":"(?:[^"\\]|\\.)*","followersCount":(\d+)', t)
    fol = int(m.group(1)) if m else None
    b = re.search(r'"reviewsCount":(\d+),"followersCount":%s,"isTopProduct":(true|false),"founderDetailedReviewsCount":\d+,'
                  r'"firstLaunch":(true|false)' % (fol if fol is not None else r"\d+"), t)
    return {"product_followers": fol, "product_reviews": int(b.group(1)) if b else None,
            "top_product": b.group(2) == "true" if b else None, "first_launch": b.group(3) == "true" if b else None}


@step("at_launch")
def s_at_launch(d, con, dry):
    """Makers' and hunter's PH follower counts as read at 00:05 PT (pipeline.at_launch), before votes: honest inputs."""
    from . import at_launch as AL
    R = AL.rows(d)
    if not dry and len(R):
        W.write("at_launch_followers", R)
    return {"items": len(R)} if len(R) else {"items": 0, "status": f"failed: no data/today/{d}.json"}


@step("list_check")
def s_list_check(d, con, dry):
    """Today's API list vs Grok Bot's newest featured leaderboard read (today's if it exists yet, else yesterday's).
    A featured launch missing today: the day is paged again in both orders and the launch added before the forecast."""
    from . import list_check as LC
    out = LC.step(d)
    if out.get("added") and not dry:
        L = day_rows(d); L[["daily_rank", "weekly_rank", "monthly_rank", "votes"]] = None
        W.write("launches", L)
    print(json.dumps({"list_check": out}), flush=True)
    return {"items": out.get("missing", 0), "status": out["status"]}


@step("snap")
def s_snap(d, con, dry):
    """Product pages of today's launches at forecast time: product followers (people who asked to be notified, plus
    earlier fans), reviews, first launch or not. Not dated in the past, so collected going forward only; the model may use
    it once enough days exist to backtest it. Votes and comments on the page are launch-day results: never stored."""
    P = json.load(open(f"{RAW}/today/{d}.json"))
    recs = F.get_many([f"https://www.producthunt.com/posts/{p['slug']}" for p in P], threads=8)
    rows = []
    for p, r in zip(P, recs):
        rows.append({"launch_id": str(p["id"]), "day": d, "observed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     **snap_fields(r["body"], p["tagline"]), "status": r["status"], "route": r["route"]})
    usd, nbytes = F.cost(recs)
    if not dry:
        W.write("launch_snapshots", pd.DataFrame(rows))
    log_spend(d, "snap", usd, dry)
    return {"items": sum(r["product_followers"] is not None for r in rows), "bytes": nbytes, "usd": sum(usd.values())}


@step("forecast")
def s_forecast(d, con, dry):
    subprocess.run(["bash", "-c", f'''NO_WB=1 python3 - {d} <<'PY'
import json, os, sys, resolve_sites as R
d = sys.argv[1]; out = "data/sites_today.jsonl"
done = {{json.loads(l)["id"] for l in open(out)}} if os.path.exists(out) else set()
with open(out, "a") as f:
    for p in json.load(open(f"data/today/{{d}}.json")):
        if p["id"] not in done:
            p["_date"] = d; R.one(p, f)
PY
python3 external.py x
python3 fol_features.py > /dev/null && python3 seg_features.py > /dev/null
TODAY={d} python3 promo_search.py 99 8 && python3 promo_features.py
python3 forecast.py {d}'''], cwd=PH, check=True)
    import re
    rows = []
    # ids from the forecast parquet (id + published_rank), not from names in the .md (bug sweep item 4: Oct 29 had 2 duplicated names, so
    # 2 launches lost their id). Falls back to the .md parse only for a parquet without published_rank (older forecast.py).
    FP = pd.read_parquet(f"{PH}/results/forecast_{d}.parquet") if os.path.exists(f"{PH}/results/forecast_{d}.parquet") else None
    if FP is not None and "published_rank" in FP:
        nm = {str(p["id"]): p["name"] for p in json.load(open(f"{RAW}/today/{d}.json"))}
        for r in FP.sort_values("published_rank").itertuples():
            rows.append({"forecast_date": d, "model": "launch_model", "predicted_rank": int(r.published_rank), "name": nm.get(str(r.id), ""),
                         "launch_id": str(r.id), "made_on": d})
        if not dry:
            W.write("forecasts", pd.DataFrame(rows))
        return {"items": len(rows), "source": "forecast parquet ids"}
    name2id = {p["name"].strip(): str(p["id"]) for p in json.load(open(f"{RAW}/today/{d}.json"))}
    for l in open(f"{PH}/results/forecast_{d}.md"):
        m = re.match(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|", l)
        if m:
            rows.append({"forecast_date": d, "model": "launch_model", "predicted_rank": int(m.group(1)), "name": m.group(2),
                         "launch_id": name2id.get(m.group(2).strip()), "made_on": d})
    if not dry:
        W.write("forecasts", pd.DataFrame(rows))
    return {"items": len(rows)}


@step("simforecast")
def s_simforecast(d, con, dry):
    """Simulation-only forecast: the person simulation scored live (pipeline.sim_daily), then the launch-level
    simulation model (ph_predict/sim_forecast.py). Written to `forecasts` as model "simulation"."""
    from . import sim_daily
    log = sim_daily.run(d)
    subprocess.run(["python3", "sim_forecast.py", d], cwd=PH, check=True)
    import re
    name2id = {p["name"].strip(): str(p["id"]) for p in json.load(open(f"{RAW}/today/{d}.json"))}
    rows = []
    for l in open(f"{PH}/results/sim_forecast_{d}.md"):
        m = re.match(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|", l)
        if m:
            rows.append({"forecast_date": d, "model": "simulation", "predicted_rank": int(m.group(1)), "name": m.group(2),
                         "launch_id": name2id.get(m.group(2).strip()), "made_on": d})
    if not dry and rows:
        W.write("forecasts", pd.DataFrame(rows))
    out = {"items": len(rows)}
    if log["launches_scored"] < log["launches_today"]:
        out["status"] = f"failed: simulation scored {log['launches_scored']} of {log['launches_today']} launches"
    return out


SHADOW = os.path.join(PH, "data", "shadow")   # shadow forecasts: <SHADOW>/<name>/predict.py, run next to the live ones
SHADOW_DEFAULT = "daycal,honest_a2"   # honest_a2: live offset + day terms + A1 team history + A2 team comments (bundle 6)


@step("shadow")
def s_shadow(d, con, dry):
    """Shadow forecasts, scored daily like the others (s_score) but not published: each installed
    <SHADOW>/<name>/predict.py (SHADOW_MODELS, comma-separated) is run in its own process as
    `python3 predict.py <day>` and prints JSON lines {"launch_id", "score"} (higher = more votes) for the day's line-up.
    Written to `forecasts` as model "shadow_<name>". A model that is not installed is skipped; one that fails, covers
    under 90% of the line-up, or prints nothing fails the step loudly."""
    lineup = {str(p["id"]): p["name"] for p in json.load(open(f"{RAW}/today/{d}.json"))}
    out, bad = {"items": 0}, []
    for name in [n for n in os.environ.get("SHADOW_MODELS", SHADOW_DEFAULT).split(",") if n]:
        path = os.path.join(SHADOW, name)
        if not os.path.exists(os.path.join(path, "predict.py")):
            out[name] = "not installed"; continue
        r = subprocess.run(["python3", "predict.py", d], cwd=path, capture_output=True, text=True, timeout=3600)
        rows = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")] if r.returncode == 0 else []
        got = {str(x["launch_id"]): float(x["score"]) for x in rows if str(x.get("launch_id")) in lineup}
        if r.returncode or len(got) < 0.9 * len(lineup):
            bad.append(f"{name}: exit {r.returncode}, {len(got)} of {len(lineup)} launches ({r.stderr.strip()[-200:]})"); continue
        rank = sorted(got, key=lambda x: -got[x])
        if not dry:   # the scores themselves, for the weekly board (comparable across days)
            pd.DataFrame({"id": list(got), "day": d, "score": list(got.values())}).to_parquet(f"{PH}/results/shadow_{name}_{d}.parquet")
        F_ = pd.DataFrame([{"forecast_date": d, "model": f"shadow_{name}", "predicted_rank": i + 1, "name": lineup[x],
                            "launch_id": x, "made_on": d} for i, x in enumerate(rank)])
        if not dry:
            W.write("forecasts", F_)
        out["items"] += len(F_); out[name] = len(F_)
    if bad:
        out["status"] = "failed: " + "; ".join(bad)
    return out


@step("ranks")
def s_ranks(d, con, dry):
    import collect_ph as C
    end = dt.date.fromisoformat(d) - dt.timedelta(days=1); start = end - dt.timedelta(days=30)
    for k in range((end - start).days + 1):               # re-read: weekly / monthly ranks are still settling
        f = C.OUT / f"{start + dt.timedelta(days=k)}.json"
        if f.exists():
            f.unlink()
    C.main(start, end)
    L = pd.concat([day_rows((start + dt.timedelta(days=k)).isoformat()) for k in range((end - start).days + 1)])
    if not dry:
        W.write("launches", L)
    return {"items": len(L)}


@step("comments")
def s_comments(d, con, dry):
    import ph_comments as PC
    plan = INC.plan(con, d); slugs = plan["comments"]
    recs = F.get_many([PC.url(s) for s in slugs], threads=8)
    sid = dict(con.execute("SELECT slug, id FROM launches").fetchall())
    rows, st, bad = [], [], 0
    with gzip.open(f"{RAW}/comments/page_daily_{d}.jsonl.gz", "wt") as f:
        for s, r in zip(slugs, recs):
            f.write(json.dumps({"url": r["url"], "status": r["status"], "route": r["route"], "html": r["body"]}) + "\n")
            try:
                info, cr = PC.parse(json.loads(r["body"]))
            except Exception:  # noqa: BLE001
                bad += 1
                continue
            rows += [dict(c, slug=s) for c in cr]; st.append({"launch_id": sid.get(s), "slug": s, "source": "comments", "last_fetched": d, "items": len(cr)})
    team = {r[0]: set(json.loads(r[1])) | {r[2]} for r in con.execute("SELECT slug, makers, poster FROM launches WHERE day = ?", [INC.days_before(d, 1)]).fetchall()}
    C = pd.DataFrame([{"person": c["username"], "launch_id": sid.get(c["slug"]), "slug": c["slug"], "date": (c["created"] or "")[:10],
                       "text": None} for c in rows if c.get("username") and c["username"] not in team.get(c["slug"], set())])
    newp = INC.new_people_from_comments(rows, plan["known"])
    json.dump(newp, open(f"/tmp/new_people_{d}.json", "w"))
    usd, nbytes = F.cost(recs)
    if not dry and len(C):
        W.write("comments", C)
        W.write("events", C.assign(kind="comment", date_quality="exact")[["person", "launch_id", "date", "kind", "date_quality"]])
        W.write("launch_state", pd.DataFrame(st))
    log_spend(d, "comments", usd, dry)
    out = {"items": len(C), "bytes": nbytes, "usd": sum(usd.values())}
    if slugs and bad / len(slugs) > 0.5:   # blocked or unparseable pages: never "ok"
        out["status"] = f"failed: {bad} of {len(slugs)} comment pages blocked or unparseable"
    return out


def log_spend(d, what, usd, dry):
    rows = [{"step": f"daily_{what}", "provider": k, "usd": v, "note": d, "logged_on": d} for k, v in usd.items() if v]
    if rows and not dry:
        W.write("spend", pd.DataFrame(rows))


PEOPLE_BUCKET = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_people_daily"


def people_delivery(d):
    """Data Feeder's daily people refresh (raw/ph_people_daily/<day>/, about 10:00 UTC): the newest folder dated d or the
    day before (this run starts at 00:05 PT, before that day's delivery). Returns (day, upvote records, follow records)
    in parse_upvotes.py / parse_following.py form, with each person's fetch status; (None, [], []) if neither exists."""
    for day in (d, INC.days_before(d, 1)):
        base = f"{PEOPLE_BUCKET}/{day}"
        got = subprocess.run(["gsutil", "-q", "cat", f"{base}/fetch_state_rows.jsonl"], capture_output=True, text=True)
        if got.returncode or not got.stdout.strip():
            continue
        st = [json.loads(l) for l in got.stdout.splitlines() if l.strip()]
        read = lambda f: [json.loads(l) for l in subprocess.run(["gsutil", "-q", "cat", f"{base}/{f}"], capture_output=True, text=True,
                                                                 check=True).stdout.splitlines() if l.strip()]
        ups, fol = defaultdict(list), defaultdict(list)
        for r in sorted(read("upvotes_page1.jsonl"), key=lambda r: r.get("position") or 0):
            ups[r["username"]].append(r)
        for r in sorted(read("following_page1.jsonl"), key=lambda r: r.get("position") or 0):
            fol[r["username"]].append(r)
        U = [{"username": r["person"], "status": r["status"], "upvotes": [str(x["post_id"]) for x in ups.get(r["person"], [])],
              "has_more": any(x.get("has_more") for x in ups.get(r["person"], [])) or not r.get("complete", False)}
             for r in st if r["source"] == "upvotes_page1"]
        Fo = [{"username": r["person"], "status": r["status"], "following": [[x["followee"], x.get("followee_followers")] for x in fol.get(r["person"], [])],
               "has_more": any(x.get("has_more") for x in fol.get(r["person"], []))}
              for r in st if r["source"] == "follows"]
        return day, U, Fo
    return None, [], []


@step("people")
def s_people(d, con, dry):
    """New commenters' and stale people's upvote and following pages. Default (PEOPLE_SRC=delivery): read Data Feeder's
    daily refresh; fails loudly when no folder is there or most of its fetches failed. PEOPLE_SRC=fetch: fetch here."""
    if os.environ.get("PEOPLE_SRC", "delivery") == "delivery":
        day, U, Fo = people_delivery(d)
        if day is None:
            return {"items": 0, "status": f"failed: no Data Feeder people delivery for {d} or the day before ({PEOPLE_BUCKET})"}
        ev, st_u, deeper = INC.merge_upvotes(con, U, day)
        fo, st_f = INC.merge_follows(con, Fo, day)
        newp = json.load(open(f"/tmp/new_people_{d}.json")) if os.path.exists(f"/tmp/new_people_{d}.json") else []
        if not dry:
            for t, df in (("events", ev), ("fetch_state", st_u), ("follows", fo), ("fetch_state", st_f)):
                if len(df):
                    W.write(t, df)
            if newp:
                W.write("people", pd.DataFrame({"person": newp, "first_seen": d}))
        json.dump(deeper, open(f"/tmp/deeper_{d}.json", "w"))
        recs = U + Fo; bad = sum(r["status"] != 200 for r in recs)
        out = {"items": len(ev) + len(fo), "delivery_day": day, "people": len(recs)}
        if not recs or bad / len(recs) > 0.5:
            out["status"] = f"failed: delivery {day} has {bad} of {len(recs)} fetches not ok"
        return out
    import importlib.util
    plan = INC.plan(con, d)
    newp = json.load(open(f"/tmp/new_people_{d}.json")) if os.path.exists(f"/tmp/new_people_{d}.json") else []
    upv = (newp + plan["refresh_upvotes"])[:PERSON_CAP]
    fol = (newp + plan["follows"])[: max(0, PERSON_CAP - len(upv))]
    recs_u = F.get_many([f"https://www.producthunt.com/@{u}/upvotes" for u in upv], threads=12, start_route=1)
    recs_f = F.get_many([f"https://www.producthunt.com/@{u}/following" for u in fol], threads=12, start_route=1)
    parse = lambda script, recs: [json.loads(l) for l in subprocess.run(
        ["python3", script], cwd=PH, input="\n".join(json.dumps({"url": r["url"], "status": r["status"], "route": r["route"],
                                                                  "html": r["body"]}) for r in recs),
        capture_output=True, text=True).stdout.splitlines() if l.strip()]
    U, Fo = parse("parse_upvotes.py", recs_u), parse("parse_following.py", recs_f)
    ev, st_u, deeper = INC.merge_upvotes(con, U, d)
    fo, st_f = INC.merge_follows(con, Fo, d)
    if not dry:
        for t, df in (("events", ev), ("fetch_state", st_u), ("follows", fo), ("fetch_state", st_f)):
            W.write(t, df)
        if newp:
            W.write("people", pd.DataFrame({"person": newp, "first_seen": d}))
    json.dump(deeper, open(f"/tmp/deeper_{d}.json", "w"))   # scrolled later, stop-at-known (rare)
    usd, nbytes = F.cost(recs_u + recs_f); log_spend(d, "people", usd, dry)
    out = {"items": len(ev) + len(fo), "bytes": nbytes, "usd": sum(usd.values())}
    # a blocked fetch must not pass as "ok" (Oct 30 - Nov 1: every upvote page was 403 and the step still said ok)
    recs = recs_u + recs_f; bad = sum(r["status"] != 200 for r in recs)
    if recs and bad / len(recs) > 0.5:
        out["status"] = f"failed: {bad} of {len(recs)} pages blocked or errored (status != 200)"
    return out


@step("ph_upvotes")
def s_ph_upvotes(d, con, dry):
    """Upvote pages fetched by Grok Bot's team (raw/ph_upvotes/), merged into events like the people step's own pages."""
    from . import load_signed_in as LS
    out = LS.load_ph(d, dry)
    res = {"items": out["new_events"]}
    if out["records"] and out["ok_pages"] / out["records"] < 0.5:
        res["status"] = f"failed: {out['ok_pages']} of {out['records']} delivered pages ok"
    return res


@step("personas")
def s_personas(d, con, dry):
    """Comment persona x today's line-up, Gemini Flash-Lite (the design that won persona_lab), for active people."""
    sys.path.insert(0, EXP)
    from simlab.persona import card
    from simlab.taste import PROMPT
    from simlab.persona_lab import gem, PRICE
    import re
    from concurrent.futures import ThreadPoolExecutor
    line = [r[0] for r in con.execute(f"SELECT id FROM launches WHERE day = '{d}' ORDER BY id").fetchall()]
    names = dict(con.execute("SELECT id, name || ': ' || coalesce(tagline, '') FROM launches").fetchall())
    slugname = dict(con.execute("SELECT slug, name || ': ' || coalesce(tagline, '') FROM launches").fetchall())
    ppl = con.execute(f"""SELECT DISTINCT e.person FROM events e JOIN comments c ON c.person = e.person AND c.date < '{d}'
                          WHERE e.date >= '{INC.days_before(d, 30)}' AND e.date < '{d}'""").df().person.tolist()[:PERSONA_CAP]
    P = con.execute("SELECT * FROM people").df().set_index("person")
    hist = con.execute(f"SELECT person, launch_id FROM events WHERE date < '{d}' ORDER BY date").df().groupby("person").launch_id.apply(list).to_dict()
    com = con.execute(f"SELECT person, slug, text FROM comments WHERE date < '{d}' AND text IS NOT NULL ORDER BY date").df().groupby("person").apply(
        lambda g: list(zip(g.slug, g.text))[-5:], include_groups=False).to_dict()
    lu = "\n".join(f"{k + 1}. {names.get(x, x)}" for k, x in enumerate(line))
    rows, tok = [], [0, 0]

    def one(u):
        p = P.loc[u].to_dict() if u in P.index else {}
        p["seg"] = p.get("segments")
        h = hist.get(u, [])
        c = card(p, list(range(len(h))), {k: names.get(x, x) for k, x in enumerate(h)}, d)
        cs = com.get(u, [])
        if cs:
            c += " | their comments: " + " / ".join(f"on {slugname.get(s, s)[:40]}: \"{t[:160]}\"" for s, t in cs)
        txt, ti, to = gem(PROMPT.format(card=c, lineup=lu, n=len(line)), "lite")
        tok[0] += ti; tok[1] += to
        try:
            rt = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))["ratings"]
            return [(u, d, x, "rate_comments_lite", float(v)) for x, v in zip(line, rt)] if len(rt) == len(line) else []
        except Exception:  # noqa: BLE001
            return []
    if not dry and line:
        with ThreadPoolExecutor(48) as ex:
            for r in ex.map(one, ppl):
                rows += r
        W.write("persona_ratings", pd.DataFrame(rows, columns=["person", "day", "launch_id", "design", "rating"]))
    usd = tok[0] / 1e6 * PRICE["lite"][0] + tok[1] / 1e6 * PRICE["lite"][1]
    log_spend(d, "personas", {"gemini": round(usd, 4)}, dry)
    return {"items": len(rows), "usd": usd}


@step("score")
def s_score(d, con, dry):
    """Yesterday's forecast vs its final daily ranks (daily rank is final the next day)."""
    y = INC.days_before(d, 1)
    T = con.execute(f"""SELECT f.model, f.predicted_rank, l.daily_rank FROM forecasts f JOIN launches l ON l.id = f.launch_id
                        WHERE f.forecast_date = '{y}' AND l.daily_rank IS NOT NULL""").df()
    if not len(T):
        return {"items": 0}
    T = T.drop_duplicates(["model", "daily_rank"])   # one row per launch and model if a forecast was written twice
    # line-up gaps, so the honest treatment is visible: late_featured = launches on the final featured board that were
    # not in the 00:05 PT line-up the forecast saw (they count as misses); late_in_top_k = those among the top k;
    # dropped_from_featured = line-up launches with no final daily rank
    lineup = set(con.execute(f"SELECT DISTINCT launch_id::VARCHAR FROM forecasts WHERE forecast_date = '{y}' AND model = 'launch_model'").df().iloc[:, 0])
    fin = con.execute(f"SELECT id::VARCHAR AS id, daily_rank FROM launches WHERE day::VARCHAR = '{y}' AND daily_rank IS NOT NULL").df()
    late = fin[~fin.id.isin(lineup)] if lineup else fin.iloc[:0]
    dropped = len(lineup - set(fin.id))
    rows = [{"day": y, "model": mdl, "k": k,
             "hit": int(((g.predicted_rank <= k) & (g.daily_rank <= k)).sum()), "recall": ((g.predicted_rank <= k) & (g.daily_rank <= k)).sum() / k,
             "late_featured": len(late), "late_in_top_k": int((late.daily_rank <= k).sum()), "dropped_from_featured": dropped}
            for mdl, g in T.groupby("model") for k in (3, 5, 10)]
    rows += weekly_scores(d, con)
    if not dry:
        W.write("daily_scores", pd.DataFrame(rows))
    return {"items": len(rows)}


def weekly_scores(d, con):
    """On the run two days after a week ends (Tuesday), that ISO week's board vs each model's scores summed over its
    seven days: the launch model (results/forecast_<day>.parquet pred) and every shadow (results/shadow_<name>_<day>.parquet).
    Rows go to daily_scores with day = the week's Sunday and model "weekly:<model>". A model missing a day is skipped."""
    sun = dt.date.fromisoformat(d) - dt.timedelta(days=2)
    if sun.weekday() != 6:
        return []
    days = [(sun - dt.timedelta(days=k)).isoformat() for k in range(6, -1, -1)]
    L = con.execute(f"SELECT id, weekly_rank FROM launches WHERE day::VARCHAR IN ({','.join(repr(x) for x in days)}) AND weekly_rank IS NOT NULL").df()
    L["id"] = L.id.astype(str)
    files = {"launch_model": [f"{PH}/results/forecast_{x}.parquet" for x in days]}
    for name in [n for n in os.environ.get("SHADOW_MODELS", SHADOW_DEFAULT).split(",") if n]:
        files[f"shadow_{name}"] = [f"{PH}/results/shadow_{name}_{x}.parquet" for x in days]
    rows = []
    for mdl, fs in files.items():
        if not all(os.path.exists(f) for f in fs):
            continue
        S = pd.concat([pd.read_parquet(f) for f in fs]); S["id"] = S.id.astype(str)
        S = S.rename(columns={"pred": "score"}).merge(L, on="id")
        for k in (3, 5, 10):
            if (S.weekly_rank <= k).sum() == k:
                hit = len(set(S.nlargest(k, "score").id) & set(S[S.weekly_rank <= k].id))
                rows.append({"day": sun.isoformat(), "model": f"weekly:{mdl}", "k": k, "hit": hit, "recall": hit / k})
    return rows


@step("poolscore")
def s_poolscore(d, con, dry):
    """The person model's daily metric: for the launches of day d-7 (complete: a person's upvotes are seen only when
    their upvote page is next read, and the daily refresh reaches stale people within about 7 days) and of day d-1
    (provisional, labelled), the within-day Spearman of the live pool simulation's expected pool picks
    (data/sim_live/pnx_<day>.json, pnx_ev) with the real number of pool people who upvoted or commented on each launch,
    and the share of each launch's final votes cast by pool people. -> warehouse table pool_scores."""
    from scipy.stats import spearmanr
    rows = []
    for lag, label in ((7, "complete"), (1, "provisional")):
        day = INC.days_before(d, lag)
        f = os.path.join(RAW, "sim_live", f"pnx_{day}.json")
        if not os.path.exists(f):
            continue
        S = json.load(open(f))
        R = con.execute(f"""SELECT l.id::VARCHAR AS id, l.votes, count(DISTINCT e.person) AS pool
                            FROM launches l LEFT JOIN events e ON e.launch_id::VARCHAR = l.id::VARCHAR AND e.kind IN ('upvote', 'comment')
                            WHERE l.day::VARCHAR = '{day}' GROUP BY 1, 2""").df()
        R["ev"] = R.id.map(lambda x: (S.get(x) or {}).get("pnx_ev"))
        R = R[R.ev.notna()]
        if len(R) < 5:
            continue
        rho = spearmanr(R.ev, R.pool).correlation if R.pool.nunique() > 1 and R.ev.nunique() > 1 else None   # none yet: no voters seen
        share = (R.pool / R.votes.where(R.votes > 0)).mean()
        rows.append({"day": day, "scored_on": d, "status": label, "model": "pnx", "launches": len(R), "pool_spearman": None if rho is None or pd.isna(rho) else float(rho),
                     "pool_share_of_votes": float(share) if pd.notna(share) else None, "pool_voters": int(R.pool.sum())})
    if rows and not dry:
        W.write("pool_scores", pd.DataFrame(rows))
    for r in rows:
        print(json.dumps({"poolscore": r}), flush=True)
    return {"items": len(rows)}


@step("earlyshock")
def s_earlyshock(d, con, dry):
    """Early-vote shock correction backtest (ph_predict/early_shock.py). Until 14 clean days exist it only reports how
    many there are (status ok); from then on it writes its results to `backtests` (run_file early_shock_<date>)."""
    r = subprocess.run(["python3", "early_shock.py"] + ([] if dry else ["--write"]), cwd=PH, capture_output=True, text=True,
                       timeout=1800)
    st = next((json.loads(l)["early_shock"] for l in r.stdout.splitlines() if l.startswith('{"early_shock"')), None)
    if r.returncode or st is None:
        return {"status": f"failed: exit {r.returncode} ({r.stderr.strip()[-200:]})"}
    print(json.dumps({"earlyshock": {k: st[k] for k in ("ready", "clean_days", "needed", "first", "last")}}), flush=True)
    return {"items": st["clean_days"]}


@step("raw")
def s_raw(d, con, dry):
    files = [f"{RAW}/today/{d}.json", f"{RAW}/comments/page_daily_{d}.jsonl.gz", f"{PH}/results/forecast_{d}.md",
             f"{PH}/results/forecast_{d}.parquet",          # the honest prior in log votes (early_shock.py reads it)
             f"{RAW}/sim_live/pnx_{d}.json"]                # popscore's live outputs (early_shock.py reads them)
    files = [f for f in files if os.path.exists(f)]
    if not dry:
        for f in files:
            subprocess.run(["gsutil", "-q", "cp", f, f"{W.BUCKET}/raw/daily/{d}/"], check=False)
    return {"items": len(files)}


STEPS = [s_launches, s_at_launch, s_list_check, s_snap, s_forecast, s_simforecast, s_shadow, s_ranks, s_comments, s_people, s_ph_upvotes, s_personas, s_score, s_poolscore, s_earlyshock, s_raw]


def main(argv):
    d = next((a for a in argv if a[:2] == "20"), pacific_today()); dry = "--dry-run" in argv
    only = next((a.split("=", 1)[1].split(",") for a in argv if a.startswith("--only=")), None)
    con = W.connect()
    for s in STEPS:
        if only is None or s.__name__ in only:
            s(d, con, dry)
            if s.__name__ in ("launches", "ranks", "comments", "people") and not dry:
                con = W.connect(do_sync=False)                  # later steps see what earlier steps wrote
    if not dry:
        W.write("pipeline_runs", pd.DataFrame(RUNS))
        secs = sum(r["seconds"] for r in RUNS) + BOOT_SECONDS
        log_spend(d, "machine", {"gcp_vm": round(secs / 3600 * VM_USD_PER_HOUR, 4)}, dry)


if __name__ == "__main__":
    main(sys.argv[1:])
