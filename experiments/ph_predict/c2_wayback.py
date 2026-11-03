"""C2 source 1: each launch's domain in the Wayback Machine before launch (free public CDX API, from the research VM:
no login, no proxy; polite pacing, backs off on 429 / 5xx). Per launch in tmp/ph_ops/c2_targets.json:
  wayback_captures_90d    distinct days with a capture of the domain in the 90 days before the launch day
  wayback_captures_365d   the same over 365 days
  wayback_domain_age_d    days from the domain's first-ever capture to the day before launch (0 if first seen after)
Output rows (raw/ph_userbase/ schema): launch_id, source, as_of_date (= launch day - 1), count, url, capture_url
-> ~/c2/wayback.jsonl, uploaded to gs://.../raw/ph_userbase/wayback.jsonl every UPLOAD_EVERY launches and at the end.
Resumable (skips launches already in the output).
usage: python c2_wayback.py <c2_targets.json>"""
import datetime as dt, json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

CDX = "https://web.archive.org/cdx/search/cdx"
OUT = os.path.expanduser("~/c2/wayback.jsonl"); os.makedirs(os.path.dirname(OUT), exist_ok=True)
DEST = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_userbase/wayback.jsonl"
PACE = float(os.environ.get("PACE", "1.0")); UPLOAD_EVERY = int(os.environ.get("UPLOAD_EVERY", "200"))
UA = {"User-Agent": "UserSim research (contact via project owner); polite CDX use"}


def cdx(params, tries=6):
    url = CDX + "?" + urllib.parse.urlencode(params)
    for k in range(tries):
        time.sleep(PACE)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                txt = r.read().decode("utf-8", "replace")
                return [l.split(" ") for l in txt.splitlines() if l.strip()]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(300, 10 * 2 ** k)); continue
            return None
        except Exception:  # noqa: BLE001
            time.sleep(min(300, 10 * 2 ** k))
    return None


def one(lid, v):
    dom, day = v.get("domain"), v["day"]
    if not dom:
        return []
    d = dt.date.fromisoformat(day); asof = (d - dt.timedelta(days=1)).isoformat()
    lo = (d - dt.timedelta(days=365)).strftime("%Y%m%d"); hi = (d - dt.timedelta(days=1)).strftime("%Y%m%d")
    rows = cdx({"url": dom, "from": lo, "to": hi, "fl": "timestamp", "collapse": "timestamp:8", "limit": 400})
    first = cdx({"url": dom, "fl": "timestamp", "limit": 1})
    if rows is None and first is None:
        return [{"launch_id": lid, "source": "wayback_error", "as_of_date": asof, "count": None, "url": dom}]
    days = sorted({r[0][:8] for r in (rows or []) if r and r[0][:8] <= hi})
    lo90 = (d - dt.timedelta(days=90)).strftime("%Y%m%d")
    out = [{"launch_id": lid, "source": "wayback_captures_365d", "as_of_date": asof, "count": len(days), "url": dom},
           {"launch_id": lid, "source": "wayback_captures_90d", "as_of_date": asof, "count": sum(x >= lo90 for x in days), "url": dom}]
    if first and first[0]:
        f0 = dt.datetime.strptime(first[0][0][:8], "%Y%m%d").date()
        out.append({"launch_id": lid, "source": "wayback_domain_age_d", "as_of_date": asof, "count": max(0, (d - dt.timedelta(days=1) - f0).days),
                    "url": dom, "capture_url": f"https://web.archive.org/web/{first[0][0]}/{dom}"})
    return out


def main(targets):
    T = json.load(open(targets))
    done = {json.loads(l)["launch_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [(k, v) for k, v in T.items() if v.get("domain") and k not in done]
    print(f"{len(T)} launches, {len(done)} done, {len(todo)} to go", flush=True)
    t0 = time.time()
    with open(OUT, "a") as f:
        for n, (k, v) in enumerate(todo, 1):
            for r in one(k, v):
                f.write(json.dumps(r) + "\n")
            f.flush()
            if n % 50 == 0:
                rate = n / (time.time() - t0) * 3600
                print(f"{n}/{len(todo)}, {rate:.0f}/h, ETA {(len(todo) - n) / max(rate, 1):.1f} h", flush=True)
            if n % UPLOAD_EVERY == 0:
                subprocess.run(["gsutil", "-q", "cp", OUT, DEST], check=False)
    subprocess.run(["gsutil", "-q", "cp", OUT, DEST], check=False)
    print("done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
