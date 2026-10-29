"""Every comment since a date with its author, time and ROOT story (comments only name their parent, so the root is
found by walking parents up to 12 levels in BigQuery). Saved locally as Parquet (person-level, private) and to the
warehouse table hn_comments with role='crowd'.

    python people_bq.py 2025-02-01
"""
import os
import sys

import store as S

SQL = """
WITH c AS (SELECT id, parent, `by` person, UNIX_SECONDS(timestamp) t FROM `bigquery-public-data.hacker_news.full`
           WHERE type = 'comment' AND timestamp >= TIMESTAMP('{a}') AND `by` IS NOT NULL),
items AS (SELECT id, parent, type FROM `bigquery-public-data.hacker_news.full` WHERE timestamp >= TIMESTAMP('{b}')),
w AS (SELECT c.id, c.person, c.t, c.parent p0 FROM c)
SELECT w.id comment_id, w.person, w.t created_at_i,
  COALESCE(IF(i0.type='story', i0.id, NULL), IF(i1.type='story', i1.id, NULL), IF(i2.type='story', i2.id, NULL),
           IF(i3.type='story', i3.id, NULL), IF(i4.type='story', i4.id, NULL), IF(i5.type='story', i5.id, NULL),
           IF(i6.type='story', i6.id, NULL), IF(i7.type='story', i7.id, NULL), IF(i8.type='story', i8.id, NULL),
           IF(i9.type='story', i9.id, NULL), IF(i10.type='story', i10.id, NULL), IF(i11.type='story', i11.id, NULL)) story_id,
  IF(i0.type='story', 1, 0) top_level
FROM w
LEFT JOIN items i0 ON i0.id = w.p0  LEFT JOIN items i1 ON i1.id = i0.parent LEFT JOIN items i2 ON i2.id = i1.parent
LEFT JOIN items i3 ON i3.id = i2.parent LEFT JOIN items i4 ON i4.id = i3.parent LEFT JOIN items i5 ON i5.id = i4.parent
LEFT JOIN items i6 ON i6.id = i5.parent LEFT JOIN items i7 ON i7.id = i6.parent LEFT JOIN items i8 ON i8.id = i7.parent
LEFT JOIN items i9 ON i9.id = i8.parent LEFT JOIN items i10 ON i10.id = i9.parent LEFT JOIN items i11 ON i11.id = i10.parent"""


def main(a):
    from auth import vertex_credentials
    from google.cloud import bigquery
    import datetime as dt
    c = bigquery.Client(project="project-amer-scs-sandbox", credentials=vertex_credentials())
    b = (dt.date.fromisoformat(a) - dt.timedelta(days=30)).isoformat()   # stories a little older than the window
    dry = c.query(SQL.format(a=a, b=b), job_config=bigquery.QueryJobConfig(dry_run=True))
    print(f"will scan {dry.total_bytes_processed / 1e9:.1f} GB", flush=True)
    job = c.query(SQL.format(a=a, b=b))
    df = job.result().to_dataframe()
    gb = (job.total_bytes_billed or 0) / 1e9
    S.spend("hn_bigquery_crowd", gb / 1000 * 6.25, f"{gb:.1f} GB billed, {len(df)} comments with root story since {a}")
    out = os.path.join(S.LOCAL, "crowd_comments.parquet")
    df.to_parquet(out, index=False)
    S.write("hn_comments", df.assign(role="crowd", observed_on=S.now()))
    print(len(df), "comments,", df.person.nunique(), "people,", df.story_id.isna().mean().round(3), "no root;",
          f"{gb:.1f} GB billed")


if __name__ == "__main__":
    main(sys.argv[1])
