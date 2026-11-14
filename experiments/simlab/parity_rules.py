"""Nightly parity_check alert rules: alert only on a NEW kind of live-vs-backtest difference."""
# Understood differences (16 nights Oct 25-Nov 12, arm2_rebuild/parity): the backtest reads the final launch list, which carries post-launch
# edits. Each such column is "known" down to a floor = lowest share_equal seen minus 0.10; below that it alerts as a new kind of difference.
KNOWN_EDIT_FLOOR = {"ph_n_makers": 0.78, "ph_n_media": 0.80, "ph_desc_len": 0.775, "ph_tagline_len": 0.752, "ph_has_video": 0.82,
                    "ph_n_topics": 0.838, "ph_name_len": 0.844, "ph_hunter_age_d": 0.88}
KNOWN_LINEUP_PREFIX = ("ph_dayrank_",)   # within-day ranks: differ whenever the two line-ups differ (seen down to 0.0 equal)
SET_CHANGE_MAX = [1, 1, 2]               # most top 3/5/10 members changed by all live columns on any of the 16 nights; above +1 alerts


def classify(res, ALERT=0.0):
    """Sets res['known differences'], res['UNEXPECTED differing columns'], res['status']; returns the unexpected dict."""
    known = {}
    for c, v in res["columns"].items():
        if v.get("expected") or v["share_equal"] >= 1 - ALERT: continue
        if c.startswith(KNOWN_LINEUP_PREFIX): known[c] = "line-up difference (known)"
        elif c in KNOWN_EDIT_FLOOR and v["share_equal"] >= KNOWN_EDIT_FLOOR[c]: known[c] = f"post-launch edit (known; floor {KNOWN_EDIT_FLOOR[c]})"
    unexp = {c: v for c, v in res["columns"].items() if not v.get("expected") and v["share_equal"] < 1 - ALERT and c not in known}
    big = [k for k, x, mx in zip((3, 5, 10), res["set change, all live columns together"], SET_CHANGE_MAX) if x > mx + 1]
    if big: unexp["ranking effect"] = {"set change top3/5/10": res["set change, all live columns together"], "above known max +1 at top": big}
    res["known differences"] = known; res["UNEXPECTED differing columns"] = unexp
    res["status"] = "ALERT" if unexp else ("ok (known differences only)" if known else "ok")
    return unexp
