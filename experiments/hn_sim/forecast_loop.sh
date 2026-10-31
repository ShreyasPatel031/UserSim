# Hourly live daily-list forecast (run as a VM job): forecast at :05 past each hour, push the JSON to the bucket.
pull fd_v4_models.pkl
while true; do
  QN_TIMEOUT=150 python -W ignore forecast_daily.py now 30 > /tmp/fd_last.log 2>&1 && tail -31 /tmp/fd_last.log | head -1
  for f in $USERSIM_CACHE/forecast_daily/*/*.json; do d=$(basename $(dirname $f)); gsutil -q cp -n $f $C/forecast_daily/$d/$(basename $f); done
  sleep $(( 3600 - $(date +%s) % 3600 + 300 ))
done
