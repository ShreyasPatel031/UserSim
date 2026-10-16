# WellSky Agent Gateway replica (SC sandbox)

A replica of WellSky's planned AgentOps control plane in `project-amer-scs-sandbox` (us-central1). It covers Agent Gateway, Agent Identity, Agent Registry, Model Armor, a Discovery Engine knowledge base and an Onspring-style MCP server. All data is synthetic. Every resource is prefixed `wsky-`.

It exists to test what the SOW promises against what the product actually does, before Andrew's call and the PSO/Searce SOW.

## What is deployed

| Piece | Resource | Mirrors at WellSky |
|---|---|---|
| Egress gateway | `agentGateways/wsky-egress-gw` (Google-managed, `AGENT_TO_ANYWHERE`) | Agent Gateway for governed agents |
| Gateway policies | `authzPolicies/wsky-gw-iap` (REQUEST_AUTHZ → IAP, currently **dry-run**), `authzPolicies/wsky-gw-model-armor` (CONTENT_AUTHZ) | Up to 10 gateway policies |
| Model Armor | `templates/wsky-request`, `templates/wsky-response` | Up to 3 templates (PHI, PII, internal-only) |
| MCP tool | Cloud Run `wsky-mcp-onspring` (IAM-only), registered as `services/wsky-mcp-onspring` | Onspring MCP |
| Knowledge base | Discovery Engine `us` data store `wsky-kb` + engine `wsky-kb-search` | Data store behind the in-house agent |
| Baseline agent | `reasoningEngines/1985445595757674496`, Agent Identity, no gateway | The Discovery Engine API agent as it runs today |
| Governed agent | `reasoningEngines/6349433634679685120`, Agent Identity + `wsky-egress-gw` | A governed agent after the SOW |

## Findings: what we were told vs. what is there

**1. Discovery Engine "permission errors": root cause reproduced and fixed.**
- Agent Identity tokens are bound to the agent's SPIFFE certificate. A Google-managed Context-Aware Access policy enforces mTLS by default.
- Custom tool code that calls `*-discoveryengine.googleapis.com` with `requests` gets **401 UNAUTHENTICATED**. This happens even after the right IAM role is granted. The token is also rejected by Google's tokeninfo endpoint.
- Gemini calls in the same agent work, because the GenAI SDK switches to mTLS on its own. So the agent looks healthy while its tools fail.
- Fix: call `*-discoveryengine.mtls.googleapis.com` with the cert at `GOOGLE_API_CERTIFICATE_CONFIG`, or use the client library with an mTLS endpoint. Then grant the agent's **own principal** (`principal://agents.global.org-…/reasoningEngines/<id>`), not a service account, a role such as `roles/discoveryengine.viewer`.
- Verified: 401 (plain REST) → 403 (mTLS, no role) → 200 (mTLS + role). See `agent/wsky_agent.py` (`search_kb`, `search_kb_mtls`, `search_kb_client_lib`) and `08_grant_de_access.sh`.

**2. Routing an agent through Agent Gateway breaks its model calls unless token binding is turned off.**
- With `agentGatewayConfig.agentToAnywhereConfig` set, the governed agent's first Gemini call fails with 401. It never reaches a tool.
- Google's own Agent Gateway codelabs deploy with `--allow-token-sharing`, which sets `GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=false`. That disables Agent Identity's protection against token replay.
- This is a security trade-off WellSky's security team has to accept in writing. The SOW and TDD should not present "per-agent identity" and "gateway routing" as free to combine. See the note in `05_deploy_agents.py`.

**3. Enforcement means registering every Google API the agent touches.**
- In dry-run, the gateway's IAP check already sees `aiplatform`, `cloudresourcemanager` and `iamcredentials` calls (`*.mtls.googleapis.com`) from the runtime itself, all as `unregisteredEndpoint`.
- Under ENFORCED, anything not registered as an Agent Registry Endpoint *and* granted `roles/iap.egressor` is denied. That includes model, telemetry, logging and session calls.
- Google's sample registers about 15 services × global/regional × mTLS host variants. This is real setup and operations work the SOW should budget for.

**4. Dry-run fails open.**
- Google's samples, and our `wsky-iap-dryrun` extension, use `failOpen: true`.
- Production needs a separate `failOpen: false` extension (`wsky-iap-enforced`) and a planned cutover. The runbook must cover this.

**5. One registry per project and region, shared by every gateway.**
- `registries` only accepts the project-scoped registry. A second gateway in the same project and region (ours, next to `a2a-crosscloud-gateway`) governs the same inventory.
- WellSky's dev/stage/prod split therefore has to be done with separate projects, not separate gateways.

**6. Model Armor out of the box does not cover healthcare data.**

| Synthetic prompt | Result |
|---|---|
| SSN + phone | Not caught by Sensitive Data Protection (only an RAI filter fired) |
| MRN + DOB + diagnosis (PHI) | **Not caught** |
| Credit card | Caught (`CREDIT_CARD_NUMBER`) |
| Prompt injection | Caught |
| "Send internal Texas EVV rules to a customer" | **Not caught**. Model Armor has no notion of content tiers. |

- PHI and PII need an advanced Sensitive Data Protection config: DLP inspect and de-identify templates with healthcare infoTypes, with the Model Armor service agent granted `roles/dlp.user` and `roles/dlp.reader`.
- Rules for internal-only and EVV content have to be enforced through data access (IAM, data store ACLs, separate stores per tier). Model Armor can't do it.
- Rerun with `09_model_armor_test.sh`.

**7. Calls to Cloud Run MCP servers need a separate invoker identity.**
- Cloud Run requires an ID token. Google's sample deploys agents with a separate `--mcp-invoker-sa` instead of using the agent identity directly.
- Not yet verified here, because finding 2 blocks it. It's next once token sharing is approved.

**8. Other gotchas.**
- The shared sandbox is out of `global` Discovery Engine data store quota, so the replica uses `us`.
- `mcp` 2.x renamed `FastMCP` (we pinned `mcp<2`).
- The `vertexai` SDK's `stream_query` fails to parse some concatenated stream chunks (`07_ask.py` uses REST instead).

## Not done yet (waiting on a decision)

- Redeploy the governed agent with token sharing allowed. Then test the Onspring MCP path through the gateway, `iap.egressor` with a CEL condition per tool, the switch to ENFORCED, and Model Armor on the gateway's CONTENT_AUTHZ path.
- Advanced Sensitive Data Protection (healthcare infoTypes) template and retest.
- Attaching the agents to a Gemini Enterprise app (the "GE tool traffic through the gateway" claim in the SOW).

## Run order

```bash
export WSKY_KEY_FILE=<path for decoded SA key>; source env.sh
./01_gateway.sh; ./02_mcp_onspring.sh; ./03_register_mcp.sh; ./04_discovery_engine.sh
python 05_deploy_agents.py baseline; python 05_deploy_agents.py governed
./06_model_armor_and_policies.sh            # ./06_model_armor_and_policies.sh enforce|dryrun to switch IAP mode
./08_grant_de_access.sh <reasoningEngine id>
python 07_ask.py <reasoningEngine name> "Call search_kb_mtls with query 'Texas EVV'"
./09_model_armor_test.sh
./99_teardown.sh                             # removes only wsky-* resources
```
