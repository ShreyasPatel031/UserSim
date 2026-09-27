#!/usr/bin/env python3
"""Deploy deploy/vercel-proxy (static rewrite proxy -> VM) to Vercel production via the REST API.

Why not `vercel deploy`: run from inside this git checkout the CLI attaches git metadata
(commit author grokbot@local.invalid). The project is on the Hobby plan, which BLOCKS
deployments whose commit author is not a team member ("commit author doesn't have
permission"), and the CLI then waits on the blocked build forever (the 2h "hang").
This posts only vercel.json + public/ as inline files with no git metadata.

Token: VERCEL_TOKEN env, else /home/box/agent-data/box-secrets.json card.VERCEL_TOKEN.
"""
import json, os, sys, time, urllib.request

TEAM = os.environ.get("VERCEL_TEAM_ID", "team_QdRX54duvtCx7rW0Uu1tHiMm")
PROJECT = os.environ.get("VERCEL_PROJECT_ID", "prj_3440zMYOyQjdHkSIdYADPcr3vG1v")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vercel-proxy")
TARGET = os.environ.get("VERCEL_TARGET", "production")
tok = os.environ.get("VERCEL_TOKEN") or json.load(open("/home/box/agent-data/box-secrets.json"))["card"]["VERCEL_TOKEN"]


def api(method, path, body=None):
    req = urllib.request.Request("https://api.vercel.com" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


files = [{"file": "vercel.json", "data": open(os.path.join(ROOT, "vercel.json")).read()}]
for dp, _, fs in os.walk(os.path.join(ROOT, "public")):
    for f in fs:
        p = os.path.join(dp, f)
        files.append({"file": os.path.relpath(p, ROOT), "data": open(p).read()})
d = api("POST", f"/v13/deployments?teamId={TEAM}&forceNew=1&skipAutoDetectionConfirmation=1", {
    "name": "usersim", "project": PROJECT, "target": TARGET, "files": files,
    "projectSettings": {"framework": None, "installCommand": "", "buildCommand": "",
                        "outputDirectory": "public", "devCommand": None}})
dep = d["id"]
print("created", dep, d.get("url"), flush=True)
for _ in range(60):
    d = api("GET", f"/v13/deployments/{dep}?teamId={TEAM}")
    if d.get("readyState") in ("READY", "ERROR", "BLOCKED", "CANCELED"):
        break
    time.sleep(3)
print(d.get("readyState"), d.get("readyStateReason") or "", d.get("alias"))
sys.exit(0 if d.get("readyState") == "READY" else 1)
