#!/bin/bash
# Build the E5 vm_writers tarball (orchestrator 18:37Z Nov 14, after the bug sweep found the tarball's writer copies lagging simlab/).
#   bash build.sh [--sync] [out.tgz]
# --sync copies simlab/<f>.py, the frozen report JSONs and pipeline/warehouse.py over the vm_writers copies first.
# GUARD: the build FAILS if any vm_writers/simlab/*.py, frozen report JSON or pipeline/warehouse.py differs from its source at build time,
# or if a writer imports a module the tarball does not carry. MANIFEST.md5 (md5 of every file) travels inside the tarball.
# Deterministic: same inputs -> same tarball md5 (sorted names, fixed mtime/owner, gzip -n).
set -euo pipefail; V="$(cd "$(dirname "$0")" && pwd)"; S="$(dirname "$V")"; P="$(dirname "$S")/pipeline"
SYNC=0; [ "${1:-}" = --sync ] && { SYNC=1; shift; }; OUT=$(readlink -f "${1:-$V/../e5_vm_writers.tgz}")
pairs() { for f in "$V"/simlab/*.py; do echo "$S/$(basename "$f") $f"; done
          (cd "$V/simlab" && find reports -name '*.json') | while read -r j; do echo "$S/$j $V/simlab/$j"; done
          echo "$P/warehouse.py $V/pipeline/warehouse.py"; }
if [ $SYNC = 1 ]; then pairs | while read -r a b; do cmp -s "$a" "$b" || { cp "$a" "$b"; echo "synced $(basename "$b")"; }; done; fi
bad=$(pairs | while read -r a b; do cmp -s "$a" "$b" || echo "${b#$V/}"; done)
[ -z "$bad" ] || { echo "BUILD FAIL: vm_writers copies differ from source: $bad (run with --sync)"; exit 1; }
miss=$(cd "$V/simlab" && python3 - <<'PY'
import ast, glob, os, sys
have = {os.path.basename(f)[:-3] for f in glob.glob("*.py")} | {"pipeline"}; std = set(sys.stdlib_module_names) | {"numpy", "pandas", "sklearn", "pyarrow", "duckdb"}
for f in sorted(glob.glob("*.py")):
    for n in ast.walk(ast.parse(open(f).read())):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module] if isinstance(n, ast.ImportFrom) and n.module else []
        for m in mods:
            if m.split(".")[0] not in have | std: print(f"{f}:{m}")
PY
)
[ -z "$miss" ] || { echo "BUILD FAIL: imports not in the tarball: $miss"; exit 1; }
bash -n "$V/run.sh"; T=$(mktemp -d); mkdir "$T/vm_writers"
(cd "$V" && find . -path ./build.sh -prune -o -name __pycache__ -prune -o -type f -print | grep -v '\.pyc$' | sort | while read -r f; do mkdir -p "$T/vm_writers/$(dirname "$f")"; cp "$f" "$T/vm_writers/$f"; done)
(cd "$T/vm_writers" && find . -type f ! -name MANIFEST.md5 | sort | xargs md5sum > MANIFEST.md5)
tar --sort=name --mtime='2026-01-01 00:00Z' --owner=0 --group=0 --numeric-owner -C "$T" -cf - vm_writers | gzip -n > "$OUT"
echo "built $OUT md5 $(md5sum < "$OUT" | cut -c1-32) files $(wc -l < "$T/vm_writers/MANIFEST.md5")"
