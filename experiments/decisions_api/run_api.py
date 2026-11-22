"""Call the Gemini Decisions API (gemini-decision-1) once per person-day: one 'noul' question per launch in the day's line-up.

  python run_api.py <out dir> [--limit N] [--workers K]

Reads <out dir>/persondays.jsonl (build_inputs.py), appends answers to <out dir>/api_answers.jsonl (resumable: done person-days
are skipped). The key is read from $GEMINI_KEY_FILE and sent only as the x-goog-api-key header; it is never printed or written.
Hard stop at $5 of input tokens ($0.10 per 1M). Retries 429/5xx with exponential back-off.
"""
import json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

OUT = sys.argv[1]
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
WORKERS = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 4
URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
KEY = open(os.environ["GEMINI_KEY_FILE"]).read().strip()
PRICE = 0.10 / 1e6; CAP_USD = 5.0
lock = threading.Lock(); spent_tokens = [0]

ans_path = f"{OUT}/api_answers.jsonl"
done = set()
if os.path.exists(ans_path):
    for l in open(ans_path):
        r = json.loads(l); done.add((r["day"], r["pid"])); spent_tokens[0] += r.get("input_tokens") or 0
R = [json.loads(l) for l in open(f"{OUT}/persondays.jsonl")]
todo = [r for r in R if (r["day"], r["pid"]) not in done][:LIMIT]
print(f"done {len(done)}, todo {len(todo)}, tokens so far {spent_tokens[0]}", flush=True)


def body(r):
    q = {}
    for lid, name, tag in zip(r["launch_ids"], r["names"], r["taglines"]):
        q[f"l{lid}"] = {"type": "noul", "instructions": f"Would this person upvote \"{name}\" ({tag}) on Product Hunt today? "
                                                        f"Answer yes only if they would upvote this launch today."}
    return {"model": "gemini-decision-1", "input": r["text"], "questions": q}


def call(r):
    if spent_tokens[0] * PRICE >= CAP_USD: return None
    b = body(r)
    for attempt in range(8):
        try:
            resp = requests.post(URL, json=b, headers={"x-goog-api-key": KEY, "Content-Type": "application/json"}, timeout=180)
        except requests.RequestException as ex:
            time.sleep(2 ** attempt); continue
        if resp.status_code == 200:
            j = resp.json()
            p = {k[1:]: (v or {}).get("noul") for k, v in (j.get("answers") or {}).items()}
            tok = (j.get("usage") or {}).get("total_input_tokens")
            out = {"day": r["day"], "pid": r["pid"], "p": p, "input_tokens": tok, "usage": j.get("usage")}
            with lock:
                spent_tokens[0] += tok or 0
                with open(ans_path, "a") as f: f.write(json.dumps(out) + "\n")
            return out
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 2 ** attempt * 2)); continue
        print("HTTP", resp.status_code, resp.text[:300].replace(KEY, "***"), flush=True); return None
    print("gave up", r["day"], flush=True); return None


t0 = time.time(); n = 0
with ThreadPoolExecutor(WORKERS) as ex:
    for out in ex.map(call, todo):
        n += 1
        if n % 25 == 0 or n == len(todo):
            print(f"{n}/{len(todo)} tokens {spent_tokens[0]} ${spent_tokens[0] * PRICE:.3f} {time.time() - t0:.0f}s", flush=True)
print("final tokens", spent_tokens[0], f"${spent_tokens[0] * PRICE:.4f}", flush=True)
