"""ph_discounted_likely flag (ring_flag.py validation: oc >= 5 and oc share >= 0.30 had recall 95% of the over-count excess, 7.0% of held
voters flagged on at-or-below-count launches vs 37.3% on over-count launches). Never deletes anyone; returns a set of person ids.
dated_flags(Ud, W, before): Ud = upvote events (person_id, target_id, lday) from reads fetched before the cut; W = warehouse launches
(id, day, votes); only launches dated before `before` count as over-count evidence (held voters in Ud > displayed votes)."""
import pandas as pd
K, SH = 5, 0.30


def dated_flags(Ud, W, before, k=K, sh=SH):
    U = Ud[Ud.lday < before]
    held = U.groupby("target_id").person_id.nunique()
    shown = W.drop_duplicates("id", keep="last").set_index("id").votes.reindex(held.index)
    oc = set(held[(shown.notna()) & (held > shown)].index)
    n_oc = U[U.target_id.isin(oc)].groupby("person_id").target_id.nunique()
    n_all = U.groupby("person_id").target_id.nunique()
    share = (n_oc / n_all.reindex(n_oc.index)).fillna(0)
    return set(n_oc[(n_oc >= k) & (share >= sh)].index), len(oc)
