#!/bin/bash
# ios_step.sh TAG X Y [sleep]   or ios_step.sh TAG label "Label"
I=/workspace/ios.sh
if [ "$2" = label ]; then $I act "{\"action\":\"tap_label\",\"label\":\"$3\"}" >/dev/null; s=${4:-3}
elif [ "$2" = type ]; then $I act "{\"action\":\"type\",\"text\":\"$3\"}" >/dev/null; s=${4:-2}
elif [ "$2" = swipe ]; then $I act "{\"action\":\"swipe\",\"direction\":\"$3\"}" >/dev/null; s=${4:-2}
elif [ -n "$2" ]; then $I act "{\"action\":\"tap\",\"x\":$2,\"y\":$3}" >/dev/null; s=${4:-3}; fi
sleep ${s:-0}; $I observe $1 | rg -v "Key '|scroll bar|jindo|Screen Recording|^Application" | cut -c1-110
