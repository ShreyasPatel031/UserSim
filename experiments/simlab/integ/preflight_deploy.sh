#!/bin/bash
# Pre-flight of tonight's deploy scripts on a MOCK /home/agent/w inside this container (orchestrator 20:11Z Nov 14). Nothing touches the VM.
# Stubs: crontab (file), id (agent), date (FAKE_PT clock), sleep (fires the cron tick when TICK=1), gsutil (local mock bucket),
# /opt/exp/bin/python3 (real python for -c / ast; import gates and the today-rows test scripts succeed and print what deploy greps for).
#   bash preflight_deploy.sh <ph-ops checkout> <out log>
set -u; PH=$1; OUT=$2; PP=$PH/experiments/pipeline_patches; MB=/tmp/pf_mock; rm -rf $MB /home/agent/w; mkdir -p $MB/bin $MB/bucket /home/agent/w /opt/exp/bin
REALDATE=$(command -v date); REALPY=$(command -v python3)
cat > $MB/bin/crontab <<S
#!/bin/bash
f=$MB/crontab.txt; [ "\${1:-}" = -l ] && { [ -f \$f ] && cat \$f || exit 1; exit 0; }; cp "\$1" \$f
S
printf '#!/bin/bash\necho agent\n' > $MB/bin/id
cat > $MB/bin/date <<S
#!/bin/bash
# FAKE_PT=HHMM sets "now" to that Pacific time on 2026-11-14 (TZ honoured by the real date afterwards)
if [ -n "\${FAKE_PT:-}" ] && ! printf '%s\n' "\$@" | grep -q -- '^-d'; then e=\$(TZ=America/Los_Angeles $REALDATE -d "2026-11-14 \${FAKE_PT:0:2}:\${FAKE_PT:2:2}" +%s); exec $REALDATE -d @\$e "\$@"; fi
exec $REALDATE "\$@"
S
cat > $MB/bin/sleep <<S
#!/bin/bash
[ "\${TICK:-1}" = 1 ] && for d in /home/agent/w/tw12a /home/agent/w/tw; do [ -d \$d ] && echo "tick \$($REALDATE -u +%H:%M) PT" > \$d/last_tick; done; exit 0
S
cat > $MB/bin/gsutil <<S
#!/bin/bash
a=(); for x in "\$@"; do case \$x in -q|-m) ;; *) a+=("\$x");; esac; done
m() { echo "$MB/bucket/\${1#gs://usersim-bakeoff-347838016394/usersim_sim/}"; }
case "\${a[0]}" in cp) s=\${a[1]}; d=\${a[2]}; [[ \$s == gs://* ]] && { [ -f "\$(m \$s)" ] && cp "\$(m \$s)" "\$d"; exit \$?; }; mkdir -p "\$(dirname "\$(m \$d)")"; cp "\$s" "\$(m \$d)";; *) exit 0;; esac
S
cat > /opt/exp/bin/python3 <<S
#!/bin/bash
# real python for -c / ast checks; the import gates and the today-rows test scripts are stubbed to pass (they were exercised in A12 / A14)
case "\${1:-}" in -c) exec $REALPY "\$@";; esac
for x in "\$@"; do case \$x in *import_gate.py) echo "import gate: stub ok"; exit 0;; *test_today_rows.py) echo "features from \${PYTHONPATH%%:*}/features.py"; echo "TEST PASS (stub)"; exit \${TEST_RC:-0};; *dryrun_tonight.py) echo "dry run stub ok"; exit \${DRY_RC:-0};; esac; done
exec $REALPY "\$@"
S
chmod +x $MB/bin/* /opt/exp/bin/python3; export PATH=$MB/bin:/opt/exp/bin:$PATH
W=/home/agent/w; BASE="@reboot bash /home/agent/w/run_daily.sh
15 * * * * bash /home/agent/w/hourly.sh"
reset() { rm -rf $W; mkdir -p $W/experiments/ph_predict/data/today $W/experiments/pipeline $W/arm2_live; touch $W/experiments/ph_predict/data/today/2026-11-14.json
  printf 'def _snapshot(): pass\ndef pacific_day(): pass\n' > $W/experiments/pipeline/hourly.py; touch $W/experiments/pipeline/__init__.py; printf '%s\n' "$BASE" > $MB/crontab.txt; }
say() { echo "$*" | tee -a $OUT; }
: > $OUT
md5c() { md5sum < $MB/crontab.txt | cut -c1-8; }
# ===================== deploy_b12a.sh (12a.2) =====================
S12=$PP/20261114_two_predictions_12a2; D12=$S12/deploy_b12a.sh
reset; c0=$(md5c)
FAKE_PT=0030 bash $D12 $S12 > $MB/l 2>&1; say "b12a: deploy at 00:30 PT -> rc=$? '$(tail -1 $MB/l)'; crontab unchanged: $([ $(md5c) = $c0 ] && echo yes || echo NO)"
FAKE_PT=2200 bash $D12 $S12 > $MB/l 2>&1; say "b12a: deploy at 22:00 PT -> rc=$? '$(tail -1 $MB/l)'"; c1=$(md5c); say "  crontab: $(grep -c usersim-b12a $MB/crontab.txt) marker lines; base kept: $(grep -c run_daily $MB/crontab.txt)"
FAKE_PT=2210 bash $D12 $S12 > $MB/l 2>&1; say "b12a: deploy twice -> rc=$? crontab same as after first: $([ $(md5c) = $c1 ] && echo yes || echo NO); prev tree kept: $(ls $W/backup_b12a | grep -c tw12a.prev)"
FAKE_PT=0030 bash $D12 rollback > $MB/l 2>&1; say "b12a: rollback at 00:30 PT -> rc=$? crontab byte-identical to pre-deploy: $([ $(md5c) = $c0 ] && echo yes || echo NO); tw12a removed: $([ -d $W/tw12a ] && echo NO || echo yes)"
reset; printf '%s\n# BEGIN usersim-b12\n* * * * * bash /home/agent/w/tw/tick12.sh\n# END usersim-b12\n' "$BASE" > $MB/crontab.txt; cb=$(md5c)
FAKE_PT=2200 bash $D12 $S12 > /dev/null 2>&1; FAKE_PT=2205 bash $D12 rollback > /dev/null 2>&1; say "b12a: with b12's block present, deploy+rollback leaves b12's block byte-identical: $([ $(md5c) = $cb ] && echo yes || echo NO)"
reset; cp -r $S12 $MB/bad; echo "# x" >> $MB/bad/two_predictions.py; FAKE_PT=2200 bash $D12 $MB/bad > $MB/l 2>&1; say "b12a: wrong two_predictions md5 -> rc=$? '$(tail -1 $MB/l)'; crontab untouched: $(grep -c usersim-b12a $MB/crontab.txt)=0 markers"
reset; FAKE_PT=2200 TICK=0 bash $D12 $S12 > $MB/l 2>&1; say "b12a: cron never ticks -> rc=$? '$(tail -2 $MB/l | head -1)'; block left: $(grep -c usersim-b12a $MB/crontab.txt) markers; tw12a: $([ -d $W/tw12a ] && echo present || echo moved)"
reset; : > $MB/crontab.txt; FAKE_PT=2200 bash $D12 $S12 > $MB/l 2>&1; say "b12a: empty crontab -> rc=$? '$(tail -1 $MB/l)'"
# kill points: (k1) after the old tree is moved away, before the new one is in place
reset; FAKE_PT=2200 bash $D12 $S12 > /dev/null 2>&1; sed 's#^mv \$N \$T$#kill -9 $$#' $D12 > $MB/d_k1.sh; FAKE_PT=2210 bash $MB/d_k1.sh $S12 > /dev/null 2>&1
say "b12a: killed between 'mv tw12a -> backup' and 'mv stage -> tw12a' -> tw12a present: $([ -d $W/tw12a ] && echo yes || echo NO); cron block still points at it: $(grep -c tw12a/tick.sh $MB/crontab.txt); rerun repairs: $(FAKE_PT=2215 bash $D12 $S12 > /dev/null 2>&1 && [ -d $W/tw12a ] && echo yes || echo NO)"
# ===================== deploy_today_rows.sh =====================
DT=$PP/20261114_today_rows/deploy_today_rows.sh; OLDF=$(dirname $PH)/a2rb/code/features.py; NEWF=$PP/20261114_today_rows/features.py
tr_reset() { reset; cp $OLDF $W/experiments/ph_predict/features.py; mkdir -p $W/today_rows.new; cp $NEWF $PP/20261114_today_rows/{test_today_rows.py,dryrun_tonight.py,import_gate.py,deploy_today_rows.sh} $W/today_rows.new/; touch $W/experiments/ph_predict/forecast.py $W/arm2_live/h25_live.py; }
m8() { md5sum < "$1" | cut -c1-8; }
tr_reset; FAKE_PT=0030 bash $DT deploy > $MB/l 2>&1; say "today_rows: deploy at 00:30 PT -> rc=$? '$(tail -1 $MB/l)'"
tr_reset; FAKE_PT=0030 bash $DT check > $MB/l 2>&1; say "today_rows: check at 00:30 PT -> rc=$? '$(tail -1 $MB/l)' live features $(m8 $W/experiments/ph_predict/features.py)"
tr_reset; FAKE_PT=2200 bash $DT deploy > $MB/l 2>&1; say "today_rows: deploy at 22:00 PT -> rc=$? live features $(m8 $W/experiments/ph_predict/features.py) '$(tail -1 $MB/l | cut -c1-90)'"
FAKE_PT=2205 bash $DT deploy > $MB/l 2>&1; say "today_rows: deploy twice -> rc=$? '$(tail -1 $MB/l)'"
FAKE_PT=0030 bash $DT rollback > $MB/l 2>&1; say "today_rows: rollback at 00:30 PT -> rc=$? live features byte-identical to the original: $(cmp -s $OLDF $W/experiments/ph_predict/features.py && echo yes || echo NO)"
tr_reset; FAKE_PT=2200 DRY_RC=1 bash $DT deploy > $MB/l 2>&1; say "today_rows: post-install dry run fails -> rc=$? auto-rollback: live features $(m8 $W/experiments/ph_predict/features.py)"
tr_reset; FAKE_PT=2200 TEST_RC=1 bash $DT deploy > $MB/l 2>&1; say "today_rows: staged test fails -> rc=$? live untouched: $(m8 $W/experiments/ph_predict/features.py); backup made: $([ -f $W/backup_today_rows/features.py ] && echo yes || echo no)"
tr_reset; echo "# drift" >> $W/experiments/ph_predict/features.py; FAKE_PT=2200 bash $DT deploy > $MB/l 2>&1; say "today_rows: live features not 981c5ded -> rc=$? '$(tail -1 $MB/l | cut -c1-80)'"
tr_reset; rm -rf $W/backup_today_rows; FAKE_PT=2200 bash $DT rollback > $MB/l 2>&1; say "today_rows: rollback with no backup -> rc=$? '$(tail -1 $MB/l)'"
tr_reset; sed 's#^cp \$N/features.py \$P/features.py.new && mv \$P/features.py.new \$P/features.py$#cp $N/features.py $P/features.py.new \&\& kill -9 $$#' $DT > $MB/t_k1.sh; FAKE_PT=2200 bash $MB/t_k1.sh deploy > /dev/null 2>&1
say "today_rows: killed after copying features.py.new, before the rename -> live $(m8 $W/experiments/ph_predict/features.py) (old=981c5ded), leftover .new: $([ -f $W/experiments/ph_predict/features.py.new ] && echo yes || echo no); rerun: $(FAKE_PT=2205 bash $DT deploy > /dev/null 2>&1; m8 $W/experiments/ph_predict/features.py)"
tr_reset; sed 's#^echo "installed \$NEW#kill -9 $$; echo "installed $NEW#' $DT > $MB/t_k2.sh; FAKE_PT=2200 bash $MB/t_k2.sh deploy > /dev/null 2>&1
say "today_rows: killed right after the install, before post-install checks -> live $(m8 $W/experiments/ph_predict/features.py) (installed, untested on the live path, no auto-rollback); rerun says: '$(FAKE_PT=2205 bash $DT deploy 2>&1 | tail -1 | cut -c1-70)'"
# ===================== deploy_b12.sh: guard, md5 pins, crontab, rollback (import gates stubbed) =====================
DB=$PP/20261114_timed_writes/deploy_b12.sh; say "b12: pinned vm_writers md5 in the script: $(grep -o 'E5W_MD5=[0-9a-f]*' $DB); tarball path: $(grep -o 'tmp/e5/vm_writers/[a-z_0-9.]*tgz' $DB | head -1)"
reset; c0=$(md5c); FAKE_PT=0030 bash $DB rollback > $MB/l 2>&1; say "b12: rollback inside the window -> rc=$? '$(tail -1 $MB/l)'; crontab identical: $([ $(md5c) = $c0 ] && echo yes || echo NO)"
reset; FAKE_PT=0030 bash $DB abc123 deadbeef > $MB/l 2>&1; say "b12: deploy at 00:30 PT -> rc=$? '$(tail -1 $MB/l)'"
reset; FAKE_PT=2200 bash $DB abc123 deadbeef > $MB/l 2>&1; say "b12: deploy with no tw_code tarball in the bucket -> rc=$? '$(tail -1 $MB/l | cut -c1-90)'; crontab untouched: $([ $(md5c) = $c0 ] && echo yes || echo NO)"
echo done >> $OUT
