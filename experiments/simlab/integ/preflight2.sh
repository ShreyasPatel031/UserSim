#!/bin/bash
# Pre-flight round 2 (orchestrator 20:31Z Nov 14): PH ops' revised scripts on a MOCK /home/agent/w (container only, nothing on the VM).
#   deploy_today_rows.sh cc69181a, deploy_b12a.sh 12a.2 0a139f70 / 12a.3 adbc3aa5, install_fixedprior_weights.sh 512891ec, deploy_b12.sh (12_3)
# Stubs: crontab file, id ($FAKE_USER, default agent), date ($FAKE_PT = PT HHMM on 2026-11-14), sleep (fires the tick), gsutil (mock bucket:
# cp/cat/stat/rm), /opt/exp/bin/python3 (real python for -c; import gates + today-rows test scripts pass unless TEST_RC / DRY_RC set).
#   bash preflight2.sh <ph-ops checkout> <out log>
set -u; PH=$1; OUT=$2; PP=$PH/experiments/pipeline_patches; MB=/tmp/pf2_mock; rm -rf $MB /home/agent/w; mkdir -p $MB/bin $MB/bucket /home/agent/w /opt/exp/bin
REALDATE=$(command -v date); REALPY=$(command -v python3)
cat > $MB/bin/crontab <<S
#!/bin/bash
f=$MB/crontab.txt; [ "\${1:-}" = -l ] && { [ -f \$f ] && cat \$f || exit 1; exit 0; }; cp "\$1" \$f
S
printf '#!/bin/bash\necho ${FAKE_USER:-agent}\n' > $MB/bin/id
cat > $MB/bin/date <<S
#!/bin/bash
if [ -n "\${FAKE_PT:-}" ] && ! printf '%s\n' "\$@" | grep -q -- '^-d'; then e=\$(TZ=America/Los_Angeles $REALDATE -d "2026-11-14 \${FAKE_PT:0:2}:\${FAKE_PT:2:2}" +%s); exec $REALDATE -d @\$e "\$@"; fi
if [ -n "\${FAKE_PT:-}" ] && printf '%s\n' "\$@" | grep -qx tomorrow; then exec $REALDATE -d "2026-11-15" +%F; fi
exec $REALDATE "\$@"
S
cat > $MB/bin/sleep <<S
#!/bin/bash
[ "\${TICK:-1}" = 1 ] && for d in /home/agent/w/tw12a /home/agent/w/tw; do [ -d \$d ] && echo "tick" > \$d/last_tick; done; exit 0
S
cat > $MB/bin/gsutil <<S
#!/bin/bash
a=(); for x in "\$@"; do case \$x in -q|-m) ;; *) a+=("\$x");; esac; done
m() { echo "$MB/bucket/\${1#gs://usersim-bakeoff-347838016394/usersim_sim/}"; }
case "\${a[0]}" in
 cp) s=\${a[1]}; d=\${a[2]}; [[ \$s == gs://* ]] && { [ -f "\$(m \$s)" ] && cp "\$(m \$s)" "\$d"; exit \$?; }; mkdir -p "\$(dirname "\$(m \$d)")"; cp "\$s" "\$(m \$d)";;
 cat) [ -f "\$(m \${a[1]})" ] && cat "\$(m \${a[1]})";; stat) [ -f "\$(m \${a[1]})" ];; rm) rm -f "\$(m \${a[1]})";; *) exit 0;; esac
S
cat > /opt/exp/bin/python3 <<S
#!/bin/bash
case "\${1:-}" in -c) exec $REALPY "\$@";; esac
for x in "\$@"; do case \$x in *import_gate.py) echo "import gate: stub ok"; exit 0;; *test_today_rows.py) echo "features from \${PYTHONPATH%%:*}/features.py"; exit \${TEST_RC:-0};; *dryrun_tonight.py) echo "dry run stub ok"; exit \${DRY_RC:-0};; esac; done
exec $REALPY "\$@"
S
chmod +x $MB/bin/* /opt/exp/bin/python3; export PATH=$MB/bin:/opt/exp/bin:$PATH
W=/home/agent/w; BASE="@reboot bash /home/agent/w/run_daily.sh"
say() { echo "$*" | tee -a $OUT; }; : > $OUT; m8() { md5sum < "$1" | cut -c1-8; }; md5c() { md5sum < $MB/crontab.txt | cut -c1-8; }
base() { rm -rf $W $MB/bucket; mkdir -p $W/experiments/ph_predict/data/today $W/experiments/pipeline $W/arm2_live $MB/bucket; touch $W/experiments/ph_predict/data/today/2026-11-14.json
  printf 'def _snapshot(): pass\ndef pacific_day(): pass\n' > $W/experiments/pipeline/hourly.py; touch $W/experiments/pipeline/__init__.py; printf '%s\n' "$BASE" > $MB/crontab.txt
  touch $W/experiments/ph_predict/forecast.py $W/arm2_live/h25_live.py; }
# ---------------- today-rows (cc69181a) ----------------
TRD=$PP/20261114_today_rows; DT=$TRD/deploy_today_rows.sh; OLDF=$(dirname $PH)/a2rb/code/features.py
trset() { base; cp $OLDF $W/experiments/ph_predict/features.py; mkdir -p $W/today_rows.new; cp $TRD/{features.py,test_today_rows.py,dryrun_tonight.py,import_gate.py,deploy_today_rows.sh} $W/today_rows.new/; }
live() { m8 $W/experiments/ph_predict/features.py; }; mk() { [ -s $W/today_rows_fix.json ] && echo "local:$(cat $W/today_rows_fix.json | $REALPY -c 'import json,sys;print(json.load(sys.stdin)["fixed_from"])')" || echo local:none; [ -f $MB/bucket/results/web/today_rows_fix.json ] && echo bucket:yes || echo bucket:none; }
say "== today-rows $(m8 $DT)"
for t in 2329 2330 0004 0030 0059 0100; do trset; FAKE_PT=$t bash $DT deploy > $MB/l 2>&1; say "deploy at $t PT -> rc=$? live $(live) | $(tail -1 $MB/l | cut -c1-60)"; done
trset; FAKE_USER=root FAKE_PT=2200 bash $DT deploy > $MB/l 2>&1; say "deploy as root -> rc=$? '$(tail -1 $MB/l)'"
trset; FAKE_PT=2200 bash $DT deploy > $MB/l 2>&1; say "deploy 22:00 -> rc=$? live $(live) state '$(cut -c1-8 $W/today_rows_state)' marker $(mk | tr '\n' ' ')"
FAKE_PT=2205 bash $DT deploy > $MB/l 2>&1; say "deploy again -> rc=$? '$(tail -1 $MB/l | cut -c1-70)'"
FAKE_PT=0030 bash $DT rollback > $MB/l 2>&1; say "rollback at 00:30 -> rc=$? live byte-identical: $(cmp -s $OLDF $W/experiments/ph_predict/features.py && echo yes || echo NO); marker $(mk | tr '\n' ' ') state '$(cut -c1-11 $W/today_rows_state)'"
trset; FAKE_PT=2200 DRY_RC=1 bash $DT deploy > $MB/l 2>&1; say "post-install dry run fails -> rc=$? live $(live) marker $(mk | tr '\n' ' ') state '$(cut -c1-11 $W/today_rows_state)'"
trset; sed 's#^echo "installed \$NEW#kill -9 $$; echo "installed $NEW#' $DT > $MB/k.sh; FAKE_PT=2200 bash $MB/k.sh deploy > /dev/null 2>&1
say "killed after install, before checks -> live $(live) state '$(cut -c1-20 $W/today_rows_state)' marker $(mk | head -1)"; FAKE_PT=2210 bash $DT deploy > $MB/l 2>&1
say "  rerun deploy -> rc=$? '$(grep -m1 resuming $MB/l | cut -c1-40)' live $(live) state '$(cut -c1-8 $W/today_rows_state)' marker $(mk | tr '\n' ' ')"
trset; sed 's#^cp \$N/features.py \$P/features.py.new && mv \$P/features.py.new \$P/features.py$#cp $N/features.py $P/features.py.new \&\& kill -9 $$#' $DT > $MB/k2.sh; FAKE_PT=2200 bash $MB/k2.sh deploy > /dev/null 2>&1
say "killed after state file, before rename -> live $(live) state '$(cut -c1-20 $W/today_rows_state)'"; FAKE_PT=2210 bash $DT deploy > $MB/l 2>&1; say "  rerun deploy -> rc=$? live $(live) state '$(cut -c1-8 $W/today_rows_state)'"
trset; FAKE_PT=2200 bash $DT deploy > /dev/null 2>&1; sed 's#^post_checks$#kill -9 $$#' $DT > $MB/k3.sh
trset; sed -i 's/^\(  write_marker \$W\/today_rows_fix.json \$GSM;\)/  kill -9 $$; \1/' $MB/k3.sh 2>/dev/null; FAKE_PT=2200 bash $MB/k3.sh deploy > /dev/null 2>&1; say "killed after checks passed, before marker -> live $(live) state '$(cut -c1-20 $W/today_rows_state)' marker $(mk | head -1)"; FAKE_PT=2210 bash $DT deploy > $MB/l 2>&1; say "  rerun deploy -> rc=$? state '$(cut -c1-8 $W/today_rows_state)' marker $(mk | head -1)"
trset; FAKE_PT=1400 bash $DT check > $MB/l 2>&1; say "check -> rc=$? '$(grep 'marker test' $MB/l | tr '\n' ' ' | cut -c1-120)' live $(live) real marker $(mk | head -1)"
# ---------------- 12a.2 / 12a.3 flips, fixed-prior installer ----------------
S2=$PP/20261114_two_predictions_12a2; S3=$PP/20261114_two_predictions_12a3; say "== 12a.2 deploy $(m8 $S2/deploy_b12a.sh), 12a.3 deploy $(m8 $S3/deploy_b12a.sh), installer $(m8 $S3/install_fixedprior_weights.sh)"
wt() { m8 $W/tw12a/hybrid_vmonly_P345_20261114.json 2>/dev/null || echo none; }; tp() { m8 $W/tw12a/two_predictions.py 2>/dev/null || echo none; }
base; c0=$(md5c); FAKE_PT=0030 bash $S2/deploy_b12a.sh $S2 > $MB/l 2>&1; say "12a.2 at 00:30 -> rc=$? '$(tail -1 $MB/l)'"
FAKE_PT=2200 bash $S3/deploy_b12a.sh $S3 > $MB/l 2>&1; say "12a.3 without the today-rows marker -> rc=$? '$(tail -1 $MB/l | cut -c1-80)'"
FAKE_PT=2200 bash $S3/install_fixedprior_weights.sh $S3 > $MB/l 2>&1; say "installer without marker -> rc=$? '$(tail -1 $MB/l | cut -c1-80)'"
FAKE_USER=root FAKE_PT=2200 bash $S3/install_fixedprior_weights.sh $S3 > $MB/l 2>&1; say "installer as root -> rc=$? '$(tail -1 $MB/l)'"
FAKE_PT=2200 bash $S2/deploy_b12a.sh $S2 > $MB/l 2>&1; c1=$(md5c); say "A: 12a.2 deploy -> rc=$? tw12a -> $(readlink $W/tw12a | xargs basename) two_predictions $(tp) weights $(wt) block lines $(grep -c usersim-b12a $MB/crontab.txt)"
echo '{"fixed_from": "2026-11-15"}' > $W/today_rows_fix.json
cp -r $S3 $MB/bad3; echo '{}' > $MB/bad3/hybrid_vmonly_P345_20261114.json; FAKE_PT=2205 bash $S3/install_fixedprior_weights.sh $MB/bad3 > $MB/l 2>&1; say "installer with wrong weights file -> rc=$? '$(tail -1 $MB/l)'"
FAKE_PT=2210 bash $S3/install_fixedprior_weights.sh $S3 > $MB/l 2>&1; say "B: installer (12a.3) -> rc=$? tw12a -> $(readlink $W/tw12a | xargs basename) two_predictions $(tp) weights $(wt) pin $(cat $W/tw12a.d/weights_pin 2>/dev/null) crontab same as A: $([ $(md5c) = $c1 ] && echo yes || echo NO)"
FAKE_PT=2215 bash $S2/deploy_b12a.sh $S2 > $MB/l 2>&1; say "12a.2 redeploy with the pin live -> rc=$? '$(tail -1 $MB/l | cut -c1-90)' weights still $(wt)"
FAKE_PT=0030 bash $S3/deploy_b12a.sh rollback > $MB/l 2>&1; say "rollback B -> A at 00:30 -> rc=$? tw12a two_predictions $(tp) weights $(wt) block kept: $(grep -c usersim-b12a $MB/crontab.txt) | pin left: $(cat $W/tw12a.d/weights_pin 2>/dev/null || echo none)"
FAKE_PT=0035 bash $S3/deploy_b12a.sh rollback > $MB/l 2>&1; say "second rollback -> rc=$? '$(tail -1 $MB/l | cut -c1-70)' tw12a: $([ -e $W/tw12a ] && echo present || echo gone) block lines $(grep -c usersim-b12a $MB/crontab.txt) crontab == pre-12a: $([ $(md5c) = $c0 ] && echo yes || echo NO)"
# kill between staging and the flip; kill right after the flip
base; FAKE_PT=2200 bash $S2/deploy_b12a.sh $S2 > /dev/null 2>&1; echo '{"fixed_from": "2026-11-15"}' > $W/today_rows_fix.json
sed 's#^flip \$N$#kill -9 $$#' $S3/deploy_b12a.sh > $S3/k.sh; FAKE_PT=2205 bash $S3/k.sh $S3 > /dev/null 2>&1; say "12a.3 killed before the flip -> live two_predictions $(tp) (12a.2 b31d0074), weights $(wt)"; rm -f $S3/k.sh
sed 's#^flip \$N$#flip $N; kill -9 $$#' $S3/deploy_b12a.sh > $S3/k.sh; FAKE_PT=2210 bash $S3/k.sh $S3 > /dev/null 2>&1; say "12a.3 killed right after the flip -> live two_predictions $(tp), weights $(wt), block lines $(grep -c usersim-b12a $MB/crontab.txt), pin $(cat $W/tw12a.d/weights_pin 2>/dev/null || echo none)"; rm -f $S3/k.sh
sed 's#^mkdir -p \$W/tw12a.d && echo b8a59cdd#kill -9 $$; mkdir -p $W/tw12a.d \&\& echo b8a59cdd#' $S3/install_fixedprior_weights.sh > $S3/ki.sh; base; FAKE_PT=2200 bash $S2/deploy_b12a.sh $S2 > /dev/null 2>&1; echo '{"fixed_from": "2026-11-15"}' > $W/today_rows_fix.json
FAKE_PT=2205 bash $S3/ki.sh $S3 > /dev/null 2>&1; FAKE_PT=2210 bash $S2/deploy_b12a.sh $S2 > $MB/l 2>&1; say "installer killed after the deploy, before the pin; then 12a.2 redeploy -> rc=$? weights now $(wt) (b8a59cdd = fixed prior kept, 16912cd6 = silently reverted)"; rm -f $S3/ki.sh
# ---------------- deploy_b12.sh (12_3) ----------------
DB=$PP/20261114_timed_writes_12_3/deploy_b12.sh; say "== deploy_b12 $(m8 $DB): pins $(grep -o 'E5W_MD5=[0-9a-f]*' $DB) file $(grep -o 'e5_vm_writers[_0-9]*.tgz' $DB | head -1)"
echo done >> $OUT
