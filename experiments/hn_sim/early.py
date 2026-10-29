"""Early traction per story from the public BigQuery HN dataset: top-level comments (and distinct commenters) in the
first 15 / 30 / 60 minutes after posting. Comments are timestamped; votes are not, so this is the only historical
early-traction signal. Stored as hn_scores kind=early.

    python early.py 2025-02-01
"""
import sys

import pandas as pd

import store as S

SQL = """
WITH s AS (SELECT id, timestamp t FROM `bigquery-public-data.hacker_news.full`
           WHERE type = 'story' AND timestamp >= TIMESTAMP('{a}')),
c AS (SELECT parent, `by`, timestamp t FROM `bigquery-public-data.hacker_news.full`
      WHERE type = 'comment' AND timestamp >= TIMESTAMP('{a}') AND (deleted IS NULL OR NOT deleted))
SELECT s.id post_id,
  COUNTIF(c.t <= TIMESTAMP_ADD(s.t, INTERVAL 15 MINUTE)) c15,
  COUNTIF(c.t <= TIMESTAMP_ADD(s.t, INTERVAL 30 MINUTE)) c30,
  COUNTIF(c.t <= TIMESTAMP_ADD(s.t, INTERVAL 60 MINUTE)) c60,
  COUNT(DISTINCT IF(c.t <= TIMESTAMP_ADD(s.t, INTERVAL 60 MINUTE), c.`by`, NULL)) u60
FROM s LEFT JOIN c ON c.parent = s.id GROUP BY 1"""


def main(a):
    from auth import vertex_credentials
    from google.cloud import bigquery
    c = bigquery.Client(project="project-amer-scs-sandbox", credentials=vertex_credentials())
    job = c.query(SQL.format(a=a))
    df = job.result().to_dataframe()
    gb = (job.total_bytes_billed or 0) / 1e9
    usd = gb / 1000 * 6.25
    S.write("hn_scores", df.assign(kind="early", made_on=S.now()))
    S.spend("hn_bigquery_early", usd, f"{gb:.1f} GB billed, early comments for {len(df)} stories since {a}")
    print(len(df), "stories", f"{gb:.1f} GB ${usd:.3f}")


if __name__ == "__main__":
    main(sys.argv[1])
