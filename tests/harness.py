"""Runs every store parser once and collects what it read. Used by record.py and test_parsers.py."""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
EXPECTED = os.path.join(HERE, "expected.json")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scraper"))


def run_all(offline=True):
    import scrape, beers
    if offline:
        time.sleep = lambda s: None  # no waiting between saved responses
    results = {}
    for key, cfg in scrape.PRODUCTS.items():
        scrape.P.clear()
        scrape.P.update(cfg)
        for store in cfg["stores"]:
            scrape.RUN.update(store=store, review=[], warn={})
            try:
                offers = [scrape.finish(o) for o in scrape.ALL_STORES[store]()]
                results[f"{key}/{store}"] = {"offers": offers, "warning": scrape.RUN["warn"].get(store),
                                             "review": sorted(r["name"] for r in scrape.RUN["review"])}
            except Exception as e:
                results[f"{key}/{store}"] = {"error": f"{type(e).__name__}: {e}"}
    for store, fn in beers.STORES.items():
        beers.STORE[0] = store
        beers.WARN.clear()
        try:
            results[f"pohjala/{store}"] = {"offers": fn(), "warning": beers.WARN.get(store)}
        except Exception as e:
            results[f"pohjala/{store}"] = {"error": f"{type(e).__name__}: {e}"}
    return results
