"""Who replied to whom: every comment since A with the author of its parent (story or comment), from BigQuery
hacker_news.full. Person-level; stays in the private cache. Cost measured from bytes billed and logged.
-> <cache>/replies.parquet {comment_id, person, t, parent_author}

    python replies_bq.py [a=2025-01-01]
"""
import os
import sys

import store as S

SQL = """
SELECT c.id comment_id, c.`by` person, UNIX_SECONDS(c.timestamp) t, p.`by` parent_author
FROM `bigquery-public-data.hacker_news.full` c
JOIN `bigquery-public-data.hacker_news.full` p ON p.id = c.parent
WHERE c.type = 'comment' AND c.timestamp >= TIMESTAMP('{a}') AND c.`by` IS NOT NULL AND p.`by` IS NOT NULL
  AND p.timestamp >= TIMESTAMP_SUB(TIMESTAMP('{a}'), INTERVAL 30 DAY)"""


def main(a="2025-01-01"):
    from auth import vertex_credentials
    from google.cloud import bigquery
    c = bigquery.Client(project="project-amer-scs-sandbox", credentials=vertex_credentials())
    dry = c.query(SQL.format(a=a), job_config=bigquery.QueryJobConfig(dry_run=True))
    print(f"will scan {dry.total_bytes_processed / 1e9:.1f} GB", flush=True)
    job = c.query(SQL.format(a=a))
    df = job.result().to_dataframe()
    gb = (job.total_bytes_billed or 0) / 1e9
    S.spend("hn_bigquery_replies", gb / 1000 * 6.25, f"{gb:.1f} GB billed, {len(df)} replies since {a}")
    df.to_parquet(os.path.join(S.LOCAL, "replies.parquet"), index=False)
    print(len(df), "comments with parent author;", df.person.nunique(), "people;", f"{gb:.1f} GB billed")


if __name__ == "__main__":
    main(*sys.argv[1:])
