# IPRoyal ISP limit finder (1 VM)

Climb **L0 → L7** on a **single dedicated IP** until blocks appear; record the last **OK** level as max steady **complete/min**.

| Level | File | Tabs | ~req/min cap |
|-------|------|------|--------------|
| L0_ultra | polite baseline | 2 | 20 |
| L1_polite | serial_polite | 4 | 36 |
| L2_modest | scale_down | 8 | 50 |
| L3_mid | scale_down | 12 | 70 |
| L4_fleet80 | fleet-shaped | 16 | 80 |
| L5_fleet120 | | 16 | 120 |
| L6_fleet160 | | 16 | 160 |
| L7_ceiling | ceiling probe | 16 | 140 |

```bash
export GCP_PROJECT=... PACE_ZONE=... MVP_GCS_BUCKET=...
export PACE_PROXY_FILE=/path/to/secrets/iproyal.purl

RUN_ID=$(date -u +%Y%m%dT%H%M%SZ) PACE_IPROYAL_RUN_ID=$RUN_ID \
  ./scripts/vm/ph_iproyal_limit_experiment.sh up

# ~25 min per level, 5 min warmup; stops after 2 bad samples (blocks / browser_open_failed)
LADDER_MINUTES=25 ./scripts/vm/ph_iproyal_limit_experiment.sh ladder L0_ultra

./scripts/vm/ph_iproyal_limit_experiment.sh summary
./scripts/vm/ph_iproyal_limit_experiment.sh down
```

Artifacts: `results/ph_iproyal_limit/<run_id>/ladder.tsv`, `samples.tsv`.

Scale the main **feeder fleet to 0** (or hold) while this runs so only one VM uses the ISP IP.
