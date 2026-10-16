# WellSky Agent Gateway replica (SC sandbox)

A replica of WellSky's planned AgentOps control plane in `project-amer-scs-sandbox` (us-central1). It covers Agent Gateway, Agent Identity, Agent Registry, Model Armor, a Discovery Engine knowledge base and an Onspring-style MCP server. All data is synthetic. Every resource is prefixed `wsky-`.

It exists to test what the SOW promises against what the product actually does, before Andrew's call and the PSO/Searce SOW.

## Demo (working end to end)

`./15_demo.sh` runs eight scenarios against the live agents. The last recorded run is in `demo_output.txt`.

| # | Scenario | Result |
|---|---|---|
| 1 | Governed agent calls the allowed Onspring MCP tool through Agent Gateway | ✅ Records returned |
| 2 | Same MCP server, a tool the policy blocks (`get_governance_record`) | ✅ 403 from the gateway (per-tool IAP rule) |
| 3 | Registered Google API (Discovery Engine over mTLS) | ✅ 200, EVV documents returned |
| 4 | Unregistered destination (`example.com`) | ✅ 403 "Only registered endpoints are allowed" |
| 5 | Prompt injection | ✅ 403 "Dangerous content not allowed" (Model Armor at the gateway) |
| 6 | PHI in a request (MRN, DOB, diagnosis) | ✅ 403 "sensitive data not allowed" (healthcare inspection template) |
| 7 | WellSky's in-house agent pattern: plain REST under Agent Identity | ✅ Reproduces the 401 "permission error" |
| 8 | Same agent, mTLS endpoint + agent principal granted `discoveryengine.viewer` | ✅ 200, the fix |

The gateway runs in **ENFORCED** mode (`wsky-iap-enforced`, fail-closed). To show what each call was allowed or denied, run `./13_gateway_decisions.sh 6349433634679685120 <RFC3339 start time>`.

Cost guard: both agents run with `min_instances=0`, `max_instances=1`, 1 vCPU / 2 GiB, so they cost nothing while idle. Everything else is pay-per-use or free tier. Run `./99_teardown.sh` when you're done.

## What is deployed

| Piece | Resource | Mirrors at WellSky |
|---|---|---|
| Egress gateway | `agentGateways/wsky-egress-gw` (Google-managed, `AGENT_TO_ANYWHERE`) | Agent Gateway for governed agents |
| Gateway policies | `authzPolicies/wsky-gw-iap` (REQUEST_AUTHZ → IAP, **enforced**), `authzPolicies/wsky-gw-model-armor` (CONTENT_AUTHZ) | Up to 10 gateway policies |
| Per-agent egress | `roles/iap.egressor` for the governed agent's principal, CEL condition denying `get_governance_record` | Agent-to-tool access matrix |
| Registered endpoints | 13 Google API hosts as Agent Registry Endpoints (`wsky-ep-*`) | Required for enforcement |
| Model Armor | `templates/wsky-request`, `templates/wsky-response`, with DLP inspect template `wsky-phi-pii` (healthcare infoTypes) | Up to 3 templates (PHI, PII, internal-only) |
| MCP invoker | SA `wsky-mcp-invoker` (run.invoker); only the governed agent's principal may mint its ID tokens | Agent → Cloud Run MCP auth |
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

**6. Model Armor out of the box does not cover healthcare data. Fixed in the replica with a healthcare inspection template.**

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
- **After `14_phi_template.sh`** (a DLP inspect template with MEDICAL_RECORD_NUMBER, DATE_OF_BIRTH, MEDICAL_TERM, US_SOCIAL_SECURITY_NUMBER, NPI, MBI and a custom MRN regex): MRN, DOB and diagnosis are caught, both by direct calls and at the gateway (demo #6). Note: the test SSN `123-45-6789` is a known-invalid number, so DLP doesn't flag it as an SSN; use realistic synthetic values in UAT.
- Model Armor at the gateway screens the agent's **model calls** as well as tool calls. The injection in demo #5 was stopped on the Gemini request, before any tool ran.

**7. Calls to Cloud Run MCP servers need a separate invoker identity. Verified.**
- Agent Identity can't mint an ID token for Cloud Run itself. The metadata server hands back a tenant-project `appspot` identity.
- Working pattern (`10_mcp_invoker.sh`): a dedicated invoker SA has `run.invoker`, and only the agent's principal has `roles/iam.serviceAccountOpenIdTokenCreator` on it. The agent calls `generateIdToken` for each MCP session.
- A `resource.name` IAM condition on `run.invoker` did not take effect in testing. The sandbox grants it project-wide to the dedicated SA. In production, bind it on the service.
- When an MCP server can't be reached, ADK silently drops its tools. The agent just reports that it has no such tool, so a gateway or auth failure looks like a missing feature. Check the agent logs for `Failed to create MCP session`.

**9. Registry and gateway details the SOW should account for.**
- The gateway matches registry entries on the exact URL. Our MCP server was first registered with the legacy `*-uc.a.run.app` URL that Cloud Run reports, so all its traffic showed as `unregisteredEndpoint` until it was re-registered with the URL the agent calls.
- Creating an authz policy while its extension is still provisioning returns success, but the operation fails silently and the policy never exists. The Model Armor policy was missing for an hour before we noticed.
- Switching the IAP policy from dry-run to enforced took about 3.5 minutes to apply.
- Under enforcement, the agent's Gemini, telemetry, IAM credentials and resource manager calls all need registered endpoints and an `iap.egressor` grant. The list came from the gateway's own dry-run logs (`13_gateway_decisions.sh`), which is the practical way to build it.
- Agent Engine defaults keep a warm instance per agent. Set `min_instances=0` for non-prod fleets.

**8. Other gotchas.**
- The shared sandbox is out of `global` Discovery Engine data store quota, so the replica uses `us`.
- `mcp` 2.x renamed `FastMCP` (we pinned `mcp<2`).
- The `vertexai` SDK's `stream_query` fails to parse some concatenated stream chunks (`07_ask.py` uses REST instead).

## Not done yet

- Attaching the agents to a Gemini Enterprise app, to test the SOW's "GE tool traffic routes through Agent Gateway" claim.
- Internal-only and EVV content rules. Model Armor can't do these; they need separate data stores or ACLs per content tier.

## Run order

```bash
export WSKY_KEY_FILE=<path for decoded SA key>; source env.sh
./01_gateway.sh; ./02_mcp_onspring.sh; ./03_register_mcp.sh; ./04_discovery_engine.sh
python 05_deploy_agents.py baseline; python 05_deploy_agents.py governed
./06_model_armor_and_policies.sh            # ./06_model_armor_and_policies.sh enforce|dryrun to switch IAP mode
./08_grant_de_access.sh <reasoningEngine id>
./10_mcp_invoker.sh <governed id>; ./11_register_endpoints.sh; ./12_grant_egress.sh <governed id>
./14_phi_template.sh
./06_model_armor_and_policies.sh enforce
PY=<venv python> ./15_demo.sh
python 07_ask.py <reasoningEngine name> "Call search_kb_mtls with query 'Texas EVV'"
./09_model_armor_test.sh
./99_teardown.sh                             # removes only wsky-* resources
```
