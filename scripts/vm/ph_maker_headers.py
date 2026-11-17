#!/usr/bin/env python3
"""Nightly maker/hunter header read on this VM's own IP (replaces the Data Feeder's DataImpulse route).

Runs on a fleet VM inside /opt/ph/reuse (Camoufox + the slot's sticky proxy from PROXY_URL/PROXY_PORT). Input and
output are the Data Feeder's raw/ph_at_launch/<day>/makers_header.jsonl: every row not yet read (status != 200) gets
one server-rendered /@<username> fetch on producthunt.com; the header counts are filled in, roles/posts/day are kept,
and every row carries fetched_at. On a block (403 / challenge) it backs off on the same IP: 10 min, doubling, cap 2 h;
no rotation, no challenge solving. The file is rewritten with a generation precondition so a concurrent Data Feeder
write is never overwritten.

  python3 ph_maker_headers.py --raw gs://.../usersim_sim/raw 2026-11-17
"""
import argparse, asyncio, json, os, subprocess, sys, tempfile, time

sys.path.insert(0, "/opt/ph/reuse")
import ph_person as P  # noqa: E402
from ssr import ssr_results  # noqa: E402
from camoufox.async_api import AsyncCamoufox  # noqa: E402

BACKOFF0, BACKOFF_CAP, PACE = 600, 7200, 3.0
FETCH_JS = """async (u)=>{const r=await fetch(u,{headers:{'accept':'text/html,application/xhtml+xml'},credentials:'include'});return [r.status,await r.text()]}"""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def gread(uri):
    st = subprocess.run(["gsutil", "-q", "stat", uri], capture_output=True, text=True).stdout
    gen = next((ln.split(":", 1)[1].strip() for ln in st.splitlines() if ln.strip().startswith("Generation:")), None)
    r = subprocess.run(["gsutil", "-q", "cat", uri], capture_output=True, text=True)
    return (r.stdout if r.returncode == 0 else None), gen


def gwrite(uri, text, gen):
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(text)
    cmd = ["gsutil", "-q"] + (["-h", f"x-goog-if-generation-match:{gen}"] if gen else []) + ["cp", f.name, uri]
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(f.name)
    return r.returncode == 0


def header(d, h):
    prof = d.get("profile") or []
    lay = next((x for x in prof if isinstance(x, dict) and "followersCount" in x), {})
    ab = next((x for x in prof if isinstance(x, dict) and "votesCount" in x), {})
    if not lay:
        return None
    return {"username": h, "ph_user_id": lay.get("id"), "name": lay.get("name"), "headline": lay.get("headline"),
            "followers": lay.get("followersCount"), "following": lay.get("followingsCount"), "products": lay.get("productsCount"),
            "hunted": lay.get("submittedPostsCount"), "upvotes": ab.get("votesCount"), "reviews": lay.get("reviewsCount"),
            "collections": lay.get("collectionsCount"), "stacks": lay.get("stacksCount")}


async def read_one(page, h):
    """-> (row or None, blocked: bool, status)"""
    st, c = await page.evaluate(FETCH_JS, f"/@{h}")
    if st in (403, 429) or "Just a moment" in c[:5000] or "security verification" in c[:20000]:
        return None, True, st
    data = {}
    for o in ssr_results(c):
        for ev in o.get("events") or []:
            if ev.get("type") == "next" and isinstance(ev.get("value"), dict):
                for k, v in (ev["value"].get("data") or {}).items():
                    data.setdefault(k, []).append(v)
    return header(data, h), False, st


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("day")
    a = ap.parse_args()
    uri = f"{a.raw}/ph_at_launch/{a.day}/makers_header.jsonl"
    text, _ = gread(uri)
    if text is None:
        print(json.dumps({"day": a.day, "error": "no makers_header.jsonl"})); return
    rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    todo = [r["username"] for r in rows if r.get("status") != 200 and r.get("username")]
    got = {}
    kw = dict(headless="virtual", i_know_what_im_doing=True, proxy=P.proxy_cfg(), geoip=True, block_images=True)
    backoff = BACKOFF0
    async with AsyncCamoufox(**kw) as br:
        page = await br.new_page()
        await page.goto(f"{P.PH}/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(10)
        for h in todo:
            while True:
                try:
                    row, blocked, st = await read_one(page, h)
                except Exception as e:
                    row, blocked, st = None, False, f"error {type(e).__name__}"
                if not blocked:
                    backoff = BACKOFF0
                    break
                print(json.dumps({"blocked": h, "status": st, "sleep_s": backoff}), flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_CAP)
                await page.goto(f"{P.PH}/", wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(10)
            got[h] = (dict(row, status=200) if row else {"username": h, "status": "no_profile_in_ssr" if st == 200 else st},
                      now())
            await asyncio.sleep(PACE)
    for _ in range(6):
        text, gen = gread(uri)
        cur = [json.loads(ln) for ln in (text or "").splitlines() if ln.strip()]
        out = []
        for r in cur:
            h = r.get("username")
            if h in got and r.get("status") != 200:
                new, ts = got[h]
                keep = {k: r[k] for k in ("roles", "posts", "day") if k in r}
                r = {**new, **keep, "fetched_at": ts, "fetched_at_source": "fleet_own_ip"}
            elif not r.get("fetched_at"):
                r["fetched_at"] = now()
            out.append(r)
        if gwrite(uri, "".join(json.dumps(r) + "\n" for r in out), gen):
            break
        time.sleep(3)
    ok = sum(1 for r in out if r.get("status") == 200)
    print(json.dumps({"day": a.day, "rows": len(out), "status_200": ok, "read_now": sum(1 for v in got.values() if v[0].get("status") == 200),
                      "attempted": len(todo)}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
