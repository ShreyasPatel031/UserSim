"""MCP server: one tool, predict_experience(product_url, person...) -> per-output data chosen by the router.

Run (stdio):  python experiments/staged_context/ux_mcp_server.py
Register in an MCP client, e.g. Claude Code:
    claude mcp add ux-experience -- python /path/to/UserSim/experiments/staged_context/ux_mcp_server.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402
import ux_mcp as U  # noqa: E402

mcp = FastMCP("ux-experience")


@mcp.tool()
def predict_experience(product_url: str, job_title: str, industry: str, company_size: str, time_used: str,
                       task: str = "not stated", previous_product: str = "not stated") -> dict:
    """Data for predicting how a specific person will experience a software product.

    company_size: one of Self-employed, 1-10 employees, 11-50 employees, 51-200 employees, 201-500 employees,
      501-1,000 employees, 1,001-5,000 employees, 5,001-10,000 employees, 10,001+ employees.
    time_used: one of I used a free trial, Less than 6 months, 6-12 months, 1-2 years, 2+ years.
    Returns, per output (ratings, recommend score, pros, cons, overall experience, unhappy risk), either an estimate
    to use directly or the context to reason from, whichever tested best for that output.
    """
    person = {"role_family": E.role_family(job_title), "company_size": company_size, "time_used": time_used,
              "industry": industry}
    out = U.respond(product_url, person)
    out["person"] = {**person, "job_title": job_title, "task": task, "previous_product": previous_product}
    return out


if __name__ == "__main__":
    mcp.run()
