"""Command line for the gateway.

    python -m fetchgate fetch [N] [--browser | --scroll] [--routes vm,vm_camoufox] [--capture SUBSTR]
                                  [--max-scrolls K] [--no-html] < urls.txt > pages.jsonl
        stdin: one URL per line. stdout: one JSON line per URL {url, status, route, final_url, html} (+ scrolls,
        responses in browser / scroll mode). N fetches at once (default 4). On a budget stop no new URL starts and
        the exit code is 3. The job's route mix and $ go to stderr at the end.
    python -m fetchgate job [JOB]          route mix, items, bytes, $ total and per item (default: FETCH_JOB / today's)
    python -m fetchgate actor ACTOR < payload.json   Apify actor run (ALLOW_APIFY=1); items as JSON lines
    python -m fetchgate health             what the gateway can reach (never credential values)
    python -m fetchgate serve              the localhost service (VM: systemd unit fetchgate.service)
    python -m fetchgate scan [--staged] [PATHS...]   the "no direct proxy / Apify use" repo check

Environment: FETCH_JOB (job name), FETCH_BUDGET_USD (job cap, default 5), ALLOW_APIFY=1 (Apify after every other
route failed), FETCHGATE_URL (the service; set for agent shells on the VM).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor


def _fetch_cmd(a: argparse.Namespace) -> int:
    import fetchgate

    urls = [u.strip() for u in sys.stdin if u.strip()]
    job = fetchgate.default_job()
    lock, stop = threading.Lock(), threading.Event()
    keys = ("url", "status", "route", "final_url", "html", "scrolls", "responses", "usd", "error")

    def one(url: str) -> None:
        if stop.is_set():
            return
        try:
            rec = fetchgate.fetch(url, browser=a.browser, scroll=a.scroll, job=job,
                                  routes=tuple(a.routes.split(",")) if a.routes else None, capture=a.capture,
                                  max_scrolls=a.max_scrolls)
        except fetchgate.BudgetExceeded as exc:
            stop.set()
            print(f"[fetchgate] budget stop: {exc}", file=sys.stderr, flush=True)
            return
        except Exception as exc:  # noqa: BLE001 - one bad URL does not end the job
            rec = {"url": url, "status": -1, "route": "", "final_url": "", "html": "", "error": repr(exc)[:300]}
        if a.no_html:
            rec["html"] = ""
        with lock:
            sys.stdout.write(json.dumps({k: rec[k] for k in keys if k in rec}) + "\n")
            sys.stdout.flush()

    with ThreadPoolExecutor(a.n) as ex:
        list(ex.map(one, urls))
    print(json.dumps({"summary": fetchgate.job_summary(job)}), file=sys.stderr, flush=True)
    return 3 if stop.is_set() else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m fetchgate", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("n", nargs="?", type=int, default=4)
    f.add_argument("--browser", action="store_true")
    f.add_argument("--scroll", action="store_true")
    f.add_argument("--routes", default="")
    f.add_argument("--capture", default=None)
    f.add_argument("--max-scrolls", type=int, default=None)
    f.add_argument("--no-html", action="store_true")
    j = sub.add_parser("job")
    j.add_argument("job", nargs="?", default=None)
    ac = sub.add_parser("actor")
    ac.add_argument("actor")
    ac.add_argument("--wait-s", type=float, default=900.0)
    sub.add_parser("health")
    sub.add_parser("serve")
    sc = sub.add_parser("scan")
    sc.add_argument("--staged", action="store_true")
    sc.add_argument("paths", nargs="*")
    a = p.parse_args(argv)

    if a.cmd == "fetch":
        return _fetch_cmd(a)
    if a.cmd == "job":
        import fetchgate

        print(json.dumps(fetchgate.job_summary(a.job), indent=1))
        return 0
    if a.cmd == "actor":
        import fetchgate

        for item in fetchgate.run_actor(a.actor, json.load(sys.stdin), wait_s=a.wait_s):
            print(json.dumps(item))
        return 0
    if a.cmd == "health":
        from fetchgate.gate import remote_url

        if remote_url():
            from fetchgate import client

            print(json.dumps(client.health(), indent=1))
        else:
            from fetchgate import service

            print(json.dumps(service.handle("/health", None)[1] | {"mode": "in-process"}, indent=1))
        return 0
    if a.cmd == "serve":
        from fetchgate import service

        service.serve()
        return 0
    from fetchgate import scan

    return scan.main((["--staged"] if a.staged else []) + a.paths)


if __name__ == "__main__":
    sys.exit(main())
