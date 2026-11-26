"""Mirror in-progress runs to the private bucket every 30 s, without anything from before the test-start mark (login).

    python -m mvp.client_qa.sync_runs mvp/client_qa/private/runs/4255 gs://.../client_qa/reframe/runs/4255
Per shard: shots/ (only after `mark`), actions.jsonl (typed text is never logged), findings.jsonl (the tester notes);
plus status.json with steps, notes and last update per shard.
"""
import json, os, shutil, subprocess, sys, time

src, dst = sys.argv[1], sys.argv[2].rstrip("/")
stage = os.path.join(src, ".sync"); os.makedirs(stage, exist_ok=True)
while True:
    status = {}
    for shard in sorted(os.listdir(src)):
        d = os.path.join(src, shard); lp = os.path.join(d, "log.jsonl")
        if shard.startswith(".") or not os.path.exists(lp):
            continue
        log = [json.loads(l) for l in open(lp) if l.strip()]
        mark = next((i for i, x in enumerate(log) if x["kind"] == "mark"), None)
        if mark is None:
            status[shard] = {"state": "logging in", "updated": time.strftime("%H:%M:%SZ", time.gmtime(os.path.getmtime(lp)))}; continue
        after = log[mark:]
        out = os.path.join(stage, shard); os.makedirs(os.path.join(out, "shots"), exist_ok=True)
        for x in after:
            if x["kind"] == "look":
                s = os.path.join(d, x["shot"]); t = os.path.join(out, x["shot"])
                if os.path.exists(s) and not os.path.exists(t): shutil.copy(s, t)
        with open(os.path.join(out, "actions.jsonl"), "w") as f:
            for x in after:
                if x["kind"] == "act": f.write(json.dumps(x) + "\n")
        notes = [x for x in after if x["kind"] == "note"]
        with open(os.path.join(out, "findings.jsonl"), "w") as f:
            for x in notes: f.write(json.dumps(x) + "\n")
        for fn in ("summary.md", "session.json"):
            if os.path.exists(os.path.join(d, fn)): shutil.copy(os.path.join(d, fn), os.path.join(out, fn))
        status[shard] = {"steps": sum(x["kind"] == "act" for x in after), "findings": len(notes),
                         "updated": time.strftime("%H:%M:%SZ", time.gmtime(os.path.getmtime(lp))),
                         "done": os.path.exists(os.path.join(d, "summary.md"))}
    json.dump(status, open(os.path.join(stage, "status.json"), "w"), indent=1)
    subprocess.run(["gsutil", "-q", "-m", "rsync", "-r", stage, dst], check=False)
    time.sleep(30)
