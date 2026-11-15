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
    return f"{i + 1}. {g['segment']} ({g['n_people']} people; median {g['median_upvotes_last_30_days']:.0f} upvotes in 30 days); upvote topics: {tops}; products they upvoted: {prods}"
