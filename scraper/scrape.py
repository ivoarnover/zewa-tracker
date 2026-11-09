"""Daily Zewa Deluxe toilet paper price scraper.

One request per store, Python stdlib only. Writes:
  docs/data/latest.json   current offers + per-store status
  docs/data/history.csv   one row per product per day
Exits 1 if any store failed (after writing data), so GitHub emails the repo owner.
"""
import csv, datetime as dt, html, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
GOOD_PRICE = 0.35  # EUR per roll
FIELDS = ["date", "store", "id", "name", "rolls", "regular", "campaign", "loyalty",
          "best", "best_type", "per_roll", "url"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "et-EE,et;q=0.9"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def is_deluxe_tp(name):
    n = name.lower()
    # Deluxe only: "Deluxe Delicate Care" is a different, cheaper line and is excluded
    return ("delux" in n and "delicate" not in n
            and re.search(r"tualettpaber|wc[ -]?paber", n) is not None)


def rolls_of(name):
    found = re.findall(r"(\d+)[\s-]*(?:rulli|rull|rul|rl)", name.lower())
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
    return dict(store=store, id=str(pid), name=clean(name), url=url, rolls=rolls_of(name),
                regular=regular, campaign=campaign, loyalty=loyalty,
                loyalty_label=loyalty_label, valid_until=valid_until)


# ---------------------------------------------------------------- stores

def selver():
    url = ("https://www.selver.ee/api/catalog/vue_storefront_catalog_et/product/_search"
           "?q=zewa&size=100")
    out = []
    for h in json.loads(fetch(url))["hits"]["hits"]:
        s = h["_source"]
        if s.get("status") != 1 or not is_deluxe_tp(s.get("name", "")):
            continue
        groups = {p.get("customer_group_id"): p for p in s.get("prices") or []}
        g0 = groups.get(0, {})
        regular = g0.get("original_price") or s.get("original_price_incl_tax") or s.get("price_incl_tax")
        now = g0.get("final_price") or s.get("final_price_incl_tax")
        # Partner card price: product_group_price, else customer group 1 (matches the Partnerkaart badge)
        loyalty = s.get("product_group_price") or groups.get(1, {}).get("final_price")
        out.append(offer("Selver", s.get("sku") or s["id"], s["name"],
                         "https://www.selver.ee/" + s["url_key"], regular, now, loyalty,
                         "Partnerkaart", s.get("special_to_date")))
    return out


def barbora():
    data = json.loads(fetch("https://barbora.ee/api/eshop/v1/search?query=zewa"))
    out = []
    for p in data.get("products", []):
        if p.get("status") != "active" or not is_deluxe_tp(p.get("title", "")):
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
    page = fetch("https://www.rimi.ee/epood/ee/otsing?query=zewa&pageSize=80")
    out = []
    for chunk in page.split('class="product-grid__item"')[1:]:
        m = re.search(r"data-gtm-eec-product='([^']+)'", chunk)
        if not m:
            continue
        j = json.loads(html.unescape(m.group(1)))
        if not is_deluxe_tp(j["name"]) or "Ei ole saadaval" in chunk:
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
    page = fetch("https://www.bauhof.ee/et/c/kodu-ja-sisustus/kodupaber/tualettpaberid")
    out = []
    for card in re.split(r'(?=<a href="/et/p/\d+/)', page)[1:]:
        title = re.search(r'class="product-card-title"[^>]*>([^<]+)<', card)
        if not title or not is_deluxe_tp(title.group(1)):
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
        if not regular and not campaign and not loyalty:
            continue
        out.append(offer("Bauhof", href.group(2), title.group(1), "https://www.bauhof.ee" + href.group(1),
                         regular, campaign, loyalty, label, until))
    return out


TAIG_PRODUCTS = ["https://taig.ee/tualettpaber-zewa-deluxe-8-rulli-pure-white-3-kihil-5-661299"]


def taig():
    out = []
    for url in TAIG_PRODUCTS:
        page = fetch(url)
        name = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
        price = re.search(r'itemprop="price" content="([\d.]+)"', page)
        if name and price:
            out.append(offer("Taig", url.rsplit("-", 1)[-1], clean(name.group(1)), url, price.group(1)))
        time.sleep(2)
    return out


STORES = {"Selver": selver, "Bauhof": bauhof, "Rimi": rimi, "Barbora": barbora, "Taig": taig}

# ---------------------------------------------------------------- main


def finish(o):
    choices = [(o["loyalty"], "loyalty"), (o["campaign"], "campaign"), (o["regular"], "regular")]
    best, kind = min(((p, k) for p, k in choices if p), default=(None, None))
    o["best"], o["best_type"] = best, kind
    o["per_roll"] = round(best / o["rolls"], 3) if best and o["rolls"] else None
    return o


def main():
    os.makedirs(DATA, exist_ok=True)
    latest_path, hist_path = os.path.join(DATA, "latest.json"), os.path.join(DATA, "history.csv")
    prev = json.load(open(latest_path)) if os.path.exists(latest_path) else {"offers": [], "status": {}}
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone(dt.timedelta(hours=2))).date().isoformat()
    offers, status, failed = [], {}, []
    for store, fn in STORES.items():
        try:
            got = [finish(o) for o in fn()]
            got = [o for o in got if o["per_roll"]]
            if not got:
                raise RuntimeError("no Zewa Deluxe products parsed (page layout changed or out of stock)")
            offers += got
            status[store] = {"ok": True, "count": len(got), "last_ok": today, "error": None}
        except Exception as e:  # keep yesterday's data for this store, mark it stale
            failed.append(store)
            old = prev.get("status", {}).get(store, {})
            status[store] = {"ok": False, "count": 0, "last_ok": old.get("last_ok"), "error": f"{type(e).__name__}: {e}"[:300]}
            offers += [dict(o, stale=True) for o in prev.get("offers", []) if o["store"] == store]
        print(store, status[store], flush=True)
        time.sleep(2)

    offers.sort(key=lambda o: o["per_roll"])
    json.dump({"updated": now.isoformat(timespec="minutes"), "good_price": GOOD_PRICE,
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

    if failed:
        print("FAILED STORES:", ", ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
