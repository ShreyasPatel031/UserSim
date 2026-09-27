"""mvp.e2e_ui_run Gemini helpers: N images, sampling knobs, 429 region fallback. No real model calls."""
from types import SimpleNamespace

import pytest

from mvp import e2e_ui_run


class _Resp:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = SimpleNamespace(prompt_token_count=11, candidates_token_count=3)


class _Err(Exception):
    def __init__(self, code):
        super().__init__(f"code {code}")
        self.code = code


@pytest.fixture
def vertex(monkeypatch):
    """Fake Vertex: records (location, model, parts, config); ``script`` is a list of exceptions/texts to return."""
    seen = []
    script = []

    def client_at(loc):
        def generate_content(*, model, contents, config):
            seen.append({"loc": loc, "model": model, "parts": contents, "config": config})
            nxt = script.pop(0) if script else '{"ok": true}'
            if isinstance(nxt, Exception):
                raise nxt
            return _Resp(nxt)

        return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    monkeypatch.setattr(e2e_ui_run, "_gemini_client_at", client_at)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return seen, script


def _images(parts):
    return [p for p in parts if getattr(p, "inline_data", None)]


def test_vision_json_defaults_unchanged(vertex):
    seen, _ = vertex
    assert e2e_ui_run.gemini_vision_json("judge", b"\x89PNG....") == {"ok": True}
    call = seen[0]
    assert call["loc"] is None and call["model"] == e2e_ui_run.JUDGE_MODEL
    cfg = call["config"]
    assert (cfg.temperature, cfg.max_output_tokens, cfg.response_mime_type) == (0.0, 512, "application/json")
    assert cfg.thinking_config.thinking_budget == 0 and cfg.seed is None and cfg.media_resolution is None
    assert len(_images(call["parts"])) == 1


def test_vision_json_takes_n_images_and_knobs(vertex):
    seen, _ = vertex
    jpeg = b"\xff\xd8\xff rest"
    e2e_ui_run.gemini_vision_json("judge", [b"\x89PNG1", jpeg, b"\x89PNG3"], temperature=0.4, max_tokens=900)
    imgs = _images(seen[0]["parts"])
    assert [i.inline_data.mime_type for i in imgs] == ["image/png", "image/jpeg", "image/png"]
    assert (seen[0]["config"].temperature, seen[0]["config"].max_output_tokens) == (0.4, 900)


def test_vision_pair_labels_sides_and_passes_seed(vertex):
    seen, _ = vertex
    e2e_ui_run.gemini_vision_pair("p", [b"a1", b"a2"], b"b1", labels=("LEFT", "RIGHT"), seed=7)
    texts = [p.text for p in seen[0]["parts"] if getattr(p, "text", None)]
    assert texts == ["p", "LEFT", "RIGHT"] and len(_images(seen[0]["parts"])) == 3
    assert seen[0]["config"].seed == 7


def test_generate_429_rotates_regions_then_succeeds(vertex, monkeypatch):
    seen, script = vertex
    monkeypatch.setattr(e2e_ui_run, "_FALLBACK_LOCATIONS", ["r1", "r2"])
    script += [_Err(429), _Err(429), _Err(503), '{"x": 1}']
    text, tin, tout = e2e_ui_run.gemini_generate(["hi"], retries=5)
    assert text == '{"x": 1}' and (tin, tout) == (11, 3)
    assert [c["loc"] for c in seen] == [None, "r1", "r2", None]


def test_generate_client_error_fails_fast(vertex):
    seen, script = vertex
    script.append(_Err(400))
    with pytest.raises(RuntimeError):
        e2e_ui_run.gemini_generate(["hi"], retries=5)
    assert len(seen) == 1
