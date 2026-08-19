"""Compact UI-element strings from Mind2Web candidate attributes."""

from __future__ import annotations

import json

KEEP_ATTRS = (
    "id",
    "name",
    "type",
    "placeholder",
    "aria-label",
    "aria_label",
    "role",
    "title",
    "alt",
    "value",
    "href",
    "text",
    "inner_text",
    "visible_text",
)


def _attrs(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def element_repr(candidate: dict, max_len: int = 220) -> str:
    attrs = _attrs(candidate.get("attributes"))
    tag = (candidate.get("tag") or "div").lower()
    parts = [f"<{tag}>"]
    for key in KEEP_ATTRS:
        val = attrs.get(key)
        if val is None or val == "":
            continue
        text = " ".join(str(val).split())
        if key == "href":
            text = text[:80]
        parts.append(f"{key}={text[:80]}")
    cls = attrs.get("class")
    if cls:
        parts.append(f"class={' '.join(str(cls).split())[:60]}")
    out = " ".join(parts)
    return out[:max_len]
