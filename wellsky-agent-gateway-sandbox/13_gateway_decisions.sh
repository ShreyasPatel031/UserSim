#!/usr/bin/env bash
# Summarize Agent Gateway IAP decisions for an agent since a timestamp: destination, registry match, allow/deny, dry-run.
set -euo pipefail; source "$(dirname "$0")/env.sh"
ENGINE_ID=${1:?reasoningEngine numeric id}; SINCE=${2:?RFC3339 timestamp}
gcloud logging read "timestamp>=\"$SINCE\" AND protoPayload.serviceName=\"iap.googleapis.com\" AND protoPayload.authenticationInfo.principalSubject:\"$ENGINE_ID\"" \
  --limit 300 --format=json | python3 -c '
import json, sys, collections
c = collections.Counter()
for e in json.load(sys.stdin):
    p = e["protoPayload"]; req = p.get("request", {})
    url = req.get("httpRequest", {}).get("url", "").split("?")[0]
    host = url.split("/")[2] if "//" in url else url
    tool = " ".join(x for x in (req.get("mcp_method", ""), req.get("mcp_tool_name", "") or req.get("mcpToolName", "")) if x)
    ai = (p.get("authorizationInfo") or [{}])[0]
    c[(host + ("/mcp" if url.endswith("/mcp") else ""), p.get("resourceName", "")[-40:], "ALLOW" if ai.get("granted") else "DENY", "dry-run" if req.get("dryRun") else "enforced", tool)] += 1
for (host, res, verdict, mode, tool), n in sorted(c.items()):
    print(f"{n:4d}  {verdict:5s} {mode:8s} {host:52s} {res:42s} {tool}")'
