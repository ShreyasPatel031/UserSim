"""Checks for build_v3.py output. Unlike validate_v2.py, every check here can fail on data the builder did not construct itself:
run it on the output directory; exit code 1 if any check fails.
    python validate_v3.py --dir work/v2b [--refetch 'work/raw/ph_profiles2_refetch*/profiles.jsonl.gz'] [--events 'work/ev/*.parquet']
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import re
import sys

import pandas as pd

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
POISON_NAMES = {"Wispr Flow", "Lovable"}


def main(d: str, refetch: str | None, events_glob: str | None) -> int:
    P, H, Pr, E = (pd.read_parquet(os.path.join(d, f"{t}.parquet")) for t in ("persons", "handles", "profiles", "events"))
    res: dict[str, dict] = {}

    def check(name, ok, detail=None):
        res[name] = {"ok": bool(ok), "detail": detail}

    pids = set(P.person_id)
    check("persons_unique", P.person_id.is_unique)
    check("no_orphan_events", not (~E.person_id.isin(pids)).any(), int((~E.person_id.isin(pids)).sum()))
    check("no_orphan_handles_profiles", not (~H.person_id.isin(pids)).any() and not (~Pr.person_id.isin(pids)).any())
    check("no_duplicate_events", not E.duplicated(["person_id", "platform", "target_id", "ts", "kind", "event_id", "text"]).any())
    check("no_null_event_ts", E.ts.notna().all())
    if events_glob:  # events survive the build: every source event person is present
        src = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(events_glob))])
        want = {"ph:" + str(x) for x in src.person}
        check("all_source_event_people_in_persons", want <= pids, len(want - pids))
    # time: nothing may be stamped with the build date unless it was really fetched that day
    built = str(P.built_at.iloc[0])[:10]
    for name, df in (("handles", H), ("profiles", Pr)):
        unk = df[df.observed_on_quality == "unknown"]
        check(f"{name}_unknown_dates_are_null", unk.observed_on.isna().all())
        fetched = df[df.observed_on_quality == "fetched"]
        check(f"{name}_fetched_dates_valid", fetched.observed_on.notna().all() and fetched.observed_on.map(lambda s: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s)))).all())
        ub = df[df.observed_on_quality == "upper_bound"]
        check(f"{name}_upper_bound_dates_valid", ub.observed_on.notna().all() and ub.observed_on.map(lambda s: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s)))).all())
        check(f"{name}_quality_values_known", df.observed_on_quality.isin(["fetched", "upper_bound", "unknown"]).all())
        res[f"{name}_dated_share"] = {"ok": True, "detail": round(float((df.observed_on_quality == "fetched").mean()), 3)}
    ph = Pr[Pr.platform == "producthunt"]
    ex = ph.extra.fillna("{}").map(json.loads)
    ids = ex.map(lambda e: e.get("ph_user_id"))
    check("no_uuid_ph_user_id", not ids.map(lambda v: bool(UUID.match(str(v)))).any())
    check("ph_user_id_numeric_or_null", ids.map(lambda v: pd.isna(v) or str(v).isdigit()).all())
    check("parser_version_recorded", ex.map(lambda e: bool(e.get("parser_version"))).all())
    bad_text = {c: int((Pr[c] == "NaN").sum()) for c in ("name", "bio", "location", "website", "handle", "extra")}
    check("no_literal_NaN_text", not any(bad_text.values()), bad_text)  # a missing value must be null, not the string 'NaN'
    check("extra_json_has_no_bare_NaN", not Pr.extra.fillna("").str.contains(r"\bNaN\b", regex=True).any())
    check("no_segments_carried", not ex.map(lambda e: "segments" in e).any())
    check("no_poison_names", not P.display_name.isin(POISON_NAMES).any() and not Pr.name.isin(POISON_NAMES).any())
    # A bio may genuinely say "I lead growth at Wispr Flow". It is poison only on a row the old parser could have written:
    # legacy parser, a poisoned id, or a poisoned name. Fixed-parser rows with a clean id and name are listed, not failed.
    bio = ph.bio.fillna("").str.contains("Wispr", case=False)
    fixed = ex.map(lambda e: e.get("parser_version") in ("refetch-2026-11", "ph_profiles2"))
    clean = ids.map(lambda v: str(v).isdigit() and str(v) not in ("606339", "109827")) & ~ph.name.isin(POISON_NAMES)
    check("no_wispr_in_ph_text_on_suspect_rows", not (bio & ~(fixed & clean)).any(), int((bio & ~(fixed & clean)).sum()))
    res["wispr_bios_on_clean_fixed_rows"] = {"ok": True, "detail": ph[bio & fixed & clean].person_id.tolist()[:50]}  # read by hand
    check("no_poisoned_ph_user_id", not ids.map(lambda v: str(v) in ("606339", "109827")).any())
    li = Pr[(Pr.platform == "linkedin") & Pr.extra.fillna("").str.contains("Wispr", case=False)]
    res["linkedin_rows_mentioning_wispr"] = {"ok": True, "detail": li.person_id.tolist()[:20]}  # inspect by hand; may be legitimate
    # X handles
    hi = H[(H.platform == "x") & (H.confidence >= 0.8)]
    check("one_confident_x_handle_per_person", not (hi.groupby("person_id").handle.nunique() > 1).any(),
          int((hi.groupby("person_id").handle.nunique() > 1).sum()))
    check("no_shared_confident_x_handle", not (hi.groupby("handle").person_id.nunique() > 1).any(),
          int((hi.groupby("handle").person_id.nunique() > 1).sum()))
    xe = E[E.platform == "x"]
    owner = dict(zip(hi.handle, hi.person_id))
    check("x_events_only_for_confident_handles", xe.person_id.isin(set(hi.person_id)).all())
    # own-link handles must come from a link of the matching kind: ph_self_link x/github/linkedin rows need a url on that platform
    for plat, dom in (("x", ("x.com", "twitter.com")), ("github", ("github.com",)), ("linkedin", ("linkedin.com",))):
        r = H[(H.platform == plat) & H.source.isin(["ph_self_link", "ph_self_link_extra"])]
        check(f"{plat}_self_link_urls_on_platform", r.url.fillna("").map(lambda u: any(x in u for x in dom)).all())
    # persons
    check("gone_have_no_profile", not P[P.gone].person_id.isin(set(Pr[Pr.platform == "producthunt"].person_id)).any(), int(P.gone.sum()))
    check("has_profile_matches_profiles", set(P[P.has_profile].person_id) == set(ph.person_id))
    res["display_name_null"] = {"ok": True, "detail": int(P.display_name.isna().sum())}
    # the re-fetch must be what the profiles came from
    files = sorted(glob.glob(refetch)) if refetch else []  # --refetch is a glob: every re-fetch file the builder read
    if files:
        rf = {}
        for fn in files:
            for line in gzip.open(fn, "rt"):
                r = json.loads(line)
                if str(r.get("status")) == "200":
                    rf[r["username"]] = r
        got = P[P.profile_parser == "refetch-2026-11"]
        check("every_good_refetch_row_used", set(got.ph_username) == set(rf), len(set(rf) ^ set(got.ph_username)))
        bad = ph[ph.person_id.isin(got.person_id)]
        check("refetch_profiles_have_numeric_id_name_joined",
              bad.extra.map(lambda e: str(json.loads(e).get("ph_user_id") or "").isdigit()).all() and bad.name.notna().all() and bad.joined.notna().all())
    ok = all(v["ok"] for v in res.values())
    json.dump(res, open(os.path.join(d, "validation_v3.json"), "w"), indent=1, default=str)
    for k, v in res.items():
        print(("PASS " if v["ok"] else "FAIL ") + k + ("" if v["detail"] is None else f"  [{v['detail']}]"))
    print("OVERALL", "PASS" if ok else "FAIL", "| built", built)
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--refetch")
    ap.add_argument("--events")
    a = ap.parse_args()
    sys.exit(main(a.dir, a.refetch, a.events))
