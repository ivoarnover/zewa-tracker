"""One-off probe: fetch test URLs once from a GitHub runner and save raw responses."""
import os, time, urllib.request, urllib.error

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
URLS = {
    "coop_hpsl_storeapi": "https://coophaapsalu.ee/wp-json/wc/store/v1/products?search=zewa&per_page=50",
    "wolt_venue": "https://restaurant-api.wolt.com/v4/venues/slug/coop_estonia/menu/data",
    "wolt_page": "https://wolt.com/et/est/tallinn/venue/coop_estonia",
    "consumer_assort": "https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug/coop_estonia/assortment",
}
os.makedirs("out", exist_ok=True)
for name, url in URLS.items():
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "et-EE,et;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body, status, final = r.read(), r.status, r.geturl()
    except urllib.error.HTTPError as e:
        body, status, final = e.read(), e.code, url
    except Exception as e:
        body, status, final = str(e).encode(), "ERR", url
    open(f"out/{name}.txt", "wb").write(body)
    print(f"{name}\t{status}\t{len(body)}\t{final}", flush=True)
    time.sleep(3)
