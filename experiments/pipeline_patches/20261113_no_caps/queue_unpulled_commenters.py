"""Bundle 11, one-off: commenters in the warehouse comments table who have never been pulled into the people store
(store_v3 persons, matched on the salted id) go to the durable pull queue raw/requests/pipeline/new_commenters/pending.txt
(handles live in the bucket only). Prints counts only; the salt is read only to hash, never printed.
usage (from experiments/): python -m pipeline.queue_unpulled_commenters [--write]"""
import hashlib, subprocess, sys, tempfile
import pandas as pd
from . import warehouse as W
from .daily import queue_read, queue_write
B = "gs://usersim-bakeoff-347838016394/usersim_sim"


def main(write):
    d = tempfile.mkdtemp()
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/population/store_v3/persons.parquet", f"{d}/p.parquet"], check=True)
    salt = subprocess.run(["gsutil", "-q", "cat", f"{B}/raw/population/_salt"], capture_output=True, text=True, check=True).stdout.strip()
    have = set(pd.read_parquet(f"{d}/p.parquet", columns=["person_id"]).person_id)
    h = lambda u: "p_" + hashlib.sha256((salt + "producthunt:" + u.lower()).encode()).hexdigest()[:16]
    people = W.query("SELECT DISTINCT person FROM comments", do_sync=True).person.dropna().str.lower().unique()
    miss = sorted(u for u in people if h(u) not in have)
    print({"commenters": len(people), "never_pulled": len(miss)})
    if write:
        print({"queued_total": queue_write("new_commenters", queue_read("new_commenters") + miss, False)})


if __name__ == "__main__":
    main("--write" in sys.argv)
