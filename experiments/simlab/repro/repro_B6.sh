#!/bin/bash
# Bug sweep item 6 (orchestrator 18:35Z Nov 14): vm_writers/run.sh period_score builds cmd="a; b" and runs $cmd unquoted, so ';' is passed
# as an argument and the second command never runs. Dry run with stub python / gsutil that log their argv.
#   bash repro_B6.sh <run.sh>     exit 0 = fixed (each day runs exactly the expected period_score calls)
RUN=$(readlink -f "$1"); T=$(mktemp -d); mkdir -p $T/w/simlab $T/bin $T/assets/a2x; cp "$RUN" $T/w/run.sh; : > $T/assets/a2x/X.parquet; echo x > $T/assets/a2x/X.parquet
printf '#!/bin/bash\nexit 0\n' > $T/bin/gsutil; printf '#!/bin/bash\necho "$*" >> %s/calls\n' $T > $T/bin/python; chmod +x $T/bin/*
ok=1
check(){ d=$1; want=$2; : > $T/calls; PATH=$T/bin:$PATH ASSETS=$T/assets LOG=$T/log bash $T/w/run.sh period_score $d >/dev/null 2>&1; rc=$?
  got=$(cat $T/calls | tr '\n' '|'); [ "$got" = "$want" ] && [ $rc = 0 ] && r=PASS || { r=FAIL; ok=0; }; echo "$d rc=$rc calls=[$got] want=[$want] $r"; }
A=$T/assets
check 2026-11-29 "period_score.py week 2026-11-29 $A|"                                  # Sunday
check 2026-11-30 "period_score.py month 2026-11-30 $A|"                                 # month end, Monday
check 2026-05-31 "period_score.py week 2026-05-31 $A|period_score.py month 2026-05-31 $A|"  # Sunday month end
check 2026-11-18 ""                                                                      # neither
[ $ok = 1 ] && echo "B6 fixed: true" || echo "B6 fixed: false"; [ $ok = 1 ]
