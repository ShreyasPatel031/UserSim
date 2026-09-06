# OM2W 300 — Flash Lite vs Flash (2026-09-05)

Machine-readable: `om2w_flash_headed_compare_20260905.json`.

## Results

| Arm | Model | Browser | Success | Eligible | BLOCKED | Cost |
|-----|-------|---------|---------|----------|---------|------|
| Flash Lite | `gemini-2.5-flash-lite` | headless | **65/300 (21.7%)** | 65/222 (29.3%) | 78 | ~$6.54 |
| Flash Lite + headed | same Lite run | headed fixes WAF on blocked hosts | **65/300 (21.7%)** | 65/255 (25.5%) | **45** (78−33) | ~$6.54 |
| Flash + headed | `gemini-2.5-flash` | headed + Xvfb | **113/300 (37.7%)** | 113/263 (43.0%) | 37 | ~$54.91 |

**Lite + headed** = the Lite headless full300 (`om2w_flashlite_20260905_1849`) with blocked/eligible adjusted by the headed rescue (`om2w_unblock_headed_rescue_1355.json`): headed opened 11 hosts covering **33** of Lite’s 78 BLOCKED tasks. Successes stay 65 — agent not re-run on those hosts; only the block count changes because headed is what actually loads those sites.

Headed rescues: carmax, dillards, drugs, fedex, kbb, landwatch, mayoclinic, nba, new.mta.info, sec.gov, zara.

Still blocked both ways (8 hosts): apartments, marriott, uniqlo, cars, carvana, microcenter, sourceforge, kaggle.

Flash headed tag: `om2w_flash_headed_20260905_2155` (discarded invalid `…_2112` Flash-403 arm).
