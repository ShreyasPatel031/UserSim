"""Send one message to a deployed replica agent and print tool calls/results and the final answer.

  python 07_ask.py <reasoningEngine resource name> "<message>"
Uses the REST :streamQuery endpoint directly (the SDK fails to parse some concatenated stream chunks).
"""
import json
import sys

import google.auth
import google.auth.transport.requests
import requests

name, message = sys.argv[1], sys.argv[2]
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
creds.refresh(google.auth.transport.requests.Request())
r = requests.post(f"https://us-central1-aiplatform.googleapis.com/v1/{name}:streamQuery",
                  headers={"Authorization": f"Bearer {creds.token}"}, timeout=300, stream=True,
                  json={"class_method": "async_stream_query", "input": {"user_id": "test-user", "message": message}})
if not r.ok:
    sys.exit(f"HTTP {r.status_code}: {r.text[:1000]}")
buf, dec = "", json.JSONDecoder()
for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
    buf += chunk
    while buf.strip():
        try:
            ev, end = dec.raw_decode(buf.lstrip())
        except json.JSONDecodeError:
            break
        buf = buf.lstrip()[end:]
        for part in (ev.get("content") or {}).get("parts", []):
            if "function_call" in part:
                print("CALL  ", json.dumps(part["function_call"].get("name")), json.dumps(part["function_call"].get("args"))[:300])
            elif "function_response" in part:
                print("RESULT", json.dumps(part["function_response"].get("response"))[:900])
            elif part.get("text"):
                print("TEXT  ", part["text"][:600].replace("\n", " "))
        code = ev.get("error_code") or ev.get("errorCode") or ev.get("code")
        if code:
            print("ERROR ", code, (ev.get("error_message") or ev.get("errorMessage") or ev.get("message", ""))[:600])
