"""Data completeness watch (Shreyas, Nov 4 ~20:30 UTC: "we will pull every piece of information we get on every single
person"; alert him if any agent caps or truncates a pull). Counts only: no usernames are printed or written.

Checks, each against the previous run's state (STATE file), so only NEW truncation alerts:
  store_v3 tabs.parquet   per tab: people with complete=False or stopped_early=True, and the header total vs rows got
                          (a full pull gets every row the header says exists)
  ph_at_launch makers     today's and yesterday's makers.jsonl: followers_cap set, followers_capped, followers_complete False
  mailbox from_grokbot    new or changed files whose text mentions a cap / limit on what is pulled
                          (cap, capped, limit to, limited, newest N, first N, max_*, truncat, skip, only page 1)
Prints one JSON line; "alerts" lists every new finding (empty = nothing new).
usage: python completeness_watch.py [state.json]"""
import datetime as dt, json, os, re, subprocess, sys, tempfile
import pandas as pd

B = "gs://usersim-bakeoff-347838016394/usersim_sim"
STATE = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.completeness_watch.json")
CAP_RE = re.compile(r"\b(capp?ed|caps?\b|limit(?:ed)? (?:to|at)|newest \d+|first \d+ |max_[a-z_]+\s*=?\s*\d+|truncat\w*|only page ?1|skip(?:ped|s)? )", re.I)


def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True)


def tabs():
    d = tempfile.mkdtemp(prefix="cw_"); f = f"{d}/tabs.parquet"
    if sh("gsutil", "-q", "cp", f"{B}/raw/population/store_v3/tabs.parquet", f).returncode:
        return {}
    T = pd.read_parquet(f)
    out = {}
    for t, g in T.groupby("tab"):
        out[t] = {"people": int(len(g)), "incomplete": int((~g.complete.astype(bool)).sum()), "stopped_early": int(g.stopped_early.astype(bool).sum()),
                  "header_total": int(g.header.fillna(0).sum()), "rows_got": int(g["count"].sum())}
    return out


def makers():
    out = {}
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-8))).date()
    for d in (today, today - dt.timedelta(days=1)):
        r = sh("gsutil", "cat", f"{B}/raw/ph_at_launch/{d}/makers.jsonl")
        if r.returncode:
            continue
        R = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        out[str(d)] = {"makers": len(R), "cap_set": sum(1 for x in R if x.get("followers_cap") not in (None, 0)),
                       "capped": sum(1 for x in R if x.get("followers_capped")),
                       "caps": sorted({x.get("followers_cap") for x in R if x.get("followers_cap") not in (None, 0)})}
    return out


def mailbox(prev):
    r = sh("gsutil", "ls", "-l", f"{B}/mailbox/from_grokbot/")
    seen, hits = dict(prev or {}), []
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) < 3 or not p[2].startswith("gs://"):
            continue
        key, stamp = p[2], p[1]
        if seen.get(key) == stamp:
            continue
        seen[key] = stamp
        if prev is None:   # first run: record, don't alert on history
            continue
        txt = sh("gsutil", "cat", key).stdout
        m = [x.group(0) for x in CAP_RE.finditer(txt)]
        if m:
            ctx = []
            for x in list(CAP_RE.finditer(txt))[:3]:
                s = txt[max(0, x.start() - 90): x.end() + 90].replace("\n", " ")
                ctx.append(re.sub(r"@\w+", "@<user>", s))
            hits.append({"file": key.rsplit("/", 1)[-1], "matches": sorted(set(m))[:8], "context": ctx})
    return seen, hits


def main():
    prev = json.load(open(STATE)) if os.path.exists(STATE) else {}
    now = {"tabs": tabs(), "makers": makers()}
    seen, mail = mailbox(prev.get("mail_seen"))
    alerts = []
    for t, v in now["tabs"].items():
        p = (prev.get("tabs") or {}).get(t, {})
        for k in ("incomplete", "stopped_early"):
            if v[k] > p.get(k, 0 if prev else v[k]):
                alerts.append(f"store_v3 {t}: {k} {p.get(k, 0)} -> {v[k]} people (rows got {v['rows_got']} of header {v['header_total']})")
    for d, v in now["makers"].items():
        p = (prev.get("makers") or {}).get(d, {})
        if v["cap_set"] or v["capped"]:
            if (v["cap_set"], v["capped"]) != (p.get("cap_set"), p.get("capped")):
                alerts.append(f"makers {d}: follower cap set on {v['cap_set']} of {v['makers']} (caps {v['caps']}), capped {v['capped']}")
    for h in mail:
        alerts.append(f"mailbox {h['file']}: mentions {h['matches']}")
    json.dump({**now, "mail_seen": seen, "at": dt.datetime.now(dt.timezone.utc).isoformat()}, open(STATE, "w"))
    print(json.dumps({"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "alerts": alerts, "mail_context": [h["context"] for h in mail],
                      "tabs": now["tabs"], "makers": now["makers"]}))


if __name__ == "__main__":
    main()
