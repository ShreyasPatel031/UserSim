#!/bin/bash
# Publish the code bundles fresh scheduled sessions run from (they have no repo checkout and no GitHub access).
#   bash experiments/simlab/fresh/publish_code.sh     (run from the UserSim checkout after pushing)
set -e; B=gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/private/code; T=$(mktemp -d); R="$(git rev-parse --show-toplevel)"
git -C "$R" archive --format=tar.gz -o $T/usersim.tar.gz HEAD experiments/pipeline experiments/simlab --prefix=usersim/
git -C "$R" fetch -q origin claude/cool-volta-l5nuo4 && git -C "$R" archive --format=tar.gz -o $T/simharness.tar.gz FETCH_HEAD simharness --prefix=cv/
git -C "$R" fetch -q origin main && MAIN=$(git -C "$R" rev-parse FETCH_HEAD) && git -C "$R" archive --format=tar.gz -o $T/mainwt.tar.gz $MAIN mvp scripts src --prefix=mainwt/   # PRODUCT-USE-1: MCP runner + safe_fetch
git -C "$R" fetch -q origin claude/cool-volta-l5nuo4
git -C "$R" archive --format=tar.gz -o $T/phops.tar.gz b86f582d026852fcc03b08119de5830029b2049f experiments/ph_predict --prefix=phops/
printf '{"usersim": "%s", "simharness": "%s", "phops": "b86f582d", "main": "%s", "published_at": "%s"}\n' "$(git -C "$R" rev-parse HEAD)" "$(git -C "$R" rev-parse FETCH_HEAD)" "$MAIN" "$(date -u +%FT%TZ)" > $T/manifest.json
gsutil -m -q cp $T/*.tar.gz $T/manifest.json $B/ && gsutil -q cp "$R/experiments/simlab/fresh/bootstrap.sh" $B/bootstrap.sh && cat $T/manifest.json; rm -rf $T
