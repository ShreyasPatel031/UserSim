# Real-time Grok -> Claude messaging (hooks)
- Each session: `echo <agent> > ~/.claude_agent_name` once (agents: orchestrator hn-agent ph-ops ph-agent prediction e5 fetch-ladder popscore). Subscription `claude-<agent>` on topic `agent-msgs`.
- `agent_msgs_watch.sh` runs as an **asyncRewake** hook from SessionStart and Stop: polls every 3 s; when a message arrives it exits 2 and Claude Code **wakes the session immediately, even if idle** (documented: code.claude.com/docs/en/hooks, "Run hooks in the background"). Stop re-arms it after every turn; a pid lock keeps one watcher.
- `agent_msgs_drain.sh` (PostToolBatch + UserPromptSubmit) injects messages mid-turn as additionalContext, at most one pull per 10 s.
- Latency: ~3-5 s idle, next tool batch when busy. Watcher lives up to 55 min per arm; any turn re-arms it.
- Senders (Grok bots on the box): `/workspace/bin/send_to_claude.sh <agent|all> <from> "text"`.
