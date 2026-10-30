"""Longer history from the public BigQuery HN dataset (data through ~Oct 17, 2026):
  stories since START: id, title, url, text, author, final points, comments, time  -> <cache>/bq_stories.parquet
  comments since START with author, time and root story (people_bq.SQL)           -> <cache>/bq_comments.parquet
Person-level data stays in the private cache / bucket. Spend logged.

    python history_bq.py 2023-01-01
"""
import datetime as dt
import os
import sys

import pandas as pd

import people_bq as P
import store as S

STORIES = """SELECT id post_id, title, url, text, `by` author, score points, descendants num_comments,
  UNIX_SECONDS(timestamp) created_at_i FROM `bigquery-public-data.hacker_news.full`
  WHERE type = 'story' AND timestamp >= TIMESTAMP('{a}') AND (dead IS NULL OR NOT dead) AND (deleted IS NULL OR NOT deleted)"""


def main(a):
    from auth import vertex_credentials
    from google.cloud import bigquery
    c = bigquery.Client(project="project-amer-scs-sandbox", credentials=vertex_credentials())
    gb = 0.0
    j = c.query(STORIES.format(a=a))
    s = j.result().to_dataframe()
    gb += (j.total_bytes_billed or 0) / 1e9
    s["day"] = pd.to_datetime(s.created_at_i, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    s.to_parquet(os.path.join(S.LOCAL, "bq_stories.parquet"), index=False)
    print("stories", len(s), s.day.min(), s.day.max(), flush=True)
    b = (dt.date.fromisoformat(a) - dt.timedelta(days=30)).isoformat()
    j = c.query(P.SQL.format(a=a, b=b))
    cm = j.result().to_dataframe()
    gb += (j.total_bytes_billed or 0) / 1e9
    cm.to_parquet(os.path.join(S.LOCAL, "bq_comments.parquet"), index=False)
    S.spend("hn_bigquery_history", gb / 1000 * 6.25, f"{gb:.1f} GB: {len(s)} stories, {len(cm)} comments since {a}")
    print("comments", len(cm), "people", cm.person.nunique(), f"{gb:.1f} GB", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
