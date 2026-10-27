"""The "no direct proxy use" scan: the repo passes, and each kind of direct use outside src/fetchgate/ fails."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetchgate import scan


class ScanTest(unittest.TestCase):
    def test_repo_has_no_direct_proxy_or_apify_use_outside_the_gateway(self):
        bad = scan.violations()
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_each_kind_of_direct_use_is_caught(self):
        lines = {
            "P = open(os.path.expanduser('~/php/proxy.txt')).read()": "proxy.txt",
            "px = 'http://auto:pw@proxy.apify.com:8000'": "proxy host",
            "requests.post(f'https://api.apify.com/v2/acts/{a}/runs')": "Apify API",
            "tok = os.environ['APIFY_TOKEN']": "Apify token",
            "P.replace('//auto:', '//groups-RESIDENTIAL,country-US:')": "builds a proxy login",
            "R.get(url, proxies={'https': px})": "passes a proxy",
            "PROXY = {'server': f'http://{u.hostname}:{u.port}'}": "passes a proxy",
            "P = json.load(open('/var/lib/usersim/discovery_keys.json'))['PROXY_URL']": "saved residential proxy",
            "user = 'abc__cr.us'": "builds a proxy login",
            "curl -x http://u:p@gw.dataimpulse.com:823 https://x": "proxy host",
        }
        with tempfile.TemporaryDirectory() as d, mock.patch.object(scan, "ROOT", Path(d)):
            for i, (line, rule) in enumerate(lines.items()):
                (Path(d) / f"s{i}.py").write_text(line + "\n")
                found = scan.violations([f"s{i}.py"])
                self.assertTrue(any(rule in f for f in found), (line, found))
            (Path(d) / "clean.py").write_text("import fetchgate\npage = fetchgate.fetch(url)\n")
            self.assertEqual(scan.violations(["clean.py"]), [])
            (Path(d) / "proxy.txt").write_text("")
            self.assertTrue(scan.violations(["proxy.txt"]))

    def test_the_gateway_itself_and_docs_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(scan, "ROOT", Path(d)):
            (Path(d) / "src/fetchgate").mkdir(parents=True)
            (Path(d) / "src/fetchgate/x.py").write_text("H = 'proxy.apify.com'\n")
            (Path(d) / "notes.md").write_text("we used proxy.apify.com\n")
            self.assertEqual(scan.violations(["src/fetchgate/x.py", "notes.md"]), [])


if __name__ == "__main__":
    unittest.main()
