"""'who_actually' block for PAST days (orchestrator 22:04Z Nov 14; Shreyas: "why can't we simply see, after the fact, which of our people voted").
From held people's own profile upvote lists (store events kind=upvote; each list is as of that profile's read time). Segments only (same
keyword rule as explain_writer), groups under 20 people folded into "smaller groups". No usernames, no person ids.
  python explain_after.py <store dir> <out dir> <day> [<day> ...] [--no-upload]
Merges into <out>/<day>.json (creates it if absent) and uploads results/web/explain/<day>.json.
Limits stated in the block: a profile read before the launch day cannot show the vote; lists capped at one page (exactly 20 upvotes) can hide
older votes; held people are a subset of Product Hunt voters, so observed / displayed votes is a lower bound on held coverage of the voters."""
import json, os, re, subprocess, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import period_parts as PP
from pipeline import warehouse  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]; ST, OUT, DAYS = args[0], args[1], args[2:]; UP = "--no-upload" not in sys.argv
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; MIN = 20; os.makedirs(OUT, exist_ok=True)
SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "explain_writer.py")).read()
exec(SRC[SRC.index("SEG = ["):SRC.index("WHO, COV = {}, {}")])   # SEG + seg_of, identical rule to the forecast-side block
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
last_read = U.groupby("person_id").ft.max(); n_up = U.groupby("person_id").size(); capped = set(n_up[n_up == 20].index)
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "headline", "bio"]).drop_duplicates("person_id")
seg = dict(zip(P.person_id, (P.headline.fillna("") + " " + P.bio.fillna("")).map(seg_of))); held = set(P.person_id)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
TD = json.loads(subprocess.run(["gsutil", "cat", f"{B}/results/web/truth_daily.json"], capture_output=True, text=True).stdout or "{}").get("days", {})
LABEL = ("observed, after the fact: held people whose own profile upvote list (read after the launch day ended) contains this launch. "
         "Held people are a subset of voters, so these counts are a floor, not all voters; a profile read before the day ended cannot show the vote; "
         "people whose list stopped at exactly 20 upvotes (one page) can hide older votes. Descriptive, not a prediction." + " observed / displayed can exceed 1: Product Hunt's displayed count discounts some voters (1-12 month old accounts count about half, fitted weight 0.48 on 84 launches).")
for D in DAYS:
    close = PP.close_utc(D); reread = set(last_read[last_read > close].index) & held
    Ld = W[W.day == D]
    T = TD.get(D, {}); ranks = T.get("ranks", {})
    UD = U[U.target_id.isin(set(Ld.id)) & U.person_id.isin(held)]
    blocks = {}
    for r in Ld.itertuples():
        who = UD[UD.target_id == r.id].person_id.unique()
        segs = pd.Series([seg.get(p, "no headline or bio") for p in who]).value_counts() if len(who) else pd.Series(dtype=int)
        big = [{"segment": s, "n_held_backers": int(n)} for s, n in segs.items() if n >= MIN]; small = int(segs[segs < MIN].sum()) if len(segs) else 0
        rd = last_read.reindex(who)
        disp = None if pd.isna(r.votes) else int(float(r.votes))
        blocks[r.id] = {"name": r.name, "who_actually": {
            "segments": big + ([{"segment": "smaller groups (each under 20 people)", "n_held_backers": small}] if small else []),
            "observed_held_backers": int(len(who)), "displayed_votes": disp,
            "observed_over_displayed": round(len(who) / disp, 3) if disp else None,
            "final_daily_rank": ranks.get(r.id),
            "profile_reads_of_these_backers": {"first": str(rd.min())[:10] if len(rd) else None, "last": str(rd.max())[:10] if len(rd) else None},
            "held_people_reread_after_the_day": len(reread), "held_people_total": len(held),
            "backers_with_capped_list (exactly 20 upvotes)": int(len(set(who) & capped)),
            "accuracy_label": LABEL}}
    p = os.path.join(OUT, f"{D}.json")
    J = json.load(open(p)) if os.path.exists(p) else {"day": D, "version": "explain_v1", "launches": {},
        "READ_ME": "Past day: only the after-the-fact block 'who_actually' is filled; the forecast-side blocks (who / say / competitors / why) start Nov 14."}
    for i, b in blocks.items(): J["launches"].setdefault(i, {}).update(b)
    J["who_actually_written_at"] = pd.Timestamp.now(tz="UTC").isoformat(); json.dump(J, open(p, "w"), indent=1, default=float)
    if UP: subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/explain/{D}.json"], check=True)
    ob = [b["who_actually"]["observed_over_displayed"] for b in blocks.values() if b["who_actually"]["observed_over_displayed"] is not None]
    print(json.dumps({"day": D, "launches": len(blocks), "reread_after": len(reread), "median observed/displayed": round(float(pd.Series(ob).median()), 3) if ob else None,
                      "with any held backer": sum(b["who_actually"]["observed_held_backers"] > 0 for b in blocks.values())}))
