"""One-off probe: fetch each store once from a GitHub runner and save raw responses."""
import os, time, urllib.request, urllib.error

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
URLS = {
    "selver_api": "https://www.selver.ee/api/catalog/vue_storefront_catalog_et/product/_search?q=zewa&size=50",
    "barbora_api": "https://barbora.ee/api/eshop/v1/search?query=zewa",
    "barbora_html": "https://barbora.ee/otsing?q=zewa",
    "rimi_html": "https://www.rimi.ee/epood/ee/otsing?query=zewa&pageSize=80",
    "bauhof_cat": "https://www.bauhof.ee/et/c/kodu-ja-sisustus/kodupaber/tualettpaberid",
    "bauhof_prod": "https://www.bauhof.ee/et/p/725169",
    "krauta_prod": "https://www.k-rauta.ee/p/tualettpaber-zewa-deluxe-pure-white-3-sl-32-tk/7qr7",
    "1a_prod": "https://www.1a.ee/p/tualettpaber-zewa-deluxe-pure-white-3-sl-32-tk/5e2y",
    "hansapost_prod": "https://hansapost.ee/et/kodukaubad/kodukeemia/wc-paber-ja-majapidamispaber/tualettpaber-zewa-deluxe-pure-white-3-kihti?id=6167",
    "kaup24_brand": "https://kaup24.ee/et/brands/z/zewa",
    "coop_haapsalu": "https://coophaapsalu.ee/?s=zewa+deluxe&post_type=product",
    "taig_prod": "https://taig.ee/tualettpaber-zewa-deluxe-8-rulli-pure-white-3-kihil-5-661299",
}
os.makedirs("out", exist_ok=True)
for name, url in URLS.items():
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "et-EE,et;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body, status, final = r.read(), r.status, r.geturl()
    except urllib.error.HTTPError as e:
        body, status, final = e.read(), e.code, url
    except Exception as e:
        body, status, final = str(e).encode(), "ERR", url
    open(f"out/{name}.txt", "wb").write(body)
    print(f"{name}\t{status}\t{len(body)}\t{final}", flush=True)
    time.sleep(3)
