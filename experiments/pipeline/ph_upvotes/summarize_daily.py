"""Work dir out_*.jsonl -> delivery files + README in the same form as raw/ph_upvotes_full, plus fetch_state rows.
usage: python3 summarize_daily.py gs://.../ph_people_daily/D/work gs://.../ph_people_daily/D"""
import collections, json, os, subprocess, sys, tempfile
W, O = sys.argv[1], sys.argv[2]; D = O.rstrip("/").rsplit("/", 1)[-1]
tmp = tempfile.mkdtemp(); subprocess.run(f"gsutil -q cp '{W}/out_*.jsonl' '{W}/job.log' {tmp}/", shell=True)
def rows(p):
    f = f"{tmp}/out_{p}.jsonl"
    last = {}
    for l in open(f) if os.path.exists(f) else []:
        try: r = json.loads(l)
        except ValueError: continue
        last[r["username"]] = r   # final attempt per person
    return last
U, F = rows("upvotes"), rows("following")
up, fo, st = [], [], []
for u, r in U.items():
    for it in r.get("items") or []:
        up.append(dict(username=u, position=it["position"], post_id=it["post_id"], post_slug=it["post_slug"], post_name=it["post_name"],
                       product_slug=it["product_slug"], launched_at=it["launched_at"], votes_total=r.get("votes_total"),
                       has_more=r.get("has_more"), source="residential_camoufox", fetched_at=r.get("fetched_at")))
    ids = [str(x) for x in r.get("upvotes") or []]
    st.append(dict(person=u, source="upvotes_page1", last_fetched=D, status=r.get("status"), items=len(ids),
                   newest_item=ids[0] if ids else None, complete=not r.get("has_more", True)))
for u, r in F.items():
    for i, (f, n) in enumerate(r.get("following") or [], 1):
        fo.append(dict(username=u, position=i, followee=f, followee_followers=n, followings=r.get("followings"),
                       has_more=r.get("has_more"), source="residential_camoufox", fetched_at=r.get("fetched_at")))
    st.append(dict(person=u, source="follows", last_fetched=D, status=r.get("status"), items=len(r.get("following") or []),
                   complete=not r.get("has_more", False)))
def w(name, L):
    with open(f"{tmp}/{name}", "w") as f:
        for x in L: f.write(json.dumps(x) + "\n")
w("upvotes_page1.jsonl", up); w("following_page1.jsonl", fo); w("fetch_state_rows.jsonl", st)
stat = lambda R: dict(collections.Counter(str(r.get("status")) for r in R.values()))
gb = sum((r.get("wire_bytes") or 0) for R in (U, F) for r in R.values()) / 1e9
nic = [l for l in open(f"{tmp}/job.log") if l.startswith("NIC")] if os.path.exists(f"{tmp}/job.log") else []
S = dict(date=D, upvotes_people=len(U), upvotes_status=stat(U), upvote_rows=len(up), following_people=len(F), following_status=stat(F),
         follow_rows=len(fo), wire_GB=round(gb, 4), usd_proxy=round(gb * 1.0, 3), nic=nic[-1].strip() if nic else None)
open(f"{tmp}/README.md", "w").write(f"""# PH people daily refresh {D} (DRAFT, needs the PH agent's verification)
Fetch-ladder route 4 (Camoufox via DataImpulse residential, PHUP_MODE=light), anonymous, read-only, no Apify. Code: experiments/pipeline/ph_upvotes
(fetch_upvotes.py with PHUP_PAGE=upvotes|following, vm_daily.sh, make_lists.py, summarize_daily.py) on claude/fetch-ladder-handover. One VM, deleted after.
Lists (make_lists.py, same rules as pipeline/incremental.plan): upvotes = new commenters + active people stale > 7 d or commented since;
following = new commenters + all active people on Mondays. Inputs: work/upvotes.txt, work/following.txt.

Files:
- upvotes_page1.jsonl: one row per upvote, same columns as raw/ph_upvotes_full/upvotes_page1_full.jsonl
  (username, position, post_id, post_slug, post_name, product_slug, launched_at, votes_total, has_more, source, fetched_at).
- following_page1.jsonl: one row per followee, page 1 (~20 rows): username, position, followee, followee_followers, followings (total), has_more, source, fetched_at.
  Matches ph_predict/parse_following.py ([username, followersCount]); feeds incremental.merge_follows.
- fetch_state_rows.jsonl: rows ready to append to tables/fetch_state (person, source upvotes_page1|follows, last_fetched, status, items, newest_item, complete).
  Upvote events: run incremental.merge_upvotes on the person -> upvotes ids, or join upvotes_page1.jsonl to launches.
- work/out_*.jsonl: raw per-person records (with wire_bytes, attempts).

Status: {json.dumps(S)}
""")
subprocess.run(f"gsutil -q cp {tmp}/upvotes_page1.jsonl {tmp}/following_page1.jsonl {tmp}/fetch_state_rows.jsonl {tmp}/README.md {O}/", shell=True)
print(json.dumps(S))
