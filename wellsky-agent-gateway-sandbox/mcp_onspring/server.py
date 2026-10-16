"""Read-only mock of WellSky's in-house Onspring MCP server (synthetic data only)."""
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("onspring-mock", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), stateless_http=True)

RECORDS = {
    "GOV-101": {"title": "EVV rules - Texas", "owner": "Support Ops", "status": "Approved", "tier": "internal"},
    "GOV-102": {"title": "EVV rules - Ohio", "owner": "Support Ops", "status": "Draft", "tier": "internal"},
    "GOV-201": {"title": "Vendor risk review - Salesforce", "owner": "IT Security", "status": "Approved", "tier": "internal"},
    "GOV-301": {"title": "AI agent intake - First Responder", "owner": "AI CoE", "status": "In Review", "tier": "solution"},
}


@mcp.tool()
def list_governance_records(status: str | None = None) -> list[dict]:
    """List Onspring governance records, optionally filtered by status (Approved, Draft, In Review)."""
    return [{"id": k, **v} for k, v in RECORDS.items() if status is None or v["status"] == status]


@mcp.tool()
def get_governance_record(record_id: str) -> dict:
    """Get one Onspring governance record by id, e.g. GOV-101."""
    return {"id": record_id, **RECORDS[record_id]} if record_id in RECORDS else {"error": "not found"}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
