#!/usr/bin/env python3
"""Resolve each launch's Product Hunt redirect link (producthunt.com/r/...) to the product URL, on this VM's own IP.

Runs on a fleet VM inside /opt/ph/reuse (Camoufox + the slot's sticky proxy from PROXY_URL/PROXY_PORT).
Firefox's redirect limit is 0, so the browser requests only producthunt.com/r/<code>, reads the 30x Location,
and never loads the product site. One request per launch; a Location that points back to producthunt.com is
followed (still producthunt.com only, max 3 hops). On a block (403 / challenge) it backs off on the same IP:
10 min, doubling, cap 2 h; no rotation, no challenge solving.

  python3 ph_sites_resolve.py --raw gs://.../usersim_sim/raw 2026-11-11 2026-11-12 ...

Writes raw/daily/<day>/sites_0005.json (one entry per launch id: final_url, status, resolved_at) and appends new
rows to raw/sites_ph.jsonl in its existing format (route "own_ip_redirect", text "", bytes 0). Re-running a day
keeps entries already resolved. No proxy details are written anywhere.
"""
import argparse, asyncio, json, os, subprocess, sys, tempfile, time, urllib.parse as up

sys.path.insert(0, "/opt/ph/reuse")
import ph_person as P  # noqa: E402
from camoufox.async_api import AsyncCamoufox  # noqa: E402

BACKOFF0, BACKOFF_CAP, PACE = 600, 7200, 3.0


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def gcat(uri):
    r = subprocess.run(["gsutil", "-q", "cat", uri], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def gput(uri, text):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(text)
    subprocess.run(["gsutil", "-q", "cp", f.name, uri], check=True)
    os.unlink(f.name)


def gappend(uri, lines):
    """Append with a generation precondition so a concurrent writer is never overwritten."""
    for _ in range(8):
        st = subprocess.run(["gsutil", "-q", "stat", uri], capture_output=True, text=True).stdout
        gen = next((ln.split(":", 1)[1].strip() for ln in st.splitlines() if ln.strip().startswith("Generation:")), "0")
        cur = gcat(uri) or ""
        if cur and not cur.endswith("\n"):
            cur += "\n"
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(cur + "".join(json.dumps(x) + "\n" for x in lines))
        r = subprocess.run(["gsutil", "-q", "-h", f"x-goog-if-generation-match:{gen}", "cp", f.name, uri], capture_output=True, text=True)
        os.unlink(f.name)
        if r.returncode == 0:
            return True
        time.sleep(3)
    return False


def ph_link(website):
    u = up.urlparse(website or "")
    if u.hostname not in ("www.producthunt.com", "producthunt.com") or not u.path.startswith("/r/"):
        return None
    return f"https://www.producthunt.com{u.path}"


async def resolve(ctx, link):
    """-> (status, final_url, note). Only producthunt.com is requested."""
    url, status = link, None
    for _ in range(3):
        hops = []
        p = await ctx.new_page()
        p.on("response", lambda r: hops.append((r.status, r.url, r.headers.get("location"))))
        err = None
        try:
            await p.goto(url, wait_until="commit", timeout=30000)
        except Exception as e:
            err = str(e)
        body = ""
        if not err:
            try: body = (await p.content())[:3000]
            except Exception: pass
        await p.close()
        first = next((h for h in hops if h[1].split("?")[0] == url.split("?")[0]), hops[0] if hops else None)
        if not first:
            return None, None, f"no_response {(err or '')[:80]}"
        status, _, loc = first
        if status in (403, 429, 503) or "Just a moment" in body:
            return status, None, "blocked"
        if 300 <= status < 400 and loc:
            nxt = up.urljoin(url, loc)
            if (up.urlparse(nxt).hostname or "").endswith("producthunt.com"):
                url = nxt
                continue
            return status, nxt, "location"
        return status, None, "no_redirect"
    return status, None, "ph_redirect_loop"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--lineup", default="today_0005.json")
    ap.add_argument("--out", default="sites_0005.json")
    ap.add_argument("days", nargs="+")
    a = ap.parse_args()
    kw = dict(headless="virtual", i_know_what_im_doing=True, proxy=P.proxy_cfg(), geoip=True, block_images=True,
              firefox_user_prefs={"network.http.redirection-limit": 0})
    backoff = BACKOFF0
    summary = {}
    async with AsyncCamoufox(**kw) as br:
        ctx = await br.new_context()
        home = await ctx.new_page()
        await home.goto(f"{P.PH}/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(10)
        for day in a.days:
            lineup = gcat(f"{a.raw}/daily/{day}/{a.lineup}")
            if lineup is None:
                summary[day] = {"error": "no lineup"}
                continue
            launches = json.loads(lineup)
            out_uri = f"{a.raw}/daily/{day}/{a.out}"
            prev = json.loads(gcat(out_uri) or "{}")
            entries = {str(k): v for k, v in (prev.get("launches") or {}).items()}
            new_rows = []
            for L in launches:
                lid = str(L.get("id"))
                if lid in entries and entries[lid].get("final_url"):
                    continue
                link = ph_link(L.get("website"))
                if not link:
                    entries[lid] = {"name": L.get("name"), "ph_link": None, "final_url": None, "status": None, "resolved_at": now(), "note": "no_ph_redirect_link"}
                    continue
                while True:
                    status, final, note = await resolve(ctx, link)
                    if note != "blocked":
                        backoff = BACKOFF0
                        break
                    print(json.dumps({"blocked": lid, "status": status, "sleep_s": backoff}), flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, BACKOFF_CAP)
                    await home.goto(f"{P.PH}/", wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(10)
                e = {"name": L.get("name"), "ph_link": link, "final_url": final, "status": status, "resolved_at": now(), "note": note}
                entries[lid] = e
                new_rows.append({"id": lid, "ph_link": link, "route": "own_ip_redirect", "status": status, "url": final,
                                 "text": "", "parked": False, "bytes": 0, "resolved_at": e["resolved_at"]})
                await asyncio.sleep(PACE)
            doc = {"day": day, "lineup": f"daily/{day}/{a.lineup}", "route": "own_ip_redirect", "written_at": now(),
                   "launches_in_lineup": len(launches), "resolved": sum(1 for v in entries.values() if v.get("final_url")),
                   "launches": entries}
            gput(out_uri, json.dumps(doc, indent=1))
            if new_rows and not gappend(f"{a.raw}/sites_ph.jsonl", new_rows):
                print(json.dumps({"day": day, "error": "sites_ph.jsonl append failed"}), flush=True)
            summary[day] = {"launches": len(launches), "resolved": doc["resolved"], "new": len(new_rows)}
            print(json.dumps({"day": day, **summary[day]}), flush=True)
    print(json.dumps({"summary": summary}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
