"""In-house review parsers against real pages saved in mvp/fixtures/reviews/ (fetched Oct 2026)."""

from __future__ import annotations

import unittest
from pathlib import Path

from mvp import review_parsers as P

FIX = Path(__file__).resolve().parent / "fixtures" / "reviews"


class CapterraTest(unittest.TestCase):
    def test_parses_every_card_with_reviewer_and_ratings(self):
        rows = P.parse_capterra((FIX / "capterra_shortcut_p1.html").read_text(), "Shortcut")
        self.assertEqual(len(rows), 25)
        first = rows[0]
        self.assertEqual((first["name"], first["role"], first["industry"], first["time_used"], first["rating"]),
                         ("Bryan M.", "Product Director", "Design", "6-12 months", 5.0))
        self.assertTrue(first["pros"] and first["cons"])
        self.assertTrue(all(r["role"] and r["rating"] for r in rows))

    def test_collect_pages_until_enough_and_stops_on_repeat(self):
        page = (FIX / "capterra_shortcut_p1.html").read_text()
        rows, info = P.collect("capterra", "https://www.capterra.com/p/1/X/reviews/", "X", lambda u: (200, page))
        self.assertEqual((len(rows), info["pages"]), (25, 2))  # page 2 repeats page 1: nothing new, stop


class G2Test(unittest.TestCase):
    def test_parses_articles_with_size_rating_and_answers(self):
        rows = P.parse_g2((FIX / "g2_linear_p1.html").read_text(), "Linear")
        self.assertEqual(len(rows), 10)
        first = rows[0]
        self.assertEqual((first["name"], first["role"], first["industry"], first["size"], first["rating"], first["date"]),
                         ("Mathan K.", "Web Developer", "Computer Software", "Small-Business (50 or fewer emp.)", 5.0, "9/16/2026"))
        self.assertTrue(first["pros"].startswith("What I like most") and "Review collected by" not in first["pros"])
        self.assertTrue(all(r["size"] and r["rating"] and r["pros"] for r in rows))


if __name__ == "__main__":
    unittest.main()
