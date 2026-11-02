"""Today's people-step lists from the warehouse, same rules as pipeline/incremental.plan:
upvotes = new commenters + active (events in last 30 d) whose upvotes_page1 200 is older than 7 d or who commented since;
following = new commenters + (Mondays) all active people.   usage: python3 make_lists.py YYYY-MM-DD outdir"""
import datetime as dt, os, subprocess, sys
import duckdb
d, out = sys.argv[1], sys.argv[2]
B = "gs://usersim-bakeoff-347838016394/usersim_sim/tables"
os.makedirs(out, exist_ok=True)
c = duckdb.connect()
for t in ("events", "people", "fetch_state", "comments"):
    os.makedirs(f"{out}/t/{t}", exist_ok=True)
    subprocess.run(["gsutil", "-q", "-m", "rsync", f"{B}/{t}", f"{out}/t/{t}"], check=True)
    c.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{out}/t/{t}/*.parquet', union_by_name=true)")
D = dt.date.fromisoformat(d); ago = lambda n: str(D - dt.timedelta(days=n))
act = [r[0] for r in c.execute(f"SELECT DISTINCT person FROM events WHERE date >= '{ago(30)}' AND date < '{d}'").fetchall()]
known = {r[0] for r in c.execute("SELECT person FROM people").fetchall()}
st = dict(c.execute("SELECT person, max(last_fetched) FROM fetch_state WHERE source = 'upvotes_page1' AND status = 200 GROUP BY 1").fetchall())
lastc = dict(c.execute(f"SELECT person, max(date) FROM comments WHERE date < '{d}' GROUP BY 1").fetchall())
ref = [u for u in act if u in known and (str(st.get(u, "0")) < ago(7) or str(lastc.get(u, "0")) > str(st.get(u, "0")))]
newp = sorted({r[0] for r in c.execute(f"SELECT DISTINCT person FROM comments WHERE date >= '{ago(1)}'").fetchall()
               if r[0] and r[0] not in known and r[0] != "[REDACTED]"})
up = sorted(set(newp) | set(ref)); fol = sorted(set(newp) | (set(act) if D.weekday() == 0 else set()))
open(f"{out}/upvotes.txt", "w").write("\n".join(up) + "\n"); open(f"{out}/following.txt", "w").write("\n".join(fol) + "\n")
print(f"{d}: refresh {len(ref)}, new {len(newp)}, upvotes {len(up)}, following {len(fol)}")
