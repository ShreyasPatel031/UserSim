"""Product Surface & Real Camoufox MCP CUA Trace Runner.

Provides two leak-sanitized product inspection tiers that materialize `CUA_TRACES`:
1. `inspect_http_and_cached`:
   - Uses launch-era `sites_ph.jsonl` scrapes where clean (zero post-launch drift), and fetches
     live HTML asynchronously for unscraped resolved URLs (e.g. Nov 2026 `sites_0005.json`),
     passing every byte through `sanitizer.parse_html_surface(..., item_day=day)` to strip PH
     badges, upvote strings, social-proof counters, and post-D dates.
2. `run_camoufox_cua_batch`:
   - Connects directly to the UserSim Camoufox MCP server (`https://35-202-98-224.sslip.io/mcp`,
     `producthunt.com` blocked in browser context) and drives multi-step real browser sessions
     with multimodal `gemini-2.5-pro` (`usersim_start_session` -> `usersim_observe` -> `usersim_act`
     -> `usersim_finish`).
   - Strictly enforces safety & harness hygiene: NEVER calls `usersim_solve_captcha` or attempts
     to bypass anti-bot challenges; any `captcha` / Turnstile / block immediately finishes with
     `access_status="captcha"` (`0.0` residual shift over structural baseline).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import asdict
from typing import Any

import httpx
import pandas as pd

from simharness.models.llm import Budget, JsonlCache, _VertexAuth
import usersim_core.cohort_sim  # noqa: F401 - installs _sa_vertex_token into _VertexAuth.token
from usersim_core.sanitizer import SanitizedSurface, parse_html_surface, sanitize_text, surface_from_cached_scrape

MCP_DEFAULT_URL = "https://35-202-98-224.sslip.io/mcp"
_CAPTCHA_WORDS_RE = re.compile(
    r"\b(captcha|recaptcha|hcaptcha|turnstile|verify\s+you\s+are\s+human|are\s+you\s+a\s+robot|cloudflare\s+ray\s+id)\b",
    re.IGNORECASE,
)


def _load_mcp_token_from_secret(project: str = "project-amer-scs-sandbox") -> str:
    """Load MCP bearer token in-memory from Secret Manager without ever logging or printing it."""
    if os.environ.get("MCP_CLIENT_TOKEN"):
        return os.environ["MCP_CLIENT_TOKEN"].strip()
    r = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=usersim-MVP_MCP_TOKEN", f"--project={project}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return ""
    toks = [x for x in re.split(r"[ ,]+", r.stdout.strip()) if x]
    return toks[0].split("=", 1)[-1] if toks else ""


def _strip_ph_ref(url: str) -> str:
    """Remove ?ref=producthunt / utm_source=producthunt query params before live fetch."""
    if not url:
        return ""
    u = re.sub(r"([?&])(ref|utm_source|utm_medium|utm_campaign)=producthunt[^&#]*", r"\1", url, flags=re.IGNORECASE)
    u = re.sub(r"\?&+", "?", u)
    return u.rstrip("?&")


async def _fetch_one_html(client: httpx.AsyncClient, url: str) -> tuple[int, float, str]:
    clean_u = _strip_ph_ref(url)
    if not clean_u or "producthunt.com" in clean_u.lower():
        return -1, 0.0, ""
    t0 = time.time()
    try:
        r = await client.get(clean_u, follow_redirects=True)
        ms = (time.time() - t0) * 1000.0
        if "producthunt.com" in str(r.url).lower():
            return -1, ms, ""
        ct = (r.headers.get("content-type") or "").lower()
        if "text/html" not in ct and "application/xhtml" not in ct and "text/plain" not in ct:
            return r.status_code, ms, ""
        return r.status_code, ms, r.text[:180000]
    except Exception:  # noqa: BLE001
        return -1, (time.time() - t0) * 1000.0, ""


def inspect_surfaces_for_items(
    items: list[dict[str, Any]],
    sites_by_id: dict[str, dict],
    daily_urls: dict[str, str],
    product_urls_by_name: dict[str, str],
    cache: JsonlCache,
    concurrency: int = 24,
) -> dict[str, SanitizedSurface]:
    """Resolve URLs & obtain leak-sanitized product surfaces for shortlist items (cached on disk)."""
    out: dict[str, SanitizedSurface] = {}
    to_fetch: list[tuple[str, str, str]] = []  # (item_id, day, url)

    for it in items:
        lid = str(it["item_id"])
        day = str(it["day"])
        ckey = ("surface_v1", lid, day)
        if ckey in cache:
            d = cache[ckey]
            out[lid] = SanitizedSurface(**d)
            continue

        rec = sites_by_id.get(lid)
        # Prefer launch-era cached scrape if it succeeded cleanly
        if rec and rec.get("url"):
            surf = surface_from_cached_scrape(rec, item_day=day)
            if surf.access_status == "clean":
                cache[ckey] = asdict(surf)
                out[lid] = surf
                continue

        # Otherwise resolve URL from sites_0005 -> sites_ph -> exact product table match
        url = (
            daily_urls.get(lid)
            or (str(rec.get("url")) if rec and rec.get("url") else "")
            or product_urls_by_name.get(str(it.get("title", "")).strip().lower(), "")
        )
        url = _strip_ph_ref(url)
        if not url or "producthunt.com" in url.lower():
            surf = SanitizedSurface(
                url="", http_status=-1, load_ms=0.0, access_status="no_url", product_trait="none",
                badges_stripped_n=0, has_interactive_demo=False, has_free_tier=False, has_open_source=False,
                has_visible_pricing=False, has_docs=False, is_waitlist=False, is_enterprise_gated=False,
                is_platform_only=False, cta_texts=[], sanitized_text="",
            )
            cache[ckey] = asdict(surf)
            out[lid] = surf
        else:
            to_fetch.append((lid, day, url))

    if to_fetch:
        async def _run_fetches() -> list[tuple[str, str, str, int, float, str]]:
            sem = asyncio.Semaphore(concurrency)
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), headers=headers, verify=False) as client:
                async def _one(lid: str, day: str, u: str):
                    async with sem:
                        st, ms, html = await _fetch_one_html(client, u)
                        return (lid, day, u, st, ms, html)
                return await asyncio.gather(*[_one(lid, d, u) for lid, d, u in to_fetch])

        fetched = asyncio.run(_run_fetches())
        for lid, day, u, st, ms, html in fetched:
            if html and _CAPTCHA_WORDS_RE.search(html[:4000]) and len(html) < 12000:
                surf = SanitizedSurface(
                    url=u, http_status=st, load_ms=ms, access_status="captcha", product_trait="none",
                    badges_stripped_n=0, has_interactive_demo=False, has_free_tier=False, has_open_source=False,
                    has_visible_pricing=False, has_docs=False, is_waitlist=False, is_enterprise_gated=False,
                    is_platform_only=False, cta_texts=[], sanitized_text="",
                )
            else:
                surf = parse_html_surface(html, url=u, http_status=st, load_ms=ms, item_day=day)
            cache[("surface_v1", lid, day)] = asdict(surf)
            out[lid] = surf

    cache.roll()
    return out


class CamoufoxCUARunner:
    """Real multi-step browser CUA runner via UserSim MCP driven by multimodal `gemini-2.5-pro`."""

    def __init__(
        self,
        budget: Budget,
        cache: JsonlCache,
        project: str = "project-amer-scs-sandbox",
        mcp_url: str = MCP_DEFAULT_URL,
        driver_model: str = "gemini-2.5-pro",
    ):
        self.budget = budget
        self.cache = cache
        self.project = project
        self.mcp_url = mcp_url
        self.driver_model = driver_model
        self._mcp_token = _load_mcp_token_from_secret(project)
        self.price_in, self.price_out = (1.25, 10.00)  # gemini-2.5-pro list USD / 1M tokens
        self.cost_usd = 0.0
        self.calls = 0

    def _mcp_call(self, client: httpx.Client, headers: dict, method_name: str, args: dict) -> list[dict]:
        resp = client.post(
            self.mcp_url,
            headers=headers,
            json={"jsonrpc": "2.0", "id": int(time.time() * 1000) % 1000000, "method": "tools/call",
                  "params": {"name": method_name, "arguments": args}},
        )
        resp.raise_for_status()
        txt = resp.text
        for line in txt.splitlines():
            if line.startswith("data:"):
                txt = line[5:].strip()
                break
        j = json.loads(txt)
        if "error" in j:
            raise RuntimeError(f"MCP {method_name} error: {j['error']}")
        return j.get("result", {}).get("content", [])

    def _ask_pro_next_action(self, item: dict, persona_brief: str, obs_text: str, obs_img_b64: str | None, obs_mime: str, step_idx: int, max_steps: int) -> dict:
        """Multimodal Gemini 2.5 Pro step planner over screenshot + sanitized DOM state."""
        worst = 0.025
        self.budget.reserve(worst)
        prompt = (
            f"You are evaluating a software product as a discerning user (Step {step_idx + 1} of {max_steps}).\n"
            f"USER PROFILE:\n{persona_brief[:700]}\n\n"
            f"PRODUCT CLAIMED AT LAUNCH:\nName: {item['title']}\nTagline: {item['summary']}\n\n"
            f"SANITIZED BROWSER OBSERVATION:\n{obs_text[:1800]}\n\n"
            "RULES:\n"
            "1. Never solve or click any CAPTCHA / human-verification challenge; if one is visible, immediately return finish with access_status='captcha'.\n"
            "2. Try to reach the product's core interactive demo, playground, live docs/code, or pricing page without creating a paid account.\n"
            "3. If this is the final step OR you have clearly verified whether an instant value moment exists vs a signup/waitlist/enterprise wall, return action='finish'.\n"
            "Reply in JSON ONLY:\n"
            '{"action": "click"|"scroll"|"finish", "x": <int or null>, "y": <int or null>, "dy": <int or null>, '
            '"thought": "<1 sentence>", "access_status": "clean"|"signup_wall"|"captcha"|"block", '
            '"has_interactive_demo": true|false, "has_free_tier": true|false, "reached_value_moment": true|false, '
            '"product_trait": "instant_demo"|"free_tier"|"waitlist_only"|"card_required"|"platform_only"|"none", '
            '"digest": "<concise factual summary of what actually works vs friction on the live product>"}'
        )
        parts: list[dict] = []
        if obs_img_b64:
            parts.append({"inlineData": {"mimeType": obs_mime or "image/jpeg", "data": obs_img_b64}})
        parts.append({"text": prompt})

        url = f"https://aiplatform.googleapis.com/v1/projects/{self.project}/locations/global/publishers/google/models/{self.driver_model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 450,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 128},
            },
        }
        try:
            r = httpx.post(
                url,
                json=body,
                timeout=45.0,
                headers={"Authorization": f"Bearer {_VertexAuth.token()}", "Content-Type": "application/json"},
            )
            r.raise_for_status()
            d = r.json()
            u = d.get("usageMetadata", {})
            ti = int(u.get("promptTokenCount", 0))
            to = int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
            actual = ti * self.price_in / 1e6 + to * self.price_out / 1e6
            self.cost_usd += actual
            self.calls += 1
            self.budget.settle(f"cua:{self.driver_model}", worst, actual)
            out_txt = "".join(p.get("text", "") for p in ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            m = re.search(r"\{.*\}", out_txt, re.S)
            return json.loads(m.group(0)) if m else {"action": "finish", "access_status": "engine", "digest": ""}
        except Exception as exc:  # noqa: BLE001
            self.budget.settle(f"cua:{self.driver_model}", worst, 0.0)
            return {"action": "finish", "access_status": "engine", "digest": f"error: {type(exc).__name__}"}

    def run_session(self, item: dict, url: str, user: dict, max_steps: int = 3) -> dict:
        """Execute a real Camoufox CUA browser session (or read from cache) and return a CUA_TRACES dict."""
        lid = str(item["item_id"])
        day = str(item["day"])
        uid = str(user["global_user_id"])
        ckey = ("cua_v1", lid, day, uid)
        if ckey in self.cache:
            return self.cache[ckey]

        clean_u = _strip_ph_ref(url)
        trace_id = "cua_" + hashlib.md5(f"{lid}:{day}:{uid}".encode()).hexdigest()[:12]
        t0 = time.time()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._mcp_token:
            headers["Authorization"] = f"Bearer {self._mcp_token}"

        steps_log: list[dict] = []
        total_stripped = 0
        session_id = ""
        final_decision: dict[str, Any] = {
            "access_status": "engine",
            "product_trait": "none",
            "has_interactive_demo": False,
            "has_free_tier": False,
            "reached_value_moment": False,
            "digest": "",
        }
        error_steps = 0
        steps_to_val = None

        try:
            with httpx.Client(timeout=60.0) as client:
                init_r = client.post(
                    self.mcp_url,
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "usersim_core_cua", "version": "1.0"}}},
                )
                if init_r.headers.get("mcp-session-id"):
                    headers["mcp-session-id"] = init_r.headers["mcp-session-id"]

                start_blocks = self._mcp_call(
                    client,
                    headers,
                    "usersim_start_session",
                    {
                        "product_url": clean_u,
                        "task": f"Inspect {item['title']} ({item['summary']}) and try its core workflow, interactive demo, or pricing/docs without paying.",
                        "persona": f"Discerning tech user ({uid}, critique_rate={user['critique_rate']})",
                    },
                )
                start_txt = " ".join(b.get("text", "") for b in start_blocks if b.get("type") == "text")
                m_sid = re.search(r'"session_id"\s*:\s*"([^"]+)"', start_txt)
                session_id = m_sid.group(1) if m_sid else ""
                load_ms = (time.time() - t0) * 1000.0

                if not session_id:
                    final_decision["access_status"] = "engine"
                else:
                    for s_idx in range(max_steps):
                        obs_blocks = self._mcp_call(client, headers, "usersim_observe", {"session_id": session_id})
                        raw_obs_txt = "\n".join(b.get("text", "") for b in obs_blocks if b.get("type") == "text")
                        img_b64, img_mime = None, "image/jpeg"
                        for b in obs_blocks:
                            if b.get("type") == "image" and b.get("data"):
                                img_b64 = b["data"]
                                img_mime = b.get("mimeType", "image/jpeg")
                                break

                        # Immediate CAPTCHA check: NEVER solve or click through!
                        if '"captcha": true' in raw_obs_txt.lower() or _CAPTCHA_WORDS_RE.search(raw_obs_txt[:1500]):
                            final_decision["access_status"] = "captcha"
                            steps_log.append({"step": s_idx, "event": "captcha_abort"})
                            break

                        clean_obs, n_st = sanitize_text(raw_obs_txt, item_day=day)
                        total_stripped += n_st
                        force_finish = (s_idx == max_steps - 1)
                        dec = self._ask_pro_next_action(
                            item=item,
                            persona_brief=user["history_brief"],
                            obs_text=clean_obs,
                            obs_img_b64=img_b64,
                            obs_mime=img_mime,
                            step_idx=s_idx,
                            max_steps=max_steps,
                        )
                        final_decision = dec
                        if dec.get("reached_value_moment") and steps_to_val is None:
                            steps_to_val = float(s_idx + 1)

                        act = str(dec.get("action") or "finish").lower()
                        steps_log.append({
                            "step": s_idx + 1,
                            "action": act,
                            "thought": str(dec.get("thought") or "")[:180],
                            "reached_value": bool(dec.get("reached_value_moment")),
                        })
                        if force_finish or act == "finish" or dec.get("access_status") in ("captcha", "block"):
                            break

                        act_args: dict[str, Any] = {"session_id": session_id, "thought": str(dec.get("thought") or "inspect")}
                        if act == "click" and dec.get("x") is not None and dec.get("y") is not None:
                            act_args.update({"action": "click", "x": int(dec["x"]), "y": int(dec["y"])})
                        else:
                            act_args.update({"action": "scroll", "dy": int(dec.get("dy") or 550)})
                        try:
                            self._mcp_call(client, headers, "usersim_act", act_args)
                        except Exception:  # noqa: BLE001
                            error_steps += 1

                    try:
                        self._mcp_call(
                            client,
                            headers,
                            "usersim_finish",
                            {"session_id": session_id, "outcome": "completed", "notes": str(final_decision.get("digest") or "")[:240]},
                        )
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as exc:  # noqa: BLE001
            load_ms = (time.time() - t0) * 1000.0
            final_decision["access_status"] = "engine"
            final_decision["digest"] = f"session_error: {type(exc).__name__}"

        clean_digest, n_d = sanitize_text(str(final_decision.get("digest") or ""), item_day=day)
        total_stripped += n_d
        acc = str(final_decision.get("access_status") or "engine")
        if acc not in ("clean", "signup_wall", "captcha", "block", "js_only", "timeout", "engine", "dead_host", "no_url"):
            acc = "clean"
        trait = str(final_decision.get("product_trait") or "none")
        if trait not in ("none", "instant_demo", "free_tier", "card_required", "onboarding_broken", "platform_only", "waitlist_only"):
            trait = "none"

        row = {
            "trace_id": trace_id,
            "domain": "producthunt",
            "item_id": lid,
            "day": day,
            "global_user_id": uid,
            "url": clean_u,
            "driver_model": self.driver_model,
            "leak_sanitized": True,
            "badges_stripped_n": int(total_stripped),
            "access_status": acc,
            "product_trait": trait,
            "http_status": 200 if session_id else -1,
            "load_ms": round(float(load_ms), 1),
            "has_interactive_demo": bool(final_decision.get("has_interactive_demo")),
            "has_free_tier": bool(final_decision.get("has_free_tier")),
            "has_open_source": "github.com/" in clean_u.lower(),
            "reached_value_moment": bool(final_decision.get("reached_value_moment")),
            "steps_to_value": steps_to_val,
            "n_steps": int(len(steps_log)),
            "error_steps": int(error_steps),
            "sanitized_digest": clean_digest[:600],
            "steps_json": json.dumps(steps_log),
            "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }
        self.cache[ckey] = row
        self.cache.roll()
        return row


def surfaces_to_cua_traces_df(
    items: list[dict[str, Any]],
    surfaces: dict[str, SanitizedSurface],
    camoufox_rows: list[dict] | None = None,
    domain: str = "producthunt",
) -> pd.DataFrame:
    """Combine HTTP/cached SanitizedSurface rows + multi-step Camoufox CUA rows into schema-validated CUA_TRACES."""
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = []
    for it in items:
        lid = str(it["item_id"])
        day = str(it["day"])
        s = surfaces.get(lid)
        if s is None:
            continue
        rows.append({
            "trace_id": f"surf_{lid}_{day}",
            "domain": domain,
            "item_id": lid,
            "day": day,
            "global_user_id": "probe:http_sanitized_v1",
            "url": s.url,
            "driver_model": "http_sanitizer_v1",
            "leak_sanitized": True,
            "badges_stripped_n": int(s.badges_stripped_n),
            "access_status": s.access_status,
            "product_trait": s.product_trait,
            "http_status": int(s.http_status),
            "load_ms": float(s.load_ms),
            "has_interactive_demo": bool(s.has_interactive_demo),
            "has_free_tier": bool(s.has_free_tier),
            "has_open_source": bool(s.has_open_source),
            "reached_value_moment": bool(s.has_interactive_demo or s.has_open_source),
            "steps_to_value": 1.0 if (s.has_interactive_demo or s.has_open_source) else None,
            "n_steps": 1,
            "error_steps": 0,
            "sanitized_digest": s.sanitized_text[:800],
            "steps_json": json.dumps([{"ctas": s.cta_texts[:8]}]),
            "frozen_at": now_iso,
        })
    if camoufox_rows:
        rows.extend(camoufox_rows)
    return pd.DataFrame(rows)
