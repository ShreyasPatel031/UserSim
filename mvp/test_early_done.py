"""A done call on the untouched start page must not end the run."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from mvp.browser_agent import reject_early_done


def _agent(url: str, actions: list[str], *, done_text: str = "looks clean") -> SimpleNamespace:
    results = []
    history = []
    for name in actions:
        history.append(
            SimpleNamespace(
                model_output=SimpleNamespace(action=[SimpleNamespace(model_dump=lambda n=name, **_k: {n: {}})]),
                result=[SimpleNamespace(is_done=False, success=None, extracted_content="", error=None, long_term_memory="")],
                state=SimpleNamespace(url=url),
            )
        )
    history.append(
        SimpleNamespace(
            model_output=SimpleNamespace(action=[SimpleNamespace(model_dump=lambda **_k: {"done": {"text": done_text}})]),
            result=[
                SimpleNamespace(
                    is_done=True,
                    success=True,
                    extracted_content=done_text,
                    error=None,
                    long_term_memory="",
                )
            ],
            state=SimpleNamespace(url=url),
        )
    )

    class History:
        def __init__(self) -> None:
            self.history = history

        def is_done(self) -> bool:
            last = self.history[-1].result[-1]
            return bool(last.is_done)

    return SimpleNamespace(history=History())


class EarlyDoneTests(unittest.TestCase):
    def test_homepage_done_is_rejected(self) -> None:
        agent = _agent("https://docs.python.org/3/", ["wait"])
        self.assertTrue(reject_early_done(agent, "https://docs.python.org/3/"))
        self.assertFalse(agent.history.is_done())

    def test_done_after_leaving_the_page_stands(self) -> None:
        agent = _agent("https://docs.python.org/3/tutorial/index.html", ["click"])
        self.assertFalse(reject_early_done(agent, "https://docs.python.org/3/"))
        self.assertTrue(agent.history.is_done())

    def test_captcha_done_stands(self) -> None:
        agent = _agent("https://www.target.com/", [], done_text="Blocked by a captcha press and hold.")
        self.assertFalse(reject_early_done(agent, "https://www.target.com/"))


if __name__ == "__main__":
    unittest.main()
