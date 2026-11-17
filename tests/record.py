"""Save fresh store responses as test fixtures and write what the parsers read from them.

  python tests/record.py            fetch real pages once (a normal daily-sized set of requests), save them
  python tests/record.py --offline  keep the saved pages, only rewrite expected.json (after a deliberate parser change)

Always look at the diff of tests/expected.json before committing: it is what the tests will hold the parsers to.
"""
import json, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import FIXTURES, EXPECTED  # noqa: E402

offline = "--offline" in sys.argv
os.environ["FIXTURES"] = FIXTURES
if not offline:
    os.environ["FIXTURES_RECORD"] = "1"
    shutil.rmtree(FIXTURES, ignore_errors=True)
from harness import run_all  # noqa: E402  (imports scrape after the env is set)

results = run_all(offline=offline)
json.dump(results, open(EXPECTED, "w"), ensure_ascii=False, indent=1, sort_keys=True)
for k, v in results.items():
    print(f"{k:40} " + (v["error"] if "error" in v else f"{len(v['offers'])} offers" + (f", WARNING {v['warning']}" if v.get("warning") else "")))
