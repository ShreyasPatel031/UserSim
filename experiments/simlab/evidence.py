"""Extra per-person evidence for personas (all dated, so a card can use only what came before a day):
  comment_text.parquet   every comment's text: person, launch slug, date, text (from the raw comment pages)
  x_posts                recent X posts per handle (store.RAW x_people / commenter_x)
  review_text            reviews with pros / cons / text (raw profile tabs)
  built                  launches the person made or posted
usage: python -m simlab.evidence   -> simlab/data/comment_text.parquet, review_text.parquet"""
import glob, gzip, json, os, re
import pandas as pd
from . import store


def comment_text():
    rows = []
    for fn in sorted(glob.glob(f"{store.RAW}/comments/page*.jsonl.gz")):
        try:
            for l in gzip.open(fn, "rt"):
                try:
                    body = json.loads(json.loads(l)["html"])
                except Exception:  # noqa: BLE001
                    continue
                post = ((body or {}).get("data") or {}).get("post") or {}

                def walk(n):
                    u = (n.get("user") or {}).get("username")
                    if u and n.get("body"):
                        rows.append((u, post.get("slug"), (n.get("createdAt") or "")[:10], re.sub(r"\s+", " ", n["body"])[:400]))
                    for e in ((n.get("replies") or {}).get("edges") or []):
                        walk(e["node"])
                for e in ((post.get("threads") or {}).get("edges") or []):
                    walk(e["node"])
        except (EOFError, OSError):  # truncated last block
            pass
    return pd.DataFrame(rows, columns=["person", "slug", "date", "text"]).drop_duplicates()


def review_text():
    rows = []
    for f in ("ph_tabs_rest", "profile_tabs"):
        p = f"{store.RAW}/{f}.jsonl.gz"
        if os.path.exists(p):
            for l in gzip.open(p, "rt"):
                t = json.loads(l)
                for r in store.lit(t.get("reviews")):
                    rows.append((t["username"], r.get("product_name") or r.get("product_slug"), r.get("rating"), (r.get("created") or "")[:10],
                                 ", ".join(r.get("pros") or []), ", ".join(r.get("cons") or []), (r.get("text") or "")[:300]))
    return pd.DataFrame(rows, columns=["person", "product", "rating", "date", "pros", "cons", "text"]).drop_duplicates()


if __name__ == "__main__":
    C = comment_text(); C.to_parquet(f"{store.OUT}/comment_text.parquet")
    R = review_text(); R.to_parquet(f"{store.OUT}/review_text.parquet")
    print("comments with text", len(C), "people", C.person.nunique(), "| reviews", len(R))
