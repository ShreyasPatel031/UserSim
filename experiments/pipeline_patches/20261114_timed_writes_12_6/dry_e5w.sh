#!/bin/bash
# Dry run of every e5w job of bundle 12.2 under tw.sh's environment, in a scratch tree; every gsutil write to gs:// is stubbed (logged, rc 0).
# held_team_* are run too: without the salt they must stop with "inputs missing: early/salt" (exit 3), never touching the store.
set -u; T=/home/agent/w/phops_tm/b126; rm -rf $T; mkdir -p $T/stub $T/cache $T/tmp $T/logs $T/e5_assets/early $T/e5_vm_writers
REAL=$(command -v gsutil)
cat > $T/stub/gsutil <<STUB
#!/bin/bash
last="\${@: -1}"
for a in "\$@"; do case "\$a" in cp|mv|rm|rsync|setmeta) op=\$a;; esac; done
if [ -n "\${op:-}" ] && [ "\${last#gs://}" != "\$last" ]; then echo "STUB-WRITE \$op -> \$last" >> $T/logs/stub_writes.log; exit 0; fi
if [ "\${op:-}" = rm ]; then echo "STUB-RM \$*" >> $T/logs/stub_writes.log; exit 0; fi
exec $REAL "\$@"
STUB
chmod +x $T/stub/gsutil
gsutil -q cp gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/vm_writers/e5_vm_writers_12_6.tgz $T/e5w.tgz
[ "$(md5sum < $T/e5w.tgz | cut -c1-8)" = 844c4673 ] || { echo "md5 mismatch"; exit 1; }
tar xzf $T/e5w.tgz -C $T/e5_vm_writers; (cd $T/e5_vm_writers/vm_writers && md5sum -c --quiet MANIFEST.md5) && echo "manifest OK"
bash -n $T/e5_vm_writers/vm_writers/run.sh && echo "bash -n OK"
gsutil -q -m rsync -r gs://usersim-bakeoff-347838016394/usersim_sim/tables $T/cache > /dev/null 2>&1 || echo "warehouse sync failed"
for J in track_record prob_0005 prob_prereveal period period_score held_team_predict held_team_score; do
  ST=$(env -i HOME=$HOME PATH=$T/stub:/opt/exp/bin:/usr/local/bin:/usr/bin:/bin TZ=America/Los_Angeles USERSIM_CACHE=$T/cache TMPDIR=$T/tmp \
       LGB_THREADS=2 MPLBACKEND=Agg ASSETS=$T/e5_assets LOG=$T/logs/e5_writers.log CLOUDSDK_CONFIG=${CLOUDSDK_CONFIG:-$HOME/.config/gcloud} \
       nice -n 19 bash $T/e5_vm_writers/vm_writers/run.sh $J 2>&1); RC=$?; ST=$(echo "$ST" | tail -1 | cut -c1-260)   # rc of run.sh itself
  echo "JOB $J rc=$RC | $ST"
done
echo "stubbed writes: $(wc -l < $T/logs/stub_writes.log 2>/dev/null || echo 0)"; sed 's|gs://[^ ]*/|gs://.../|' $T/logs/stub_writes.log 2>/dev/null | head -12
