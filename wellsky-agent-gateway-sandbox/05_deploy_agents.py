"""Deploy replica agents to Agent Platform Runtime (Agent Engine) with Agent Identity.

  python 05_deploy_agents.py baseline   # agent identity, no gateway (WellSky's DE agent today)
  python 05_deploy_agents.py governed   # agent identity + egress through wsky-egress-gw
  WSKY_UPDATE=<reasoningEngine name> python 05_deploy_agents.py <mode>   # update in place
"""
import os
import sys

import vertexai
from vertexai import types
from vertexai.agent_engines import AdkApp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "agent"))
os.chdir(os.path.join(HERE, "agent"))

PROJECT, REGION = "project-amer-scs-sandbox", "us-central1"
PROJECT_NUMBER = "347838016394"
MCP_URL = "https://wsky-mcp-onspring-347838016394.us-central1.run.app/mcp"
GATEWAY = f"projects/{PROJECT}/locations/{REGION}/agentGateways/wsky-egress-gw"

mode = sys.argv[1]
os.environ["WSKY_MCP_URL"] = MCP_URL
from wsky_agent import root_agent  # noqa: E402  (needs WSKY_MCP_URL set first)

client = vertexai.Client(project=PROJECT, location=REGION)
config = {
    "display_name": f"wsky-{mode}-agent",
    "description": f"WellSky replica ({mode}). Synthetic data only.",
    "staging_bucket": f"gs://wsky-replica-{PROJECT_NUMBER}",
    "requirements": "requirements.txt",
    "extra_packages": ["wsky_agent.py"],
    "identity_type": types.IdentityType.AGENT_IDENTITY,
    # Cost guard for the sandbox: scale to zero when idle, one small instance at most.
    "min_instances": 0,
    "max_instances": 1,
    "resource_limits": {"cpu": "1", "memory": "2Gi"},
    "labels": {"owner": "searce-sc", "purpose": "wellsky-replica"},
    "env_vars": {"WSKY_MCP_URL": MCP_URL, "WSKY_MCP_INVOKER_SA": f"wsky-mcp-invoker@{PROJECT}.iam.gserviceaccount.com", "WSKY_DE_LOC": "us", "WSKY_ENGINE": "wsky-kb-search",
                 "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
                 "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "EVENT_ONLY",
                 "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true"},
}
if mode == "governed":
    config["agent_gateway_config"] = {"agent_to_anywhere_config": {"agent_gateway": GATEWAY}}
    # Without this, every Google API call through the gateway (including Gemini) fails with 401:
    # Agent Identity tokens are bound to the agent's mTLS cert by default, and the gateway re-originates TLS.
    # Google's own Agent Gateway codelabs set the same flag (--allow-token-sharing). It disables token binding.
    if os.environ.get("WSKY_ALLOW_TOKEN_SHARING", "true") == "true":
        config["env_vars"]["GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES"] = "false"

existing = os.environ.get("WSKY_UPDATE")  # reasoningEngine name to update in place
if existing:
    remote = client.agent_engines.update(name=existing, agent=AdkApp(agent=root_agent), config=config)
else:
    remote = client.agent_engines.create(agent=AdkApp(agent=root_agent), config=config)
print("RESOURCE", remote.api_resource.name)
print("IDENTITY", remote.api_resource.spec.effective_identity)
