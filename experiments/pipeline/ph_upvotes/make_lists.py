"""Today's people-step lists from the warehouse, same rules as pipeline/incremental.plan:
upvotes = new commenters + active (events in last 30 d) whose upvotes_page1 200 is older than 7 d or who commented since;
following = new commenters + (Mondays) all active people.   usage: python3 make_lists.py YYYY-MM-DD outdir

Whole-pool weekly rota (OFF by default; ask 20261103T0345_ph_follows_whole_pool_weekly). With PHUP_FOLLOW_ROTA=1:
following = new commenters + ALL active people every day + today's bucket of the non-active pool (PHUP_POOL, default
raw/requests/upvote_refresh_20261103_full.txt). Each username has a fixed bucket rota_bucket(u) in 0..6 (sha1 of the lowercased
name, stable across runs and machines); day D reads bucket D.toordinal() % 7, so every pool person is read at least once a week.
PHUP_ROTA_ACTIVE_DAILY=0 keeps active people on Mondays only (cheaper variant). This is paid route-4 traffic (~6.7k pages/day instead of ~4.3k on Mondays only), so run_daily.sh also raises the weekly cap when the flag is on."""
import datetime as dt, hashlib, os, subprocess, sys

POOL_DEFAULT = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/requests/upvote_refresh_20261103_full.txt"


def rota_bucket(u: str) -> int:
    return int(hashlib.sha1(u.strip().lower().encode()).hexdigest(), 16) % 7


def rota_today(pool, active, day: dt.date) -> list:
    k, act = day.toordinal() % 7, set(active)
    return sorted({u for u in pool if u and u != "[REDACTED]" and u not in act and rota_bucket(u) == k})


def following_list(newp, act, day: dt.date, rota: bool, pool=(), active_daily: bool = True) -> list:
    act_today = set(act) if (day.weekday() == 0 or (rota and active_daily)) else set()
    return sorted(set(newp) | act_today | (set(rota_today(pool, act, day)) if rota else set()))


def read_pool(path: str) -> list:
    txt = subprocess.run(["gsutil", "-q", "cat", path], capture_output=True, text=True, check=True).stdout if path.startswith("gs://") \
        else open(path).read()
    return [u.strip() for u in txt.split() if u.strip()]


def main():
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
    rota = os.environ.get("PHUP_FOLLOW_ROTA", "0") == "1"
    pool = read_pool(os.environ.get("PHUP_POOL", POOL_DEFAULT)) if rota else []
    active_daily = os.environ.get("PHUP_ROTA_ACTIVE_DAILY", "1") == "1"   # 0 = rota for the non-active pool, active stay Mondays-only
    up = sorted(set(newp) | set(ref)); fol = following_list(newp, act, D, rota, pool, active_daily)
    open(f"{out}/upvotes.txt", "w").write("\n".join(up) + "\n"); open(f"{out}/following.txt", "w").write("\n".join(fol) + "\n")
    extra = f", rota on: pool {len(pool)}, bucket {D.toordinal() % 7} = {len(rota_today(pool, act, D))}" if rota else ", rota off"
    print(f"{d}: refresh {len(ref)}, new {len(newp)}, upvotes {len(up)}, following {len(fol)}{extra}")


if __name__ == "__main__":
    main()
