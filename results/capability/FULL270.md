# Full270 — matched-triplet persona × journey × seed × platform

**Cells:** 6 personas × 5 journeys × 3 seeds × 3 platforms = **270**  
**Reserve:** ~30 sessions outside this set for invalid replacements + predefined robustness (do not casually expand the primary 270).

## Design

| Dimension | Values |
|-----------|--------|
| Personas | owner, CX ops, RevOps, conversation designer, integration developer, enterprise admin |
| Journeys | (1) rapid setup (2) knowledge support (3) logic/routing (4) integration (5) testing/debug |
| Seeds | 1, 2, 3 |
| Platforms | Bland, Vapi, Retell |

Matched block = `(persona, journey, seed)` → identical prompt cloned to three platforms.

Journeys **2–5** start from an **existing baseline agent** so Task-1 create failures do not contaminate later journeys. Templates / built-in AI assistants are allowed (product UX).

## Fleet (same wall-clock idea as full80)

```text
12 Spot VMs × 8 workers × 3 platforms = 36 VMs
90 tasks / platform ÷ 12 shards ≈ 7–8 tasks/VM → ~1 wave (≈ longest task, 8–15 min)
KEEP_VM=0 → VM self-deletes after complete shard
--relaunch → restore GCS checkpoints + resume unfinished / preempted
```

Equal concurrency per platform (12×8 slots each) so rate limits / load are not an accidental treatment.

## Launch

```bash
# Requires secrets/env, secrets/vertex_adc.json, secrets/voice_ai_sessions/{bland,vapi,retell}.json
./scripts/vm/fleet_full270.sh

./scripts/vm/fleet_full270.sh --status
./scripts/vm/fleet_full270.sh --relaunch   # spot failures / incomplete shards
./scripts/vm/fleet_full270.sh --pull
./scripts/vm/fleet_full270.sh --down
```

Defaults: `gemini-2.5-flash-lite`, `MAX_ACTIONS=40`, tag `full270_flashlite_m40`.

Local triad smoke (3 sessions):

```bash
PYTHONPATH=src .venv/bin/python -m capability.run_bakeoff \
  --stage product_full270_smoke --harness browser_use --max-actions 40 --tag smoke270
```

## Analysis notes

- Keep robustness / reserve replacements **separate** from the primary 270.
- Replace invalids only with the **same** persona–journey–platform–seed cell.
- Grade with journey `success_criteria` (LLM judge) + `capability.full270_validators` heuristics.
