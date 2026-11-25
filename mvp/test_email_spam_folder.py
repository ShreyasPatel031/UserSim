"""Nov 25: verification mail that Gmail files as Spam is read too (INBOX-only polls never saw it)."""

from __future__ import annotations

import email.message
import email.utils
import unittest
from unittest import mock

from mvp import email_codes as ec


def _mail(to: str, subject: str, body: str) -> bytes:
    m = email.message.EmailMessage()
    m["To"], m["From"], m["Subject"] = to, "Acme <hi@acme.test>", subject
    m["Date"] = email.utils.formatdate()
    m["Message-ID"] = f"<{subject.replace(' ', '')}@acme.test>"
    m.set_content(body)
    return m.as_bytes()


class FakeImap:
    boxes: dict[str, list[bytes]] = {}
    fail_spam = False

    def __init__(self, host, timeout=None):
        self.box = None

    def login(self, user, pw):
        return "OK", [b""]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"']

    def select(self, box, readonly=False):
        box = box.strip('"')
        if box not in self.boxes or (self.fail_spam and box != "INBOX"):
            return "NO", [b""]
        self.box = box
        return "OK", [b""]

    def noop(self):
        return "OK", [b""]

    def uid(self, cmd, *args):
        msgs = self.boxes[self.box]
        if cmd == "search":
            lo = int(args[-1].split(":")[0]) if args[-2] == "UID" else 1
            return "OK", [b" ".join(str(i + 1).encode() for i in range(len(msgs)) if i + 1 >= lo)]
        out = []
        for u in args[0].split(b","):
            raw = msgs[int(u) - 1]
            if b"HEADER.FIELDS" in args[1].encode():
                raw = raw.split(b"\n\n", 1)[0] + b"\n\n"
            out.append((b"%s (UID %s BODY[] {1}" % (u, u), raw))
        return "OK", out

    def logout(self):
        return "BYE", [b""]


class SpamFolderTests(unittest.TestCase):
    def setUp(self):
        for st in (ec._POLL, ec._JUNK_POLL):
            st.pop("con", None)
            st.update(user="", ts=0.0, rows=[], max_uid=0)
        ec._JUNK_POLL["box"] = None
        ec._BODIES.clear()
        ec._JUNK_BODIES.clear()
        FakeImap.fail_spam = False
        FakeImap.boxes = {
            "INBOX": [_mail("other+x@gmail.com", "Welcome", "hello")],
            "[Gmail]/Spam": [_mail("signups+acme1@gmail.com", "Verify your email", "Your code is 482913")],
        }
        self.p = mock.patch("imaplib.IMAP4_SSL", FakeImap)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_mail_in_spam_is_found(self):
        msgs = ec.messages_for_alias("signups@gmail.com", "pw", "signups+acme1@gmail.com")
        self.assertEqual([m["Subject"] for m in msgs], ["Verify your email"])
        diag = ec.recent_mail_diagnostics("signups@gmail.com", "pw", "signups+acme1@gmail.com", since=0)
        self.assertIn({"folder": "spam", "matched": True}, [{"folder": d["folder"], "matched": d["matched"]} for d in diag])

    def test_spam_failure_never_breaks_inbox(self):
        FakeImap.fail_spam = True
        FakeImap.boxes["INBOX"].append(_mail("signups+acme1@gmail.com", "Confirm", "code 111222"))
        msgs = ec.messages_for_alias("signups@gmail.com", "pw", "signups+acme1@gmail.com")
        self.assertEqual([m["Subject"] for m in msgs], ["Confirm"])

    def test_can_be_disabled(self):
        with mock.patch.dict("os.environ", {"MVP_IMAP_JUNK": "0"}):
            self.assertEqual(ec.messages_for_alias("signups@gmail.com", "pw", "signups+acme1@gmail.com"), [])


if __name__ == "__main__":
    unittest.main()
