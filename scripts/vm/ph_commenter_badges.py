#!/usr/bin/env python3
"""Launch-day commenter account flags on this VM's own IP (orchestrator 10:58Z Nov 17).

For each person who commented on the day's launches (raw/ph_at_launch/<day>/live/comments_ts.jsonl) and has no row yet in
raw/ph_at_launch/<day>/commenter_badges.jsonl, one server-rendered /@<username> fetch on producthunt.com records:
  verified   - the profile's verified badge
  prominent  - the profile's prominent badge
with fetched_at, the commenter's first comment created_at that day, and lag_s = fetched_at - created_at. The live API does
not return these flags. On a block (403 / challenge) it backs off on the same IP: 10 min, doubling, cap 2 h; no rotation,
no challenge solving. Rows are appended with a generation precondition.

  python3 ph_commenter_badges.py --raw gs://.../usersim_sim/raw 2026-11-17
  python3 ph_commenter_badges.py --raw gs://.../usersim_sim/raw --probe 3 2026-11-17   # print flag-like profile fields
"""
import argparse, asyncio, calendar, json, re, sys, time

sys.path.insert(0, "/opt/ph/reuse")
import ph_person as P  # noqa: E402
from ssr import ssr_results  # noqa: E402
from camoufox.async_api import AsyncCamoufox  # noqa: E402
from ph_maker_headers import FETCH_JS, gread, gwrite, now  # noqa: E402

BACKOFF0, BACKOFF_CAP, PACE = 600, 7200, 3.0
MAX_PER_RUN = 400
FLAG_RE = re.compile(r"verif|badge|prominent", re.I)
VERIFIED_KEYS = ("isVerified", "verified", "isVerifiedUser")
PROMINENT_KEYS = ("isProminent", "prominent", "isProminentUser")


def ts(s):
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def user_objs(c, h):
    out = []
    for o in ssr_results(c):
        for d in walk(o):
            if str(d.get("username") or "").lower() == h.lower():
                out.append(d)
    return out


def flag(objs, keys):
    for d in objs:
        for k in keys:
            if k in d and d[k] is not None:
                return bool(d[k]), k
    return None, None


def badge_names(objs):
    names = set()
    for d in objs:
        for k, v in d.items():
            if FLAG_RE.search(k) and isinstance(v, (list, dict)):
                for e in walk(v):
                    for kk in ("name", "type", "kind", "slug", "__typename"):
                        if isinstance(e.get(kk), str):
                            names.add(e[kk])
    return sorted(names)


async def read_one(page, h):
    st, c = await page.evaluate(FETCH_JS, f"/@{h}")
    if st in (403, 429) or "Just a moment" in c[:5000] or "security verification" in c[:20000]:
        return None, True, st, c
    return user_objs(c, h), False, st, c


def commenters(text, day):
    first = {}
    for ln in (text or "").splitlines():
        try:
            r = json.loads(ln)
        except Exception:
            continue
        h, ca = r.get("username"), r.get("created_at") or ""
        if not h or r.get("day", day) != day:
            continue
        cur = first.get(h)
        if cur is None or (ca and ca < cur["comment_created_at"]):
            first[h] = {"username": h, "user_id": r.get("commenter_user_id") or r.get("user_id"),
                        "comment_created_at": ca, "comment_id": r.get("comment_id"), "slug": r.get("slug")}
    return sorted(first.values(), key=lambda x: x["comment_created_at"], reverse=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--probe", type=int, default=0)
    ap.add_argument("day")
    a = ap.parse_args()
    base = f"{a.raw}/ph_at_launch/{a.day}"
    out_uri = f"{base}/commenter_badges.jsonl"
    ctext, _ = gread(f"{base}/live/comments_ts.jsonl")
    done_text, _ = gread(out_uri)
    done = {json.loads(ln).get("username") for ln in (done_text or "").splitlines() if ln.strip()}
    todo = [c for c in commenters(ctext, a.day) if c["username"] not in done]
    todo = todo[: a.probe or MAX_PER_RUN]
    if not todo:
        print(json.dumps({"day": a.day, "todo": 0, "done_before": len(done)})); return
    kw = dict(headless="virtual", i_know_what_im_doing=True, proxy=P.proxy_cfg(), geoip=True, block_images=True)
    rows, backoff = [], BACKOFF0
    async with AsyncCamoufox(**kw) as br:
        page = await br.new_page()
        await page.goto(f"{P.PH}/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(10)
        for c in todo:
            h = c["username"]
            while True:
                try:
                    objs, blocked, st, html = await read_one(page, h)
                except Exception as e:
                    objs, blocked, st, html = None, False, f"error {type(e).__name__}", ""
                if not blocked:
                    backoff = BACKOFF0
                    break
                print(json.dumps({"blocked": h, "status": st, "sleep_s": backoff}), flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_CAP)
                await page.goto(f"{P.PH}/", wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(10)
            if a.probe:
                fl = {k: v for d in objs or [] for k, v in d.items() if FLAG_RE.search(k)}
                print(json.dumps({"probe": h, "status": st, "n_user_objs": len(objs or []),
                                  "keys": sorted({k for d in objs or [] for k in d}), "flag_fields": fl,
                                  "html_flag_words": sorted(set(re.findall(r'"([A-Za-z]*(?:[Vv]erif|[Bb]adge|[Pp]rominent)[A-Za-z]*)"', html)))[:40]},
                                 default=str), flush=True)
                await asyncio.sleep(PACE)
                continue
            f_at = now()
            v, vk = flag(objs or [], VERIFIED_KEYS)
            p, pk = flag(objs or [], PROMINENT_KEYS)
            t0, t1 = ts(c["comment_created_at"]), ts(f_at)
            rows.append({**c, "status": 200 if objs else (st if st != 200 else "no_profile_in_ssr"),
                         "verified": v, "prominent": p, "verified_field": vk, "prominent_field": pk,
                         "badges": badge_names(objs or []), "fetched_at": f_at,
                         "lag_s": (t1 - t0) if t0 and t1 else None, "fetched_at_source": "fleet_own_ip", "day": a.day})
            await asyncio.sleep(PACE)
    if a.probe or not rows:
        return
    for _ in range(6):
        text, gen = gread(out_uri)
        have = {json.loads(ln).get("username") for ln in (text or "").splitlines() if ln.strip()}
        new = [r for r in rows if r["username"] not in have]
        if gwrite(out_uri, (text or "") + "".join(json.dumps(r) + "\n" for r in new), gen):
            break
        time.sleep(3)
    print(json.dumps({"day": a.day, "commenters_read_now": len(rows), "status_200": sum(r["status"] == 200 for r in rows),
                      "verified_true": sum(r["verified"] is True for r in rows), "prominent_true": sum(r["prominent"] is True for r in rows),
                      "median_lag_s": sorted(r["lag_s"] for r in rows if r["lag_s"] is not None)[len(rows) // 2] if rows else None}),
          flush=True)


if __name__ == "__main__":
    asyncio.run(main())
