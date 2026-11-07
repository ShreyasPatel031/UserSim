# PH tab/ramp strategy bake-off (4 VMs × 4 h)

## Identity rotation (no cold VM)

**Rotate between queue profiles / sessions**, not on every HTTP request:

- **Same VM**, **same `phsuper`**, same sticky **`proxy-port`** for a run until you deliberately change it.
- **New identity** = new **sticky port** (10000–20000) and/or new **`/opt/ph/profiles/p{port}/`** when starting the **next** person after a 403/challenge — not a VM reboot.
- **Do not** swap proxy/session on every GraphQL call.

## Tab ceiling

Empirical in-flight ceiling ~**64** tabs; arms use **8 / 16 / 32 / 48** (`pdeep-tabs`). Strategy **C** is the **32** exploratory setpoint.

## Strategies

| ID | `pdeep-tabs` | `pdeep-ramp` |
|----|--------------|--------------|
| A | 8 | `1:30,8:60` |
| B | 16 | `1:30,8:90,16:120` |
| C | 32 | `1:30,8:90,16:120,32:150` |
| D | 48 | `1:40,16:120,32:150,48:180` |

Each VM: **e2-standard-2**, one hot browser (`k-levels=1,1`), own sticky port, `pace_startup.sh` → **phsuper** on people queue.

## Run (from laptop / env with `gcloud`)

```bash
cd UserSim
chmod +x scripts/vm/ph_tab_strategy_experiment.sh pace_startup.sh
export PACE_EXPERIMENT_RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)

./scripts/vm/ph_tab_strategy_experiment.sh up --fetch-proxy-from feeder-phpeople-1
./scripts/vm/ph_tab_strategy_experiment.sh monitor --loop   # 15 min × 4 h
./scripts/vm/ph_tab_strategy_experiment.sh summary
./scripts/vm/ph_tab_strategy_experiment.sh down
```

Samples: `results/ph_tab_experiment/<RUN_ID>/samples.tsv` (status, phsuper, JSON count, est. people/min, 403 hints).

**Status:** Not auto-running in cloud agents without `gcloud`; launch the commands above in GCP-enabled shell.
