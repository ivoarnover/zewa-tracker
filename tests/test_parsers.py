"""Offline parser tests: every store parser must read the saved pages exactly as recorded in expected.json.

Run: python -m unittest discover tests
Catches code changes that break a parser. New site layouts are caught by the daily run's own checks.
"""
import json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import FIXTURES, EXPECTED  # noqa: E402

os.environ["FIXTURES"] = FIXTURES
os.environ.pop("FIXTURES_RECORD", None)
from harness import run_all  # noqa: E402


class Parsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(EXPECTED) as f:
            cls.expected = json.load(f)
        cls.got = json.loads(json.dumps(run_all(offline=True)))

    def test_every_store(self):
        for key, exp in self.expected.items():
            with self.subTest(store=key):
                self.assertEqual(self.got.get(key), exp)

    def test_saved_pages_parse_cleanly(self):
        for key, exp in self.expected.items():
            with self.subTest(store=key):
                self.assertNotIn("error", exp, "recorded page failed to parse; re-record or fix the parser")
                self.assertFalse(exp.get("warning"), "recorded page raised a warning")


if __name__ == "__main__":
    unittest.main()
