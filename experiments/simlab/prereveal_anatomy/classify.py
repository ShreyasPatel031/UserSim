import json, sys, numpy as np, pandas as pd
SP = sys.argv[1]; OUT = f"{SP}/pra/out"; D = pd.read_parquet(f"{OUT}/launch_rows.parquet")
print("ring share held: median", D.ring_share_held.median(), "p90", D.ring_share_held.quantile(.9), "votes_0400 present", D.votes_0400.notna().mean())
M = []
for d, g in D.groupby("day"):
    for r in g.itertuples():
        fn = r.final <= 10 and r.pred_rank > 10; fp = r.pred_rank <= 10 and r.final > 10
        if not (fn or fp): continue
        side = (lambda x: x <= 10) if fn else (lambda x: x > 10)   # True = the signal said the right thing
        if side(r.pos): c = "midnight prior / ridge moved it wrong (hidden order was right)"
        elif r.vrank_0400 == r.vrank_0400 and side(r.vrank_0400): c = "hidden order wrong (votes at 04:00 were right)"
        elif r.ring_share_held == r.ring_share_held and r.ring_share_held >= 0.30: c = "ring or vote spike (30%+ of held voters ring-flagged)"
        elif 9 <= r.final <= 12: c = "boundary (final rank 9-12)"
        elif r.vrank_0400 != r.vrank_0400: c = "other (no 04:00 votes)"
        else: c = "late surge or fade after the reveal"
        M.append({"day": d, "id": r.id, "type": "false negative (finished top 10, not predicted)" if fn else "false positive (predicted top 10, finished outside)", "class": c,
                  "final": r.final, "pred_rank": r.pred_rank, "hidden_0345": r.pos, "hidden_0100": r.pos_0100, "rank_0005": r.r_clean, "comments": r.comments, "comment_vel_1h": r.comment_vel_1h,
                  "maker_comment_share": r.maker_comment_share, "hunter_top5": r.hunter_top5, "hunter_n": r.hunter_n, "vrank_0400": r.vrank_0400, "vrank_0500": r.vrank_0500, "vrank_0600": r.vrank_0600,
                  "ring_share_held": r.ring_share_held, "held_voters": r.held_voters, "n_day": r.n_day})
M = pd.DataFrame(M); M.to_csv(f"{OUT}/misses_top10.csv", index=False)
print(len(M), "misses on", D.day.nunique(), "days"); print(M.groupby(["class", "type"]).size().unstack(fill_value=0))
pd.set_option("display.width", 250); print(M.drop(columns=["id"]).round(2).to_string(index=False))
# what separates the hidden-order misses: compare missed-FN vs FP on features
