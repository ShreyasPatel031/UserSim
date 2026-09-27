"""Collective insights on top of summary['comparison']: buyer groups, task groups, a 3-line summary, 3 recommendations.

Buyers are grouped under the product they picked after trying them. That
pick is blind: the buyer is not told which product they were expected to
favor, and a score tie is not awarded to the product under study. Tasks stay
under the product that won them.
Gemini only names each group, says why, and writes the summary and the
recommendations from those groups. The report fetches this separately, so an old
study gets it on first view; the result is cached per study under MVP_RUNS_DIR.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

LAYER_VERSION = 3
_MEM: dict[str, dict[str, Any]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def _best_site(scores: dict[str, Any], order: list[str], tied: list[str] | None = None) -> str | None:
    vals = {k: float(v) for k, v in (scores or {}).items() if isinstance(v, (int, float))}
    if not vals:
        return None
    top = max(vals.values())
    leaders = [k for k in order if vals.get(k) == top] or [k for k, v in vals.items() if v == top]
    # A tie is not a win. Awarding it to the product put other products' customers in its group.
    if len(leaders) != 1 or (tied and len(tied) > 1):
        return None
    return leaders[0]


def _buyer_site(persona: dict[str, Any], order: list[str]) -> str | None:
    """The product this buyer preferred.

    The preference is the pick they made after the runs. The plan's hidden
    expected favorite is not a preference they hold, so it never places them.
    """
    known = set(order)
    pick = str(persona.get("pick") or "")
    if pick in known:
        return pick
    return _best_site(persona.get("scores") or {}, order, tied=persona.get("score_tied"))


def build_groups(comp: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Buyers under the product they picked; tasks under the product that won them."""
    order = [str(s.get("key")) for s in comp.get("sites") or []]
    labels = {str(s.get("key")): str(s.get("label") or s.get("key")) for s in comp.get("sites") or []}

    def grouped(items: list[tuple[str, str]]) -> list[dict[str, Any]]:
        by_site: dict[str, list[str]] = {}
        for site, member in items:
            by_site.setdefault(site, []).append(member)
        keys = sorted(by_site, key=lambda k: (k != "product", -len(by_site[k]), order.index(k) if k in order else 99))
        return [{"site": k, "site_label": labels.get(k, k), "members": by_site[k]} for k in keys]

    buyers = []
    for p in comp.get("by_persona") or []:
        site = _buyer_site(p, order)
        if site:
            buyers.append((site, str(p.get("persona_id"))))
    tasks = []
    for t in comp.get("by_task") or []:
        site = t.get("winner") or _best_site(t.get("scores") or {}, order)
        if "product" in (t.get("tied") or []):
            site = "product"
        if site:
            tasks.append((str(site), str(t.get("task"))))
    return {"buyers": grouped(buyers), "tasks": grouped(tasks)}


def _fmt_scores(scores: Any, labels: dict[str, str]) -> str:
    return ", ".join(f"{labels.get(k, k)} {v}" for k, v in (scores or {}).items() if v is not None)


def _prompt(comp: dict[str, Any], groups: dict[str, list[dict[str, Any]]]) -> str:
    label = comp.get("product_label") or "the product"
    labels = {str(s.get("key")): str(s.get("label") or s.get("key")) for s in comp.get("sites") or []}
    level_labels = comp.get("level_labels") or {}
    personas = {str(p.get("persona_id")): p for p in comp.get("by_persona") or []}
    tasks = {str(t.get("task")): t for t in comp.get("by_task") or []}

    buyer_lines = []
    for g in groups["buyers"]:
        buyer_lines.append(f"[{g['site']}] buyers who preferred {g['site_label']}:")
        for pid in g["members"]:
            p = personas.get(pid) or {}
            buyer_lines.append(
                f"  - {pid}: {p.get('name')}, {p.get('role')}. {p.get('bio') or ''} Scores: {_fmt_scores(p.get('scores'), labels)}"
            )
    task_lines = []
    for g in groups["tasks"]:
        task_lines.append(f"[{g['site']}] {g['site_label']} won:")
        for name in g["members"]:
            t = tasks.get(name) or {}
            how = ", ".join(f"{labels.get(k, k)} {level_labels.get(v, v)}" for k, v in (t.get("levels") or {}).items())
            task_lines.append(
                f"  - \"{name}\". Scores: {_fmt_scores(t.get('scores'), labels)}. How far buyers usually got: {how}. "
                f"Winner's evidence: {t.get('why') or ''}"
            )
    loss_lines = [
        f"  - \"{x.get('task')}\" for {x.get('persona')}: {x.get('competitor_label')} {x.get('competitor_score')} vs {label} "
        f"{x.get('product_score')}. {x.get('competitor_label')}: {(x.get('competitor_evidence') or {}).get('reason') or x.get('reason') or ''} "
        f"{label}: {(x.get('product_evidence') or {}).get('reason') or ''}"
        for x in (comp.get("all_losses") or [])[:15]
    ]
    sites = "\n".join(f"  {k}: {v}" for k, v in labels.items())
    return f"""You write the insight layer of a competitive study for {label}'s product team. Simulated buyers tried {label} and competitors on the same tasks; a judge scored each run 0-10 from its trace and final page.

Sites (key: name):
{sites}

Buyers, grouped under the product each one picked:
{chr(10).join(buyer_lines) or '  (none)'}

Tasks, grouped under the site that won them:
{chr(10).join(task_lines) or '  (none)'}

Head-to-head losses for {label} (competitor's evidence, then {label}'s):
{chr(10).join(loss_lines) or '  (none)'}

Talk about groups, not individuals: name what the buyers in a group have in common, and what kind of job the tasks in a group are.
Ignore problems of the test itself: our agents getting stuck or looping, captchas, timeouts, and signups that failed because every agent shared one test inbox.

Return JSON only:
{{"buyer_groups": {{"<site key>": {{"label": "2-5 word collective name for these buyers", "why": "one sentence, at most 22 words: what they share and why they preferred this product"}}}},
  "task_groups": {{"<site key>": {{"label": "2-5 word name for this kind of job", "why": "one sentence, at most 22 words: why this site wins these jobs"}}}},
  "summary": ["Buyers: which buyer groups {label} wins and loses, at most 28 words",
              "Tasks: which kinds of job {label} wins and loses, at most 28 words",
              "Improve: the single most important change for {label}, at most 28 words"],
  "recommendations": [{{"title": "at most 10 words", "detail": "at most 32 words: what to change and what the winning competitor does", "buyers": ["buyer ids it would win back"], "tasks": ["exact task names it would win back"]}}]}}
Give one entry per site key listed in each grouping above, and exactly 3 recommendations, most important first, each for {label}'s team."""


def _clean(data: Any, comp: dict[str, Any], groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    pids = {str(p.get("persona_id")) for p in comp.get("by_persona") or []}
    task_names = {str(t.get("task")) for t in comp.get("by_task") or []}

    def text(v: Any, n: int) -> str:
        return " ".join(str(v or "").split())[:n]

    def named(kind: str) -> list[dict[str, Any]]:
        raw = data.get(f"{kind[:-1]}_groups")
        raw = raw if isinstance(raw, dict) else {}
        out = []
        for g in groups[kind]:
            meta = raw.get(g["site"])
            meta = meta if isinstance(meta, dict) else {}
            out.append({**g, "label": text(meta.get("label"), 60), "why": text(meta.get("why"), 220)})
        return out

    recs = []
    for r in (data.get("recommendations") or [])[:3]:
        if not isinstance(r, dict) or not r.get("title"):
            continue
        recs.append(
            {
                "title": text(r.get("title"), 100),
                "detail": text(r.get("detail"), 300),
                "buyers": [str(b) for b in r.get("buyers") or [] if str(b) in pids],
                "tasks": [str(t) for t in r.get("tasks") or [] if str(t) in task_names],
            }
        )
    summary = [text(s, 240) for s in (data.get("summary") or []) if str(s or "").strip()][:3]
    return {"buyers": named("buyers"), "tasks": named("tasks"), "summary": summary, "recommendations": recs}


def _cache_key(comp: dict[str, Any], groups: dict[str, Any]) -> str:
    # New scores or regrouping (a study still finishing) must not reuse old labels.
    basis = json.dumps(
        {"v": LAYER_VERSION, "g": groups, "p": [p.get("scores") for p in comp.get("by_persona") or []],
         "t": [t.get("scores") for t in comp.get("by_task") or []], "l": len(comp.get("all_losses") or [])},
        sort_keys=True, default=str,
    )
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def _cache_path(study_id: str):
    from mvp.paths import MVP_RUNS_DIR

    return MVP_RUNS_DIR / "insight_layer" / f"{study_id}.json"


def cached_layer(study_id: str) -> dict[str, Any] | None:
    """The saved layer for this study, without loading the study."""
    hit = _MEM.get(study_id)
    if hit:
        return hit
    try:
        saved = json.loads(_cache_path(study_id).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if isinstance(saved, dict) and saved.get("key"):
        _MEM[study_id] = saved
        return saved
    return None


async def insight_layer_for(study_id: str, comp: dict[str, Any], *, status: str = "") -> dict[str, Any]:
    groups = build_groups(comp)
    key = _cache_key(comp, groups)
    hit = _MEM.get(study_id)
    if hit and hit.get("key") == key and (not status or hit.get("status") == status):
        return hit
    lock = _LOCKS.setdefault(study_id, asyncio.Lock())
    async with lock:
        path = _cache_path(study_id)
        saved = cached_layer(study_id)
        if saved and saved.get("key") == key:
            if status and saved.get("status") != status:
                saved = {**saved, "status": status}
                _MEM[study_id] = saved
                try:
                    path.write_text(json.dumps(saved), encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
            return saved
        from mvp.comparison import _json_call

        data = await _json_call(_prompt(comp, groups), timeout=90.0)
        layer = {"key": key, "version": LAYER_VERSION, "status": status, **_clean(data, comp, groups)}
        _MEM[study_id] = layer
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(layer), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return layer
