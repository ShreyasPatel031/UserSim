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
  8 raw        today's raw files copied to the bucket (raw/<source>/<date>/)
usage: python -m pipeline.daily [YYYY-MM-DD] [--only step,step] [--dry-run]   (date = Pacific day; default today)"""
import datetime as dt, gzip, json, os, subprocess, sys, time
import pandas as pd
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
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=7)).date().isoformat()


def step(name):
    def deco(fn):
        def run(d, con, dry):
            t0 = time.time(); rec = {"run_date": d, "step": name, "status": "ok", "items": 0, "bytes": 0, "usd": 0.0}
            try:
                out = fn(d, con, dry) or {}
                rec.update({k: out[k] for k in ("items", "bytes", "usd") if k in out})
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
    return {"items": len(L)}


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
    rows, st = [], []
    with gzip.open(f"{RAW}/comments/page_daily_{d}.jsonl.gz", "wt") as f:
        for s, r in zip(slugs, recs):
            f.write(json.dumps({"url": r["url"], "status": r["status"], "route": r["route"], "html": r["body"]}) + "\n")
            try:
                info, cr = PC.parse(json.loads(r["body"]))
            except Exception:  # noqa: BLE001
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
    return {"items": len(C), "bytes": nbytes, "usd": sum(usd.values())}


def log_spend(d, what, usd, dry):
    rows = [{"step": f"daily_{what}", "provider": k, "usd": v, "note": d, "logged_on": d} for k, v in usd.items() if v]
    if rows and not dry:
        W.write("spend", pd.DataFrame(rows))


@step("people")
def s_people(d, con, dry):
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
    return {"items": len(ev) + len(fo), "bytes": nbytes, "usd": sum(usd.values())}


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
    T = con.execute(f"""SELECT f.predicted_rank, l.daily_rank FROM forecasts f JOIN launches l ON l.id = f.launch_id
                        WHERE f.forecast_date = '{y}' AND l.daily_rank IS NOT NULL""").df()
    if not len(T):
        return {"items": 0}
    rows = [{"day": y, "model": "launch_model", "k": k,
             "hit": int(((T.predicted_rank <= k) & (T.daily_rank <= k)).sum()), "recall": ((T.predicted_rank <= k) & (T.daily_rank <= k)).sum() / k}
            for k in (3, 5, 10)]
    if not dry:
        W.write("daily_scores", pd.DataFrame(rows))
    return {"items": len(rows)}


@step("raw")
def s_raw(d, con, dry):
    files = [f"{RAW}/today/{d}.json", f"{RAW}/comments/page_daily_{d}.jsonl.gz", f"{PH}/results/forecast_{d}.md"]
    files = [f for f in files if os.path.exists(f)]
    if not dry:
        for f in files:
            subprocess.run(["gsutil", "-q", "cp", f, f"{W.BUCKET}/raw/daily/{d}/"], check=False)
    return {"items": len(files)}


STEPS = [s_launches, s_forecast, s_ranks, s_comments, s_people, s_personas, s_score, s_raw]


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
