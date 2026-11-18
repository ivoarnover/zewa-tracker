"""Tests for the daily safeguards (checks A, B, C in scraper/scrape.py)."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import FIXTURES  # noqa: E402

os.environ["FIXTURES"] = FIXTURES
os.environ.pop("FIXTURES_RECORD", None)
import scrape  # noqa: E402

BAUHOF = "https://www.bauhof.ee/et/c/kodu-ja-sisustus/kodupaber/tualettpaberid"


class CheckA(unittest.TestCase):
    def test_bauhof_club_price_miss_is_caught(self):
        # Nov 2026: Bauhof added a "Meistriklubi hind" block the parser didn't know. Simulate a parser that misses it.
        page = scrape.fetch(BAUHOF).replace("club-information-item__name", "club-information-item__label")
        scrape.P.clear(); scrape.P.update(scrape.PRODUCTS["zewa"])
        scrape.RUN.update(store="Bauhof", warn={}, review=[])
        real, scrape.fetch = scrape.fetch, lambda url: page
        try:
            scrape.bauhof()
        finally:
            scrape.fetch = real
        self.assertIn("13.49 € that was not read", scrape.RUN["warn"].get("Bauhof", ""))

    def test_shown_prices_skip_unit_prices_and_deposit(self):
        card = '<b>6</b><sup>19</sup> 6.19 € per tk Tavahind: 7,99 € Hind ühiku kohta: 0,77 €/tk 5,60 € / l pant 0,10 €'
        self.assertEqual(scrape.shown_prices(card), {6.19, 7.99})

    def test_unread_loyalty_word(self):
        self.assertIn("loyalty", scrape.unread_prices("Rimi kaardiga 2,99 €", [2.99], loyalty_read=False))
        self.assertIsNone(scrape.unread_prices("Rimi kaardiga 2,99 €", [2.99], loyalty_read=True))


class CheckB(unittest.TestCase):
    kinds = {"loyalty": lambda o: o.get("loyalty"), "campaign": lambda o: o.get("campaign")}

    def test_loyalty_vanished(self):
        prev = [{"id": "1", "loyalty": 2.6}, {"id": "2", "loyalty": None}]
        now = [{"id": "1", "loyalty": None}, {"id": "2", "loyalty": None}]
        self.assertIn("loyalty prices on 1", scrape.vanished(prev, now, lambda o: o["id"], self.kinds, "2026-11-17"))

    def test_campaign_ended_on_time_is_fine(self):
        prev = [{"id": "1", "campaign": 8.88, "valid_until": "16.11.2026"}]
        now = [{"id": "1", "campaign": None}]
        self.assertIsNone(scrape.vanished(prev, now, lambda o: o["id"], self.kinds, "2026-11-17"))

    def test_product_gone_is_not_a_vanished_price(self):
        prev = [{"id": "1", "loyalty": 2.6}]
        self.assertIsNone(scrape.vanished(prev, [{"id": "9", "loyalty": None}], lambda o: o["id"], self.kinds, "2026-11-17"))


class CheckC(unittest.TestCase):
    def test_expired_campaign_and_jump(self):
        prev = [{"id": "1", "per_roll": 0.28}]
        now = [{"id": "1", "per_roll": 0.56, "campaign": 8.88, "valid_until": "16.11.2026"}]
        notes = [n for _, n in scrape.odd_prices(prev, now, lambda o: o["id"], "per_roll", "roll", "2026-11-17")]
        self.assertEqual(len(notes), 2)
        self.assertIn("has passed", notes[0])
        self.assertIn("0.280 € yesterday, 0.560 € today", notes[1])

    def test_small_change_is_quiet(self):
        out = scrape.odd_prices([{"id": "1", "per_roll": 0.40}], [{"id": "1", "per_roll": 0.45}],
                                lambda o: o["id"], "per_roll", "roll", "2026-11-17")
        self.assertEqual(out, [])


class WoltGrace(unittest.TestCase):
    def test_email_only_after_three_failing_days(self):
        w = "Coop Lasnamäe (Wolt)"
        self.assertTrue(scrape.in_grace(w, "2026-11-17", "2026-11-18"))   # 1st failing day: page only
        self.assertTrue(scrape.in_grace(w, "2026-11-16", "2026-11-18"))   # 2nd day
        self.assertFalse(scrape.in_grace(w, "2026-11-15", "2026-11-18"))  # 3rd day in a row: run fails, email
        self.assertFalse(scrape.in_grace("Selver", "2026-11-17", "2026-11-18"))  # other stores: no grace


if __name__ == "__main__":
    unittest.main()
