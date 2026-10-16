"""WellSky replica agent: Discovery Engine search, Onspring MCP and egress probes.

Every tool returns raw errors rather than hiding them, because the point of the
replica is to see exactly what the runtime identity and the gateway allow.
"""
import os

import google.auth
import google.auth.transport.requests
import requests
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

PROJECT = os.environ.get("WSKY_PROJECT", "project-amer-scs-sandbox")
DE_LOC = os.environ.get("WSKY_DE_LOC", "us")
ENGINE = os.environ.get("WSKY_ENGINE", "wsky-kb-search")
MCP_URL = os.environ.get("WSKY_MCP_URL", "")
MCP_PRIVATE_URL = os.environ.get("WSKY_MCP_PRIVATE_URL", "")  # internal-only Cloud Run, reached via gateway PSC


def _session():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def whoami() -> dict:
    """Report the identity this agent runs as (service account or agent identity principal)."""
    creds = _session()
    info = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": creds.token}, timeout=10)
    return {"credential_type": type(creds).__name__,
            "service_account_email": getattr(creds, "service_account_email", None),
            "tokeninfo_status": info.status_code, "tokeninfo": info.json() if info.ok else info.text[:300]}


def search_kb(query: str) -> dict:
    """Search the WellSky knowledge base (Discovery Engine) for support and EVV content."""
    creds = _session()
    url = (f"https://{DE_LOC}-discoveryengine.googleapis.com/v1/projects/{PROJECT}/locations/{DE_LOC}"
           f"/collections/default_collection/engines/{ENGINE}/servingConfigs/default_search:search")
    r = requests.post(url, headers={"Authorization": f"Bearer {creds.token}", "X-Goog-User-Project": PROJECT},
                      json={"query": query, "pageSize": 3,
                            "contentSearchSpec": {"snippetSpec": {"returnSnippet": True}}}, timeout=30)
    if not r.ok:
        return {"status": r.status_code, "error": r.text[:800]}
    results = r.json().get("results", [])
    return {"status": 200, "results": [
        {"uri": x["document"].get("derivedStructData", {}).get("link"),
         "snippets": [s.get("snippet") for s in x["document"].get("derivedStructData", {}).get("snippets", [])]}
        for x in results]}


def search_kb_client_lib(query: str) -> dict:
    """Search the knowledge base using the official google-cloud-discoveryengine client library."""
    from google.api_core.client_options import ClientOptions
    from google.cloud import discoveryengine_v1 as de
    try:
        # Let the library pick the mTLS endpoint from GOOGLE_API_CERTIFICATE_CONFIG instead of forcing a plain host.
        os.environ.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "true")
        client = de.SearchServiceClient(client_options=ClientOptions(
            api_endpoint=f"{DE_LOC}-discoveryengine.mtls.googleapis.com"))
        serving = (f"projects/{PROJECT}/locations/{DE_LOC}/collections/default_collection"
                   f"/engines/{ENGINE}/servingConfigs/default_search")
        resp = client.search(de.SearchRequest(serving_config=serving, query=query, page_size=3))
        return {"status": 200, "endpoint": client.api_endpoint,
                "results": [r.document.derived_struct_data.get("link") for r in resp.results]}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:800]}


def search_kb_mtls(query: str, host: str = "") -> dict:
    """Search the knowledge base over mTLS using the agent's SPIFFE certificate. host defaults to the regional mTLS endpoint."""
    host = host or f"{DE_LOC}-discoveryengine.mtls.googleapis.com"
    base = "/var/run/secrets/workload-spiffe-credentials"
    creds = _session()
    url = (f"https://{host}/v1/projects/{PROJECT}/locations/{DE_LOC}"
           f"/collections/default_collection/engines/{ENGINE}/servingConfigs/default_search:search")
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {creds.token}", "X-Goog-User-Project": PROJECT},
                          json={"query": query, "pageSize": 3}, timeout=30,
                          cert=(f"{base}/certificates.pem", f"{base}/private_key.pem"))
    except Exception as e:
        return {"host": host, "error": f"{type(e).__name__}: {e}"[:500]}
    if not r.ok:
        return {"host": host, "status": r.status_code, "error": r.text[:600]}
    return {"host": host, "status": 200,
            "results": [x["document"].get("derivedStructData", {}).get("link") for x in r.json().get("results", [])]}


def runtime_env() -> dict:
    """Show the runtime's certificate/mTLS configuration and identity-related environment variables."""
    keys = [k for k in os.environ if any(t in k for t in ("CERT", "MTLS", "GOOGLE_API", "SPIFFE", "WORKLOAD", "AGENT"))]
    out = {k: os.environ[k][:200] for k in keys}
    cfg = os.environ.get("GOOGLE_API_CERTIFICATE_CONFIG")
    if cfg and os.path.exists(cfg):
        out["certificate_config"] = open(cfg).read()[:600]
    for d in ("/var/run/secrets", "/run/secrets", "/var/run/secrets/workload-spiffe-credentials"):
        if os.path.isdir(d):
            out[f"ls {d}"] = os.listdir(d)
    return out


def probe_url(url: str) -> dict:
    """Make an unauthenticated GET to a URL to test whether egress to it is allowed."""
    try:
        r = requests.get(url, timeout=15)
        return {"status": r.status_code, "body": r.text[:200]}
    except Exception as e:  # surface the network error verbatim
        return {"error": f"{type(e).__name__}: {e}"[:500]}


MCP_INVOKER_SA = os.environ.get("WSKY_MCP_INVOKER_SA", "")


def _mcp_headers(_ctx, url: str = "") -> dict:
    """Cloud Run needs an ID token. Agent Identity can't mint one for itself, so the agent's principal
    asks IAM Credentials for an ID token of a dedicated invoker SA (roles/iam.serviceAccountOpenIdTokenCreator)."""
    audience = (url or MCP_URL).rsplit("/mcp", 1)[0]
    try:
        creds = _session()
        r = requests.post(
            f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{MCP_INVOKER_SA}:generateIdToken",
            headers={"Authorization": f"Bearer {creds.token}"},
            json={"audience": audience, "includeEmail": True}, timeout=15)
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['token']}"}
    except Exception as e:
        return {"X-Wsky-IdToken-Error": f"{type(e).__name__}: {e}"[:200]}


def mcp_auth_debug() -> dict:
    """Show whether the agent could mint an ID token for the Onspring MCP server (token value masked)."""
    h = _mcp_headers(None)
    if "Authorization" in h:
        import base64, json as _j
        payload = h["Authorization"].split(".")[1]
        claims = _j.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return {"minted": True, "claims": {k: claims.get(k) for k in ("aud", "email", "iss")}}
    return {"minted": False, **h}


tools = [mcp_auth_debug, whoami, runtime_env, search_kb, search_kb_client_lib, search_kb_mtls, probe_url]
if MCP_URL:
    tools.append(McpToolset(connection_params=StreamableHTTPConnectionParams(url=MCP_URL, timeout=30),
                            header_provider=_mcp_headers, tool_name_prefix="onspring"))
if MCP_PRIVATE_URL:
    tools.append(McpToolset(connection_params=StreamableHTTPConnectionParams(url=MCP_PRIVATE_URL, timeout=30),
                            header_provider=lambda ctx: _mcp_headers(ctx, MCP_PRIVATE_URL),
                            tool_name_prefix="onspring_private"))

root_agent = Agent(
    name="wsky_agent",
    model="gemini-2.5-flash",
    instruction=(
        "You are a WellSky internal support agent used for governance testing. "
        "Always call the tool the user asks for and return the tool's raw output, including any error, "
        "status code and identity details, verbatim in your answer. Never reveal patient identifiers."),
    tools=tools,
)
