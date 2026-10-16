"""Deploy the non-ADK PlainAgent to Agent Runtime with Agent Identity, bound to the egress gateway."""
import os
import sys

import vertexai
from vertexai import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "agent"))
os.chdir(os.path.join(HERE, "agent"))
from plain_agent import PlainAgent  # noqa: E402

PROJECT, REGION, PROJECT_NUMBER = "project-amer-scs-sandbox", "us-central1", "347838016394"
client = vertexai.Client(project=PROJECT, location=REGION)
remote = client.agent_engines.create(agent=PlainAgent(), config={
    "display_name": "wsky-plain-agent",
    "description": "WellSky replica: non-ADK agent behind Agent Gateway. Synthetic.",
    "staging_bucket": f"gs://wsky-replica-{PROJECT_NUMBER}",
    "requirements": ["google-cloud-aiplatform[agent_engines]", "google-genai"],
    "extra_packages": ["plain_agent.py"],
    "identity_type": types.IdentityType.AGENT_IDENTITY,
    "min_instances": 0, "max_instances": 1, "resource_limits": {"cpu": "1", "memory": "2Gi"},
    "labels": {"owner": "searce-sc", "purpose": "wellsky-replica"},
    "env_vars": {"GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES": "false"},
    "agent_gateway_config": {"agent_to_anywhere_config": {
        "agent_gateway": f"projects/{PROJECT}/locations/{REGION}/agentGateways/wsky-egress-gw"}},
})
print("RESOURCE", remote.api_resource.name)
print("IDENTITY", remote.api_resource.spec.effective_identity)
