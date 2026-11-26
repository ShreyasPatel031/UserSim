"""Comparative Frontier Cohort Simulator (`openai/gpt-oss-120b-maas` + `gemini-2.5-pro`).

Replaces single-launch `gemini-2.5-flash` metadata prompts with a domain-agnostic, leak-scrubbed
comparative cohort simulator:
  1. Shuffles Day D's shortlist deterministically (`md5(day + pass_id)`) so zero structural rank
     order leaks into the prompt.
  2. Grounds evaluation in (a) matched real discerning users from `UniversalUserPool` (< D),
     (b) leak-sanitized live product / Camoufox CUA trace reality (`SanitizedSurface` + `CUA_TRACES`),
     and (c) walk-forward `< D` category calibration priors (`WalkForwardCalibrator`).
  3. Runs TWO orthogonal non-Flash frontier reasoning families (`openai/gpt-oss-120b-maas` and
     `gemini-2.5-pro`) under a strict shared `Budget` cap and persistent `JsonlCache`.
  4. Never penalizes missing URLs or harness access failures (`no_url`, `dead_host`, `captcha`, `block`).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from typing import Any

import numpy as np

from simharness.bench import scrub
from simharness.models.llm import Budget, BudgetExceeded, JsonlCache, PRICES, VertexGemini, VertexOpenAICompat, _VertexAuth, _post, _host
from usersim_core.sanitizer import SanitizedSurface

# Ensure gemini-2.5-pro is accurately priced in simharness.models.llm.PRICES ($1.25 / $10.00 per 1M tokens)
PRICES["gemini-2.5-pro"] = (1.25, 10.00)

# Patch _VertexAuth.token to use gcloud service-account access token (cached 30m) without needing google-auth package
_gcloud_tok = {"t": "", "at": 0.0}
_gcloud_lock = threading.Lock()


def _sa_vertex_token() -> str:
    with _gcloud_lock:
        if not _gcloud_tok["t"] or time.time() - _gcloud_tok["at"] > 1800:
            env = os.environ.copy()
            env.setdefault("CLOUDSDK_CORE_ACCOUNT", "usersim-cloud-agent@project-amer-scs-sandbox.iam.gserviceaccount.com")
            _gcloud_tok["t"] = subprocess.check_output(
                ["gcloud", "auth", "print-access-token"], text=True, env=env
            ).strip()
            _gcloud_tok["at"] = time.time()
        return _gcloud_tok["t"]


_VertexAuth.token = staticmethod(_sa_vertex_token)  # type: ignore[assignment]


class VertexGeminiPro(VertexGemini):
    """Gemini 2.5 Pro with explicit thinkingBudget support (Gemini 2.5 Pro requires thinking >= 128)."""

    def __init__(
        self,
        project: str = "project-amer-scs-sandbox",
        region: str = "global",
        temperature: float = 0.15,
        budget: Budget | None = None,
        max_out: int = 4096,
        thinking_budget: int = 256,
    ):
        super().__init__(
            model="gemini-2.5-pro",
            project=project,
            region=region,
            temperature=temperature,
            budget=budget,
            max_out=max_out,
        )
        self.thinking_budget = thinking_budget
        self.price_in, self.price_out = (1.25, 10.00)

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
        d = _post(url, {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}, timeout=90.0)
        u = d.get("usageMetadata", {})
        parts = ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        ti = int(u.get("promptTokenCount", 0))
        to = int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
        return text, ti, to


COMPARATIVE_COHORT_PROMPT = """You are simulating a calibrated panel of 5 real, discerning {domain_label} users evaluating today's competing product launches AFTER clicking through to inspect each live product surface.

PANEL OF REAL MATCHED USERS (strictly from activity BEFORE today):
{panel_block}

HISTORICAL CATEGORY CALIBRATION NOTES (strictly from days BEFORE today):
{category_notes}

TODAY'S COMPETING CANDIDATES (listed in randomized order 1..{n_items}; structural team reach is ALREADY factored out separately, so judge ONLY product resonance, immediate concrete utility, real differentiation, technical craft, and onboarding friction):
{items_block}

EVALUATION RULES:
1. Calibrate across the whole slate so scores use the full range (mean around 0.45-0.50, top standouts 0.75-0.92, derivative AI wrappers / vague B2B pitches / waitlist-only pages 0.15-0.35). Do NOT give every launch 0.7+.
2. Products with concrete, immediately usable value (live interactive demo/playground, open-source repo/CLI, Chrome/desktop utility, clear free tier, crisp problem-solution) outperform generic "AI agent / workflow / SEO / lead-gen" wrappers when real users try them.
3. CRITICAL FAIRNESS RULE: If a candidate says `[SITE_UNVERIFIED: harness/network could not inspect live page]`, DO NOT penalize or reward it for missing site details — set `friction_severity` near 0.45 and judge from its 00:05 product specification & category competition.

Return JSON ONLY in this exact schema (every candidate `idx` 1..{n_items} MUST appear once):
{{
  "evaluations": [
    {{
      "idx": 1,
      "p_endorse": 0.00,
      "would_use": 0.00,
      "instant_clarity": 0.00,
      "differentiation": 0.00,
      "technical_substance": 0.00,
      "friction_severity": 0.00,
      "critique": "<max 12 words: sharpest skeptical question or product risk>",
      "comment": "<max 16 words: realistic user reaction>"
    }}
  ]
}}"""


def _format_surface_summary(surf: SanitizedSurface | None, cua_row: dict | None = None) -> str:
    # Only fall back to CUA digest when static HTTP was blind (js_only), keeping comparative formatting symmetric!
    if (surf is None or surf.access_status != "clean") and cua_row and cua_row.get("access_status") == "clean" and cua_row.get("sanitized_digest"):
        flags = []
        if cua_row.get("has_interactive_demo"):
            flags.append("interactive_demo=YES")
        if cua_row.get("reached_value_moment"):
            flags.append(f"reached_value=YES(steps={cua_row.get('steps_to_value') or 1})")
        if cua_row.get("has_free_tier"):
            flags.append("free_tier=YES")
        if cua_row.get("product_trait") and cua_row["product_trait"] != "none":
            flags.append(f"trait={cua_row['product_trait']}")
        return f"[LIVE_SURFACE_CLEAN: {', '.join(flags) or 'inspected'}] {cua_row['sanitized_digest'][:280]}"

    if surf is None or surf.access_status != "clean":
        return "[SITE_UNVERIFIED: harness/network could not inspect live page — judge neutrally without site penalty]"

    flags = []
    if surf.has_interactive_demo:
        flags.append("interactive_demo=YES")
    if surf.has_open_source:
        flags.append("open_source_or_cli=YES")
    if surf.has_free_tier:
        flags.append("free_tier=YES")
    if surf.has_visible_pricing:
        flags.append("transparent_pricing=YES")
    if surf.has_docs:
        flags.append("docs_api=YES")
    if surf.is_waitlist:
        flags.append("WAITLIST_GATED=YES")
    if surf.is_enterprise_gated:
        flags.append("BOOK_DEMO_SALES_GATE=YES")
    if surf.is_platform_only:
        flags.append("specific_os_or_extension=YES")
    ctas = ", ".join(surf.cta_texts[:5]) if surf.cta_texts else ""
    snippet = surf.sanitized_text[:300]
    return f"[LIVE_SURFACE_CLEAN: {', '.join(flags) or 'standard_landing'}" + (f" | CTAs: {ctas}" if ctas else "") + f"] {snippet}"


def _parse_comparative_json(raw_text: str, n_items: int) -> dict[int, dict[str, Any]]:
    if not raw_text:
        return {}
    # Find outermost JSON object
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw_text[start : end + 1])
    except ValueError:
        return {}
    evals = obj.get("evaluations") if isinstance(obj, dict) else None
    if not isinstance(evals, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for row in evals:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("idx", 0))
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= n_items:
            def _f(k: str, default: float = 0.5) -> float:
                try:
                    v = float(row.get(k, default))
                    return float(np.clip(v, 0.0, 1.0)) if np.isfinite(v) else default
                except (TypeError, ValueError):
                    return default
            out[idx] = {
                "p_endorse": _f("p_endorse", 0.45),
                "would_use": _f("would_use", 0.45),
                "instant_clarity": _f("instant_clarity", 0.50),
                "differentiation": _f("differentiation", 0.45),
                "technical_substance": _f("technical_substance", 0.45),
                "friction_severity": _f("friction_severity", 0.45),
                "critique": str(row.get("critique") or "")[:180],
                "comment": str(row.get("comment") or "")[:200],
            }
    return out


class ComparativeCohortSimulator:
    """Multi-model comparative shortlist evaluator (`gpt-oss-120b` + `gemini-2.5-pro`) with disk cache."""

    def __init__(
        self,
        budget: Budget,
        cache: JsonlCache,
        project: str = "project-amer-scs-sandbox",
        workers: int = 10,
    ):
        self.budget = budget
        self.cache = cache
        self.workers = workers
        self.gpt120b = VertexOpenAICompat(
            model="openai/gpt-oss-120b-maas",
            project=project,
            region="us-central1",
            temperature=0.15,
            budget=budget,
            max_out=4096,
            extra={"reasoning_effort": "low", "response_format": {"type": "json_object"}},
        )
        self.pro = VertexGeminiPro(
            project=project,
            region="global",
            temperature=0.15,
            budget=budget,
            max_out=4096,
            thinking_budget=256,
        )

    def _build_day_prompt(
        self,
        day: str,
        ordered_items: list[dict[str, Any]],
        cohort_panel: list[dict[str, Any]],
        category_notes: list[str],
        surfaces: dict[str, SanitizedSurface],
        cua_by_id: dict[str, dict],
        domain_label: str = "Product Hunt",
    ) -> str:
        panel_lines = []
        for u in cohort_panel[:5]:
            hb = " | ".join(line.strip() for line in u["history_brief"].splitlines()[:4])
            panel_lines.append(
                f"- User `{u['global_user_id'][:14]}` (archetype={u['archetype_id']}, critique_rate={u['critique_rate']:.2f}, "
                f"tech_focus={u['tech_focus']:.2f}, pricing_focus={u['pricing_focus']:.2f}): {hb[:320]}"
            )
        panel_block = "\n".join(panel_lines) if panel_lines else "- Discerning builders, engineers, and product operators."
        cat_block = "\n".join(f"- {n}" for n in category_notes[:10]) if category_notes else "- Judge on concrete utility."

        item_lines = []
        for i, it in enumerate(ordered_items, start=1):
            lid = str(it["item_id"])
            desc = scrub(" ".join(str(it.get("description") or "").split()))[:260]
            raw_tags = it.get("tags")
            tag_list = [str(t) for t in raw_tags] if raw_tags is not None and len(raw_tags) > 0 else []
            tags = ", ".join(tag_list)[:120] or "General"
            cat = str(it.get("category_0005") or "General")
            surf_str = _format_surface_summary(surfaces.get(lid), cua_by_id.get(lid))
            item_lines.append(
                f"{i}. Name: {scrub(str(it['title']))} | Tagline: {scrub(str(it['summary']))} | "
                f"Category: {cat} | Topics: {tags}\n"
                f"   00:05 Description: {desc or '(none)'}\n"
                f"   Product Reality: {surf_str}"
            )

        return COMPARATIVE_COHORT_PROMPT.format(
            domain_label=domain_label,
            panel_block=panel_block,
            category_notes=cat_block,
            n_items=len(ordered_items),
            items_block="\n".join(item_lines),
        )

    def _eval_one_day_model(
        self,
        backend,
        cache_tag: str,
        day: str,
        shortlist: list[dict[str, Any]],
        cohort_panel: list[dict[str, Any]],
        category_notes: list[str],
        surfaces: dict[str, SanitizedSurface],
        cua_by_id: dict[str, dict],
        domain_label: str = "Product Hunt",
    ) -> dict[str, dict[str, Any]]:
        item_sig = ",".join(sorted(str(x["item_id"]) for x in shortlist))
        cua_sig = ",".join(sorted(k for k, v in cua_by_id.items() if v.get("access_status") == "clean"))
        sig_hash = hashlib.md5(f"{item_sig}|{cua_sig}".encode()).hexdigest()[:10]
        ckey = ("comp_cohort_v1", cache_tag, day, sig_hash)
        if ckey in self.cache:
            return self.cache[ckey]

        # Deterministic position-debiased shuffle (different per model/pass, ZERO structural rank leak!)
        seed_int = int(hashlib.md5(f"{day}:{cache_tag}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed_int)
        perm = rng.permutation(len(shortlist)).tolist()
        ordered = [shortlist[idx] for idx in perm]

        prompt = self._build_day_prompt(
            day=day,
            ordered_items=ordered,
            cohort_panel=cohort_panel,
            category_notes=category_notes,
            surfaces=surfaces,
            cua_by_id=cua_by_id,
            domain_label=domain_label,
        )
        parsed = {}
        for attempt in range(6):
            try:
                raw = backend.call(prompt)
                parsed = _parse_comparative_json(raw, len(ordered))
                if len(parsed) >= max(1, int(0.75 * len(ordered))):
                    break
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001
                time.sleep(min(45.0, 4.0 * (attempt + 1)))
                if attempt == 5:
                    print(f"  [WARN] {cache_tag} {day} failed after 6 attempts: {type(exc).__name__}: {str(exc)[:120]}", flush=True)

        by_item: dict[str, dict[str, Any]] = {}
        for pos_1idx, it in enumerate(ordered, start=1):
            lid = str(it["item_id"])
            if pos_1idx in parsed:
                by_item[lid] = parsed[pos_1idx]
            else:
                by_item[lid] = {
                    "p_endorse": 0.45, "would_use": 0.45, "instant_clarity": 0.50,
                    "differentiation": 0.45, "technical_substance": 0.45, "friction_severity": 0.45,
                    "critique": "", "comment": "",
                }

        if len(parsed) >= max(1, int(0.75 * len(ordered))):
            self.cache[ckey] = by_item
        return by_item

    def evaluate_days(
        self,
        day_payloads: list[dict[str, Any]],
        use_pro: bool = True,
        domain_label: str = "Product Hunt",
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Evaluate many days in parallel using gpt-oss-120b (2 position-shuffled passes) + gemini-2.5-pro."""
        results_120b_a: dict[str, dict[str, dict]] = {}
        results_120b_b: dict[str, dict[str, dict]] = {}
        results_pro: dict[str, dict[str, dict]] = {}

        def _job(payload: dict[str, Any]):
            d = payload["day"]
            sl = payload["shortlist"]
            pan = payload["cohort_panel"]
            cn = payload["category_notes"]
            surfs = payload["surfaces"]
            cua_m = payload.get("cua_by_id") or {}
            r_a = self._eval_one_day_model(self.gpt120b, "gpt120b_p1", d, sl, pan, cn, surfs, cua_m, domain_label)
            r_b = self._eval_one_day_model(self.gpt120b, "gpt120b_p2", d, sl, pan, cn, surfs, cua_m, domain_label)
            r_p = (
                self._eval_one_day_model(self.pro, "gem25pro_p1", d, sl, pan, cn, surfs, cua_m, domain_label)
                if use_pro else r_a
            )
            return d, r_a, r_b, r_p

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = [ex.submit(_job, p) for p in day_payloads]
            for idx_done, fut in enumerate(as_completed(futs), start=1):
                d, r_a, r_b, r_p = fut.result()
                results_120b_a[d] = r_a
                results_120b_b[d] = r_b
                results_pro[d] = r_p
                if idx_done % 25 == 0 or idx_done == len(day_payloads):
                    self.cache.roll()
                    print(
                        f"  [CohortSim] {idx_done}/{len(day_payloads)} days done | "
                        f"gpt-120b=${self.gpt120b.cost_usd:.2f} ({self.gpt120b.calls} calls) | "
                        f"pro=${self.pro.cost_usd:.2f} ({self.pro.calls} calls) | total=${self.budget.spent:.2f}",
                        flush=True,
                    )

        self.cache.roll()
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for p in day_payloads:
            d = p["day"]
            for it in p["shortlist"]:
                lid = str(it["item_id"])
                a = results_120b_a[d].get(lid, {})
                b = results_120b_b[d].get(lid, {})
                pr = results_pro[d].get(lid, {})

                # Position-debiased 120B average + Gemini 2.5 Pro ensemble
                def _ens(k: str) -> float:
                    v_120 = 0.5 * (float(a.get(k, 0.45)) + float(b.get(k, 0.45)))
                    v_pro = float(pr.get(k, v_120))
                    return 0.50 * v_120 + 0.50 * v_pro

                p_120 = 0.5 * (float(a.get("p_endorse", 0.45)) + float(b.get("p_endorse", 0.45)))
                p_pro = float(pr.get("p_endorse", p_120))
                merged[(d, lid)] = {
                    "p_endorse": _ens("p_endorse"),
                    "would_use": _ens("would_use"),
                    "instant_clarity": _ens("instant_clarity"),
                    "differentiation": _ens("differentiation"),
                    "technical_substance": _ens("technical_substance"),
                    "friction_severity": _ens("friction_severity"),
                    "p_120b": p_120,
                    "p_pro": p_pro,
                    "pro_120b_min": min(p_120, p_pro),
                    "critique": pr.get("critique") or a.get("critique") or "",
                    "comment": pr.get("comment") or a.get("comment") or "",
                }
        return merged
