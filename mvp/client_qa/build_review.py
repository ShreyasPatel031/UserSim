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
    manifest = {"runs": []}
    for r in runs:
        steps = []
        for i, s in enumerate(r["shots"]):
            name = f"img/{r['name']}_{i:03d}.jpg"
            Image.open(os.path.join(r["dir"], s)).convert("RGB").resize((786, 1704)).save(os.path.join(a.out, name), quality=78)
            steps.append({"img": name, "src": os.path.join(r["dir"], s), "w": 393, "h": 852, "taps": r["taps"].get(s, [])})
        manifest["runs"].append({"id": r["name"], "title": r["name"], "steps": steps, "notes": r["notes"]})
    if a.detect:
        import mvp.client_qa.detect_eval as d
        cl = d.client()
        def det(run):
            sc = [{"img": s["img"], "path": s["src"], "title": run["title"] + " (build 4255)"} for s in run["steps"]]
            return d.detect_flow(cl, run["id"], sc, [])[0] if sc else []
        with cf.ThreadPoolExecutor(6) as ex:
            manifest["detected"] = [f for fl in ex.map(det, manifest["runs"]) for f in fl]
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
    for r in man["runs"]:
        src2img = {os.path.relpath(s["src"], os.path.join(os.path.dirname(s["src"]), "..")): s for s in r["steps"]}
        for n in r["notes"]:
            t = note_type(n)
            st = src2img.get(n.get("shot") or "")
            if not t or not st:
                continue
            cands.append({"flow": r["id"], "img": st["img"], "path": st["src"], "type": t, "title": n["what"].split(". ")[0][:110],
                          "detail": n["what"] + (" Expected: " + n["expected"] if n.get("expected") else ""), "confidence": 0.9, "source": "tester"})
    for f in man.get("detected", []):
        st = next(s for r in man["runs"] if r["id"] == f["flow"] for s in r["steps"] if s["img"] == f["img"])
        cands.append({"flow": f["flow"], "img": f["img"], "path": st["src"], "type": f["severity"], "title": f["title"],
                      "detail": f["detail"], "confidence": round(f["confidence"], 2), "source": "detector"})
    cl = d.client()
    sch = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "short_title": {"type": "string"}}, "required": ["x", "y", "short_title"]}
    def loc(c):
        r, _ = d.call_json(cl, sch, "You locate a reported UI problem on an iPhone screenshot.", [d.img_block(c["path"]), {"type": "text", "text":
            "Problem: " + c["title"] + ". " + c["detail"][:400] + "\nGive x,y = centre of the faulty element as fractions (0-1) of image width and height, "
            "and short_title = the problem in at most 8 plain words, sentence case."}], effort="low", max_tokens=4000)
        return r or {}
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(loc, cands))
    out = []
    for c, r in zip(cands, res):
        f = {k: c[k] for k in ("flow", "img", "type", "detail", "confidence", "source")}
        f["title"] = r.get("short_title") or c["title"]
        f["x"] = min(.95, max(.05, float(r.get("x", .5)))); f["y"] = min(.95, max(.05, float(r.get("y", .5))))
        f["id"] = "p" + hashlib.sha1((f["flow"] + "|" + f["img"] + "|" + f["title"]).encode()).hexdigest()[:10]
        out.append(f)
    json.dump(out, open(os.path.join(a.out, "findings.json"), "w"), indent=1)
    print(len(g["nodes"]), "screens,", len(out), "findings (", sum(f["source"] == "tester" for f in out), "from testers )")


def main() -> None:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--runs", nargs="+", required=True); p.add_argument("--out", required=True); p.add_argument("--detect", action="store_true")
    f = sub.add_parser("finalize"); f.add_argument("--out", required=True); f.add_argument("--assets", required=True)
    a = ap.parse_args()
    prepare(a) if a.cmd == "prepare" else finalize(a)


if __name__ == "__main__":
    main()
