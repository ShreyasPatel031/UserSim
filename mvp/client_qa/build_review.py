"""Merge hand-driven runs (mvp.client_qa.drive) into the data files of a flow-map review page.

    python -m mvp.client_qa.build_review prepare --runs dirA dirB ... --out OUT [--detect]
        -> OUT/img/*.jpg (one per distinct screenshot, to upload as page assets), OUT/manifest.json
    python -m mvp.client_qa.build_review finalize --out OUT --assets assets.json
        -> OUT/flows.json, OUT/canvas.json, OUT/findings.json   (assets.json: {"img/x.jpg": "/_blob/<id>", ...})

Findings = the testers' `note`s (fail -> bug or visual, confusing -> ux; pass/blocked are not problems) plus, with --detect,
a blind detector pass over every run (mvp.client_qa.detect_eval, no known problems given). Each finding is placed on its
screen (x, y) by one small model call and ordered most-certain first by the page.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os

from PIL import Image

VISUAL_WORDS = ("visual", "icon", "font", "text size", "type scale", "colour", "color", "capsule", "align", "toast", "overlap",
                "truncat", "cut off", "spacing", "style", "design")


def load_run(d: str) -> dict:
    log = [json.loads(l) for l in open(os.path.join(d, "log.jsonl"))]
    shots = []
    for x in log:
        if x["kind"] == "look" and x["shot"] not in shots:
            shots.append(x["shot"])
    taps: dict[str, list] = {}
    for x in log:
        if x["kind"] == "act" and x.get("on"):
            a = x["action"]; t = {"kind": a["action"]}
            if "x" in a: t.update(x=a["x"], y=a["y"])
            if a.get("label"): t["label"] = a["label"]
            if a.get("direction"): t["dir"] = a["direction"]
            taps.setdefault(x["on"], []).append(t)
    mark = next((i for i, x in enumerate(log) if x["kind"] == "mark"), None)
    hidden = set()
    if mark is not None:   # screens before the test-start mark (login) are left out of the map
        hidden = {x["shot"] for x in log[:mark] if x["kind"] == "look"}
    notes = [x for x in log if x["kind"] == "note"]
    return {"dir": d, "name": os.path.basename(d.rstrip("/")), "shots": [s for s in shots if s not in hidden], "taps": taps, "notes": notes}


def prepare(a) -> None:
    os.makedirs(os.path.join(a.out, "img"), exist_ok=True)
    runs = [load_run(d) for d in a.runs]
    mp = os.path.join(a.out, "manifest.json")   # additive: runs can be prepared one at a time as they finish
    manifest = json.load(open(mp)) if os.path.exists(mp) else {"runs": [], "detected": []}
    names = {r["name"] for r in runs}
    manifest["runs"] = [r for r in manifest["runs"] if r["id"] not in names]
    manifest["detected"] = [f for f in manifest.get("detected", []) if f["flow"] not in names]
    new_runs = []
    for r in runs:
        steps = []
        for i, s in enumerate(r["shots"]):
            name = f"img/{r['name']}_{i:03d}.jpg"
            Image.open(os.path.join(r["dir"], s)).convert("RGB").resize((786, 1704)).save(os.path.join(a.out, name), quality=78)
            steps.append({"img": name, "src": os.path.join(r["dir"], s), "w": 393, "h": 852, "taps": r["taps"].get(s, [])})
        new_runs.append({"id": r["name"], "title": r["name"], "steps": steps, "notes": r["notes"]})
    manifest["runs"] += new_runs
    if a.detect:
        import mvp.client_qa.detect_eval as d
        cl = d.client()
        def det(run):
            sc = [{"img": s["img"], "path": s["src"], "title": run["title"] + " (build 4255)"} for s in run["steps"]]
            return d.detect_flow(cl, run["id"], sc, [])[0] if sc else []
        with cf.ThreadPoolExecutor(6) as ex:
            manifest["detected"] += [f for fl in ex.map(det, new_runs) for f in fl]
    json.dump(manifest, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print(len(manifest["runs"]), "runs,", sum(len(r["steps"]) for r in manifest["runs"]), "screens,",
          len(manifest.get("detected", [])), "detector flags")


def note_type(n: dict) -> str | None:
    st = n.get("status")
    if st == "confusing":
        return "ux"
    if st != "fail":
        return None
    txt = (n.get("what", "") + " " + str(n.get("item", ""))).lower()
    return "visual" if str(n.get("item", "")).upper().startswith("V") or any(w in txt for w in VISUAL_WORDS) else "bug"


def finalize(a) -> None:
    import hashlib
    import mvp.client_qa.detect_eval as d
    from mvp.client_qa.flowmap import build
    man = json.load(open(os.path.join(a.out, "manifest.json"))); assets = json.load(open(a.assets))
    flows = [{"id": r["id"], "title": r["title"], "build": "4255", "tapsBound": True,
              "steps": [{"img": s["img"], "url": assets[s["img"]], "w": 393, "h": 852, "taps": s["taps"]} for s in r["steps"]]}
             for r in man["runs"]]
    shots = {r["id"]: [s["src"] for s in r["steps"]] for r in man["runs"]}
    json.dump(flows, open(os.path.join(a.out, "flows.json"), "w"))
    g = build(flows, shots, set()); json.dump(g, open(os.path.join(a.out, "canvas.json"), "w"))
    cands = []
    auto = json.load(open(a.automark)) if getattr(a, "automark", None) else None
    noted = {n["what"] for r in man["runs"] for n in r["notes"] if n.get("marked_png")}
    for k, v in (auto or {}).items():   # mvp.client_qa.automark: verified pen-marked shot, or "needs screenshot"
        if k != "_usage" and v.get("finding", "").split(" Expected: ")[0] in noted:
            continue
        run = next((r for r in man["runs"] if r["id"] == v.get("shard")), None) if k != "_usage" else None
        if not run or not run["steps"]:
            continue
        st = next((s for s in run["steps"] if v.get("shot") and s["src"].endswith("/" + v["shot"])), run["steps"][-1])
        t = note_type({"status": "fail", "what": v["finding"], "item": v.get("item", "")})
        cands.append({"flow": run["id"], "img": st["img"], "path": st["src"], "type": t, "title": v["finding"].split(". ")[0][:110],
                      "detail": v["finding"], "confidence": 0.9, "source": "tester", "auto": v,
                      "auto_png": os.path.join(os.path.dirname(a.automark), "..", "..", v["png"]) if v.get("png") else None})
    for r in man["runs"]:
        src2img = {os.path.relpath(s["src"], os.path.join(os.path.dirname(s["src"]), "..")): s for s in r["steps"]}
        for n in r["notes"]:
            t = note_type(n)
            st = src2img.get(n.get("shot") or "")
            if not t or not st:
                continue
            c = {"flow": r["id"], "img": st["img"], "path": st["src"], "type": t, "title": n["what"].split(". ")[0][:110],
                 "detail": n["what"] + (" Expected: " + n["expected"] if n.get("expected") else ""), "confidence": 0.9, "source": "tester"}
            if n.get("marked_png") and os.path.exists(n["marked_png"]):
                # marked by the tester's own `note --on/--box` at the moment the bug was flagged: used as is, no second pass
                cands.append({**c, "auto": {"png": n["marked_png"]}, "auto_png": n["marked_png"]})
            elif auto is None:
                cands.append(c)
    for f in man.get("detected", []):
        st = next(s for r in man["runs"] if r["id"] == f["flow"] for s in r["steps"] if s["img"] == f["img"])
        cands.append({"flow": f["flow"], "img": f["img"], "path": st["src"], "type": f["severity"], "title": f["title"],
                      "detail": f["detail"], "confidence": round(f["confidence"], 2), "source": "detector"})
    cl = d.client()
    sch = {"type": "object", "properties": {"visible": {"type": "boolean"}, "element": {"type": "integer"}, "short_title": {"type": "string"}},
           "required": ["visible", "element", "short_title"]}
    def page_source(c):   # saved by mvp.client_qa.drive next to each screenshot; older runs have none
        q = c["path"][:-4] + ".elements.json"
        return json.load(open(q)) if os.path.exists(q) else None
    def loc(c):
        src = page_source(c)
        els = [e for e in (src or {}).get("elements", []) if e.get("label") and e.get("frame")]
        listing = "\n".join(f"{i}: {e['type']} \"{e['label']}\" frame {e['frame']}" for i, e in enumerate(els)) or "(no page source saved)"
        r, _ = d.call_json(cl, sch, "You check a reported UI problem against one iPhone screenshot and its page source. Be strict.", [d.img_block(c["path"]), {"type": "text", "text":
            "Problem: " + c["title"] + ". " + c["detail"][:400] + "\n\nPage source of THIS screenshot (index: type \"label\" frame [x,y,w,h] in points):\n" + listing +
            "\n\nvisible = the problem itself is plainly visible in THIS screenshot (not inferred from another screen or from the description). "
            "element = index of the page-source element the problem is about, or -1 if no listed element is it. "
            "short_title = the problem in at most 8 plain words, sentence case."}], effort="low", max_tokens=4000)
        return (r or {}), els, src
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(loc, cands))
    out, dropped = [], []
    for c, (r, els, src) in zip(cands, res):
        f = {k: c[k] for k in ("flow", "img", "type", "detail", "confidence", "source")}
        f["title"] = r.get("short_title") or c["title"]
        f["id"] = "p" + hashlib.sha1((f["flow"] + "|" + f["img"] + "|" + c["title"]).encode()).hexdigest()[:10]
        if c.get("auto"):
            if c["auto_png"]:
                f["auto_png"] = c["auto_png"]; f["x"], f["y"] = .5, .5
            else:
                f["needs_screenshot"] = True; f["x"], f["y"] = .9, .06
            out.append(f); continue
        if not r.get("visible"):   # its own screenshot does not show it: not a finding on this page
            dropped.append({"title": c["title"], "flow": c["flow"], "img": c["img"], "source": c["source"]}); continue
        i = r.get("element", -1)
        if isinstance(i, int) and 0 <= i < len(els):
            W, H = Image.open(c["path"]).size
            k = W / src["size"]["width"]   # points -> screenshot pixels (x3 on these iPhones)
            x, y, w, h = els[i]["frame"]
            f["element"] = els[i]["label"]
            f["box"] = [x * k / W, y * k / H, (x + w) * k / W, (y + h) * k / H]
            f["x"], f["y"] = (x + w / 2) * k / W, (y + h / 2) * k / H
            f["src"] = c["path"]
        else:   # no element located in this screenshot's page source: no mark
            f["needs_screenshot"] = True
            f["x"], f["y"] = .9, .06
        out.append(f)
    # pen-marked screenshot only around a page-source element (mvp.client_qa.annotate), like the team's Slack screenshots
    from mvp.client_qa.annotate import annotate
    mdir = os.path.join(a.out, "marked"); os.makedirs(mdir, exist_ok=True)
    for f in out:
        if f.get("auto_png"):
            Image.open(f.pop("auto_png")).convert("RGB").save(os.path.join(mdir, f["id"] + ".jpg"), quality=82)
            f["marked_img"] = "marked/" + f["id"] + ".jpg"; f["marked"] = assets.get(f["marked_img"])
            continue
        if "src" not in f:
            continue
        W, H = Image.open(f["src"]).size
        x1, y1, x2, y2 = f["box"]
        png = os.path.join(mdir, f["id"] + ".png")
        annotate(f["src"], png, [(int(x1 * W), int(y1 * H), int(x2 * W), int(y2 * H))], f["title"])
        Image.open(png).convert("RGB").save(png[:-4] + ".jpg", quality=82)
        f["marked_img"] = "marked/" + f["id"] + ".jpg"
        f["marked"] = assets.get(f["marked_img"])
        del f["src"]
    json.dump(dropped, open(os.path.join(a.out, "dropped.json"), "w"), indent=1)
    json.dump(out, open(os.path.join(a.out, "findings.json"), "w"), indent=1)
    # publish gate (mvp.client_qa.gate): crash/freeze held for a manual repro, no-screenshot held, weak/duplicate/slop dropped
    from mvp.client_qa.gate import gate
    bp = os.path.join(a.out, "brief.txt")
    rep = gate(a.out, lambda f: os.path.join(a.out, f["marked_img"]) if f.get("marked_img") and os.path.exists(os.path.join(a.out, f["marked_img"])) else None,
               open(bp).read() if os.path.exists(bp) else "")
    out = json.load(open(os.path.join(a.out, "findings.json")))
    print("gate:", rep["published"], "published,", len(rep["held"]), "held,", len(rep["dropped"]), "dropped (see gate.json)")
    json.dump(out, open(os.path.join(a.out, "findings.json"), "w"), indent=1)
    print(len(g["nodes"]), "screens,", len(out), "findings (", sum(f["source"] == "tester" for f in out), "from testers,",
          sum(bool(f.get("needs_screenshot")) for f in out), "need a screenshot ),", len(dropped), "dropped: not visible on their own screenshot")


def main() -> None:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--runs", nargs="+", required=True); p.add_argument("--out", required=True); p.add_argument("--detect", action="store_true")
    f = sub.add_parser("finalize"); f.add_argument("--out", required=True); f.add_argument("--assets", required=True)
    f.add_argument("--automark", help="runs/<build>/marked/auto/index.json: tester findings and their verified marks come from here")
    a = ap.parse_args()
    prepare(a) if a.cmd == "prepare" else finalize(a)


if __name__ == "__main__":
    main()
