"""Daily Põhjala brewery beer price tracker.

Many beers instead of one product: every store offer is matched to a beer
(by EAN barcode when the store gives one, otherwise by a cleaned-up name) and
priced per litre (main comparison) and per can, so cases and can sizes compare fairly.

Writes docs/pohjala/data/latest.json and docs/pohjala/data/history.csv.
Exits 1 if a store failed (after writing data), so GitHub emails the owner.
"""
import csv, datetime as dt, gzip, html, json, os, re, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape import fetch, clean, num, UA, replay, record, unread_prices, shown_prices, vanished, odd_prices, RETRY_LATER, in_grace  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "pohjala", "data")
WARN, STORE = {}, [None]  # cut-off warnings per store, current store


def warn(msg):
    WARN[STORE[0]] = (WARN[STORE[0]] + "; " if WARN.get(STORE[0]) else "") + msg


def check_cutoff(count, limit):
    if limit and count >= limit:
        warn(f"returned {count} results, the page limit; some beers may be missing")


FIELDS = ["date", "beer", "store", "name", "pack", "volume_l", "regular", "best", "best_type", "per_can", "per_litre", "url"]

# ------------------------------------------------------------- matching

NOT_BEER = re.compile(r"tee\b|teetalu|taimetee|marjatee|münt|püramiid|\bkali\b|\bgin\b|müts|särk|pusa|kott|kinke", re.I)
ALCOHOL_FREE = re.compile(r"alk\.?\s*v|alko\.?\s*vaba|alkoholivaba|\ba/v\b", re.I)
ALIASES = [  # store abbreviations -> brewery spelling
    (r"prenzl\.?\s*berg|prenzlauer(\s+berg)?", "prenzlauer berg"),
    (r"treen\.?\s*laager|treeninglaag(?!er)\.?", "treeninglaager "),
    (r"treeninglaager\s+vaarika\b", "treeninglaager vaarikas"),
    (r"sun city ale", "sun city"),
    (r"\bgrapefruit\b", "gf"),  # Kaupmees "Grapefruit Pale Ale 3,5%" = brewery "GF"
]
NOISE = re.compile(
    r"(?<![\w])(alkoholivaba|alko\.?\s*vaba|alk\.?\s*vaba|alk\.?\s*v\.|a/v|kange|hele|tume|õlu|olu|põhjala|pohjala|prk|purk|pdl|pudel|"
    r"ipa|vol|kast|kastis|tin|klaas|nisuõlu|ne|session|festive|hazy|pale|ale|porter|sour)(?![\w])", re.I)


def volume_l(text):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b", text.lower())
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return round(v / {"ml": 1000, "cl": 100, "l": 1}[m.group(2)], 3)


def pack_of(text):
    text = html.unescape(text)
    m = re.search(r"(\d+)\s*[x×]\s*\d", text.lower()) or re.search(r"(\d+)\s*-?\s*(?:pakk|pk)\b", text.lower())
    return int(m.group(1)) if m else 1


def beer_key(name):
    n = html.unescape(name).lower().replace("×", "x")
    tume = n.strip().startswith("tume") or re.search(r"\btume laager\b", n) is not None
    af = bool(ALCOHOL_FREE.search(n))
    n = re.sub(r"\d+\s*x\s*\d+(?:[.,]\d+)?\s*(ml|cl|l)\b", " ", n)  # 24 x 0.44l, 6x44cl
    n = re.sub(r"\d+\s*-?\s*(pakk|pk)\b", " ", n)                     # 6-pakk
    n = re.sub(r"\d+(?:[.,]\d+)?\s*(ml|cl|l)\b", " ", n)            # 330ml, 0,44l, 44cl
    n = re.sub(r"\d+(?:[.,]\d+)?\s*%\s*(vol)?", " ", n)              # 6.5%, 4,7%vol
    for pat, rep in ALIASES:
        n = re.sub(pat, rep, n)
    n = re.sub(r"alkoholivaba|alko\.?\s*vaba|alk\.?\s*vaba|alk\.?\s*v\.?|(?<!\w)a/v(?!\w)", " ", n)
    n = n.replace("põhjala", " põhjala ")
    n = NOISE.sub(" ", n)
    n = re.sub(r"^\s*x\s+", " ", n)                                  # "Põhjala x Other Half ..." -> "Other Half ..."
    n = re.sub(r"[^\wõäöüšž0 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    if tume and n == "laager":
        n = "tume laager"
    if af and not n.endswith(" 0") and "treeninglaager" not in n:
        n += " 0"
    return n


def offer(store, name, url, price, regular=None, loyalty=None, label=None, ean=None, vol=None):
    price, regular, loyalty = num(price), num(regular) or num(price), num(loyalty)
    choices = [(loyalty, "loyalty"), (price if price and regular and price < regular else None, "campaign"), (regular, "regular")]
    best, kind = min(((p, k) for p, k in choices if p), default=(None, None))
    pack = pack_of(name)
    return dict(store=store, name=clean(html.unescape(name)), url=url, ean=ean, key=beer_key(name),
                pack=pack, volume_l=vol or volume_l(name), regular=regular, best=best, best_type=kind,
                loyalty_label=label if kind == "loyalty" else None,
                per_can=round(best / pack, 3) if best else None)

# ------------------------------------------------------------- stores


def woo(base, query):
    items = json.loads(fetch(base + "/wp-json/wc/store/v1/products?" + query + "&per_page=100"))
    check_cutoff(len(items), 100)
    for p in items:
        pr, div = p["prices"], 10 ** p["prices"].get("currency_minor_unit", 2)
        yield p, int(pr["price"]) / div, int(pr["regular_price"]) / div


def pohjala_shop():
    out = []
    for p, price, regular in woo("https://shop.pohjalabeer.com", "category=olu"):
        if not p.get("is_in_stock") or NOT_BEER.search(p["name"]):
            continue
        desc = clean(p.get("short_description", "") + " " + p.get("description", ""))
        out.append(offer("Põhjala e-shop", p["name"], p["permalink"], price, regular, ean=p.get("sku"),
                         vol=volume_l(p["name"]) or volume_l(desc)))
    return out


def coop():
    out = []
    for p, price, regular in woo("https://coophaapsalu.ee", "search=p%C3%B5hjala"):
        if not p.get("is_in_stock") or NOT_BEER.search(p["name"]):
            continue
        out.append(offer("Coop", p["name"], p["permalink"], price, regular, ean=p.get("sku")))
    return out


def selver():
    url = "https://www.selver.ee/api/catalog/vue_storefront_catalog_et/product/_search?q=p%C3%B5hjala&size=200"
    out = []
    res = json.loads(fetch(url))["hits"]
    hits, total = res["hits"], (res.get("total") or {}).get("value", 0)
    if total > len(hits):  # the search found more than one page
        check_cutoff(len(hits), len(hits))
    for h in hits:
        s = h["_source"]
        if s.get("status") != 1 or "PÕHJALA" not in s.get("name", "") or NOT_BEER.search(s["name"]):
            continue
        groups = {p.get("customer_group_id"): p for p in s.get("prices") or []}
        g0 = groups.get(0, {})
        regular = g0.get("original_price") or s.get("price_incl_tax")
        now = g0.get("final_price") or s.get("final_price_incl_tax")
        loyalty = s.get("product_group_price") or groups.get(1, {}).get("final_price")
        if loyalty and regular and loyalty >= regular:
            loyalty = None
        out.append(offer("Selver", s["name"], "https://www.selver.ee/" + s["url_key"], now, regular, loyalty,
                         "Partnerkaart", s.get("product_main_ean"), volume_l(s.get("product_volume") or "")))
    return out


def barbora():
    data = json.loads(fetch("https://barbora.ee/api/eshop/v1/search?query=p%C3%B5hjala"))
    check_cutoff(len(data.get("products", [])), data.get("limit"))
    out = []
    for p in data.get("products", []):
        t = p.get("title", "")
        if p.get("status") != "active" or "hjala" not in t.lower() or NOT_BEER.search(t):
            continue
        promo = p.get("promotion") or {}
        price, old = p.get("price"), promo.get("oldPrice")
        url = "https://barbora.ee/p/" + p["Url"]
        if promo.get("loyaltyCardRequired"):
            out.append(offer("Barbora", t, url, old or price, old or price, price, "AITÄH kaart"))
        else:
            out.append(offer("Barbora", t, url, price, old or price))
    return out


def rimi():
    page = fetch("https://www.rimi.ee/epood/ee/otsing?query=p%C3%B5hjala&pageSize=80")
    check_cutoff(page.count('class="product-grid__item"'), 80)
    out = []
    for chunk in page.split('class="product-grid__item"')[1:]:
        m = re.search(r"data-gtm-eec-product='([^']+)'", chunk)
        if not m:
            continue
        j = json.loads(html.unescape(m.group(1)))
        if "hjala" not in j["name"].lower() or NOT_BEER.search(j["name"]) or "Ei ole saadaval" in chunk:
            continue
        href = re.search(r'href="(/epood/ee/tooted/[^"]+)"', chunk)
        old = re.search(r"Tavahind:\s*([\d.,]+)", chunk)
        problem = unread_prices(chunk[:chunk.find("Lisa ostukorvi") if "Lisa ostukorvi" in chunk else 6000],
                                [j["price"], old.group(1) if old else None])
        if problem:
            warn(f"product {j['id']} {problem}")
        out.append(offer("Rimi", j["name"], "https://www.rimi.ee" + href.group(1) if href else "",
                         j["price"], old.group(1) if old else j["price"]))
    return out


def wolt_coop():
    api = "https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/coop-lasname"
    root = json.loads(fetch(api + "/assortment?language=et"))
    cat, stack = None, list(root.get("categories", []))
    while stack:
        c = stack.pop()
        if c.get("name", "").strip().lower() == "õlu":
            cat = c["slug"]
            break
        stack += c.get("subcategories", [])
    if not cat:
        raise RuntimeError("Õlu category not found on Wolt")
    time.sleep(2)
    items, token = [], None
    for _ in range(10):  # category is paged, 50 items per page
        url = api + "/assortment/categories/slug/" + cat + "?language=et" + ("&page_token=" + token if token else "")
        data = json.loads(fetch(url))
        items += data.get("items", [])
        token = (data.get("metadata") or {}).get("next_page_token")
        if not token:
            break
        time.sleep(2)
    out = []
    for i in items:
        if i.get("disabled_info") or "hjala" not in i["name"].lower() or NOT_BEER.search(i["name"]):
            continue
        price, orig = i["price"] / 100, (i.get("original_price") or 0) / 100
        o = offer("Coop Lasnamäe (Wolt)", i["name"], "https://wolt.com/et/est/tallinn/venue/coop-lasname",
                  price, orig or price, ean=i.get("barcode_gtin"))
        out.append(o)
    return out


# Viinarannasta sometimes answers automated requests with a "One moment, please..." bot check. We don't try to get
# around it: that day its last prices stay on the page (marked old) and the run doesn't fail or send an email.
SOFT_FAIL = {"Viinarannasta"}
MAY_BE_EMPTY = {"Coop Lasnamäe (Wolt)"}  # Wolt's Coop Lasnamäe had no Põhjala beers when this was built
VAT = 1.24  # Estonian VAT; Kaupmees shows prices without VAT ("+KM")


def kaupmees():
    # Kaupmees & Ko e-shop: beer category filtered by brand, server-rendered cards; prices are excl. VAT
    page = fetch("https://www.kaupmees.ee/et/alkohol-ja-tubakas/olled?brand=P%C3%95HJALA")
    check_cutoff(page.count(' Hind"'), 48)
    out = []
    for m in re.finditer(r'<section aria-label="([^"]+?) Hind"', page):
        name = html.unescape(m.group(1))
        sec = page[m.end():page.find("</section>", m.end())]
        before = page[max(0, m.start() - 4000):m.start()]
        links = re.findall(r'href="(/et/[^"]+-c\d+)"', before)
        major = re.search(r'price-major[^"]*">(\d+)<', sec)
        minor = re.search(r'price-minor[^"]*">(\d+)<', sec)
        if not major or "PÕHJALA" not in name.upper() or NOT_BEER.search(name):
            continue
        price = int(major.group(1)) + int(minor.group(1)) / 100 if minor else int(major.group(1))
        problem = unread_prices(sec, [price])
        if sec.count("price-major") > 1:
            problem = f"shows {sec.count('price-major')} prices, only 1 was read; layout may have changed"
        if problem:
            warn(f"{name}: {problem}")
        if "+KM" in re.sub(r"<[^>]+>", "", sec):
            price *= VAT
        pct = re.search(r"-(\d+)%", re.sub(r"<[^>]+>", " ", sec))
        regular = price / (1 - int(pct.group(1)) / 100) if pct else price
        out.append(offer("Kaupmees", name, "https://www.kaupmees.ee" + links[-1] if links else
                         "https://www.kaupmees.ee/et/alkohol-ja-tubakas/olled?brand=P%C3%95HJALA",
                         round(price, 2), round(regular, 2)))
    return out


class Challenged(Exception):
    """The shop showed its bot check ("One moment, please...") instead of the page."""


def polite_fetch(url):
    # one plain GET with honest, browser-like headers; we never run or answer the bot check
    saved = replay(url)
    if saved is not None:
        return saved
    req = urllib.request.Request(url, headers={
        "User-Agent": "zewa-tracker/1.0 (+https://github.com/ivoarnover/zewa-tracker)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "et-EE,et;q=0.9,en;q=0.5", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=45) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return record(url, body.decode("utf-8", "replace"))


def viinarannasta():
    # Viinarannasta (Aldar Eesti) e-shop search, server-rendered cards with price.
    # The host uses Imunify360 bot protection, which sometimes challenges cloud IPs.
    page = polite_fetch("https://viinarannasta.ee/shop?search=p%C3%B5hjala")
    if "One moment, please" in page or "product-detail/" not in page:
        raise Challenged("bot check page instead of results (Imunify360); last prices kept")
    out = []
    for card in page.split('<div class="item"')[1:]:
        link = re.search(r'href="(https://viinarannasta\.ee/product-detail/[^"]+)"[^>]*>([^<]+)</a>', card)
        if not link or "hjala" not in link.group(2).lower() or NOT_BEER.search(link.group(2)):
            continue
        text = re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>|<script.*?</script>", "", card[:6000], flags=re.S))
        prices = [float(p) for p in re.findall(r"(\d+\.\d{2})\s*€", text)]
        if not prices:
            continue
        problem = unread_prices(card[:6000], [min(prices), max(prices)])
        if len(set(prices)) > 2:
            problem = f"shows {len(set(prices))} prices, only lowest and highest were read; layout may have changed"
        if problem:
            warn(f"{link.group(2)}: {problem}")
        out.append(offer("Viinarannasta", link.group(2), link.group(1), min(prices), max(prices)))
    if not out:
        title = re.search(r"<title>([^<]*)", page)
        raise RuntimeError(f"no Põhjala cards on search page ({len(page)} bytes, title {title.group(1).strip() if title else '?'!r}, "
                           f"{page.count('product-detail/')} product links)")
    return out


STORES = {"Põhjala e-shop": pohjala_shop, "Selver": selver, "Rimi": rimi, "Barbora": barbora, "Coop": coop,
          "Coop Lasnamäe (Wolt)": wolt_coop, "Kaupmees": kaupmees, "Viinarannasta": viinarannasta}

# ------------------------------------------------------------- main


def build_beers(offers):
    """Group offers into beers: EAN links names across stores, then names link the rest."""
    ean_key = {}
    for o in offers:  # brewery shop and EAN stores first, so their spelling wins
        if o["ean"]:
            ean_key.setdefault(o["ean"], o["key"])
    for o in offers:
        if o["ean"] and o["ean"] in ean_key:
            o["key"] = ean_key[o["ean"]]
    known = {o["key"] for o in offers if o["ean"] or o["store"] == "Põhjala e-shop"}
    for o in offers:  # name-only stores: map "kask laager" -> "kask", "kosmos ne ipa hele" -> "kosmos"
        if o["ean"] or o["key"] in known:
            continue
        toks = o["key"].split()
        best = None
        for k in known:
            kt = k.split()
            if all(t in toks for t in kt):
                score = (len(kt), -min(toks.index(t) for t in kt))
                if not best or score > best[0]:
                    best = (score, k)
        if best:
            o["key"] = best[1]
        else:
            o["unmatched"] = True  # new beer, or a name we couldn't link: listed under "check these"
    beers = {}
    for o in sorted(offers, key=lambda o: o["store"] != "Põhjala e-shop"):
        b = beers.setdefault(o["key"], {"key": o["key"], "name": None, "volume_l": None, "alcohol_free": o["key"].endswith(" 0") or "treeninglaager" in o["key"]})
        if o["store"] == "Põhjala e-shop" and (not b["name"] or o["pack"] == 1):
            n = re.sub(r"\s*\d+\s*[x×]\s*[\d.,]+\s*l\b", "", o["name"], flags=re.I)
            b["name"] = re.sub(r"\s*\d+(?:[.,]\d+)?\s*(ml|l)\b", "", n, flags=re.I).strip()
        if o["volume_l"] and not b["volume_l"]:
            b["volume_l"] = o["volume_l"]
    for b in beers.values():  # beers not sold by the brewery shop: readable name from the key
        if not b["name"]:
            b["name"] = b["key"].replace(" 0", " 0%").title().replace("0%", "0")
    for o in offers:
        o["beer"] = o["key"]
    return beers


def main():
    os.makedirs(DATA, exist_ok=True)
    latest_path, hist_path = os.path.join(DATA, "latest.json"), os.path.join(DATA, "history.csv")
    prev = json.load(open(latest_path)) if os.path.exists(latest_path) else {"offers": [], "status": {}}
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone(dt.timedelta(hours=2))).date().isoformat()
    offers, status, failed = [], {}, []
    order = list(STORES)
    retried, first_try = False, {}
    while order:
        store = order.pop(0)
        fn = STORES[store]
        STORE[0] = store
        if store in first_try:  # second try for a busy store (Wolt): at least 3 minutes after the first
            time.sleep(max(0, 180 - (time.time() - first_try[store])))
        try:
            try:
                got = [o for o in fn() if o["per_can"]]
            except Challenged:
                if retried or os.environ.get("NO_RETRY"):
                    raise
                retried = True  # one more try at the end of the run, 20 minutes later; never more
                print(store, "challenged, retrying once in 20 minutes", flush=True)
                time.sleep(1200)
                got = [o for o in fn() if o["per_can"]]
            if not got and store not in MAY_BE_EMPTY:
                raise RuntimeError("no Põhjala beers parsed (page layout changed?)")
            offers += got
            before = [o for o in prev.get("offers", []) if o["store"] == store]
            gone = vanished(before, got, lambda o: o["name"],  # check B
                            {k: (lambda o, k=k: o.get("best_type") == k) for k in ("loyalty", "campaign")}, today)
            if gone:
                warn(gone)
            status[store] = {"ok": True, "count": len(got), "last_ok": today, "error": None, "warning": WARN.get(store)}
            if WARN.get(store):
                failed.append(store + " (warning)")
        except Exception as e:
            old = prev.get("status", {}).get(store, {})
            if store in RETRY_LATER and store not in first_try and not os.environ.get("NO_RETRY"):
                first_try[store] = time.time()
                order.append(store)
                print(store, f"failed ({type(e).__name__}: {e}), trying once more at the end", flush=True)
                continue
            if store not in SOFT_FAIL and not in_grace(store, old.get("last_ok"), today):
                failed.append(store)
            status[store] = {"ok": False, "count": 0, "last_ok": old.get("last_ok"), "error": f"{type(e).__name__}: {e}"[:300]}
            recent = old.get("last_ok") and (dt.date.fromisoformat(today) - dt.date.fromisoformat(old["last_ok"])).days <= 60
            if recent:  # keep the last good prices for up to 60 days, then drop them
                offers += [dict(o, stale=True) for o in prev.get("offers", []) if o["store"] == store]
        print(store, status[store], flush=True)
        time.sleep(2)

    beers = build_beers(offers)
    for o in offers:  # fill missing can size from the beer (e.g. brewery shop names have no size)
        if not o["volume_l"]:
            o["volume_l"] = beers[o["beer"]]["volume_l"]
        # main comparison: price per litre (can size doesn't matter to the buyer)
        o["per_litre"] = round(o["best"] / (o["pack"] * o["volume_l"]), 2) if o["best"] and o["volume_l"] else None
    review = sorted({(o["store"], o["name"], "") for o in offers if o.get("unmatched") and not o.get("stale")})
    for store in STORES:  # check C: big jumps per litre since yesterday
        before = [o for o in prev.get("offers", []) if o["store"] == store]
        now_ = [o for o in offers if o["store"] == store and not o.get("stale")]
        review += [(store, o["name"], note) for o, note in odd_prices(before, now_, lambda o: o["name"], "per_litre", "litre", today)]
    json.dump({"updated": now.isoformat(timespec="minutes"),
               "review": [dict(store=st, name=n, **({"note": nt} if nt else {})) for st, n, nt in review], "beers": sorted(beers.values(), key=lambda b: b["name"].lower()),
               "offers": offers, "status": status}, open(latest_path, "w"), ensure_ascii=False, indent=1)

    rows = []
    if os.path.exists(hist_path):
        rows = [r for r in csv.DictReader(open(hist_path, encoding="utf-8")) if r["date"] != today]
    rows += [dict({k: o.get(k) for k in FIELDS}, date=today) for o in offers if not o.get("stale")]
    with open(hist_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if failed:
        print("FAILED STORES:", ", ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
