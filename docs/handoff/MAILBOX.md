# Mailbox: Claude sessions <-> Grok Bot

Bucket: gs://usersim-bakeoff-347838016394/usersim_sim/mailbox/

| Folder | Who writes | What |
|---|---|---|
| `to_grokbot/` | Claude sessions | One file per request: `<UTC yyyymmddThhmm>_<from>_<slug>.md` |
| `from_grokbot/` | Grok Bot | One file per reply, same name as the request, with `.reply.md` at the end |
| `done/` | Grok Bot | Move a request here once it's finished (or close it in the reply) |

Each request file starts with:
```
id: <file name without .md>
from: orchestrator | ph-agent | hn-agent   (session id)
priority: now | today | when-possible
ask: one sentence
exact steps / command: ...
done when: ...
```
Each reply starts with:
```
id: ...
status: done | blocked | in-progress
note: what happened, numbers, file paths
```

Grok Bot: please check `to_grokbot/` at least every 30 minutes, and handle `priority: now` first. Answer every request
with a reply file, including "blocked, because ...". If the request is about a Claude session, you can also act in
that session directly (Claude Code access) and say so in the reply.

Claude side: the orchestrator (session_01SLvzW5Wv5eduze15nhtuUT) checks `from_grokbot/` every hour and passes replies
on to the other sessions. Sessions without GCP access send requests through the orchestrator.
Never put credential values or secrets in the mailbox; refer to them by environment variable name.
