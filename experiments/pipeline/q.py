"""Query the warehouse from the command line.
usage: python -m pipeline.q "SELECT kind, count(*) AS n FROM events GROUP BY 1"
       python -m pipeline.q --tables          (list tables and row counts)
       python -m pipeline.q --no-sync "..."   (skip pulling new parts from Cloud Storage)"""
import sys
import pandas as pd
from . import warehouse as W

if __name__ == "__main__":
    args = sys.argv[1:]
    sync = "--no-sync" not in args; args = [a for a in args if a != "--no-sync"]
    con = W.connect(sync)
    pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30); pd.set_option("display.max_colwidth", 60)
    if not args or args[0] == "--tables":
        for (t,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
            print(f"{t:18s} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>10,}")
    else:
        print(con.execute(" ".join(args)).df().to_string(index=False))
