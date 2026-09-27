#!/usr/bin/env python3
"""Free diagnosis of Claude-on-Vertex access for one model (no enablement, no quota requests; probes are 5-token calls).

usage: claude_access.py [claude-haiku-4-5@20251001] [--regions global,us,eu,us-east5,europe-west1,...]
1. Model Garden listing (publishers/anthropic/models, v1beta1): is the model / version published?
2. Cloud Quotas (quotaInfos of aiplatform.googleapis.com): per-region / multi-region request quotas for the base model.
3. rawPredict (anthropic_version vertex-2023-10-16) in each region, with Sonnet 5 on global as a control.
Reading: 404 "not found or your project does not have access" in regions WITH quota = the project has not been granted
access to the model (Model Garden "Enable" / partner terms for this project); 429 on us/eu multi-region with no quota
value = quota 0 there (not a burst: it persists across retries).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> None:
    from google.auth.transport.requests import AuthorizedSession

    from auth import vertex_credentials
    from config import GCP_PROJECT

    argv = sys.argv[1:]
    args = [a for n, a in enumerate(argv) if not a.startswith("--") and (n == 0 or argv[n - 1] != "--regions")]
    model = args[0] if args else "claude-haiku-4-5@20251001"
    regions = (sys.argv[sys.argv.index("--regions") + 1].split(",") if "--regions" in sys.argv else
               ["global", "us", "eu", "us-east5", "europe-west1", "us-east1", "europe-west4", "asia-southeast1"])
    base = model.split("@")[0]
    s = AuthorizedSession(vertex_credentials().with_quota_project(GCP_PROJECT))
    r = s.get("https://us-central1-aiplatform.googleapis.com/v1beta1/publishers/anthropic/models",
              params={"pageSize": 200, "listAllVersions": "true"})
    pub = {m["name"].split("/")[-1]: m.get("versionId") for m in r.json().get("publisherModels", [])}
    print(f"[listing] {base}: {'published, version ' + str(pub[base]) if base in pub else 'NOT listed'} "
          f"({len(pub)} anthropic models listed)")
    url = (f"https://cloudquotas.googleapis.com/v1/projects/{GCP_PROJECT}/locations/global/services/"
           "aiplatform.googleapis.com/quotaInfos")
    tok = None
    while True:
        j = s.get(url, params={"pageSize": 1000, **({"pageToken": tok} if tok else {})}).json()
        for q in j.get("quotaInfos", []):
            if "requests" not in q.get("quotaId", "").lower():
                continue
            for d in q.get("dimensionsInfos", []):
                if d.get("dimensions", {}).get("base_model") == f"anthropic-{base}":
                    print(f"[quota] {q['quotaId']} {d['dimensions'].get('region', '(multi/global)')}: "
                          f"{d.get('details', {}).get('value', 'no value (0)')}")
        tok = j.get("nextPageToken")
        if not tok:
            break
    body = {"anthropic_version": "vertex-2023-10-16", "max_tokens": 5, "messages": [{"role": "user", "content": "Say OK"}]}

    def host(loc: str) -> str:
        return ("aiplatform.googleapis.com" if loc == "global" else
                f"aiplatform.{loc}.rep.googleapis.com" if loc in ("us", "eu") else f"{loc}-aiplatform.googleapis.com")

    for m, locs in ((model, regions), ("claude-sonnet-5", ["global"])):
        for loc in locs:
            u = f"https://{host(loc)}/v1/projects/{GCP_PROJECT}/locations/{loc}/publishers/anthropic/models/{m}:rawPredict"
            r = s.post(u, json=body, timeout=60)
            msg = "OK" if r.status_code == 200 else json.loads(r.text.strip().lstrip("[").rstrip("]") or "{}").get(
                "error", {}).get("message", r.text)[:110]
            print(f"[rawPredict] {m} {loc}: {r.status_code} {msg}")


if __name__ == "__main__":
    main()
