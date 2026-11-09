"""One-off probe: fetch test URLs once from a GitHub runner and save raw responses."""
import os, time, urllib.request, urllib.error

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
URLS = {
    "bauhof_p2": "https://www.bauhof.ee/et/c/kodu-ja-sisustus/kodupaber/tualettpaberid?page=2",
    "bauhof_limit": "https://www.bauhof.ee/et/c/kodu-ja-sisustus/kodupaber/tualettpaberid?limit=128",
    "bauhof_search": "https://www.bauhof.ee/et/search?q=zewa",
    "bauhof_otsing": "https://www.bauhof.ee/et/otsing?q=zewa",
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
