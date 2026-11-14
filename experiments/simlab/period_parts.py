"""Warehouse `launches` parts, read one file at a time (orchestrator 12:38Z Nov 14: truth from the NEWEST PART ONLY, never the
newest-row-per-launch merge, which kept two dropped launches in week Nov 2-8). Part time = the UTC stamp in the file name; the
initial snapshot counts as written 2026-10-28T00:00Z. Counts and launch ids only."""
import glob, os, re
import pandas as pd
LOC = os.path.expanduser("~/.usersim_sim/launches"); PT = "America/Los_Angeles"
COLS = ["id", "day", "votes", "weekly_rank", "monthly_rank", "updated_at"]


def parts():
    out = []
    for f in glob.glob(f"{LOC}/*.parquet"):
        m = re.match(r"(\d{8}T\d{6})", os.path.basename(f))
        ts = pd.Timestamp(m.group(1), tz="UTC") if m else pd.Timestamp("2026-10-28T00:00Z")
        out.append((ts, f))
    return sorted(out)


_cache = {}
def read(f):
    if f not in _cache:
        x = pd.read_parquet(f, columns=COLS); x["id"] = x.id.astype(str); x["votes"] = pd.to_numeric(x.votes, errors="coerce"); _cache[f] = x
    return _cache[f]


def close_utc(day):
    """End of PT day `day` (next PT midnight) in UTC, DST-aware."""
    return (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(PT).tz_convert("UTC")


def period(per, d):
    d = pd.Timestamp(d)
    if per == "week": s = d - pd.Timedelta(days=d.weekday()); e = s + pd.Timedelta(days=6)
    else: s = d.replace(day=1); e = s + pd.offsets.MonthEnd(0)
    return s, e


def held(asof):
    """What the writer sees at time `asof`: every part written by then, newest row per id (warehouse rule)."""
    P = [read(f) for ts, f in parts() if ts <= asof]
    if not P: return pd.DataFrame(columns=COLS)
    return pd.concat(P).sort_values("updated_at").drop_duplicates("id", keep="last")


def missing_days(per, d, asof):
    """Days X in [period start, d] with no part written after X's close (and by `asof`) holding non-null votes for X's launches."""
    s, _ = period(per, d); miss = []
    for X in pd.date_range(s, pd.Timestamp(d)):
        x = X.strftime("%Y-%m-%d"); c = close_utc(x)
        ok = any((ts > c) and (ts <= asof) and read(f).loc[read(f).day == x, "votes"].notna().any() for ts, f in parts())
        if not ok: miss.append(x)
    return miss


def board(per, d, asof):
    s, _ = period(per, d); L = held(asof); dd = pd.to_datetime(L.day)
    g = L[(dd >= s) & (dd <= pd.Timestamp(d))].dropna(subset=["votes"]).sort_values(["votes", "id"], ascending=[False, True])
    return g.id.tolist(), (L.updated_at.max() if len(L) else None)


def truth(per, d):
    """First part written after the period's close that holds non-null votes for the period's launches; rows of that part only."""
    s, e = period(per, d); c = close_utc(e.strftime("%Y-%m-%d")); col = "weekly_rank" if per == "week" else "monthly_rank"
    for ts, f in parts():
        if ts <= c: continue
        x = read(f); dd = pd.to_datetime(x.day); g = x[(dd >= s) & (dd <= e)]
        if g.votes.notna().any():
            return g[["id", col]].rename(columns={col: "rank"}).dropna(), ts, os.path.basename(f)
    return None, None, None
