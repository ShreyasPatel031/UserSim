"""Launch-page assets from the official Product Hunt API (no page scraping): logo (thumbnail), gallery images, video
link, product links (social / company). 25 launches per request by id; resumable.
usage: PH_TOKEN=... python page_media.py -> data/page_media.jsonl (stops at the first rate-limit reply; the daily run resumes it)"""
import glob, json, os, time, urllib.error, urllib.request

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/page_media.jsonl"
FIELDS = "id thumbnail{url} media{type url videoUrl} productLinks{type url}"


def ids():
    out = {}
    for f in sorted(glob.glob(f"{D}/days/*.json")) + sorted(glob.glob(f"{D}/today/*.json")):
        for p in json.load(open(f)):
            out[str(p["id"])] = 1
    return list(out)


def query(batch):
    q = "query{" + " ".join(f"p{i}: post(id:\"{x}\"){{{FIELDS}}}" for i, x in enumerate(batch)) + "}"
    req = urllib.request.Request("https://api.producthunt.com/v2/api/graphql", json.dumps({"query": q}).encode(),
                                 {"Authorization": "Bearer " + os.environ["PH_TOKEN"], "Content-Type": "application/json"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("data") or {}
        except urllib.error.HTTPError as e:
            if e.code == 429:              # API rate limit: stop for today, the daily run resumes tomorrow
                return None
            print("retry", a, e.code, flush=True); time.sleep(10)
        except Exception as e:  # noqa: BLE001
            print("retry", a, str(e)[:100], flush=True); time.sleep(10)
    return {}


def main():
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [x for x in ids() if x not in done]
    print("launches", len(todo), flush=True)
    with open(OUT, "a") as f:
        for k in range(0, len(todo), 25):
            got = query(todo[k:k + 25])
            if got is None:
                print("rate limited after", k, "launches; stopping", flush=True); break
            for v in got.values():
                if v:
                    f.write(json.dumps(v) + "\n")
            if k % 500 == 0:
                print(k, flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
