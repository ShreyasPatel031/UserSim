"""Build the client report from hand-driven runs (mvp.client_qa.drive).

    python -m mvp.client_qa.report --checklist checklist.json --runs dir_A dir_B --out report_dir \
        [--build 4244 --arrived-utc 2026-11-25T00:16:00Z]

checklist.json: [{"id": "A1", "text": "Share a daily reading (... -> Share) by DM"}, ...]
Each run dir holds session.json, log.jsonl and shots/. Status per item is the last note for that item across runs
(fail beats pass if both appear); items never noted are "not reached". Output: report.md and report.html (screenshots
embedded) in --out. Reports hold client screenshots: keep them under mvp/client_qa/private/ (gitignored).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import io
import json
import os

RANK = {"fail": 4, "confusing": 3, "blocked": 2, "pass": 1}


def load(run: str) -> tuple[dict, list[dict]]:
    meta = json.load(open(f"{run}/session.json")) if os.path.exists(f"{run}/session.json") else {}
    log = [json.loads(l) for l in open(f"{run}/log.jsonl")] if os.path.exists(f"{run}/log.jsonl") else []
    return meta, log


def thumb(path: str, width: int = 280) -> str:
    try:
        from PIL import Image
        im = Image.open(path); im = im.resize((width, int(im.height * width / im.width)))
        b = io.BytesIO(); im.convert("RGB").save(b, "JPEG", quality=72)
        return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return ""


def fast_video(run: str) -> str | None:
    """Fetch the full LambdaTest recording fresh (links expire) and cut it with mvp.device.fast_video into
    <run>/fast.mp4. Secure password fields render as dots; still check the login frames before sending."""
    import subprocess
    import requests
    meta = json.load(open(f"{run}/session.json"))
    sid = meta.get("session_id")
    if not sid:
        return None
    r = requests.get(f"https://mobile-api.lambdatest.com/mobile-automation/api/v1/sessions/{sid}",
                     auth=(os.environ.get("LT_USERNAME", "proxy-injected"), os.environ.get("LT_ACCESS_KEY", "proxy-injected")),
                     timeout=60)
    url = ((r.json() if r.ok else {}).get("data") or {}).get("video_url")
    if not url:
        return None
    full = f"{run}/full.mp4"
    with requests.get(url, stream=True, timeout=600) as v:
        v.raise_for_status()
        with open(full, "wb") as f:
            for chunk in v.iter_content(1 << 20):
                f.write(chunk)
    # Client rule: the video starts at the first screen of the test, never setup, install or login. A run without a
    # mark gets no client video (start would be 0 and show the login).
    if meta.get("test_start_video_s") is None:
        print(f"{run}: no test-start mark; not cutting a client video")
        return None
    start = max(0.0, meta["test_start_video_s"] - 1.0)
    # drive.py logs a tap just before sending it; on LambdaTest the touch lands ~1 s later (screen changes 1.2 s after
    # the logged time, measured Nov 25), hence --offset 0.9.
    # trim to the test part, draw every touch (iOS recordings show none), then cut freezes and speed up
    trimmed, touched = f"{run}/test.mp4", f"{run}/touched.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", full, "-c:v", "libx264", "-preset", "veryfast",
                    "-an", trimmed], check=True)
    shifted = f"{run}/actions_test.jsonl"
    with open(shifted, "w") as out:
        for line in open(f"{run}/actions.jsonl"):
            row = json.loads(line)
            if row["t"] >= start:
                out.write(json.dumps({**row, "t": round(row["t"] - start, 1)}) + "\n")
    subprocess.run(["python3", "-m", "mvp.device.touch_overlay", trimmed, shifted, touched, "--offset", "0.9"], check=True)
    subprocess.run(["python3", "-m", "mvp.device.fast_video", touched, f"{run}/fast.mp4"], check=True)
    meta["video_url"] = url
    meta["fast_video"] = "fast.mp4"
    json.dump(meta, open(f"{run}/session.json", "w"), indent=1)
    return f"{run}/fast.mp4"


def build(a) -> None:
    if a.videos:
        for r in a.runs:
            print("video", r, fast_video(r))
    items = json.load(open(a.checklist))
    os.makedirs(a.out, exist_ok=True)
    runs, notes = [], []
    for r in a.runs:
        meta, log = load(r)
        acts = sum(1 for x in log if x["kind"] == "act")
        runs.append({"dir": r, "var": os.path.basename(r.rstrip("/")), "meta": meta, "acts": acts})
        for x in log:
            if x["kind"] == "note":
                notes.append({**x, "var": runs[-1]["var"], "shot_path": os.path.join(r, x.get("shot") or "")})
    status = {}
    for n in notes:
        cur = status.get(n["item"])
        if cur is None or RANK.get(n["status"], 0) >= RANK.get(cur["status"], 0):
            status[n["item"]] = n
    now = dt.datetime.now(dt.timezone.utc)
    ttr = ""
    if a.arrived_utc:
        arr = dt.datetime.fromisoformat(a.arrived_utc.replace("Z", "+00:00"))
        ttr = f"{(now - arr).total_seconds() / 60:.0f} min from build arrival to report"
    counts = {k: sum(1 for i in items if (status.get(i["id"]) or {}).get("status", "not reached") == k)
              for k in ("pass", "fail", "confusing", "blocked", "not reached")}

    md = [f"# Build {a.build} — test report", "", f"Generated {now:%Y-%m-%d %H:%M} UTC. {ttr}", "",
          "**Summary:** " + ", ".join(f"{v} {k}" for k, v in counts.items() if v), "", "## Runs and videos", ""]
    for r in runs:
        m = r["meta"]
        md.append(f"- **{r['var']}** — {m.get('device')} iOS {m.get('os')}, {m.get('seconds', '?')} s, {r['acts']} actions — "
                  f"sped-up video: {os.path.join(r['dir'], m['fast_video']) if m.get('fast_video') else 'pending'} "
                  f"(full recording: LambdaTest session {m.get('session_id')})")
    md += ["", "## Checklist", "", "| Item | Status | What happened | Expected |", "|---|---|---|---|"]
    for i in items:
        n = status.get(i["id"]) or {}
        md.append(f"| {i['id']} {i['text']} | {n.get('status', 'not reached')} | {n.get('what', '')} | {n.get('expected', '')} |")
    md += ["", "## Findings", ""]
    for n in notes:
        if n["status"] in ("fail", "confusing"):
            md.append(f"- **{n['item']} ({n['status']}, run {n['var']}, {n['t']} s)** {n['what']} — expected: "
                      f"{n.get('expected', '')} — screenshot `{n.get('shot')}`")
    open(f"{a.out}/report.md", "w").write("\n".join(md) + "\n")

    e = html.escape
    rows = "".join(
        f"<tr class='{e((status.get(i['id']) or {}).get('status', 'nr').replace(' ', ''))}'><td>{e(i['id'])}</td><td>{e(i['text'])}</td>"
        f"<td>{e((status.get(i['id']) or {}).get('status', 'not reached'))}</td><td>{e((status.get(i['id']) or {}).get('what', ''))}</td>"
        f"<td>{e((status.get(i['id']) or {}).get('expected', ''))}</td></tr>" for i in items)
    finds = "".join(
        f"<div class='f'><img src='{thumb(n['shot_path'])}'><div><b>{e(n['item'])} — {e(n['status'])}</b> (run {e(n['var'])})"
        f"<p>{e(n['what'])}</p><p><i>Expected:</i> {e(n.get('expected', ''))}</p></div></div>"
        for n in notes if n["status"] in ("fail", "confusing"))
    vids = "".join(f"<li><b>{e(r['var'])}</b>: <a href='{e(r['meta'].get('fast_video') and r['var'] + '/' + r['meta']['fast_video'] or '#')}'>sped-up video</a> "
                   f"({e(str(r['meta'].get('seconds', '?')))} s, {r['acts']} actions)</li>" for r in runs)
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Build {e(a.build)} test report</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd;--pass:#e6f4ea;--fail:#fde8e8;--warn:#fff4e0;--blk:#eef0f3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--mut:#9aa;--line:#333;--pass:#1d3326;--fail:#3d1e1e;--warn:#3a3020;--blk:#262a30}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:1000px;margin:0 auto;padding:16px}}
table{{border-collapse:collapse;width:100%}}td{{border-bottom:1px solid var(--line);padding:6px;vertical-align:top}}
tr.pass{{background:var(--pass)}}tr.fail{{background:var(--fail)}}tr.confusing{{background:var(--warn)}}tr.blocked,tr.notreached,tr.nr{{background:var(--blk)}}
.f{{display:flex;gap:16px;border-bottom:1px solid var(--line);padding:12px 0}}.f img{{width:180px;border-radius:8px}}
.mut{{color:var(--mut)}}@media(max-width:600px){{.f{{flex-direction:column}}td{{font-size:13px}}}}</style>
<h1>Build {e(a.build)} — test report</h1><p class=mut>Generated {now:%Y-%m-%d %H:%M} UTC. {e(ttr)}</p>
<p><b>Summary:</b> {e(', '.join(f'{v} {k}' for k, v in counts.items() if v))}</p>
<h2>Runs and videos</h2><ul>{vids}</ul><h2>Checklist</h2><table>{rows}</table><h2>Findings</h2>{finds or '<p>None.</p>'}"""
    open(f"{a.out}/report.html", "w").write(page)
    print(f"{a.out}/report.md", counts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checklist", required=True); ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--build", default="?"); ap.add_argument("--arrived-utc")
    ap.add_argument("--videos", action="store_true", help="fetch each run's recording and cut it to fast.mp4")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
