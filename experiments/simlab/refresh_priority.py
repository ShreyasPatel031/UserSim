"""Write a day's listed people (frozen CF-only list) as a re-read priority list for the fleet (orchestrator 18:07Z Nov 16).
The store holds no handles and the person-id salt is off limits here, so this writes salted person ids and PH user ids only, to a private
bucket path; the population agent maps them to fleet handles. Nothing is written to the repo.
    python refresh_priority.py <store dir> <scratchpad> <day> [...]  -> gs://.../tmp/e5/private/refresh_priority/<day>.tsv"""
import os, subprocess, sys, pandas as pd
ST, SP = sys.argv[1:3]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "ph_user_id"]).drop_duplicates("person_id").set_index("person_id").ph_user_id
os.makedirs(f"{SP}/refresh_priority", exist_ok=True)
for D in sys.argv[3:]:
    F = pd.read_parquet(f"{SP}/bp/backer_arms_{D}.parquet"); F = F[F.arm == "CF-only"]
    o = F.groupby("person_id").p.max().sort_values(ascending=False).reset_index(); o["ph_user_id"] = o.person_id.map(P)
    p = f"{SP}/refresh_priority/{D}.tsv"; o[["person_id", "ph_user_id"]].to_csv(p, sep="\t", index=False)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/private/refresh_priority/{D}.tsv"], check=True)
    print(D, "people", len(o), "with ph_user_id", int(o.ph_user_id.notna().sum()))
