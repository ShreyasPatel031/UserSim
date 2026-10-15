from mvp.signup_inbox import Inbox
from mvp.signup_tools import wait_mail


class _CodeOnly(Inbox):
    backend = "fake"

    def messages(self, newer_than):
        return [{"id": "<m1>", "subject": "Your Reframe Verification Code", "sender": "noreply@reframeapp.com",
                 "text": "Your verification code is 482913", "links": [], "ts": newer_than + 5}]


def test_link_wait_does_not_use_up_a_code_only_mail():
    inbox, seen = _CodeOnly(), set()
    assert wait_mail(inbox, "onboarding.joinreframeapp.com", since=0.0, timeout_s=1, seen=seen, want="link") is None
    assert "<m1>" not in seen
    got = wait_mail(inbox, "onboarding.joinreframeapp.com", since=0.0, timeout_s=1, seen=seen, want="code")
    assert got and got["code"] == "482913"
    assert "<m1>" in seen
    # once returned it is used: the next wait does not hand the same mail out again
    assert wait_mail(inbox, "onboarding.joinreframeapp.com", since=0.0, timeout_s=1, seen=seen, want="code") is None


def test_any_wait_returns_the_mail_and_marks_it():
    inbox, seen = _CodeOnly(), set()
    got = wait_mail(inbox, "x.com", since=0.0, timeout_s=1, seen=seen)
    assert got and got["id"] == "<m1>" and "<m1>" in seen
