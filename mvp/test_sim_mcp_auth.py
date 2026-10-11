"""Oct 11: /mcp always needs the bearer token; the study view stays public by unguessable id, like the website.

Live check (read-only, Oct 11): https://usersim.vercel.app/api/studies/<random uuid> answers 404 "Study not found"
without any auth, and the watch link handed to humans is /?study=<id>. So the study JSON is public by id on the
website, and the MCP side server serves the same route the same way. Only /mcp is guarded.
"""
from __future__ import annotations

import importlib
import os
import unittest
from unittest import mock


def _app(env: dict[str, str]):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from mvp.sim_mcp import server as SV

    app = FastAPI()

    @app.get("/api/studies/{study_id}")
    async def study(study_id: str):  # stands in for the website's public study view
        return {"id": study_id}

    with mock.patch.dict(os.environ, env, clear=False):
        for k in ("MVP_MCP_TOKEN", "MVP_MCP_TOKEN_FILE", "MVP_MCP_ALLOW_OPEN"):
            if k not in env:
                os.environ.pop(k, None)
        importlib.reload(SV)
        SV.mount(app)
    return TestClient(app)


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class McpAuthTests(unittest.TestCase):
    def test_no_token_and_wrong_token_rejected(self):
        c = _app({"MVP_MCP_TOKEN": "s3cret-token"})
        self.assertEqual(c.post("/mcp", json=INIT, headers=HDR).status_code, 401)
        self.assertEqual(c.post("/mcp", json=INIT, headers={**HDR, "Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(c.post("/mcp", json=INIT, headers={**HDR, "Authorization": "Basic s3cret-token"}).status_code, 401)
        self.assertEqual(c.get("/mcp", headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(c.delete("/mcp").status_code, 401)

    def test_right_token_reaches_mcp(self):
        with _app({"MVP_MCP_TOKEN": "s3cret-token"}) as c:  # context runs startup (MCP session manager)
            r = c.post("/mcp", json=INIT, headers={**HDR, "Authorization": "Bearer s3cret-token"})
            self.assertEqual(r.status_code, 200)

    def test_unset_token_fails_closed(self):
        c = _app({})
        self.assertEqual(c.post("/mcp", json=INIT, headers=HDR).status_code, 401)
        self.assertEqual(c.post("/mcp", json=INIT, headers={**HDR, "Authorization": "Bearer "}).status_code, 401)

    def test_study_view_public_by_id_like_the_website(self):
        c = _app({"MVP_MCP_TOKEN": "s3cret-token"})
        self.assertEqual(c.get("/api/studies/0b9d1d5e-0000-4000-8000-000000000000").status_code, 200)
