"""Mock of an agent WellSky runs outside Agent Runtime (e.g. the Salesforce First Responder).

Agent Gateway can't govern it, so the contingency is controls in code:
- every prompt is screened by Model Armor before the agent acts,
- every decision is written as a structured audit log line,
- it publishes an A2A agent card so it can be listed in Agent Registry (inventory).
"""
import json
import os

import google.auth
import google.auth.transport.requests
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
TEMPLATE = os.environ.get("MA_TEMPLATE", f"projects/{PROJECT}/locations/us-central1/templates/wsky-request")
CARD = {
    "name": "First Responder (mock)", "version": "0.1.0",
    "description": "Mock of WellSky's Salesforce support agent, hosted outside Agent Runtime. Synthetic.",
    "url": os.environ.get("PUBLIC_URL", ""), "protocolVersion": "0.3.0",
    "capabilities": {}, "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "triage", "name": "Triage support case", "description": "Classify and route a support case", "tags": ["support"]}],
}


def screen(text: str) -> dict:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    r = requests.post(f"https://modelarmor.us-central1.rep.googleapis.com/v1/{TEMPLATE}:sanitizeUserPrompt",
                      headers={"Authorization": f"Bearer {creds.token}"}, json={"userPromptData": {"text": text}}, timeout=15)
    r.raise_for_status()
    res = r.json()["sanitizationResult"]
    hits = [k for k, v in res.get("filterResults", {}).items() if '"matchState": "MATCH_FOUND"' in json.dumps(v)]
    return {"blocked": res.get("filterMatchState") == "MATCH_FOUND", "filters": hits}


@app.get("/.well-known/agent-card.json")
def card():
    return jsonify(CARD)


@app.post("/ask")
def ask():
    text = (request.get_json(silent=True) or {}).get("text", "")
    verdict = screen(text)
    print(json.dumps({"severity": "NOTICE", "wsky_audit": True, "agent": "first-responder-mock",
                      "decision": "DENY" if verdict["blocked"] else "ALLOW", "filters": verdict["filters"]}), flush=True)
    if verdict["blocked"]:
        return jsonify({"status": 403, "error": "Blocked by Model Armor", "filters": verdict["filters"]}), 403
    return jsonify({"status": 200, "answer": "Case triaged to Tier 2 EVV support (mock)."})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
