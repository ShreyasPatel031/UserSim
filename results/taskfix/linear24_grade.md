# Linear 24-agent study for PR #46 to grade

This run is not an independent pass until PR #46 grades it. Browserbase sessions for this study are already released. Grade by id.

```
python3 -m mvp.e2e2_matrix --grade-study 70557bae-83af-4bf9-9bbb-3135046193cd
```

| | |
| --- | --- |
| study_id | `70557bae-83af-4bf9-9bbb-3135046193cd` |
| product | https://linear.app |
| report | http://127.0.0.1:3000/report?study=70557bae-83af-4bf9-9bbb-3135046193cd |
| harness summary | `results/taskfix/linear24_summary.md` |
| harness log | `results/taskfix/linear24.log` |
| final screenshots | `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/<agent>/screenshots/final.png` |

24 final screenshots are on disk (gitignored under `mvp/runs/`). Product agents:

- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t1__p1__product/screenshots/final.png`
- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t1__p2__product/screenshots/final.png`
- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t1__p3__product/screenshots/final.png`
- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t1__p4__product/screenshots/final.png`
- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t2__p1__product/screenshots/final.png`
- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t2__p2__product/screenshots/final.png`
- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t2__p3__product/screenshots/final.png`
- `mvp/runs/70557bae-83af-4bf9-9bbb-3135046193cd/t2__p4__product/screenshots/final.png`

Local harness product vision was 8/8 (create-issue docs and pricing). That score waits on `--grade-study`.
