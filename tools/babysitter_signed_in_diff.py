"""Diff signed-out vs signed-in Product Hunt captures (babysitter). Prints field names and counts only, never usernames.

Input: a local copy of gs://.../raw/_babysitter/signed_in_diff/ with out/<target>/<tab>.{html.gz,xhr.jsonl.gz,meta.json}
and in/<target>/<tab>.*  (the target folder names are opaque; output refers to targets by index).
Output: markdown table per tab: items rendered (out/in), JSON key paths seen only signed in, only signed out, time-like
fields, voter-like fields, load secs.
Usage: python3 -I babysitter_signed_in_diff.py <dir> > signed_in_diff.md
"""
import collections, gzip, json, os, re, sys

TIMEY = re.compile(r"(At|_at|Date|date|time|Time|ago)$")
VOTEY = re.compile(r"(vote|Vote|upvot|Upvot|voter|Voter)")


def paths(o, pre="", out=None):
    out = set() if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            if k.startswith("__") and k != "__typename":
                continue
            p = f"{pre}.{k}" if pre else k
            out.add(p); paths(v, p, out)
    elif isinstance(o, list):
        for v in o[:50]:
            paths(v, pre + "[]", out)
    return out


def typed(o, out=None):
    """key paths prefixed by the nearest __typename, e.g. Post.votesCount, so differences read as fields."""
    out = set() if out is None else out
    if isinstance(o, dict):
        t = o.get("__typename", "?")
        for k, v in o.items():
            if k == "__typename":
                continue
            out.add(f"{t}.{k}"); typed(v, out)
    elif isinstance(o, list):
        for v in o[:50]:
            typed(v, out)
    return out


def load(d, tgt, tab):
    base = os.path.join(d, tgt, tab)
    meta = {}
    if os.path.exists(base + ".meta.json"):
        meta = json.load(open(base + ".meta.json"))
    fields = set(); n = 0
    if os.path.exists(base + ".xhr.jsonl.gz"):
        for l in gzip.open(base + ".xhr.jsonl.gz", "rt", errors="replace"):
            try:
                r = json.loads(l); b = r.get("body")
                b = json.loads(b) if isinstance(b, str) else b
                typed(b, fields); n += 1
            except Exception:
                pass
    if os.path.exists(base + ".html.gz"):
        h = gzip.open(base + ".html.gz", "rt", errors="replace").read()
        for m in re.finditer(r'<script[^>]*>(\{.*?\})</script>', h, re.S):
            try:
                typed(json.loads(m.group(1)), fields)
            except Exception:
                pass
    return meta, fields, n


def main():
    d = sys.argv[1]
    outs = sorted(os.listdir(os.path.join(d, "out"))) if os.path.isdir(os.path.join(d, "out")) else []
    ins = set(os.listdir(os.path.join(d, "in"))) if os.path.isdir(os.path.join(d, "in")) else set()
    tabs_all = collections.defaultdict(lambda: {"only_in": collections.Counter(), "only_out": collections.Counter(), "rows": []})
    for i, t in enumerate(outs):
        if t not in ins:
            continue
        tabs = {f.split(".")[0] for f in os.listdir(os.path.join(d, "out", t))} | {f.split(".")[0] for f in os.listdir(os.path.join(d, "in", t))}
        for tab in sorted(tabs):
            mo, fo, no = load(os.path.join(d, "out"), t, tab)
            mi, fi, ni = load(os.path.join(d, "in"), t, tab)
            T = tabs_all[tab]
            T["only_in"].update(fi - fo); T["only_out"].update(fo - fi)
            T["rows"].append((i, mo.get("items_rendered"), mi.get("items_rendered"), no, ni, mo.get("load_secs"), mi.get("load_secs"),
                              mo.get("captcha") or mo.get("block"), mi.get("captcha") or mi.get("block")))
    print("# Signed-out vs signed-in Product Hunt diff\n")
    for tab, T in sorted(tabs_all.items()):
        print(f"## {tab}\n\n| target | items out | items in | xhr out | xhr in | secs out | secs in | block out | block in |\n|---|---|---|---|---|---|---|---|---|")
        for r in T["rows"]:
            print("| " + " | ".join("" if x is None else str(x) for x in r) + " |")
        oi = [k for k, _ in T["only_in"].most_common(60)]
        print(f"\nFields only signed in ({len(T['only_in'])}): " + (", ".join(oi) or "none"))
        print("Of those, time-like: " + (", ".join(k for k in oi if TIMEY.search(k.split('.')[-1])) or "none"))
        print("Of those, vote-like: " + (", ".join(k for k in oi if VOTEY.search(k)) or "none"))
        print(f"Fields only signed out ({len(T['only_out'])}): " + (", ".join(k for k, _ in T['only_out'].most_common(30)) or "none") + "\n")


if __name__ == "__main__":
    main()
