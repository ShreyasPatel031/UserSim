"""Rotating-holdout evaluation of the screen-review problem detector.

Known problems (the review page's `problems` collection: the client team's own findings plus earlier AI findings) are
split into folds, stratified by source (team vs ai) and severity. For each fold the detector reviews every screen of
every run with only the TRAINING problems as guidance, and is scored on the HELD-OUT problems:

    recall     = held-out problems matched by at least one flag / held-out problems
    precision  = flags matched to a held-out problem / (all flags - flags that only re-find a training problem)
    unmatched  = flags that match no known problem (false positives, or real issues nobody had logged; audited by hand)

    python -m mvp.client_qa.detect_eval --problems problems.json --screens screens.json --out results_dir \
        [--folds 2 --repeats 3 --model claude-opus-5-5]

problems.json: {id: {flow, img, title, detail, severity, source}}.  screens.json: {flow: [{img, path, title}]}.
The detector and the judge are Claude on Vertex AI (GOOGLE_CLOUD_PROJECT, region global).
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import io
import json
import os
import random
import time

from PIL import Image

MODEL = "claude-opus-5-5"


def client():
    from anthropic import AnthropicVertex
    return AnthropicVertex(project_id=os.environ["GOOGLE_CLOUD_PROJECT"], region="global")


def img_block(path: str, width: int = 520) -> dict:
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, int(im.height * width / im.width)))
    b = io.BytesIO(); im.save(b, "JPEG", quality=80)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}}


def call_json(cl, schema: dict, system: str, content: list, effort: str = "medium", max_tokens: int = 16000):
    for attempt in range(5):
        try:
            # Structured outputs are blocked by this project's Vertex org policy, so the schema goes in the prompt
            sys2 = system + "\n\nAnswer with one JSON object only, no prose, matching this JSON schema:\n" + json.dumps(schema)
            with cl.messages.stream(model=MODEL, max_tokens=max_tokens, system=sys2,
                                    output_config={"effort": effort},
                                    messages=[{"role": "user", "content": content}]) as s:
                m = s.get_final_message()
            if m.stop_reason == "refusal":
                return None, m.usage
            text = "".join(b.text for b in m.content if b.type == "text")
            text = text[text.find("{"): text.rfind("}") + 1]
            return json.loads(text), m.usage
        except Exception as e:  # noqa: BLE001  (rate limits / transient)
            if attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))


DETECT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["findings"], "properties": {"findings": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["screen", "title", "detail", "severity", "confidence"],
                               "properties": {"screen": {"type": "string"}, "title": {"type": "string"},
                                              "detail": {"type": "string"},
                                              "severity": {"type": "string", "enum": ["bug", "visual", "ux"]},
                                              "confidence": {"type": "number"}}}}}}

DETECT_SYSTEM = """You are a senior mobile QA reviewer for the Reframe iOS app (alcohol reduction). You review real iPhone
screenshots from one test run, in the order they were taken, and report product problems the app team would accept and fix.

Report only problems you can see in these screenshots: broken or wrong behaviour, numbers or labels that contradict each
other across screens, visual inconsistency with the app's own design system (components, colours, type sizes, icons,
toasts), layout faults (overlap, truncation, content under the status bar, blank images), confusing or redundant UX,
and copy errors. Be precise and specific; name the element. Do NOT report: test-harness artefacts (the red recording dot,
LambdaTest UI, an on-screen keyboard, the iOS tracking/notification permission prompts themselves), personal taste,
generic suggestions, or anything you cannot point to on a screen. False positives waste the team's time: when unsure,
leave it out. Report each distinct problem once, on the screen where it is clearest. confidence = your probability that
the team would accept it as a real problem."""


def guidance(train: list[dict]) -> str:
    if not train:
        return ""
    lines = [f"- [{p['severity']}] {p['title']}" + (f": {p['detail'][:220]}" if p.get('detail') else "") for p in train]
    return ("Problems this team has already accepted as real in earlier reviews (learn the KIND of issue they care about "
            "and the level of detail; do not just re-report these):\n" + "\n".join(lines) + "\n\n")


def detect_flow(cl, flow: str, screens: list[dict], train: list[dict], chunk: int = 12):
    out, usage = [], [0, 0]
    for k in range(0, len(screens), chunk):
        part = screens[k:k + chunk]
        content = [{"type": "text", "text": guidance(train) + f"Run: {part[0]['title']}. Screens {k + 1}-{k + len(part)} of {len(screens)}, in order. Each image is preceded by its label."}]
        for i, s in enumerate(part):
            content += [{"type": "text", "text": f"S{k + i + 1}"}, img_block(s["path"])]
        content.append({"type": "text", "text": "List the problems (JSON). Use the screen labels exactly as given."
                        + (" x and y are the centre of the faulty element as fractions of the screen width and height."
                           if "x" in DETECT_SCHEMA["properties"]["findings"]["items"]["properties"] else "")})
        res, u = call_json(cl, DETECT_SCHEMA, DETECT_SYSTEM, content)  # schema swapped for the final pass
        usage[0] += u.input_tokens; usage[1] += u.output_tokens
        for f in (res or {}).get("findings", []):
            try:
                idx = int(str(f["screen"]).lstrip("Ss")) - 1
            except ValueError:
                continue
            if 0 <= idx < len(screens):
                out.append({**f, "flow": flow, "img": screens[idx]["img"], "screen_no": idx + 1})
    return out, usage


JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["matches"], "properties": {"matches": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["flag", "problem"],
                               "properties": {"flag": {"type": "string"}, "problem": {"type": "string"}}}}}}

JUDGE_SYSTEM = """You match QA flags to known problems for the same app run. A flag matches a known problem only if it
describes the same underlying defect (same element or same inconsistency), even if worded differently or reported on a
neighbouring screen of the same run. A flag that is merely in the same general area, or a different defect on the same
screen, does NOT match. A flag may match at most one problem; a problem may be matched by several flags. Return only
real matches."""


def judge_flow(cl, flags: list[dict], problems: list[dict]):
    if not flags or not problems:
        return [], [0, 0]
    txt = "Known problems:\n" + "\n".join(f"{p['id']}: [{p['severity']}] {p['title']} — {p.get('detail', '')[:300]} (screen {p.get('screen_no', '?')})" for p in problems)
    txt += "\n\nFlags:\n" + "\n".join(f"F{i}: [{f['severity']}] {f['title']} — {f['detail'][:300]} (screen {f['screen_no']})" for i, f in enumerate(flags))
    res, u = call_json(cl, JUDGE_SCHEMA, JUDGE_SYSTEM, [{"type": "text", "text": txt}], effort="medium")
    ids = {p["id"] for p in problems}
    m = [(int(x["flag"].lstrip("Ff")), x["problem"]) for x in (res or {}).get("matches", [])
         if x["problem"] in ids and x["flag"].lstrip("Ff").isdigit() and int(x["flag"].lstrip("Ff")) < len(flags)]
    return m, [u.input_tokens, u.output_tokens]


def folds(problems: dict, k: int, seed: int) -> list[set]:
    rng = random.Random(seed)
    strata: dict[tuple, list[str]] = {}
    for pid, p in problems.items():
        strata.setdefault(("team" if p["source"] == "team" else "ai", p["severity"]), []).append(pid)
    out = [set() for _ in range(k)]
    offset = rng.randrange(k)
    for key in sorted(strata):
        ids = sorted(strata[key]); rng.shuffle(ids)
        for i, pid in enumerate(ids):
            out[(i + offset) % k].add(pid)
        offset += len(ids)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", required=True); ap.add_argument("--screens", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--folds", type=int, default=2); ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--baseline", action="store_true", help="also run once with no training guidance")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    problems = json.load(open(a.problems)); screens = json.load(open(a.screens))
    for pid, p in problems.items():
        p["id"] = pid
        sc = screens.get(p["flow"], [])
        p["screen_no"] = next((i + 1 for i, s in enumerate(sc) if s["img"] == p["img"]), None)
    problems = {k: v for k, v in problems.items() if v["flow"] in screens}
    cl = client()
    runs = []
    if a.baseline:
        runs.append(("baseline", set(), set(problems)))
    for r in range(a.repeats):
        fs = folds(problems, a.folds, seed=1000 + r)
        for i, held in enumerate(fs):
            runs.append((f"r{r}f{i}", set(problems) - held, held))
    cost = [0, 0]
    results = []
    for name, train_ids, held_ids in runs:
        path = f"{a.out}/{name}.json"
        if os.path.exists(path):
            results.append(json.load(open(path))); continue
        train = [problems[i] for i in sorted(train_ids)]
        with cf.ThreadPoolExecutor(6) as ex:
            futs = {ex.submit(detect_flow, cl, fl, sc, train): fl for fl, sc in screens.items()}
            flags = []
            for fu in cf.as_completed(futs):
                fl, u = fu.result(); flags += fl; cost[0] += u[0]; cost[1] += u[1]
        # judge per flow against ALL known problems of that flow (train and held-out), so re-found training problems
        # are not counted as false positives
        matches = []
        with cf.ThreadPoolExecutor(6) as ex:
            jobs = {}
            for fl in screens:
                ff = [f for f in flags if f["flow"] == fl]
                pp = [p for p in problems.values() if p["flow"] == fl]
                jobs[ex.submit(judge_flow, cl, ff, pp)] = (fl, ff)
            for fu in cf.as_completed(jobs):
                fl, ff = jobs[fu]; m, u = fu.result(); cost[0] += u[0]; cost[1] += u[1]
                for fi, pid in m:
                    matches.append({"flag": ff[fi], "problem": pid})
        rec = {"name": name, "train": sorted(train_ids), "held": sorted(held_ids), "flags": flags, "matches": matches}
        json.dump(rec, open(path, "w"), indent=1)
        results.append(rec)
        print(name, len(flags), "flags", flush=True)
    summary = score(results, problems)
    summary["tokens"] = {"input": cost[0], "output": cost[1], "usd_est": round(cost[0] / 1e6 * 4 + cost[1] / 1e6 * 20, 2)}
    json.dump(summary, open(f"{a.out}/summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


def score(results: list[dict], problems: dict, thresholds=(0.0, 0.6, 0.8)) -> dict:
    out = {}
    for th in thresholds:
        rows = []
        for r in results:
            if r["name"] == "baseline":
                continue
            held, train = set(r["held"]), set(r["train"])
            flags = [f for f in r["flags"] if f["confidence"] >= th]
            fkey = lambda f: (f["flow"], f["img"], f["title"])  # noqa: E731
            keep = {fkey(f) for f in flags}
            m = [x for x in r["matches"] if fkey(x["flag"]) in keep]
            hit_held = {x["problem"] for x in m if x["problem"] in held}
            flag_held = {fkey(x["flag"]) for x in m if x["problem"] in held}
            flag_train_only = {fkey(x["flag"]) for x in m if x["problem"] in train} - flag_held
            flag_any = {fkey(x["flag"]) for x in m}
            n = len(keep)
            team_held = {p for p in held if problems[p]["source"] == "team"}
            rows.append({"fold": r["name"], "held": len(held), "recall": len(hit_held) / len(held),
                         "team_held": len(team_held), "team_recall": len(hit_held & team_held) / max(1, len(team_held)),
                         "ai_recall": len(hit_held - team_held) / max(1, len(held - team_held)),
                         "flags": n, "flags_on_held": len(flag_held), "flags_on_train_only": len(flag_train_only),
                         "unmatched": n - len(flag_any),
                         "precision": len(flag_held) / max(1, n - len(flag_train_only))})
        avg = {k: round(sum(x[k] for x in rows) / len(rows), 3) for k in rows[0] if k != "fold"} if rows else {}
        out[f"conf>={th}"] = {"mean": avg, "folds": rows}
    base = next((r for r in results if r["name"] == "baseline"), None)
    if base:
        hit = {x["problem"] for x in base["matches"]}
        out["baseline_no_training"] = {"recall_all": round(len(hit) / len(problems), 3), "flags": len(base["flags"]),
                                       "unmatched": len(base["flags"]) - len({(x['flag']['flow'], x['flag']['img'], x['flag']['title']) for x in base['matches']})}
    return out


if __name__ == "__main__":
    main()


FINAL_SCHEMA = json.loads(json.dumps(DETECT_SCHEMA))
FINAL_SCHEMA["properties"]["findings"]["items"]["properties"].update({"x": {"type": "number"}, "y": {"type": "number"}})
FINAL_SCHEMA["properties"]["findings"]["items"]["required"] += ["x", "y"]


def final_findings(problems_path: str, screens_path: str, out_path: str, skip=("team",), min_conf: float = 0.6) -> None:
    """Review every screen with ALL known problems as guidance and keep confident findings, with the problem's
    position on the screen (x, y as fractions of width and height) so the page can pin it."""
    global DETECT_SCHEMA
    problems = json.load(open(problems_path)); screens = json.load(open(screens_path))
    train = [dict(v, id=k) for k, v in problems.items()]
    saved = DETECT_SCHEMA; DETECT_SCHEMA = FINAL_SCHEMA
    try:
        cl = client(); flags = []
        with cf.ThreadPoolExecutor(6) as ex:
            for fl, _ in ex.map(lambda kv: detect_flow(cl, kv[0], kv[1], train), [(f, s) for f, s in screens.items() if f not in skip]):
                flags += fl
    finally:
        DETECT_SCHEMA = saved
    keep = sorted([f for f in flags if f["confidence"] >= min_conf], key=lambda f: (f["flow"], f["screen_no"]))
    out = [{"id": f"d{i + 1}", "flow": f["flow"], "img": f["img"], "type": f["severity"], "title": f["title"], "detail": f["detail"],
            "x": min(.95, max(.05, float(f.get("x", .5)))), "y": min(.95, max(.05, float(f.get("y", .5)))), "confidence": f["confidence"]}
           for i, f in enumerate(keep)]
    json.dump(out, open(out_path, "w"), indent=1)
    print(len(flags), "flags,", len(out), "kept at confidence >=", min_conf)
