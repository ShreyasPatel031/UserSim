# Next bundle (20261115): NOT DEPLOYED. It deploys only on Shreyas's word.

| file | md5 | destination |
|---|---|---|
| ctrl.py | b47fc28f | ~/w/arm2_live/ctrl.py (tracked copy of the file hand-added at 09:02Z Nov 14; arm 2's import chain needs it) |
| readable_shadow.py | 2851a666 | ~/w/tw/h25/readable_shadow.py (bundle 12.8 tree): each forecast row gains "values" = raw X10 inputs from the 00:05 rows (null if missing); ph_n_makers == 0 treated as missing |
| import_gate.py | (from 12.8) | gate helper |

`bash deploy_nb.sh check`: manifest, then both import gates on a scratch copy (read-only).
`bash deploy_nb.sh deploy`: refuses 23:30-01:00 PT and when 12.8 is not deployed. It backs files up to ~/w/nb_backup, installs, gates, and rolls back on failure.
`bash deploy_nb.sh rollback`: restores the backups.
Order: after DEPLOY_ORDER step 6 (bundle 12.8).
| arm2_shap.py | 5e2e9112 | ~/w/tw/experiments/ph_predict/arm2_shap.py: arm 2's own TreeSHAP (5 seeds, refit as at 00:05, groups centred within the day) plus each launch's raw arm-2 input "values". Bundle 12.8's why_drivers job already runs it nightly; it writes results/shadow_arm2_shap/<d>.json. Dry run on the VM for Nov 14: 28 launches, 40 inputs, max |sum(shap) - pred| = 0.0 |
