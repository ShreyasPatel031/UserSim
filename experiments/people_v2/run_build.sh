#!/bin/bash
# One reproducible people_v2 build. Local files only: reads WORKDIR, writes WORKDIR/OUTNAME; nothing is uploaded or deleted.
# usage: bash run_build.sh WORKDIR OUTNAME [PREV_BUILD_DIR]
#   WORKDIR must hold (same layout as the v3g run): raw/ph_profiles*.jsonl.gz, raw/ph_profiles2_refetch*/profiles.jsonl.gz, raw/x_people.jsonl.gz,
#   raw/x_posts.jsonl.gz, raw/profile_tabs.jsonl.gz, li/*, t/people*.parquet (all tables/people parts), ev/*.parquet, file_dates.json, x_lookup.json.
# Needs: python3 with pandas, pyarrow, pytest. Stops at the first failure (set -e); exit 2 = missing input, 1 = test/build/validation failure.
set -euo pipefail
W=${1:?workdir}; OUT=${2:?outname}; PREV=${3:-}; HERE=$(cd "$(dirname "$0")" && pwd)
cd "$W"
need() { [ -e "$1" ] || { echo "MISSING INPUT: $1" >&2; exit 2; }; }
for f in raw/ph_profiles.jsonl.gz raw/ph_profiles2.jsonl.gz raw/ph_profiles_rest.jsonl.gz raw/x_people.jsonl.gz raw/x_posts.jsonl.gz file_dates.json x_lookup.json ev; do need "$f"; done
compgen -G "raw/ph_profiles2_refetch*/profiles.jsonl*" >/dev/null || { echo "MISSING INPUT: raw/ph_profiles2_refetch*/profiles.jsonl*" >&2; exit 2; }
{ compgen -G "t/people*.parquet" || compgen -G "t/people/*.parquet"; } >/dev/null || { echo "MISSING INPUT: t/people*.parquet or t/people/*.parquet" >&2; exit 2; }
compgen -G "ev/*.parquet" >/dev/null || { echo "MISSING INPUT: ev/*.parquet" >&2; exit 2; }
echo "== inputs (name, bytes, sha256 of the X shards the builder reads)"; ls -l raw/x_people.jsonl.gz raw/x_posts.jsonl.gz x_lookup.json file_dates.json | awk '{print $5, $9}'
sha256sum raw/x_people.jsonl.gz raw/x_posts.jsonl.gz | cut -c1-16,65-
echo "== 1/5 tests"; if [ -n "${SKIP_TESTS:-}" ]; then echo "skipped (SKIP_TESTS set)"; else python3 -m pytest "$HERE/test_build_v3.py" -q; fi
echo "== 2/5 build (adopted flags: --x-fallback, name similarity >= 0.5)"
python3 "$HERE/build_v3.py" --root . --out "$OUT" --x-fallback --x-fallback-sim 0.5 --x-lookup x_lookup.json
echo "== 3/5 validate"
python3 "$HERE/validate_v3.py" --dir "$OUT" --refetch 'raw/ph_profiles2_refetch*/profiles.jsonl.gz' --events 'ev/*.parquet' | tee "$OUT/validate.log"
echo "== 4/5 promoted handles for hand review"
python3 "$HERE/promoted_margin.py" "$OUT" x_lookup.json > "$OUT/promoted_name_margin.csv"; wc -l < "$OUT/promoted_name_margin.csv"
if [ -n "$PREV" ]; then echo "== 5/5 compare with $PREV"; python3 "$HERE/compare_builds.py" "$PREV" "$OUT" | tee "$OUT/deltas.txt"; else echo "== 5/5 compare: skipped (no PREV_BUILD_DIR)"; fi
echo "DONE: $W/$OUT  (send back: build_report.json validation_v3.json validate.log deltas.txt promoted_name_margin.csv)"
