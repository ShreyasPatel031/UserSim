#!/bin/bash
# usage: ios.sh observe TAG | ios.sh act '{"action":...}'
if [ "$1" = observe ]; then curl -s -XPOST localhost:8799/observe -d "{\"tag\":\"$2\"}" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("shot"),d.get("err",""));[print(e["type"],repr(e["label"]),e["x"],e["y"]) for e in d.get("elements",[])]'
else curl -s -XPOST localhost:8799/$1 -d "$2"; echo; fi
