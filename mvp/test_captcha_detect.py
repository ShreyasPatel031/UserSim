"""Detection and solver-mapping tests. No live solves and no API key."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "captcha"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text()


class DetectHtmlTests(unittest.TestCase):
    def test_retell_auth0_enterprise_sitekey_and_token_field(self) -> None:
        from mvp.captcha import detect_captcha_in_html

        info = detect_captcha_in_html(_html("retell_auth0.html"), page_url="https://auth.retellai.com/u/signup")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["type"], "recaptcha_enterprise")
        self.assertEqual(info["sitekey"], "6LeRetellEnterpriseSitekeyXXXX")
        self.assertEqual(info["token_field"], 'input[name="captcha"]')

    def test_bland_react_turnstile_sitekey_needs_onsuccess(self) -> None:
        from mvp.captcha import detect_captcha_in_html

        info = detect_captcha_in_html(_html("bland_turnstile.html"), page_url="https://app.bland.ai/signup")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["type"], "turnstile")
        self.assertEqual(info["sitekey"], "0x4AAAAAAA-wFNpU7mZhDp4F")
        self.assertEqual(info["callback"], "onSuccess")

    def test_bland_known_sitekey_when_html_omits_it(self) -> None:
        from mvp.captcha import detect_captcha_in_html

        info = detect_captcha_in_html("<html><body><form>Sign up</form></body></html>", page_url="https://app.bland.ai/signup")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["type"], "turnstile")
        self.assertEqual(info["sitekey"], "0x4AAAAAAA-wFNpU7mZhDp4F")
        self.assertEqual(info["callback"], "onSuccess")

    def test_arkose_public_key(self) -> None:
        from mvp.captcha import detect_captcha_in_html

        info = detect_captcha_in_html(_html("arkose.html"))
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["type"], "arkose")
        self.assertEqual(info["sitekey"], "ARKOSE-PUBLIC-KEY-123")

    def test_classic_widgets_still_detected(self) -> None:
        from mvp.captcha import detect_captcha_in_html

        recaptcha = detect_captcha_in_html(_html("recaptcha_v2.html"))
        hcaptcha = detect_captcha_in_html(_html("hcaptcha.html"))
        turnstile = detect_captcha_in_html(_html("turnstile_widget.html"))
        assert recaptcha and hcaptcha and turnstile
        self.assertEqual(recaptcha["type"], "recaptcha")
        self.assertTrue(recaptcha["sitekey"].startswith("6Le"))
        self.assertEqual(hcaptcha["type"], "hcaptcha")
        self.assertEqual(turnstile["type"], "turnstile")
        self.assertEqual(turnstile["callback"], "onTurnstileSuccess")


class SolverMapTests(unittest.TestCase):
    def test_capsolver_maps_enterprise_and_arkose(self) -> None:
        from mvp.captcha import _solver_task, capsolver_task_type

        self.assertEqual(capsolver_task_type("recaptcha_enterprise"), "ReCaptchaV2EnterpriseTaskProxyLess")
        self.assertEqual(capsolver_task_type("recaptcha_v3_enterprise"), "ReCaptchaV3EnterpriseTaskProxyLess")
        self.assertEqual(capsolver_task_type("arkose"), "FunCaptchaTaskProxyLess")
        self.assertEqual(capsolver_task_type("turnstile"), "AntiTurnstileTaskProxyLess")
        self.assertIsNone(capsolver_task_type("friendly_captcha"))
        arkose = _solver_task(
            "FunCaptchaTaskProxyLess",
            sitekey="ARKOSE-PUBLIC-KEY-123",
            page_url="https://example.test/signup",
            action=None,
        )
        self.assertEqual(arkose["websitePublicKey"], "ARKOSE-PUBLIC-KEY-123")
        self.assertNotIn("websiteKey", arkose)

    def test_anticaptcha_is_not_sent_to_2captcha(self) -> None:
        from mvp.captcha import solve_sitekey

        posts: list[tuple[str, dict | None]] = []

        def fake_post(url, json=None, data=None, timeout=None):
            posts.append((url, json))

            class Resp:
                def json(self):
                    if url.endswith("/createTask"):
                        return {"errorId": 0, "taskId": 7}
                    return {
                        "errorId": 0,
                        "status": "ready",
                        "solution": {"gRecaptchaResponse": "enterprise-token"},
                    }

            return Resp()

        with (
            patch("mvp.captcha.httpx.post", side_effect=fake_post),
            patch("mvp.captcha.time.sleep"),
            patch("mvp.captcha._api_key", return_value="k"),
            patch.dict(os.environ, {"MVP_CAPTCHA_API": "anti-captcha"}),
        ):
            token = solve_sitekey(
                sitekey="6LeRetellEnterpriseSitekeyXXXX",
                page_url="https://auth.retellai.com/u/signup",
                captcha_type="recaptcha_enterprise",
            )
        self.assertEqual(token, "enterprise-token")
        urls = [url for url, _ in posts]
        self.assertTrue(any(url.startswith("https://api.anti-captcha.com/") for url in urls))
        self.assertFalse(any("2captcha.com" in url for url in urls))
        task = posts[0][1]["task"]
        self.assertEqual(task["type"], "RecaptchaV2EnterpriseTaskProxyless")
        self.assertEqual(task["websiteKey"], "6LeRetellEnterpriseSitekeyXXXX")

    def test_2captcha_turnstile_and_enterprise_flags(self) -> None:
        from mvp.captcha import twocaptcha_params

        turnstile = twocaptcha_params(
            "turnstile",
            sitekey="0x4AAAAAAA-wFNpU7mZhDp4F",
            page_url="https://app.bland.ai/signup",
            action=None,
        )
        enterprise = twocaptcha_params(
            "recaptcha_enterprise",
            sitekey="6Le",
            page_url="https://auth.retellai.com/u/signup",
            action=None,
        )
        arkose = twocaptcha_params(
            "arkose",
            sitekey="PKEY",
            page_url="https://example.test/",
            action=None,
        )
        assert turnstile and enterprise and arkose
        self.assertEqual(turnstile["method"], "turnstile")
        self.assertEqual(enterprise["enterprise"], 1)
        self.assertEqual(arkose["method"], "funcaptcha")
        self.assertEqual(arkose["publickey"], "PKEY")

    def test_inject_script_sets_auth0_field_and_turnstile_callback(self) -> None:
        from mvp.captcha import _inject_token
        import inspect

        src = inspect.getsource(_inject_token)
        self.assertIn('input[name="captcha"]', src)
        self.assertIn("onSuccess", src)
        self.assertIn("cf-turnstile-response", src)


class SmsDefaultTests(unittest.TestCase):
    def test_default_provider_is_not_sms_activate(self) -> None:
        from mvp.sms_provider import _api_name

        with patch.dict(os.environ, {"MVP_SMS_API": ""}):
            os.environ.pop("MVP_SMS_API", None)
            self.assertEqual(_api_name(), "textverified")

    def test_explicit_sms_activate_refuses_without_buying(self) -> None:
        from mvp.sms_provider import lease_number

        with patch.dict(
            os.environ,
            {
                "MVP_SMS_BACKEND": "api",
                "MVP_SMS_API": "sms-activate",
                "MVP_SMS_API_KEY": "not-a-real-key",
            },
        ):
            with self.assertRaises(RuntimeError) as caught:
                lease_number("other")
        self.assertIn("2025-12-29", str(caught.exception))
        self.assertIn("textverified", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
