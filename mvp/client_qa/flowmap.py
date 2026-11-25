"""Build the review page's flow graph (canvas.json): every distinct app screen is one node, every move a test run made
between two screens is an edge (cycles allowed), laid out in layers from the app's entry screens.

    python -m mvp.client_qa.flowmap flows.json shots.json canvas.json [--skip team]

flows.json: the review page's runs ([{id, title, steps:[{img, url, taps?}], tapsBound?}]).
shots.json: {"<flow id>": ["local/path/of/step0.png", ...]}; local screenshots, used only to tell screens apart.
Screens are matched by a perceptual hash with the status bar ignored. Edge labels come from the taps bound to each screen
(runs driven with mvp.client_qa.drive); `paths` keeps each run's node sequence so the page can step through a run.
"""
from __future__ import annotations

import argparse
import json

from PIL import Image

SAME = 50   # max hash distance for two screenshots to count as the same screen


def dhash(p: str) -> list[bool]:
    im = Image.open(p).convert("L"); w, h = im.size
    im = im.crop((0, int(h * 0.07), w, h)).resize((17, 32))
    px = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
    return [px[r * 17 + c] > px[r * 17 + c + 1] for r in range(32) for c in range(16)]


def dist(a, b) -> int:
    return sum(x != y for x, y in zip(a, b))


def tap_label(step: dict) -> str:
    out = []
    for t in step.get("taps", []):
        k = t.get("kind", "")
        if k.startswith("tap") and t.get("label"):
            out.append(f"Tap “{t['label']}”")
        elif k.startswith("tap"):
            out.append("Tap")
        elif k in ("type", "type_into"):
            out.append("Type")
        elif k in ("swipe", "scroll"):
            out.append("Scroll " + t.get("dir", ""))
        elif k == "back":
            out.append("Back")
        elif k == "multi_tap":
            out.append("Tap-tap-hold")
    # keep it short: the last meaningful action is what moved the screen
    return out[-1] if out else ""


def build(flows: list[dict], shots: dict, skip: set[str]) -> dict:
    clusters: list[dict] = []   # {id, rep, members:[{flow, step}]}
    paths: dict[str, list[dict]] = {}
    for f in flows:
        if f["id"] in skip or f["id"] not in shots:
            continue
        seq = []
        for i, _ in enumerate(f["steps"]):
            h = dhash(shots[f["id"]][i])
            best = min(((dist(c["rep"], h), c) for c in clusters), default=(999, None), key=lambda x: x[0])
            c = best[1] if best[0] <= SAME else None
            if c is None:
                c = {"id": f"n{len(clusters)}", "rep": h, "members": []}; clusters.append(c)
            c["members"].append({"flow": f["id"], "step": i})
            if seq and seq[-1]["node"] == c["id"]:
                seq[-1]["steps"].append(i)
            else:
                seq.append({"node": c["id"], "steps": [i]})
        paths[f["id"]] = seq
    edges: dict[tuple, dict] = {}
    fl = {f["id"]: f for f in flows}
    for fid, seq in paths.items():
        for a, b in zip(seq, seq[1:]):
            e = edges.setdefault((a["node"], b["node"]), {"from": a["node"], "to": b["node"], "labels": [], "flows": []})
            lab = tap_label(fl[fid]["steps"][a["steps"][-1]]) if fl[fid].get("tapsBound") else ""
            if lab and lab not in e["labels"]:
                e["labels"].append(lab)
            if fid not in e["flows"]:
                e["flows"].append(fid)
    # layers: shortest hop count from any run's first screen
    out = {c["id"]: [] for c in clusters}
    for e in edges.values():
        out[e["from"]].append(e["to"])
    depth = {}
    frontier = [seq[0]["node"] for seq in paths.values() if seq]
    for n in frontier:
        depth.setdefault(n, 0)
    q = list(dict.fromkeys(frontier))
    while q:
        n = q.pop(0)
        for m in out[n]:
            if m not in depth:
                depth[m] = depth[n] + 1; q.append(m)
    layers: dict[int, list[str]] = {}
    for c in clusters:
        layers.setdefault(depth.get(c["id"], 0), []).append(c["id"])
    # order within layers by the mean position of predecessors (two sweeps)
    pos = {}
    for d in sorted(layers):
        for i, n in enumerate(layers[d]):
            pos[n] = i
    preds: dict[str, list[str]] = {c["id"]: [] for c in clusters}
    for e in edges.values():
        preds[e["to"]].append(e["from"])
    for _ in range(3):
        for d in sorted(layers)[1:]:
            layers[d].sort(key=lambda n: (sum(pos[p] for p in preds[n] if depth.get(p, 0) < d) /
                                          max(1, sum(1 for p in preds[n] if depth.get(p, 0) < d))) if preds[n] else pos[n])
            for i, n in enumerate(layers[d]):
                pos[n] = i
    W, H, GX, GY = 240, 520, 300, 140
    tallest = max(len(v) for v in layers.values())
    nodes = []
    for c in clusters:
        d = depth.get(c["id"], 0); col = layers[d]
        y0 = (tallest - len(col)) * (H + GY) / 2
        nodes.append({"id": c["id"], "x": d * (W + GX), "y": y0 + col.index(c["id"]) * (H + GY), "depth": d,
                      "members": c["members"]})
    return {"node_w": W, "node_h": H, "nodes": nodes, "edges": list(edges.values()), "paths": paths}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("flows"); ap.add_argument("shots"); ap.add_argument("out"); ap.add_argument("--skip", nargs="*", default=[])
    a = ap.parse_args()
    g = build(json.load(open(a.flows)), json.load(open(a.shots)), set(a.skip))
    json.dump(g, open(a.out, "w"))
    term = [n["id"] for n in g["nodes"] if not any(e["from"] == n["id"] for e in g["edges"])]
    print(len(g["nodes"]), "screens,", len(g["edges"]), "transitions,", len(term), "dead ends,",
          max(n["depth"] for n in g["nodes"]) + 1, "layers")


if __name__ == "__main__":
    main()
