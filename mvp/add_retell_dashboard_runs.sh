#!/bin/bash
# Add Retell logged-in dashboard runs when credentials become available
#
# Usage: ./add_retell_dashboard_runs.sh <retell_results.json>
#
# This script merges new Retell dashboard runs into the existing
# voice_dashboard_browser_use_all_v1.json file.

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <retell_results.json>"
    echo ""
    echo "This script adds Retell logged-in dashboard runs to the bakeoff."
    echo "The input file should be a JSON with the same format as the other"
    echo "voice_dashboard_*.json files."
    exit 1
fi

INPUT_FILE="$1"
DASHBOARD_FILE="mvp/bakeoff_data/voice_dashboard_browser_use_all_v1.json"

if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: Input file not found: $INPUT_FILE"
    exit 1
fi

if [ ! -f "$DASHBOARD_FILE" ]; then
    echo "Error: Dashboard file not found: $DASHBOARD_FILE"
    exit 1
fi

echo "Adding Retell runs from $INPUT_FILE to $DASHBOARD_FILE..."

python3 -c "
import json
from pathlib import Path

dashboard = json.loads(Path('$DASHBOARD_FILE').read_text())
new_runs = json.loads(Path('$INPUT_FILE').read_text())

# Filter for retell runs that had auth
retell_runs = [r for r in new_runs.get('runs', []) if r.get('website') == 'retell' and r.get('had_auth')]

if not retell_runs:
    print('No authenticated Retell runs found in input file')
    exit(1)

# Remove old retell runs (no auth)
old_runs = [r for r in dashboard.get('runs', []) if r.get('website') != 'retell']

# Add new retell runs
dashboard['runs'] = old_runs + retell_runs

# Update counts
successes = sum(1 for r in dashboard['runs'] if r.get('success'))
dashboard['successes'] = successes
dashboard['n'] = len(dashboard['runs'])

Path('$DASHBOARD_FILE').write_text(json.dumps(dashboard, indent=2, default=str))
print(f'Added {len(retell_runs)} Retell runs. New total: {len(dashboard[\"runs\"])} runs, {successes} successes')
"

echo "Done! Commit and push the changes."
