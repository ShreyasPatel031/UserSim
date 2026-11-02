"""Read-only verification of the PH re-fetch and tables_v2. Writes one JSON report and a few CSVs; changes nothing else.

Setup (read-only copies; nothing is written to the bucket):
    B=gs://usersim-bakeoff-347838016394/usersim_sim
    mkdir -p work/raw work/v2 work/refetch work/out
    gcloud storage cp "$B/raw/ph_profiles2.jsonl.gz" "$B/raw/ph_profiles_rest.jsonl.gz" "$B/raw/ph_profiles.jsonl.gz" work/raw/
    gcloud storage cp -r "$B/raw/ph_profiles2_refetch/*" work/refetch/
    gcloud storage cp -r "$B/tables_v2/*" work/v2/              # persons/handles/profiles/events .parquet
Run:
    python scripts/people_v2_checks.py --raw work/raw --refetch work/refetch --v2 work/v2 --out work/out
    gcloud storage cp work/out/* "$B/mailbox/from_grokbot/"      # results back to the mailbox

Needs pandas + pyarrow. Missing inputs are reported as {"skipped": ...}, not guessed.
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import os
import random
import re
from urllib.parse import unquote, urlparse

import pandas as pd

POISON_IDS = {"606339", "109827"}
POISON_NAMES = {"Wispr Flow", "Lovable"}
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def jl(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                pass


def load_dir(d):
    rows = []
    for fn in sorted(glob.glob(os.path.join(d, "**", "*.jsonl*"), recursive=True)):
        rows += [r | {"_file": os.path.basename(fn)} for r in jl(fn)]
    return rows


def pct(n, d):
    return round(100 * n / d, 2) if d else None


def slug_x(url):
    p = urlparse(url if "://" in (url or "") else "https://" + (url or ""))
    parts = [x for x in unquote(p.path).split("/") if x]
    if not any(h in p.netloc.lower() for h in ("twitter.com", "x.com")) or not parts:
        return None
    s = parts[0].lstrip("@").lower()
    return s if re.fullmatch(r"[a-z0-9_]{1,15}", s) else None


# ---------------------------------------------------------------- A. the re-fetch
def check_refetch(raw, refetch):
    out = {}
    new = load_dir(refetch)
    if not new:
        return {"skipped": f"no *.jsonl* files under {refetch}"}
    out["files"] = collections.Counter(r["_file"] for r in new)
    out["records"] = len(new)
    out["status_values"] = collections.Counter(str(r.get("status")) for r in new).most_common(10)
    by_user = collections.defaultdict(list)
    for r in new:
        if r.get("username"):
            by_user[r["username"]].append(r)
    out["unique_usernames"] = len(by_user)
    out["usernames_with_multiple_records"] = sum(len(v) > 1 for v in by_user.values())
    # coverage against the 16,528 people in ph_profiles_rest
    rest_path = os.path.join(raw, "ph_profiles_rest.jsonl.gz")
    if os.path.exists(rest_path):
        rest = {r["username"]: r for r in jl(rest_path) if r.get("username")}
        out["rest_people"] = len(rest)
        out["rest_missing_from_refetch"] = len(set(rest) - set(by_user))
        out["refetch_not_in_rest"] = len(set(by_user) - set(rest))
        out["missing_sample"] = sorted(set(rest) - set(by_user))[:15]
        # did the old parser get the non-poisoned fields right? (headline / followers / twitter agreement)
        agree = collections.Counter(); both = collections.Counter()
        for u, rs in by_user.items():
            o, n = rest.get(u), rs[-1]
            if not o:
                continue
            for k in ("headline", "followers", "followings", "twitter", "is_maker"):
                if o.get(k) is not None and n.get(k) is not None:
                    both[k] += 1
                    agree[k] += str(o[k]).lower() == str(n[k]).lower()
        out["old_vs_new_field_agreement_pct"] = {k: pct(agree[k], both[k]) for k in both}
        out["old_vs_new_pairs"] = dict(both)
    last = [v[-1] for v in by_user.values()]
    n = len(last)
    uid = [str(r.get("user_id") or "") for r in last]
    out["user_id"] = {"numeric": sum(u.isdigit() for u in uid), "uuid": sum(bool(UUID.match(u)) for u in uid),
                      "null": sum(u == "" for u in uid), "poison_ids": sum(u in POISON_IDS for u in uid)}
    out["name"] = {"null": sum(not r.get("name") for r in last),
                   "poison_names": sum(r.get("name") in POISON_NAMES for r in last),
                   "equals_username": sum((r.get("name") or "").lower() == (r.get("username") or "").lower() for r in last)}
    out["joined_null"] = sum(not r.get("joined") for r in last)
    out["joined_null_pct"] = pct(out["joined_null"], n)
    shared = collections.Counter(u for u in uid if u)
    out["user_ids_shared_by_multiple_usernames"] = {k: v for k, v in shared.items() if v > 1}  # poison signature
    out["parser_version_values"] = collections.Counter(str(r.get("parser_version") or r.get("parser")) for r in last).most_common(5)
    out["fetched_at_present_pct"] = pct(sum(bool(r.get("fetched_at") or r.get("observed_on")) for r in last), n)
    # cross-check against ph_profiles2 (already correct): same people must agree
    p2_path = os.path.join(raw, "ph_profiles2.jsonl.gz")
    if os.path.exists(p2_path):
        p2 = {r["username"]: r for r in jl(p2_path) if r.get("username")}
        common = [u for u in by_user if u in p2]
        out["overlap_with_ph_profiles2"] = len(common)
        out["overlap_name_user_id_agree_pct"] = pct(sum(by_user[u][-1].get("name") == p2[u].get("name") and
                                                       str(by_user[u][-1].get("user_id")) == str(p2[u].get("user_id")) for u in common), len(common))
    out["rows_failing_acceptance"] = sum(1 for r in last if not (str(r.get("user_id") or "").isdigit() and r.get("name")
                                                                 and r.get("joined") and r.get("name") not in POISON_NAMES))
    out["acceptance_rule"] = "numeric user_id AND non-empty name AND non-null joined AND name not Wispr Flow/Lovable"
    return out


# ---------------------------------------------------------------- B. tables_v2
def check_v2(v2, out_dir):
    try:
        P, H, Pr, E = (pd.read_parquet(os.path.join(v2, f"{t}.parquet")) for t in ("persons", "handles", "profiles", "events"))
    except Exception as exc:  # noqa: BLE001
        return {"skipped": repr(exc)[:200]}
    r = {"rows": {"persons": len(P), "handles": len(H), "profiles": len(Pr), "events": len(E)}}
    r["schema"] = {n: {c: str(t) for c, t in d.dtypes.items()} for n, d in (("persons", P), ("handles", H), ("profiles", Pr), ("events", E))}
    r["persons_unique"] = bool(P.person_id.is_unique)
    r["display_name_null"] = int(P.display_name.isna().sum())
    r["display_name_poisoned"] = int(P.display_name.isin(POISON_NAMES).sum())
    # keys / foreign keys
    pids = set(P.person_id)
    r["fk"] = {"handles_not_in_persons": int((~H.person_id.isin(pids)).sum()), "profiles_not_in_persons": int((~Pr.person_id.isin(pids)).sum()),
               "events_not_in_persons": int((~E.person_id.isin(pids)).sum())}
    r["events_dup_keys"] = int(E.duplicated(["person_id", "platform", "target_id", "ts", "kind", "event_id"]).sum())
    r["events_null_ts"] = int(E.ts.isna().sum())
    r["events_ts_range"] = {p: [str(g.ts.min()), str(g.ts.max())] for p, g in E.groupby("platform")}
    r["x_events_null_event_id"] = int(E[E.platform == "x"].event_id.isna().sum())
    # temporal: are facts dated by when they were read?
    r["observed_on_values"] = {"handles": H.observed_on.value_counts().head(5).to_dict(), "profiles": Pr.observed_on.value_counts().head(5).to_dict()}
    # ids
    ph = Pr[Pr.platform == "producthunt"]
    ids = ph.extra.map(lambda s: (json.loads(s).get("ph_user_id") if isinstance(s, str) else None))
    r["ph_user_id_format"] = {"null": int(ids.isna().sum()), "numeric": int(ids.map(lambda v: str(v).isdigit()).sum()),
                              "uuid": int(ids.map(lambda v: bool(UUID.match(str(v)))).sum())}
    # handles
    hi = H[H.confidence >= 0.8]
    x = hi[hi.platform == "x"]
    r["x_hi_conf"] = {"people": int(x.person_id.nunique()), "people_with_multiple": int((x.groupby("person_id").handle.nunique() > 1).sum()),
                      "handles_shared_by_multiple_people": int((x.groupby("handle").person_id.nunique() > 1).sum())}
    r["x_shared_handle_top"] = x.groupby("handle").person_id.nunique().sort_values(ascending=False).head(15).to_dict()
    r["handles_by_source"] = H.groupby(["platform", "source"]).confidence.agg(["count", "min", "max"]).reset_index().to_dict("records")
    conf = H[(H.source == "ph_twitter_field") & (H.confidence < 0.5)]
    r["x_conflicts_demoted"] = len(conf)
    gh = H[(H.platform == "github")]
    r["github_url_with_repo_path"] = int(gh.url.fillna("").map(lambda u: len([p for p in urlparse(u).path.split("/") if p]) > 1).sum())
    # Wispr/Lovable leakage anywhere
    for name, d, col in (("profiles_extra", Pr, "extra"), ("profiles_name", Pr, "name"), ("profiles_bio", Pr, "bio")):
        r[f"wispr_in_{name}"] = int(d[col].fillna("").str.contains("Wispr", case=False).sum())
    li = Pr[(Pr.platform == "linkedin") & Pr.extra.fillna("").str.contains("Wispr", case=False)]
    r["linkedin_rows_mentioning_wispr"] = li[["person_id", "source", "name"]].head(20).to_dict("records")
    seg = ph.extra.fillna("").map(lambda s: (json.loads(s).get("segments") if s else None))
    r["segments"] = {"present": int(seg.notna().sum()), "mentioning_wispr": int(seg.fillna("").astype(str).str.contains("Wispr", case=False).sum())}
    r["ph_extended_fields_people"] = int(ph.extra.fillna("").str.contains('"products_made": [0-9]').sum())
    # precision audit sample for hand labelling (seed fixed): X handle + what the person wrote about themselves
    random.seed(11)
    pick = random.sample(sorted(x.person_id.unique()), min(100, x.person_id.nunique()))
    rows = []
    for pid in pick:
        hs = x[x.person_id == pid]
        pr = ph[ph.person_id == pid]
        rows.append({"person_id": pid, "x_handle": ";".join(hs.handle), "source": ";".join(hs.source), "confidence": ";".join(hs.confidence.astype(str)),
                     "display_name": P.loc[P.person_id == pid, "display_name"].iloc[0], "ph_bio": (pr.bio.iloc[0] or "")[:200] if len(pr) else "",
                     "label_personal_or_company_or_wrong": ""})
    pd.DataFrame(rows).to_csv(os.path.join(out_dir, "x_handle_audit_100.csv"), index=False)
    r["audit_csv"] = "x_handle_audit_100.csv (100 rows; label_personal_or_company_or_wrong to be filled by a human)"
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="work/raw"); ap.add_argument("--refetch", default="work/refetch")
    ap.add_argument("--v2", default="work/v2"); ap.add_argument("--out", default="work/out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rep = {"refetch": check_refetch(a.raw, a.refetch), "tables_v2": check_v2(a.v2, a.out)}
    with open(os.path.join(a.out, "people_v2_checks.json"), "w") as f:
        json.dump(rep, f, indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
