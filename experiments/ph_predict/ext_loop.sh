#!/bin/bash
# one loop per outside source; each pass only does keys it has not seen
cd "$(dirname "$0")"
for k in x rdap hn wb sitex; do
  (while true; do python3 external.py $k >> ext_$k.log 2>&1; sleep 90; done) &
done
wait
