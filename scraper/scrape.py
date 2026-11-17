"""Daily price scraper for a few tracked products (see PRODUCTS at the bottom).

A few requests per store, Python stdlib only. For each product it writes:
  <data_dir>/latest.json   current offers + per-store status
  <data_dir>/history.csv   one row per offer per day
Fields are named after the first product (rolls, per_roll) but mean "units" and "price per unit".
Exits 1 if any store failed (after writing data), so GitHub emails the repo owner.
"""
import csv, datetime as dt, html, json, os, re, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
P = {}  # the product being scraped right now (set in main)
RUN = {"store": None, "review": [], "warn": {}}  # current store, names to check by hand, cut-off warnings
FIELDS = ["date", "store", "id", "name", "rolls", "regular", "campaign", "loyalty",
          "best", "best_type", "per_roll", "url", "ean"]


_cache = {}


def fetch(url):
    # same URL twice in one run (e.g. Wolt's category list for both products) is fetched once;
    # on 429 Too Many Requests wait and retry, so one busy minute doesn't fail the store
    if url in _cache:
        return _cache[url]
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "et-EE,et;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                _cache[url] = r.read().decode("utf-8", "replace")
                return _cache[url]
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(30 * (attempt + 1))  # busy (429) or a passing server error (5xx): wait and retry


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def is_match(name):
    ok = P["match"](name)
    if not ok and P.get("near") and P["near"](name):  # looks like our product but wasn't understood
        RUN["review"].append({"store": RUN["store"], "name": clean(html.unescape(name))})
    return ok


def check_cutoff(count, limit):
    """A store returned a full page: there may be more products we didn't see."""
    if limit and count >= limit:
        RUN["warn"][RUN["store"]] = f"returned {count} results, the page limit; some products may be missing"


def count_of(name):
    return P["count"](name)


def is_deluxe_tp(name):
    n = name.lower()
    # Zewa Deluxe only (incl. Delicate Care, Pure White, Lavender); Zewa Everyday is excluded
    # napkins, tissues, kitchen rolls and wet wipes are excluded; a roll count must be present
    return ("delux" in n and "everyday" not in n
            and not re.search(r"salvr|rätik|ratik|majapidamis|niisk|köögi", n)
            and rolls_of(name) is not None)


def rolls_of(name):
    n = name.lower()
    multi = re.search(r"(\d+)\s*[x×]\s*(\d+)\s*(?:rulli|rull|rul|rl)", n)  # e.g. 2x24 rl
    if multi:
        return int(multi.group(1)) * int(multi.group(2))
    found = re.findall(r"(\d+)[\s-]*(?:rulli|rull|rul|rl)", n) or re.findall(r"(\d+)\s*tk\b", n)
    return int(found[-1]) if found else None


def near_zewa(name):
    n = name.lower()
    return ("delux" in n and "everyday" not in n and rolls_of(name) is None
            and not re.search(r"salvr|rätik|ratik|majapidamis|niisk|köögi", n))


def near_huggies(name):
    n = name.lower()
    return ("huggies" in n and re.search(r"pants|püksm|puksm", n) is not None and diapers_of(name) is None
            and not re.search(r"extra ?care|overnight|dry ?n|ultra|swim|elite|niisk|salvr", n)
            and not ("girl" in n and "boy" not in n)
            and re.search(r"(?<![\d-])(?:s\s?)?5(?![\d.]|\s*-\s*\d|\s*kg)|12\s*-\s*17\s*kg", n) is not None)


def is_huggies_pants5_boy(name):
    # Huggies Pants (incl. Little Movers) size 5 / 12-17 kg, Boy or no gender given; Girl and other lines excluded
    n = name.lower()
    if "huggies" not in n or not re.search(r"pants|püksm|puksm", n):
        return False
    if re.search(r"extra ?care|overnight|dry ?n|ultra|swim|elite|niisk|salvr", n):
        return False
    if "girl" in n and "boy" not in n:
        return False
    size5 = re.search(r"(?<![\d-])(?:s\s?)?5(?![\d.]|\s*-\s*\d|\s*kg)|12\s*-\s*17\s*kg", n)
    return bool(size5) and diapers_of(name) is not None


def diapers_of(name):
    found = re.findall(r"(\d+)\s*(?:tk|pcs)\b", name.lower())
    return int(found[-1]) if found else None


def num(x):
    try:
        v = float(str(x).replace(",", ".").replace("€", "").strip())
        return round(v, 2) if v > 0 else None
    except (TypeError, ValueError):
        return None


def offer(store, pid, name, url, regular=None, campaign=None, loyalty=None,
          loyalty_label=None, valid_until=None):
    regular, campaign, loyalty = num(regular), num(campaign), num(loyalty)
    if campaign and regular and campaign >= regular:
        campaign = None
    if loyalty and regular and loyalty >= regular:
        loyalty = None
    return dict(store=store, id=str(pid), name=clean(name), url=url, rolls=count_of(name),
                regular=regular, campaign=campaign, loyalty=loyalty,
                loyalty_label=loyalty_label, valid_until=valid_until)


# ---------------------------------------------------------------- stores

def selver():
    url = ("https://www.selver.ee/api/catalog/vue_storefront_catalog_et/product/_search"
           "?q=" + P["term"] + "&size=300")
    out = []
    res = json.loads(fetch(url))["hits"]
    hits, total = res["hits"], (res.get("total") or {}).get("value", 0)
    if total > len(hits):  # the search found more than one page
        check_cutoff(len(hits), len(hits))
    for h in hits:
        s = h["_source"]
        if s.get("status") != 1 or not is_match(s.get("name", "")):
            continue
        groups = {p.get("customer_group_id"): p for p in s.get("prices") or []}
        g0 = groups.get(0, {})
        regular = g0.get("original_price") or s.get("original_price_incl_tax") or s.get("price_incl_tax")
        now = g0.get("final_price") or s.get("final_price_incl_tax")
        # Partner card price: product_group_price, else customer group 1 (matches the Partnerkaart badge)
        loyalty = s.get("product_group_price") or groups.get(1, {}).get("final_price")
        o = offer("Selver", s.get("sku") or s["id"], s["name"],
                  "https://www.selver.ee/" + s["url_key"], regular, now, loyalty,
                  "Partnerkaart", s.get("special_to_date"))
        o["ean"] = s.get("product_main_ean")
        out.append(o)
    return out


def barbora():
    data = json.loads(fetch("https://barbora.ee/api/eshop/v1/search?query=" + P["term"]))
    check_cutoff(len(data.get("products", [])), data.get("limit"))
    out = []
    for p in data.get("products", []):
        if p.get("status") != "active" or not is_match(p.get("title", "")):
            continue
        promo = p.get("promotion") or {}
        price, old = p.get("price"), promo.get("oldPrice")
        regular = old or price
        if promo.get("loyaltyCardRequired"):
            o = offer("Barbora", p["id"].lstrip("0"), p["title"], "https://barbora.ee/p/" + p["Url"],
                      regular, None, price, "AITÄH kaart")
        else:
            o = offer("Barbora", p["id"].lstrip("0"), p["title"], "https://barbora.ee/p/" + p["Url"],
                      regular, price if old else None)
        out.append(o)
    return out


def rimi():
    page = fetch("https://www.rimi.ee/epood/ee/otsing?query=" + P["term"] + "&pageSize=80")
    check_cutoff(page.count('class="product-grid__item"'), 80)
    out = []
    for chunk in page.split('class="product-grid__item"')[1:]:
        m = re.search(r"data-gtm-eec-product='([^']+)'", chunk)
        if not m:
            continue
        j = json.loads(html.unescape(m.group(1)))
        if not is_match(j["name"]) or "Ei ole saadaval" in chunk:
            continue
        href = re.search(r'href="(/epood/ee/tooted/[^"]+)"', chunk)
        old = re.search(r"Tavahind:\s*([\d.,]+)", chunk)
        card = re.search(r"kaardiga|Mina Rimi", chunk, re.I)
        url = "https://www.rimi.ee" + href.group(1) if href else ""
        if old and card:
            out.append(offer("Rimi", j["id"], j["name"], url, old.group(1), None, j["price"], "Rimi kaart"))
        else:
            out.append(offer("Rimi", j["id"], j["name"], url, old.group(1) if old else j["price"],
                             j["price"] if old else None))
    return out


def bauhof():
    page = fetch(P["bauhof_url"])
    check_cutoff(page.count('class="product-card-title"'), 32)
    out = []
    for card in re.split(r'(?=<a href="/et/p/\d+/)', page)[1:]:
        title = re.search(r'class="product-card-title"[^>]*>([^<]+)<', card)
        if not title or not is_match(title.group(1)):
            continue
        card = card[:card.find("</a>", card.find("product-card-bottom"))]
        href = re.match(r'<a href="(/et/p/(\d+)/[^"]+)"', card)
        regular = campaign = loyalty = label = until = None
        # campaign / advanced price blocks: label + price
        for name, body in re.findall(
                r'advanced-product-prices__name[^>]*>(.*?)</div>\s*<div class="advanced-product-prices__price[^"]*"[^>]*>(.*?)</div>',
                card, re.S):
            n, price = clean(name), num(re.sub(r"[^\d.]", "", clean(re.search(r'price-block[^>]*>(.*?€)', body, re.S).group(1))))
            u = re.search(r"(\d{2}\.\d{2}\.\d{4})", n)
            if re.search(r"kliendi|klubi|sisse", n, re.I):
                loyalty, label = price, re.sub(r"\s*kehtib kuni.*", "", n)
            elif re.search(r"kampaania|e-hind", n, re.I):
                campaign, until = price, u.group(1) if u else None
            else:
                regular = price
        reg = re.search(r'product-price__regular"[^>]*>(.*?)</span>\s*</span>|product-price__regular"[^>]*>(.*?€)', card, re.S)
        if reg:
            regular = num(re.sub(r"[^\d.]", "", clean(reg.group(1) or reg.group(2))))
        tier = re.search(r'product-price__tier-price_active[^"]*"[^>]*>(.*?€).*?tier-price__name[^>]*>([^<]+)<', card, re.S)
        if tier:
            loyalty, label = num(re.sub(r"[^\d.]", "", clean(tier.group(1)))), clean(tier.group(2))
        # Since Nov 2026: club price block, e.g. "Meistriklubi hind 13.49 €" (shown without logging in)
        club = re.search(r'club-information-item__name[^>]*>([^<]+)<.*?club-information-item__value[^>]*>(.*?€)', card, re.S)
        if club:
            loyalty, label = num(re.sub(r"[^\d.]", "", clean(club.group(2)))), clean(club.group(1))
        # Safeguard: every price on the card must be understood, else the layout changed again
        shown = len(set(re.findall(r'price-block__integer"[^>]*>(\d+)</span>([.,]\d+)', card)))
        parsed = len({p for p in (regular, campaign, loyalty) if p})
        if shown > parsed:
            RUN["warn"][RUN["store"]] = f"card {href.group(2)} shows {shown} prices but only {parsed} were parsed; layout may have changed"
        if not regular and not campaign and not loyalty:
            continue
        out.append(offer("Bauhof", href.group(2), title.group(1), "https://www.bauhof.ee" + href.group(1),
                         regular, campaign, loyalty, label, until))
    return out


def coop():
    # Coop has no central e-shop; Coop Haapsalu's WooCommerce Store API is the only public Coop price source found.
    return woo("Coop", "https://coophaapsalu.ee")


def lapseriided():
    return woo("Lapseriided.com", "https://lapseriided.com")


def woo(store, base):
    # WooCommerce Store API (public, read-only product search)
    items = json.loads(fetch(base + "/wp-json/wc/store/v1/products?search=" + P["term"] + "&per_page=100"))
    check_cutoff(len(items), 100)
    out = []
    for p in items:
        name = html.unescape(p["name"])
        if not p.get("is_in_stock") or not is_match(name):
            continue
        pr, div = p["prices"], 10 ** p["prices"].get("currency_minor_unit", 2)
        regular, now = int(pr["regular_price"]) / div, int(pr["price"]) / div
        o = offer(store, p["id"], name, p["permalink"], regular, now if now < regular else None)
        o["ean"] = p.get("sku")
        out.append(o)
    return out


WOLT_VENUES = {"Coop Lasnamäe (Wolt)": "coop-lasname"}
WOLT_API = "https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/"


def wolt_coop():
    # Wolt prices include Wolt's markup; kept to compare with Coop Haapsalu shelf prices by EAN.
    out = []
    for store, slug in WOLT_VENUES.items():
        root = json.loads(fetch(WOLT_API + slug + "/assortment?language=et"))
        cat = None
        stack = list(root.get("categories", []))
        while stack:
            c = stack.pop()
            if c.get("name", "").strip().lower() == P["wolt_category"]:
                cat = c["slug"]
                break
            stack += c.get("subcategories", [])
        if not cat:
            raise RuntimeError(P["wolt_category"] + " category not found on Wolt")
        time.sleep(2)
        items, token = [], None
        for _ in range(10):  # categories are paged, 50 items per page
            data = json.loads(fetch(WOLT_API + slug + "/assortment/categories/slug/" + cat + "?language=et"
                                    + ("&page_token=" + token if token else "")))
            items += data.get("items", [])
            token = (data.get("metadata") or {}).get("next_page_token")
            if not token:
                break
            time.sleep(2)
        for i in items:
            if i.get("disabled_info") or not is_match(i["name"]):
                continue
            price, orig = i["price"] / 100, (i.get("original_price") or 0) / 100
            o = offer(store, i["id"], i["name"], f"https://wolt.com/et/est/tallinn/venue/{slug}",
                      orig or price, price if orig else None)
            o["ean"] = i.get("barcode_gtin")
            o["wolt"] = True
            out.append(o)
    return out


def coop_leaflet():
    # Coop kliendileht (iPaper flipbook): each page's product hotspots carry name + price, no OCR needed.
    # Leaflet prices are treated as Säästukaart (customer card) prices.
    index = fetch("https://www.coop.ee/kliendileht")
    links = set(re.findall(r'href="(https://kliendileht\.coop\.ee/[^"]+/)"', index))
    links.add("https://kliendileht.coop.ee/hoiame-soodsana/hoiame-soodsana/")  # always check the everyday-price list
    links = sorted(links)[:6]
    today = dt.date.today()
    best, seen = {}, 0
    for link in links:
        time.sleep(2)
        page = fetch(link)
        dates = re.search(r"(\d{1,2})\.(\d{1,2})\.?\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", page)
        until = None
        if dates:
            until = dt.date(int(dates.group(5)), int(dates.group(4)), int(dates.group(3)))
            if until < today:
                continue
        for jurl in sorted(set(re.findall(r'https://cdn\.ipaper\.io/iPaper/Papers/[^"\s]+?/Page\d+-\d+\.json[^"\s]*', page))):
            time.sleep(2)
            data = json.loads(fetch(jurl.replace("\\u0026", "&").replace("\\/", "/")))
            for e in data.get("enrichments", []):
                seen += 1
                name = e.get("name") or e.get("alttext") or ""
                if not e.get("price") or not is_match(name):
                    continue
                key = e.get("productId") or name
                if until:  # weekly leaflet: card price until the end date
                    o = offer("Coop kliendileht", key, name, link, None, None, e["price"], "Säästukaart",
                              until.isoformat())
                else:  # undated lists (e.g. "Hoiame soodsana") are standing everyday prices
                    o = offer("Coop kliendileht", key, name, link, e["price"])
                price = o["loyalty"] or o["regular"]
                if key not in best or price < (best[key]["loyalty"] or best[key]["regular"]):
                    best[key] = o
    if not links or not seen:
        raise RuntimeError("no leaflet product data found (page layout changed?)")
    return list(best.values())


def depo():
    # DEPO DIY online (Tallinn, Veskiposti 1): public GraphQL API used by online.depo.ee
    q = ('query($s: String) { products(searchString: $s, rows: 100, start: 0) { edges { node { id name '
         'prices { yellow { priceWithVat } } stockItems { quantity } } } } }')
    body = json.dumps({"query": q, "variables": {"s": P["term"]}}).encode()
    req = urllib.request.Request("https://online.depo.ee/graphql", data=body, method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read().decode("utf-8"))
    check_cutoff(len(data["data"]["products"]["edges"]), 100)
    out = []
    for e in data["data"]["products"]["edges"]:
        n = e["node"]
        if not is_match(n["name"]) or not any((s.get("quantity") or 0) > 0 for s in n.get("stockItems") or []):
            continue
        price = (n.get("prices") or {}).get("yellow", {}).get("priceWithVat")
        out.append(offer("DEPO", n["id"], n["name"], f"https://online.depo.ee/product/{n['id']}", price))
    return out


def juku():
    # Jukukeskus.ee: search is rendered in the browser, so we read fixed product pages.
    # Each page has hidden Nosto tags with name, price, list_price and availability.
    out = []
    urls = list(P.get("juku_urls", []))
    if P.get("juku_slug"):  # find new packs: all product links from Juku's sitemap, filtered by URL words
        sitemap = fetch("https://www.jukukeskus.ee/sitemap/products_1.xml")
        found = re.findall(r"<loc>https?://www\.jukukeskus\.ee(/et/[^<]+)</loc>", sitemap)
        if not found:
            raise RuntimeError("Juku sitemap had no product links")
        for path in found:
            if re.search(P["juku_slug"], path) and not re.search(P.get("juku_skip", "$^"), path):
                u = "https://www.jukukeskus.ee" + path
                if u not in urls:
                    urls.append(u)
        time.sleep(2)
    for url in urls:
        page = fetch(url)
        tag = lambda k: (re.search(r'<span class="' + k + r'">([^<]*)</span>', page) or [None, None])[1]
        name, price, listp, avail, pid = tag("name"), tag("price"), tag("list_price"), tag("availability"), tag("product_id")
        if not name or not price:
            raise RuntimeError("product data not found on " + url)
        if avail == "InStock" and is_match(html.unescape(name)):
            regular = listp or price
            out.append(offer("Juku", pid, html.unescape(name), url, regular, price if num(price) < num(regular) else None))
        time.sleep(2)
    return out


ALL_STORES = {"Selver": selver, "Bauhof": bauhof, "Rimi": rimi, "Barbora": barbora, "Coop": coop,
              "Coop kliendileht": coop_leaflet, "Coop Lasnamäe (Wolt)": wolt_coop, "Lapseriided.com": lapseriided, "DEPO": depo, "Juku": juku}

PRODUCTS = {
    "zewa": dict(
        data_dir="docs/data", good_price=0.35, term="zewa", match=is_deluxe_tp, near=near_zewa, count=rolls_of,
        bauhof_url="https://www.bauhof.ee/et/c/kodu-ja-sisustus/kodupaber/tualettpaberid", wolt_category="kodupaber",
        stores=["Selver", "Bauhof", "Rimi", "Barbora", "Coop", "Coop kliendileht", "Coop Lasnamäe (Wolt)"],
        may_be_empty={"Coop kliendileht"},  # Zewa is only in the leaflet some weeks
        info={"title": "Zewa Deluxe Price Watch", "what": "Zewa Deluxe toilet paper", "unit": "roll", "units": "rolls",
              "about": "Only Zewa Deluxe toilet paper is tracked (all variants, any pack size). Zewa Everyday and other lines are left out."}),
    "huggies": dict(
        data_dir="docs/huggies/data", good_price=0.30, term="huggies", match=is_huggies_pants5_boy, near=near_huggies, count=diapers_of,
        wolt_category="mähkmed",
        stores=["Selver", "Rimi", "Barbora", "Coop", "Coop kliendileht", "Coop Lasnamäe (Wolt)", "Lapseriided.com", "DEPO", "Juku"],
        juku_slug=r"huggies.*(s5-|5-suurus|5\.-suurus).*boy|huggies.*boy.*(s5-|5-suurus)",
        juku_skip=r"girl|elite|overnight|extra-care|swim|dry",
        may_be_empty={"Coop kliendileht", "Coop Lasnamäe (Wolt)", "Coop"},
        info={"title": "Huggies Pants 5 Boy Price Watch", "what": "Huggies Pants size 5 (12-17 kg) Boy diapers", "unit": "diaper", "units": "diapers",
              "about": "Only Huggies Pants size 5 (12-17 kg) Boy diapers are tracked, including Little Movers, any pack size. Packs that don't say Boy or Girl are included; Girl, Extra Care, Overnights and other lines are left out."}),
}

# ---------------------------------------------------------------- main


def finish(o):
    choices = [(o["loyalty"], "loyalty"), (o["campaign"], "campaign"), (o["regular"], "regular")]
    best, kind = min(((p, k) for p, k in choices if p), default=(None, None))
    o["best"], o["best_type"] = best, kind
    o["per_roll"] = round(best / o["rolls"], 3) if best and o["rolls"] else None
    return o


def main():
    failed = []
    for key, cfg in PRODUCTS.items():
        P.clear()
        P.update(cfg)
        print("==", key, flush=True)
        failed += [key + ": " + s for s in run_product()]
    if failed:
        print("FAILED STORES:", ", ".join(failed), file=sys.stderr)
        sys.exit(1)


def run_product():
    DATA = os.path.join(ROOT, P["data_dir"])
    os.makedirs(DATA, exist_ok=True)
    latest_path, hist_path = os.path.join(DATA, "latest.json"), os.path.join(DATA, "history.csv")
    prev = json.load(open(latest_path)) if os.path.exists(latest_path) else {"offers": [], "status": {}}
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone(dt.timedelta(hours=2))).date().isoformat()
    offers, status, failed = [], {}, []
    RUN["review"], RUN["warn"] = [], {}
    for store in P["stores"]:
        fn = ALL_STORES[store]
        RUN["store"] = store
        try:
            got = [finish(o) for o in fn()]
            got = [o for o in got if o["per_roll"]]
            if not got and store not in P["may_be_empty"]:
                raise RuntimeError("no matching products parsed (page layout changed or out of stock)")
            offers += got
            status[store] = {"ok": True, "count": len(got), "last_ok": today, "error": None,
                             "warning": RUN["warn"].get(store)}
            if RUN["warn"].get(store):
                failed.append(store + " (warning)")
        except Exception as e:  # keep yesterday's data for this store, mark it stale
            failed.append(store)
            old = prev.get("status", {}).get(store, {})
            status[store] = {"ok": False, "count": 0, "last_ok": old.get("last_ok"), "error": f"{type(e).__name__}: {e}"[:300]}
            recent = old.get("last_ok") and (dt.date.fromisoformat(today) - dt.date.fromisoformat(old["last_ok"])).days <= 60
            if recent:  # keep the last good prices for up to 60 days, then drop them
                offers += [dict(o, stale=True) for o in prev.get("offers", []) if o["store"] == store]
        print(store, status[store], flush=True)
        time.sleep(2)

    offers.sort(key=lambda o: o["per_roll"])
    review = [dict(t) for t in {tuple(r.items()) for r in RUN["review"]}]
    json.dump({"updated": now.isoformat(timespec="minutes"), "good_price": P["good_price"], "product": P["info"],
               "review": sorted(review, key=lambda r: (r["store"], r["name"])),
               "offers": offers, "status": status},
              open(latest_path, "w"), ensure_ascii=False, indent=1)

    rows = []
    if os.path.exists(hist_path):
        rows = [r for r in csv.DictReader(open(hist_path, encoding="utf-8")) if r["date"] != today]
    rows += [dict({k: o.get(k) for k in FIELDS}, date=today) for o in offers if not o.get("stale")]
    with open(hist_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return failed


if __name__ == "__main__":
    main()
