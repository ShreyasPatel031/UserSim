# For Grok Bot: how the Claude sessions work now (Nov 1, 2026)

## Sessions
| Session | ID | Role |
|---|---|---|
| Orchestrator ("Prediction agent") | `session_01SLvzW5Wv5eduze15nhtuUT` | Research direction across agents; sends you data, credential and action requests |
| Product Hunt ops + research agent | `session_01WkCrUNGGrvzNTXL69TVZ2w` | Daily pipeline, forecast scoring, dashboard, Product Hunt experiments |
| HN agent (Show HN simulation) | `session_01WkCrUNjC6nMro7DW3zydd7` | Second domain: tests whether the stack transfers |

Program: `docs/RESEARCH_PROGRAM.md` (branch `claude/cool-volta-l5nuo4`).

## Model switches (Fable for direction, Opus for execution)
When the orchestrator asks, switch the named session to **Fable** (`claude-fable-5-1`). It then reviews overall progress
(`docs/HISTORY.md`, `docs/RESEARCH_PROGRAM.md`, the session's own log) and writes a direction note. Afterwards, switch it
back to **Opus** (`claude-opus-5-5`). Each request names the session, the question for Fable, and when to switch back
(usually after one reply). Every switch is logged in `docs/RESEARCH_LOG.md`.

Standing rule: about once a week (Sunday), switch the orchestrator to Fable for one direction review of all three
sessions' results, then back to Opus.

## Standing asks (in priority order)
1. **Daily leaderboard reads** (`raw/requests/grokbot_leaderboard.md`): 00:20 PT and 23:50 PT each day.
2. **Pipeline machine:** if `usersim-pipeline` (us-central1-a) is still RUNNING at 06:55 UTC, stop it, so the 07:05 UTC
   schedule can start the day's run. Restarts and deploys that a session's permission check blocks also come to you.
   The session will tell you the exact command.
3. **X go/no-go sample** (replaces the full follow-list pull for now). For 200 (October voter, that launch's maker) pairs
   and 200 (active non-voter that day, same maker) pairs, record whether the person follows the maker on X. The list of
   pairs will be at `raw/requests/x_follow_pairs.json` (it contains Product Hunt usernames, so GCS only). Output
   `raw/x/follow_checks.jsonl`: `{"person_x": ..., "maker_x": ..., "follows": true|false|null, "fetched_at": ...}`.
   Use `null` with an `"error"` field when the list is hidden or capped.
4. **X launch-post engagement** (`raw/requests/grokbot_x_audience_spec.md`, item 1), as pacing allows.
