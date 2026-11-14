# Full-night integration dry run (orchestrator 19:31Z Nov 14)
`integ_night.py <D> normal|fallback <workdir>`: private root, fake bucket (`gsutil_stub.py`: writes local; chain paths authoritative locally; others read-only through), no VM, no new LLM calls.
Chain: today/D line-up → forecast.py + h25_live (today-rows patch) → 12a.2 two_predictions midnight + prereveal (stored recorder) → vm_writers run.sh jobs (TZ PT, private HOME / USERSIM_CACHE).
Probes: D-1 decoys (ids DECOY_*) and *_latest pointers planted; inputs deleted in turn; outputs scanned for decoys.
Nights: Nov 12 (arm 2 normal), Nov 13 (fallback: 2025 lists withheld so arm 2 fails → clean_nosite). Reports in results/ (n12/n13 = build 12.2, *_123 = build 12.3 candidate).
