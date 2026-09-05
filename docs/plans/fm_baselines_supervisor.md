# FM baseline Colab supervisor — ops plan

## Problem
Colab runtimes go zombie overnight: listed in `sessions`, keep-alive dead, local
`sessions.json` pruned, `exec` → 404. Cursor ending a chat must not kill the jobs.

You already solved this for OmniBehavior with:
- `~/Centaur/colab_minitaur/resilient_binary_driver.py`
- `~/Centaur/colab_minitaur/launchd_supervisor.py`

Reuse that pattern. Do **not** invent a new one.

## Hard rules
1. **Never trust `colab status` alone** — probe `/content` with upload+download canary.
2. **Local disk is source of truth** — pull `predictions.jsonl` / `SUMMARY.json` / task JSONs every poll.
3. **Respawn on zombie / stall / missing PID**.
4. **2 GPU cap** on this Colab account → only 2 jobs concurrent.
5. **Centaur-70B skipped**.
6. Run supervisor under **launchd or tmux**, not only inside Cursor.

## Jobs
| Job | Session | GPU | Progress signal | Done signal |
|---|---|---|---|---|
| Socrates full | `fm-socrates` | L4→T4 | lines in `results/socrates/predictions.jsonl` | `SUMMARY.json` with `n_studies>=40` |
| Minitaur NLL | `fm-minitaur` | T4→L4 | `SUMMARY.json` growth / log `scored N/6561` | `SUMMARY.json` with `n_items>=6500` |
| BeFM (optional) | `fm-befm` | T4 | task JSON files | `DONE.json` (8-task subset already finished) |

## Script
`scripts/fm_baselines/resilient_fm_supervisor.py`

```bash
# foreground test
python3 -u scripts/fm_baselines/resilient_fm_supervisor.py --once

# forever (tmux)
tmux new -s fm-sup -- python3 -u scripts/fm_baselines/resilient_fm_supervisor.py

# launchd (preferred — same as Minitaur)
# plist runs every 90s OR KeepAlive on the forever loop
```

Poll loop (90s):
1. For each unfinished job: `ensure_session` (filesystem probe).
2. If worker PID dead → push boot script → `nohup` worker (resume-capable).
3. Pull progress artifact → local `results/fm_baselines/<job>/`.
4. If no growth for 45m after 30m grace → `colab stop` + respawn.

## Boot scripts (idempotent)
- `boot_socrates_l4.py` — starts full eval; resumes `predictions.jsonl`
- `boot_minitaur_t4.py` — `MAX_SEQ=4096` (T4 OOM'd at 8192)
- BeFM boot only if `--with-befm`

## launchd (same pattern as Minitaur)

Template lives in-repo:
`scripts/fm_baselines/com.usersim.fm-baselines.plist`

Install + load (survives Cursor exit / reboot login):
```bash
cp scripts/fm_baselines/com.usersim.fm-baselines.plist \
  ~/Library/LaunchAgents/com.usersim.fm-baselines.plist
launchctl bootout gui/$(id -u)/com.usersim.fm-baselines 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.usersim.fm-baselines.plist
launchctl enable gui/$(id -u)/com.usersim.fm-baselines
launchctl kickstart -k gui/$(id -u)/com.usersim.fm-baselines
```

Logs:
- `results/fm_baselines/supervisor.log` (app)
- `results/fm_baselines/supervisor.launchd.out.log`
- `results/fm_baselines/supervisor.launchd.err.log`

Unload:
```bash
launchctl bootout gui/$(id -u)/com.usersim.fm-baselines
```

## Revive checklist
1. `colab --auth=adc sessions` — stop zombies if any
2. Prefer launchd (above) so polling continues after Cursor closes
3. Or smoke once: `python3 -u scripts/fm_baselines/resilient_fm_supervisor.py --once`
4. Confirm local progress under `results/fm_baselines/{socrates,minitaur}/`
5. Do not rely on Cursor staying open
