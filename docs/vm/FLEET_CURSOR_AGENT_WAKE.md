# Real-time mail to fleet-cursor (Pub/Sub push → Cursor steer)

Cloud Agents **do not** subscribe to GCP Pub/Sub. Polling `fleet-cursor` on a timer burns tokens. Use a **push subscription** and the [Cursor Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints) **`delivery: "steer"`** instead (same pattern as external webhooks: event in → one HTTP handler → agent turn).

## Flow

1. Peer publishes to topic `agent-msgs` with `to=fleet-cursor` (`scripts/vm/ph_fleet_agent_relay.sh`).
2. Pub/Sub subscription **`fleet-cursor-wake`** (push) POSTs to Cloud Run **`fleet-cursor-wake`**.
3. Handler calls `POST https://api.cursor.com/v1/agents/{bc_id}/runs` with `{"prompt":{"text":"…"},"delivery":"steer"}`.
4. The fleet babysit agent gets a **chat notification** immediately (no timer poll).
5. The existing **pull** subscription `fleet-cursor` is unchanged: 15m check-in still durably appends JSONL and acks.

Dedupe: handler writes `usersim_sim/mailbox/from_cursor/wake_dedupe/{messageId}` so the same Pub/Sub id does not steer twice.

## One-time setup

1. Cursor Dashboard → **API Keys** → create a key.
2. GCP Secret Manager (project = `AGENT_MSGS_PROJECT`):

   ```bash
   printf '%s' "$CURSOR_API_KEY" | gcloud secrets create cursor-fleet-api-key \
     --project=PROJECT --data-file=-
   ```

3. Deploy:

   ```bash
   export CURSOR_API_KEY=...  # only needed if not using --set-secrets above
   export FLEET_CURSOR_BC_ID=bc-....      # this Cursor chat's id, or leave unset
   bash scripts/vm/ph_fleet_cursor_publish_bc.sh   # writes bc id to GCS for the bridge
   bash scripts/vm/ph_fleet_cursor_wake_deploy.sh
   ```

4. Each fleet check-in runs `ph_fleet_cursor_publish_bc.sh` when `CURSOR_CONVERSATION_ID` is set (Cloud Agent VM).

## Peers (Population / Claude / Grok)

**Urgent (real-time):**

```bash
scripts/vm/ph_fleet_agent_relay.sh fleet-cursor population "your message"
```

**Broadcast** (`to=all`) also wakes the bridge **except** lines from `fleet-cursor` (15m check-in spam is filtered out).

**Non-urgent:** read `gs://BUCKET/usersim_sim/mailbox/from_cursor/status.json` (15m).

## Grok Bot note

`grokbot-inbox` on the same topic is still **pull** on the orchestrator VM; Grok's *webhook* path is separate (HTTP → its runtime). fleet-cursor's equivalent is **Pub/Sub push → Cursor API steer**, not another 5m Cursor timer.
