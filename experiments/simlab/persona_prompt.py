"""Shared persona-panel prompt (persona_say.py and the reactions_v2.py PERSONA variants)."""
PROMPT = """You simulate how distinct audience groups on Product Hunt react to a product launch. Each group below is a real aggregate of
20 or more Product Hunt users (their role, how active they are, the topics they upvote and products they commonly upvoted). Speak as a
typical member of each group, in a short Product Hunt comment voice. Be specific to THIS product; do not praise generically.

LAUNCH
Name: {name}
Tagline: {tagline}
Description: {desc}
Topics: {topics}

GROUPS
{groups}

For EVERY group (same order), return JSON only:
{{"reactions": [{{"group": <number>, "reaction": "<1-2 sentences>", "concern": "<one specific concern or objection>", "question": "<one question they would ask the makers>", "interest": "high"|"medium"|"low"}}, ...]}}"""
def gtxt(i, g):
    tops = ", ".join(f"{t['topic']} {round(100 * t['share'])}%" for t in g.get("topic_shares", []))
    prods = ", ".join(p["product"] for p in g.get("products_they_commonly_upvoted", [])[:5])
    pr = g.get("segment_profile") or {}; who = f"; who they are: {pr['who']}" if pr.get("who") else ""
    if pr.get("says"): who += "; what members of this group typically say on launches (paraphrased from their own past comments): " + " / ".join(pr["says"][:3])
    if g.get("share_of_expected_voters") is not None: who += f"; share of this launch's expected voters: {round(100 * g['share_of_expected_voters'])}%"
    if g.get("lift") is not None: who += f" vs {round(100 * (g.get('base_share') or 0))}% of all recent votes (lift {g['lift']}x; interest in this launch: {g.get('interest')})"
    return f"{i + 1}. {g['segment']} ({g['n_people']} people; median {g['median_upvotes_last_30_days']:.0f} upvotes in 30 days){who}; upvote topics: {tops}; products they upvoted: {prods}"
