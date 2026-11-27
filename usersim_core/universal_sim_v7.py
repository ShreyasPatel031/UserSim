"""Domain-Agnostic Multi-Family Universal User Simulator (`usersim_core/universal_sim_v7.py`).

Core reusable user-simulation engine designed to plug into ANY social/product benchmark
(`Product Hunt`, `Hacker News`, `SaaS / App Beta Feedback`):
  1. Simulates 5 orthogonal, empirically calibrated human adopter archetypes grounded in `< D` real user
     histories (`UniversalUserPool` or domain commenter histories):
       - `arch_systems`: Systems / Open-Source / Infra Engineer
       - `arch_power`: High-Frequency Daily Adopter / Power Builder
       - `arch_craft`: Native App, Design & UX Craft Connoisseur
       - `arch_buyer`: Pragmatic Buyer & Competitor Switcher
       - `arch_skeptic_keep`: Anti-Wrapper / Anti-Slop Survival Judge (plus verbatim predicted complaints!)
  2. Executes across MULTIPLE independent frontier model families (`claude-sonnet-4-6`, `gemini-2.5-pro`,
     `openai/gpt-oss-120b-maas`) to eliminate single-model blind spots, load-balancing Anthropic across
     `global` + `us-east5` with `timeout=110s` and parallel dual-family execution per slate.
  3. Strictly separates:
       - `simulate_product_only_day` (ZERO comments, ZERO votes, ZERO order — pure product + CUA + `< D` priors)
       - `simulate_discourse_day` (adds order-free, vote-scrubbed pre-reveal early community threads & Q&A)
  4. Randomizes candidate order via deterministic MD5 hash (`domain:day:id:v7`) so list-position leakage is 0.0.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import itertools
import json
import re
from typing import Any

import numpy as np

from simharness.bench import scrub
from simharness.models.llm import Budget, JsonlCache, VertexClaude, VertexOpenAICompat, _host, _post
from usersim_core.cohort_sim import VertexGeminiPro


UNIV_PRODUCT_ONLY_FEATURES = [
    "u7_po_claude_adopt_z",
    "u7_po_claude_breakout_z",
    "u7_po_claude_skeptic_z",
    "u7_po_claude_craft_z",
    "u7_po_claude_systems_z",
    "u7_po_gempro_adopt_z",
    "u7_po_gempro_breakout_z",
    "u7_po_consensus_z",
]

UNIV_DISCOURSE_FEATURES = [
    "u7_disc_claude_organic_z",
    "u7_disc_claude_breakout_z",
    "u7_disc_gpt_organic_z",
    "u7_disc_consensus_z",
]


UNIV_PRODUCT_ONLY_NUMERIC_PROMPT = """You are a calibrated Universal User Simulator for {domain_label}.
You are simulating 5 distinct real user archetypes evaluating today's candidate items STRICTLY FROM THE PRODUCT / ARTIFACT ITSELF (zero post-launch comments, zero votes, zero rankings exist).

MATCHED REAL HISTORICAL COHORT (< today):
{panel_block}

HISTORICAL DOMAIN & CATEGORY CALIBRATION PRIORS (< today):
{calibration_notes}

CANDIDATES (listed in randomized order 1..{n_items}; team follower reach is modeled separately, so judge ONLY real human adoption value, hands-on CUA product verification, concrete differentiation vs named competitors, craft, and friction):
{items_block}

SIMULATE THESE 5 ARCHETYPES FOR EVERY CANDIDATE (0.00 to 1.00 scale, full dynamic range 0.12..0.94, mean ~0.46):
- `systems`: Principal Systems/OSS Engineer — rewards real engineering, open-source code/CLI/MCP/SDKs, benchmarks; penalizes thin AI wrappers & vague "autonomous coworker / agent stack" buzzwords.
- `power`: High-Frequency Power User — rewards immediate daily utility, demo video clarity, instant no-login playground or clean Google-SSO workspace.
- `craft`: Design & Native App Connoisseur — rewards focused single-purpose UX delight, desktop/mobile/creative polish, crisp visual/workflow execution.
- `buyer`: Pragmatic Buyer & Competitor Switcher — rewards solving real incumbent pain points with transparent pricing & free tier; penalizes waitlist-only, enterprise-contact walls, or crowded me-too clones.
- `skeptic_keep`: Anti-Slop Survival (1.0 = rock-solid genuine product; 0.1 = generic AI wrapper, crypto/SEO spam, broken onboarding, or vaporware).
- `p_breakout`: Overall calibrated probability (0.00..1.00) this item breaks out into the top tier of real organic user endorsements today.
- If a candidate says `[SITE_UNVERIFIED]`, do NOT penalize missing browser inspection — judge neutrally from product specification, demo media, and competitor fit.

Return compact JSON ONLY (every `idx` 1..{n_items} MUST appear once, no extra text):
{{"evaluations":[{{"idx":1,"systems":0.00,"power":0.00,"craft":0.00,"buyer":0.00,"skeptic_keep":0.00,"p_breakout":0.00}}]}}"""


UNIV_PRODUCT_ONLY_COMMENTS_PROMPT = """You are a calibrated Universal User Simulator for {domain_label}.
You are simulating 5 distinct real user archetypes evaluating today's candidate items STRICTLY FROM THE PRODUCT / ARTIFACT ITSELF (zero post-launch comments, zero votes, zero rankings exist).

MATCHED REAL HISTORICAL COHORT (< today):
{panel_block}

HISTORICAL DOMAIN & CATEGORY CALIBRATION PRIORS (< today):
{calibration_notes}

CANDIDATES (listed in randomized order 1..{n_items}; team follower reach is modeled separately, so judge ONLY real human adoption value, hands-on CUA product verification, concrete differentiation vs named competitors, craft, and friction):
{items_block}

SIMULATE THESE 5 ARCHETYPES FOR EVERY CANDIDATE (0.00 to 1.00 scale, full dynamic range 0.12..0.94, mean ~0.46):
- `systems`: Principal Systems/OSS Engineer — rewards real engineering, open-source code/CLI/MCP/SDKs, benchmarks; penalizes thin AI wrappers & vague buzzwords.
- `power`: High-Frequency Power User — rewards immediate daily utility, demo video clarity, instant no-login playground or clean Google-SSO workspace.
- `craft`: Design & Native App Connoisseur — rewards focused single-purpose UX delight, desktop/mobile/creative polish, crisp visual/workflow execution.
- `buyer`: Pragmatic Buyer & Competitor Switcher — rewards solving real incumbent pain points with transparent pricing & free tier; penalizes waitlist-only, enterprise-contact walls, or crowded me-too clones.
- `skeptic_keep`: Anti-Slop Survival (1.0 = rock-solid genuine product; 0.1 = generic AI wrapper, crypto/SEO spam, broken onboarding, or vaporware).
- `p_breakout`: Overall calibrated probability (0.00..1.00) this item breaks out into the top tier of real organic user endorsements today.
- If a candidate says `[SITE_UNVERIFIED]`, do NOT penalize missing browser inspection — judge neutrally from product specification, demo media, and competitor fit.

Return compact JSON ONLY (every `idx` 1..{n_items} MUST appear once):
{{"evaluations":[{{"idx":1,"systems":0.00,"power":0.00,"craft":0.00,"buyer":0.00,"skeptic_keep":0.00,"p_breakout":0.00,"praise":"<concise <=14 word praise>","complaints":["<specific worry/bug/pricing critique 1 (<=14 words)>","<specific critique/question 2 (<=14 words)>"]}}]}}"""


UNIV_DISCOURSE_PROMPT = """You are a calibrated Universal User & Community Discourse Simulator for {domain_label}.
Vote counts and rankings are HIDDEN. You observe each item's product specification, hands-on CUA inspection, AND the complete early community comment/reply activity recorded strictly before the cutoff.

CANDIDATES (listed in randomized order 1..{n_items}; zero vote counts or rankings exist):
{items_block}

EVALUATION RULES:
1. Distinguish AUTHENTIC ORGANIC ADOPTION MOMENTUM from coordinated launch-pod fluff:
   - Strong positive signal (0.75..0.95): Multiple distinct established users asking specific workflow/pricing/technical questions, reporting hands-on tests, comparing against named tools, plus responsive maker answers.
   - Neutral / weak signal (0.35..0.55): Quiet thread on a niche product, OR only generic 3-word "Congrats on the launch!" praise from zero-follower accounts.
   - Negative signal (0.10..0.30): Early users reporting broken signups, paywalls, bugs, or calling out derivative/misleading claims, OR complete crickets despite heavy promotional push.
2. Combine product quality + CUA verification + authentic early community traction into `organic_momentum` (0.00..1.00) and `p_breakout` (0.00..1.00), spanning the full 0.12..0.94 range across the slate.

Return compact JSON ONLY (every `idx` 1..{n_items} MUST appear once):
{{"evaluations":[{{"idx":1,"organic_momentum":0.00,"qa_substance":0.00,"pod_fluff_risk":0.00,"p_breakout":0.00}}]}}"""


class VertexClaudeBalanced(VertexClaude):
    """Claude Sonnet 4.6 load-balanced across `global` + `us-east5` with 115s timeout so 25-item slates never cut off."""

    _rr = itertools.cycle(["global", "us-east5"])

    def _call(self, prompt: str) -> tuple[str, int, int]:
        reg = next(self._rr)
        url = (
            f"https://{_host(reg)}/v1/projects/{self.project}/locations/{reg}"
            f"/publishers/anthropic/models/{self.model}:rawPredict"
        )
        d = _post(
            url,
            {
                "anthropic_version": "vertex-2023-10-16",
                "max_tokens": self.max_out,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            retries=4,
            timeout=115.0,
        )
        text = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")
        u = d.get("usage", {})
        return text, u.get("input_tokens", 0), u.get("output_tokens", 0)


class VertexGeminiProFast(VertexGeminiPro):
    """Gemini 2.5 Pro with 115s timeout and 192 thinking budget."""

    def _call(self, prompt: str) -> tuple[str, int, int]:
        url = (
            f"https://{_host(self.region)}/v1/projects/{self.project}/locations/{self.region}"
            f"/publishers/google/models/{self.model}:generateContent"
        )
        gen = {
            "temperature": self.temperature,
            "maxOutputTokens": self.max_out,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": self.thinking_budget},
        }
        d = _post(
            url,
            {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen},
            retries=4,
            timeout=115.0,
        )
        u = d.get("usageMetadata", {})
        parts = ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)


def _extract_evals_json(raw_text: str, n_items: int) -> dict[int, dict[str, Any]]:
    if not raw_text:
        return {}
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.I)
    m = re.search(r"\{.*\}", cleaned, re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return {}
    arr = obj.get("evaluations") if isinstance(obj, dict) else None
    if not isinstance(arr, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for r in arr:
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r.get("idx"))
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= n_items:
            out[idx] = r
    return out


class UniversalUserSimulatorV7:
    """Reusable multi-family 5-archetype simulator for Product Hunt, Hacker News, and SaaS user feedback."""

    def __init__(
        self,
        cache: JsonlCache,
        budget: Budget,
        project: str = "project-amer-scs-sandbox",
    ) -> None:
        self.cache = cache
        self.budget = budget
        self.claude_num = VertexClaudeBalanced(
            model="claude-sonnet-4-6",
            project=project,
            region="global",
            temperature=0.15,
            budget=budget,
            max_out=2600,
        )
        self.claude_comm = VertexClaudeBalanced(
            model="claude-sonnet-4-6",
            project=project,
            region="global",
            temperature=0.15,
            budget=budget,
            max_out=6400,
        )
        self.gempro_num = VertexGeminiProFast(
            project=project,
            region="global",
            temperature=0.15,
            budget=budget,
            max_out=2800,
            thinking_budget=192,
        )
        self.gempro_comm = VertexGeminiProFast(
            project=project,
            region="global",
            temperature=0.15,
            budget=budget,
            max_out=6800,
            thinking_budget=192,
        )
        self.gpt120b = VertexOpenAICompat(
            model="openai/gpt-oss-120b-maas",
            project=project,
            region="us-central1",
            temperature=0.15,
            budget=budget,
            max_out=3200,
            extra={"reasoning_effort": "low", "response_format": {"type": "json_object"}},
        )

    def _run_model_cached(
        self,
        ck_primary: tuple,
        ck_legacy: tuple | None,
        backend: Any,
        prompt: str,
        n_it: int,
    ) -> dict[int, dict[str, Any]]:
        if ck_primary in self.cache:
            return {int(k): v for k, v in self.cache[ck_primary].items()}
        if ck_legacy is not None and ck_legacy in self.cache:
            return {int(k): v for k, v in self.cache[ck_legacy].items()}
        ev: dict[int, dict[str, Any]] = {}
        for _ in range(2):
            try:
                raw = backend.call(prompt)
                ev = _extract_evals_json(raw, n_it)
                if len(ev) >= max(1, int(0.75 * n_it)):
                    break
            except Exception as exc:
                print(f"    [UnivSim warn] {backend.name} {ck_primary[:3]} err: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
        if ev:
            self.cache[ck_primary] = {str(k): v for k, v in ev.items()}
        return ev

    def simulate_product_only_day(
        self,
        domain: str,
        domain_label: str,
        day: str,
        candidates: list[dict[str, Any]],
        panel_block: str,
        calibration_notes: str,
        emit_comments: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Run strictly ZERO-COMMENT 5-archetype simulation across Claude Sonnet 4.6 + Gemini 2.5 Pro in parallel."""
        if not candidates:
            return {}
        ordered = sorted(
            candidates,
            key=lambda x: hashlib.md5(f"{domain}:{day}:{x['item_id']}:u7_po".encode()).hexdigest(),
        )
        n_it = len(ordered)
        id_sig = hashlib.md5(",".join(str(x["item_id"]) for x in ordered).encode()).hexdigest()[:12]

        lines = []
        for i, c in enumerate(ordered, start=1):
            lines.append(
                f"[{i}] {scrub(str(c.get('title') or ''))} — {scrub(str(c.get('summary') or ''))}\n"
                f"    Tags/Topics: {scrub(str(c.get('tags_str') or 'General'))} | Media: {c.get('media_str', 'n/a')}\n"
                f"    Spec: {scrub(str(c.get('desc_short') or ''))}\n"
                f"    Hands-On CUA & Surface: {scrub(str(c.get('cua_str') or '[SITE_UNVERIFIED]'))}\n"
                f"    Named Competitors (<D) & User Pain: {scrub(str(c.get('comp_str') or 'none'))}\n"
                f"    Pre-Launch Brand/OSS Context: {scrub(str(c.get('brand_str') or 'standard'))}"
            )

        tmpl = UNIV_PRODUCT_ONLY_COMMENTS_PROMPT if emit_comments else UNIV_PRODUCT_ONLY_NUMERIC_PROMPT
        prompt = tmpl.format(
            domain_label=domain_label,
            panel_block=panel_block[:1500],
            calibration_notes=calibration_notes[:850],
            n_items=n_it,
            items_block="\n".join(lines),
        )

        ck_c_leg = ("u7_po_claude46_v1", domain, day, id_sig)
        ck_g_leg = ("u7_po_gempro_v1", domain, day, id_sig)
        if emit_comments:
            ck_c = ("u7_po_claude46_comm_v1", domain, day, id_sig)
            ck_g = ("u7_po_gempro_comm_v1", domain, day, id_sig)
            b_c, b_g = self.claude_comm, self.gempro_comm
            # Legacy v1 ALREADY emitted praises & complaints!
            leg_c, leg_g = ck_c_leg, ck_g_leg
        else:
            ck_c = ("u7_po_claude46_num_v1", domain, day, id_sig)
            ck_g = ("u7_po_gempro_num_v1", domain, day, id_sig)
            b_c, b_g = self.claude_num, self.gempro_num
            leg_c, leg_g = ck_c_leg, ck_g_leg

        with ThreadPoolExecutor(max_workers=2) as sub_ex:
            fc = sub_ex.submit(self._run_model_cached, ck_c, leg_c, b_c, prompt, n_it)
            fg = sub_ex.submit(self._run_model_cached, ck_g, leg_g, b_g, prompt, n_it)
            ev_c = fc.result()
            ev_g = fg.result()

        def _f(d: dict[str, Any], k: str, default: float = 0.46) -> float:
            try:
                return float(np.clip(float(d.get(k, default)), 0.0, 1.0))
            except (TypeError, ValueError):
                return default

        out: dict[str, dict[str, Any]] = {}
        for i, c in enumerate(ordered, start=1):
            lid = str(c["item_id"])
            rc = ev_c.get(i, {})
            rg = ev_g.get(i, {})
            c_sys = _f(rc, "systems")
            c_pow = _f(rc, "power")
            c_crf = _f(rc, "craft")
            c_buy = _f(rc, "buyer")
            c_skp = _f(rc, "skeptic_keep", 0.50)
            c_brk = _f(rc, "p_breakout")
            c_adopt = 0.22 * c_sys + 0.26 * c_pow + 0.22 * c_crf + 0.15 * c_buy + 0.15 * c_skp

            g_adopt = (
                0.22 * _f(rg, "systems")
                + 0.26 * _f(rg, "power")
                + 0.22 * _f(rg, "craft")
                + 0.15 * _f(rg, "buyer")
                + 0.15 * _f(rg, "skeptic_keep", 0.50)
            )
            g_brk = _f(rg, "p_breakout")

            praises = [str(x).strip() for x in (rc.get("praise"), rg.get("praise")) if x and str(x).strip()]
            comps: list[str] = []
            for src_r in (rc, rg):
                for cm in src_r.get("complaints") or []:
                    if cm and str(cm).strip():
                        comps.append(scrub(str(cm).strip())[:200])

            out[lid] = {
                "raw_u7_claude_adopt": c_adopt,
                "raw_u7_claude_breakout": c_brk,
                "raw_u7_claude_skeptic": c_skp,
                "raw_u7_claude_craft": c_crf,
                "raw_u7_claude_systems": c_sys,
                "raw_u7_gempro_adopt": g_adopt,
                "raw_u7_gempro_breakout": g_brk,
                "raw_u7_po_consensus": 0.55 * (0.5 * c_adopt + 0.5 * c_brk) + 0.45 * (0.5 * g_adopt + 0.5 * g_brk),
                "predicted_praises": praises[:2],
                "predicted_complaints": comps[:4],
            }
        return out

    def simulate_discourse_day(
        self,
        domain: str,
        domain_label: str,
        day: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Run pre-reveal early-discourse simulation (`Claude Sonnet 4.6` + `GPT-OSS-120B` in parallel)."""
        if not candidates:
            return {}
        ordered = sorted(
            candidates,
            key=lambda x: hashlib.md5(f"{domain}:{day}:{x['item_id']}:u7_disc".encode()).hexdigest(),
        )
        n_it = len(ordered)
        id_sig = hashlib.md5(",".join(str(x["item_id"]) for x in ordered).encode()).hexdigest()[:12]

        lines = []
        for i, c in enumerate(ordered, start=1):
            lines.append(
                f"[{i}] {scrub(str(c.get('title') or ''))} — {scrub(str(c.get('summary') or ''))}\n"
                f"    Hands-On CUA & Product: {scrub(str(c.get('cua_str') or '[SITE_UNVERIFIED]'))}\n"
                f"    Pre-Cutoff Discourse Stats: {scrub(str(c.get('disc_stats_str') or '0 comments'))}\n"
                f"    Maker Pitch Excerpt: {scrub(str(c.get('maker_pitch_str') or '(none)'))}\n"
                f"    Sample Early User Comments: {scrub(str(c.get('user_comments_str') or '(none yet)'))}"
            )

        prompt = UNIV_DISCOURSE_PROMPT.format(
            domain_label=domain_label,
            n_items=n_it,
            items_block="\n".join(lines),
        )

        ck_c = ("u7_disc_claude46_v1", domain, day, id_sig)
        ck_m = ("u7_disc_gpt120b_v1", domain, day, id_sig)

        with ThreadPoolExecutor(max_workers=2) as sub_ex:
            fc = sub_ex.submit(self._run_model_cached, ck_c, None, self.claude_num, prompt, n_it)
            fm = sub_ex.submit(self._run_model_cached, ck_m, None, self.gpt120b, prompt, n_it)
            ev_c = fc.result()
            ev_m = fm.result()

        def _f(d: dict[str, Any], k: str, default: float = 0.45) -> float:
            try:
                return float(np.clip(float(d.get(k, default)), 0.0, 1.0))
            except (TypeError, ValueError):
                return default

        out: dict[str, dict[str, Any]] = {}
        for i, c in enumerate(ordered, start=1):
            lid = str(c["item_id"])
            rc = ev_c.get(i, {})
            rm = ev_m.get(i, {})
            c_org = 0.55 * _f(rc, "organic_momentum") + 0.30 * _f(rc, "qa_substance") - 0.20 * _f(rc, "pod_fluff_risk", 0.3)
            c_brk = _f(rc, "p_breakout")
            m_org = 0.55 * _f(rm, "organic_momentum") + 0.30 * _f(rm, "qa_substance") - 0.20 * _f(rm, "pod_fluff_risk", 0.3)
            m_brk = _f(rm, "p_breakout")
            out[lid] = {
                "raw_u7_disc_claude_org": c_org,
                "raw_u7_disc_claude_brk": c_brk,
                "raw_u7_disc_gpt_org": 0.5 * m_org + 0.5 * m_brk,
                "raw_u7_disc_consensus": 0.60 * (0.5 * c_org + 0.5 * c_brk) + 0.40 * (0.5 * m_org + 0.5 * m_brk),
            }
        return out

    def run_batch(
        self,
        domain: str,
        domain_label: str,
        day_payloads: list[dict[str, Any]],
        include_discourse: bool = False,
        workers: int = 8,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        results: dict[tuple[str, str], dict[str, Any]] = {}
        done = 0
        total = len(day_payloads)

        def _work(dp: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
            d = str(dp["day"])
            if include_discourse:
                res = self.simulate_discourse_day(domain, domain_label, d, dp["candidates"])
            else:
                res = self.simulate_product_only_day(
                    domain,
                    domain_label,
                    d,
                    dp["candidates"],
                    dp.get("panel_block", ""),
                    dp.get("calibration_notes", ""),
                    emit_comments=bool(dp.get("emit_comments", False)),
                )
            return d, res

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_work, dp) for dp in day_payloads]
            for fut in as_completed(futs):
                d, d_map = fut.result()
                for lid, vals in d_map.items():
                    results[(d, lid)] = vals
                done += 1
                if done % 15 == 0 or done == total:
                    mode_s = "Discourse" if include_discourse else "Product-Only"
                    print(f"  [UnivSim v7 {domain} {mode_s}] {done}/{total} days (${self.budget.spent:.3f})", flush=True)
        self.cache.roll()
        return results
