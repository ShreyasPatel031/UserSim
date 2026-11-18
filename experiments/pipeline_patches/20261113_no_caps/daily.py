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
# No-caps rule (AGENTS.md, Nov 13; bundle 11): PERSON_CAP no longer truncates. PERSON_BUDGET (pages per run) is a budget guard
# only: people beyond it are persisted to the bucket queue and read FIRST by the next run (never dropped).
PERSON_BUDGET = int(os.environ.get("PERSON_BUDGET", os.environ.get("PERSON_CAP", "8000")))
REQ = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/requests/pipeline"   # durable queues (handles live in the bucket only)


def _gcat_lines(path):
    r = subprocess.run(["gsutil", "-q", "cat", path], capture_output=True, text=True)
    return [l.strip() for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []


def _gput_lines(path, lines, dry):
    """Write a queue file to the bucket (temp object, then move: a reader never sees a half-written queue)."""
    if dry:
        return
    tmp = path + ".tmp"
    subprocess.run(["gsutil", "-q", "cp", "-", tmp], input="\n".join(lines) + ("\n" if lines else ""), text=True, check=True)
    subprocess.run(["gsutil", "-q", "mv", tmp, path], check=True)


def queue_read(name):
    """Every pending entry of a durable queue (raw/requests/pipeline/<name>/pending.txt)."""
    return _gcat_lines(f"{REQ}/{name}/pending.txt")


def queue_write(name, entries, dry):
    """Replace the pending list (deduplicated, order kept) and keep a dated copy for audit."""
    seen = set(); entries = [e for e in entries if not (e in seen or seen.add(e))]
    _gput_lines(f"{REQ}/{name}/pending.txt", entries, dry)
    return len(entries)
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
    # re-read (weekly / monthly ranks are still settling) into a fresh folder, verify every file, THEN replace the old one;
    # the old file is never deleted first (bundle 11: a failed re-pull used to leave the day missing)
    import pathlib, tempfile
    final = C.OUT; tmpd = pathlib.Path(tempfile.mkdtemp(prefix="ranks_", dir=str(final.parent)))
    C.OUT = tmpd
    try:
        C.main(start, end)
    finally:
        C.OUT = final
    replaced, kept = 0, []
    for k in range((end - start).days + 1):
        day = (start + dt.timedelta(days=k)).isoformat(); new, old = tmpd / f"{day}.json", final / f"{day}.json"
        try:
            rows = json.loads(new.read_text())
            ok = isinstance(rows, list) and (len(rows) > 0 or not old.exists() or not json.loads(old.read_text()))
            ok = ok and (not old.exists() or len(rows) >= 0.9 * len(json.loads(old.read_text())))   # a re-read never shrinks a day by >10%
        except Exception:  # noqa: BLE001
            ok = False
        if ok and not dry:
            os.replace(new, old); replaced += 1
        elif not ok:
            kept.append(day)
    import shutil
    shutil.rmtree(tmpd, ignore_errors=True)
    L = pd.concat([day_rows((start + dt.timedelta(days=k)).isoformat()) for k in range((end - start).days + 1)])
    if not dry:
        W.write("launches", L)
    out = {"items": len(L), "replaced": replaced}
    if kept:
        out["status"] = f"partial: {len(kept)} re-read day files failed verification and the previous files were kept ({', '.join(kept[:5])})"
    return out


@step("comments")
def s_comments(d, con, dry):
    import ph_comments as PC
    plan = INC.plan(con, d); slugs = plan["comments"]
    recs = F.get_many([PC.url(s) for s in slugs], threads=8)
    sid = dict(con.execute("SELECT slug, id FROM launches").fetchall())
    rows, st, bad, extra_pages = [], [], 0, 0
    with gzip.open(f"{RAW}/comments/page_daily_{d}.jsonl.gz", "wt") as f:
        for s, r in zip(slugs, recs):
            f.write(json.dumps({"url": r["url"], "status": r["status"], "route": r["route"], "html": r["body"]}) + "\n")
            try:
                info, cr = PC.parse(json.loads(r["body"]))
            except Exception:  # noqa: BLE001
                bad += 1
                continue
            # bundle 11: page 1 holds 50 threads; read every further page until the source says there is none
            page = 1
            while info.get("has_next") and page < 200:
                page += 1; rp = F.get_many([PC.url(s, page=page)], threads=1)[0]
                f.write(json.dumps({"url": rp["url"], "status": rp["status"], "route": rp["route"], "html": rp["body"], "page": page}) + "\n")
                try:
                    info, more = PC.parse(json.loads(rp["body"]))
                except Exception:  # noqa: BLE001
                    break
                if not more:
                    break
                cr += more; extra_pages += 1
            rows += [dict(c, slug=s) for c in cr]; st.append({"launch_id": sid.get(s), "slug": s, "source": "comments", "last_fetched": d, "items": len(cr),
                                                              "complete": not info.get("has_next")})
    team = {r[0]: set(json.loads(r[1])) | {r[2]} for r in con.execute("SELECT slug, makers, poster FROM launches WHERE day = ?", [INC.days_before(d, 1)]).fetchall()}
    C = pd.DataFrame([{"person": c["username"], "launch_id": sid.get(c["slug"]), "slug": c["slug"], "date": (c["created"] or "")[:10],
                       "text": None} for c in rows if c.get("username") and c["username"] not in team.get(c["slug"], set())])
    newp = INC.new_people_from_comments(rows, plan["known"])
    json.dump(newp, open(f"/tmp/new_people_{d}.json", "w"))
    # bundle 11: new commenters also go to a durable pull queue (they used to be counted, then pulled only if a later step ran)
    queue_write("new_commenters", queue_read("new_commenters") + list(newp), dry)
    usd, nbytes = F.cost(recs)
    if not dry and len(C):
        W.write("comments", C)
        W.write("events", C.assign(kind="comment", date_quality="exact")[["person", "launch_id", "date", "kind", "date_quality"]])
        W.write("launch_state", pd.DataFrame(st))
    log_spend(d, "comments", usd, dry)
    out = {"items": len(C), "bytes": nbytes, "usd": sum(usd.values()), "extra_thread_pages": extra_pages}
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


STORE_V3 = os.environ.get("PEOPLE_STORE", "gs://usersim-bakeoff-347838016394/usersim_sim/raw/population/store_v3")
SALT_GS = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/population/_salt"


def _hid(sl, u):
    """store_v3's person key: "p_" + sha256(salt + "producthunt:" + lower(username))[:16] (pool_size.hid, people_full.hid)."""
    import hashlib
    return "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16]


def people_from_store(con, d, dry, local=None):
    """Bundle 11 (orchestrator 15:26Z / 15:4xZ Nov 13): the people step reads the population store (raw/population/store_v3:
    events, tabs; full depth, every pull merged losslessly) instead of the page-1 delivery folders (raw/ph_people_daily/,
    last delivered Nov 2-3). Nothing in the store's upvotes or follows is dropped: every (person, target) pair goes either to
    the existing tables (same columns as before) or to a new unmatched table keyed on the store's own salted ids:
      events            upvotes of a person the warehouse knows by handle, on a launch in the launches table:
                        (person, launch_id, date = launch day, kind "upvote", date_quality "launch_day"), the warehouse convention
                        for every upvote (PH shows no upvote time)
      events_unmatched  every other store upvote: (person_id, target_id, kind, date, date_quality, reason) with the store's own
                        date (PT day of ts_lo if set, else of ts_hi) and quality (ts_quality: snapshot / bounded / ...), reason
                        person_no_handle or launch_not_in_warehouse
      follows           follows where both sides have a warehouse handle: (person, followee, observed_on = PT day the store
                        first saw it, new_since_last = True)
      follows_unmatched every other store follow: (person_id, followee_id, first_seen, reason), salted ids, reason
                        person_no_handle or followee_no_handle
      fetch_state       one row per person and source ("store_v3_upvotes", "store_v3_follows") when the store's tab pull is newer
                        than the last row written for it
      people            new commenters (the comments step's list), first_seen = d, as before
    Handles: store ids are matched to the usernames the warehouse already holds by hashing those usernames with the salt
    (never printed); no handle is ever read from the store or written to the unmatched tables. Dedup is incremental: a pair
    already in its table is not written again. Check (per kind): distinct store pairs == pairs in the matched table +
    pairs in the unmatched table after this run, else the step fails. Fails loudly when the store or salt cannot be read.
    local: a directory holding events/tabs parquet (dry tests)."""
    import pyarrow.parquet as pq, tempfile, shutil
    tmp = None
    try:
        if local:
            src = local
        else:
            tmp = src = tempfile.mkdtemp(prefix="ppl_store_")
            for f in ("events.parquet", "tabs.parquet"):
                if subprocess.run(["gsutil", "-q", "cp", f"{STORE_V3}/{f}", f"{src}/{f}"]).returncode:
                    return None, {"items": 0, "status": f"failed: cannot read {STORE_V3}/{f}"}
        sl_p = subprocess.run(["gsutil", "-q", "cat", SALT_GS], capture_output=True, text=True) if not os.environ.get("PEOPLE_SALT_FILE") \
            else None
        sl = (open(os.environ["PEOPLE_SALT_FILE"]).read() if sl_p is None else sl_p.stdout).strip()
        if not sl:
            return None, {"items": 0, "status": "failed: salt unreadable"}
        E = pq.read_table(f"{src}/events.parquet", columns=["person_id", "kind", "target_id", "ts_lo", "ts_hi", "ts_quality", "first_seen_at"],
                          filters=[("kind", "in", ["upvote", "follows"])]).to_pandas()
        T = pq.read_table(f"{src}/tabs.parquet", columns=["person_id", "tab", "count", "complete", "fetched_at"],
                          filters=[("tab", "in", ["upvotes", "following"])]).to_pandas()
        if E.empty or T.empty:
            return None, {"items": 0, "status": f"failed: store_v3 events/tabs empty ({len(E)} / {len(T)} rows)"}
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)   # everything needed is in memory by now
    def rows(q):
        try:
            return con.execute(q).fetchall()
        except Exception:   # table not created yet (first run)
            return []
    names = set()
    for q in ("SELECT DISTINCT person FROM people", "SELECT DISTINCT person FROM events", "SELECT DISTINCT person FROM comments",
              "SELECT DISTINCT person FROM follows", "SELECT DISTINCT followee FROM follows"):
        names |= {r[0] for r in rows(q) if r[0]}
    newp = json.load(open(f"/tmp/new_people_{d}.json")) if os.path.exists(f"/tmp/new_people_{d}.json") else []
    names |= set(newp)
    u_of = {_hid(sl, u): u for u in names}
    pt = lambda s: s.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
    E["person"] = E.person_id.map(u_of)
    stats = {"store_people": int(E.person_id.nunique()), "store_people_mapped": int(E.loc[E.person.notna(), "person_id"].nunique())}
    check, out_t = {}, {}
    # ---- upvotes
    day = dict(rows("SELECT id, day FROM launches"))
    U = E[E.kind == "upvote"].sort_values("first_seen_at").drop_duplicates(["person_id", "target_id"])
    ok = U.person.notna() & U.target_id.isin(day.keys())
    have = set(map(tuple, rows("SELECT person, launch_id FROM events WHERE kind = 'upvote'")))
    M = U[ok]; Mn = M[[(p, t) not in have for p, t in zip(M.person, M.target_id)]]
    out_t["events"] = pd.DataFrame({"person": Mn.person.values, "launch_id": Mn.target_id.values, "date": Mn.target_id.map(day).values,
                                    "kind": "upvote", "date_quality": "launch_day"})
    have_u = set(map(tuple, rows("SELECT person_id, target_id FROM events_unmatched WHERE kind = 'upvote'")))
    X = U[~ok]; Xn = X[[(p, t) not in have_u for p, t in zip(X.person_id, X.target_id)]]
    out_t["events_unmatched"] = pd.DataFrame({
        "person_id": Xn.person_id.values, "target_id": Xn.target_id.values, "kind": "upvote",
        "date": pt(Xn.ts_lo.fillna(Xn.ts_hi)).values, "date_quality": Xn.ts_quality.fillna("unknown").values,
        "reason": pd.Series(Xn.person.isna().values).map({True: "person_no_handle", False: "launch_not_in_warehouse"}).values})
    in_m = sum((p, t) in have for p, t in zip(M.person, M.target_id)) + len(Mn)
    in_x = sum((p, t) in have_u for p, t in zip(X.person_id, X.target_id)) + len(Xn)
    check["upvote"] = {"store_pairs": len(U), "in_events": int(in_m), "in_events_unmatched": int(in_x),
                       "written_events": len(Mn), "written_unmatched": len(Xn),
                       "unmatched_by_reason": out_t["events_unmatched"].reason.value_counts().to_dict() if len(Xn) else {}}
    # ---- follows (followee is a salted id in the store)
    Fo = E[E.kind == "follows"].sort_values("first_seen_at").drop_duplicates(["person_id", "target_id"]).copy()
    Fo["followee"] = Fo.target_id.map(u_of)
    ok = Fo.person.notna() & Fo.followee.notna()
    havef = set(map(tuple, rows("SELECT person, followee FROM follows")))
    M = Fo[ok]; Mn = M[[(p, f) not in havef for p, f in zip(M.person, M.followee)]]
    out_t["follows"] = pd.DataFrame({"person": Mn.person.values, "followee": Mn.followee.values, "observed_on": pt(Mn.first_seen_at).values,
                                     "new_since_last": True})
    havefu = set(map(tuple, rows("SELECT person_id, followee_id FROM follows_unmatched")))
    X = Fo[~ok]; Xn = X[[(p, f) not in havefu for p, f in zip(X.person_id, X.target_id)]]
    out_t["follows_unmatched"] = pd.DataFrame({
        "person_id": Xn.person_id.values, "followee_id": Xn.target_id.values, "first_seen": pt(Xn.first_seen_at).values,
        "reason": pd.Series(Xn.person.isna().values).map({True: "person_no_handle", False: "followee_no_handle"}).values})
    in_m = sum((p, f) in havef for p, f in zip(M.person, M.followee)) + len(Mn)
    in_x = sum((p, f) in havefu for p, f in zip(X.person_id, X.target_id)) + len(Xn)
    check["follows"] = {"store_pairs": len(Fo), "in_follows": int(in_m), "in_follows_unmatched": int(in_x),
                        "written_follows": len(Mn), "written_unmatched": len(Xn),
                        "unmatched_by_reason": out_t["follows_unmatched"].reason.value_counts().to_dict() if len(Xn) else {}}
    # ---- fetch_state
    T["person"] = T.person_id.map(u_of)
    last = dict(((p, s), v) for p, s, v in rows(
        "SELECT person, source, max(last_fetched) FROM fetch_state WHERE source IN ('store_v3_upvotes','store_v3_follows') GROUP BY 1, 2"))
    T = T[T.person.notna()].copy(); T["source"] = T.tab.map({"upvotes": "store_v3_upvotes", "following": "store_v3_follows"})
    T["last_fetched"] = pt(T.fetched_at)
    T = T[[str(l) > str(last.get((p, s)) or "") for p, s, l in zip(T.person, T.source, T.last_fetched)]]
    out_t["fetch_state"] = pd.DataFrame({"person": T.person.values, "source": T.source.values, "last_fetched": T.last_fetched.values,
                                         "status": 200, "items": pd.to_numeric(T["count"], errors="coerce").values,
                                         "complete": T.complete.astype(bool).values})
    bad = [k for k, c in check.items() if c["store_pairs"] != list(c.values())[1] + list(c.values())[2]]
    res = {"items": sum(len(v) for v in out_t.values()), "source": "store_v3", **{k: len(v) for k, v in out_t.items()},
           "new_people": len(newp), **stats, "check": check}
    if bad:   # never write a partial picture
        res["status"] = f"failed: store pairs != matched + unmatched for {bad}"
        return out_t, res
    if not dry:
        for t in ("events", "events_unmatched", "follows", "follows_unmatched", "fetch_state"):
            if len(out_t[t]):
                W.write(t, out_t[t])
        if newp:
            W.write("people", pd.DataFrame({"person": newp, "first_seen": d}))
    return out_t, res


@step("people")
def s_people(d, con, dry):
    """New commenters' and stale people's upvotes and follows. Default (PEOPLE_SRC=store_v3, bundle 11): read the population
    store (people_from_store; fails loudly when the store is unreadable). PEOPLE_SRC=delivery: Data Feeder's page-1 folders
    (fails loudly when none is there). PEOPLE_SRC=fetch: fetch here."""
    # bundle 11 (orchestrator 15:26Z Nov 13): default source is the population store (full depth). PEOPLE_SRC=delivery
    # reads the old page-1 folders; PEOPLE_SRC=fetch fetches here
    if os.environ.get("PEOPLE_SRC", "store_v3") == "store_v3":
        _, out = people_from_store(con, d, dry)
        return out
    if os.environ.get("PEOPLE_SRC") == "delivery":
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
        # bundle 11: people whose page 1 did not reach their newest known item go to the durable scroll-deeper queue (the
        # population fleet's full pulls read it); before, the list sat in /tmp and nothing read it
        queue_write("scroll_deeper", queue_read("scroll_deeper") + list(deeper), dry)
        recs = U + Fo; bad = sum(r["status"] != 200 for r in recs)
        out = {"items": len(ev) + len(fo), "delivery_day": day, "people": len(recs)}
        if not recs or bad / len(recs) > 0.5:
            out["status"] = f"failed: delivery {day} has {bad} of {len(recs)} fetches not ok"
        return out
    import importlib.util
    plan = INC.plan(con, d)
    newp = json.load(open(f"/tmp/new_people_{d}.json")) if os.path.exists(f"/tmp/new_people_{d}.json") else []
    # bundle 11: no truncation. The queues left by earlier runs are read FIRST; anything past the per-run budget is written
    # back to the queue for the next run (never dropped)
    prev_deeper = queue_read("scroll_deeper"); carry_u = queue_read("people_upvotes"); carry_f = queue_read("people_follows")
    want_u = list(dict.fromkeys(carry_u + prev_deeper + newp + plan["refresh_upvotes"]))
    want_f = list(dict.fromkeys(carry_f + newp + plan["follows"]))
    upv = want_u[:PERSON_BUDGET]; fol = want_f[: max(0, PERSON_BUDGET - len(upv))]
    queue_write("people_upvotes", want_u[len(upv):], dry); queue_write("people_follows", want_f[len(fol):], dry)
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
    json.dump(deeper, open(f"/tmp/deeper_{d}.json", "w"))
    # bundle 11: the scroll-deeper list is durable; this run consumed the previous queue (want_u above), so it is replaced
    queue_write("scroll_deeper", list(deeper), dry)
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
