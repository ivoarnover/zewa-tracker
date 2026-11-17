# Estonian store price trackers

Daily price trackers for a few products in Estonian shops, run for free on GitHub Actions and published on GitHub Pages.

| Page | Tracks | Compared by | Good price |
|---|---|---|---|
| https://ivoarnover.github.io/zewa-tracker/ | Zewa Deluxe toilet paper (all variants, any pack; not Everyday) | € per roll | under 0.35 € |
| https://ivoarnover.github.io/zewa-tracker/huggies/ | Huggies Pants size 5 (12-17 kg) Boy, incl. Little Movers; packs without gender included | € per diaper | under 0.30 € |
| https://ivoarnover.github.io/zewa-tracker/pohjala/ | every Põhjala beer, incl. alcohol-free | € per litre (and per can) | none; labels "lowest in 30/90 days" |

## How it works
- `.github/workflows/daily.yml` runs every day at 03:17 UTC (05:17 Tallinn winter time): `scraper/scrape.py` (Zewa, Huggies)
  and `scraper/beers.py` (Põhjala), then commits `docs/**/data/latest.json` and `history.csv`. Manual run: Actions tab,
  "daily-prices", Run workflow.
- Python stdlib only, a few requests per store, 2 s apart; 429/5xx answers are retried after 30 s (max 3 tries).
- Every run searches each store again, so new pack sizes and new beers appear by themselves.
- The price used is the lowest of regular, campaign and loyalty price; loyalty prices are labelled.
- Wolt rows are delivery prices with Wolt's markup: shown grey, never counted as best. EANs are saved so Wolt vs Coop
  Haapsalu prices can later be compared to estimate Wolt's markup.
- Products, search terms, matching rules, stores and good-price lines: `PRODUCTS` in `scraper/scrape.py`.
  Beer stores and name matching (`beer_key`, `ALIASES`, `NOISE`, `NOT_BEER`): `scraper/beers.py`.

## Safeguards
- Store fails: its last prices stay, marked "(old)", for at most 60 days; the run goes red and GitHub emails the owner.
- Cut-off: if a store returns a full results page (or Selver's total is larger than the page), the page shows a warning and the run fails.
- Unparsed price (Bauhof): if a product card shows more prices than the parser understood, the page shows a warning and the run fails, so a layout change can't silently drop a price.
- "Check these": products that look relevant but weren't understood (no pack size; beer names not linked to a known beer).
- "No longer found": items seen in the last 60 days but not today; after 60 days they are dropped from the pages
  (history stays in the CSV files).
- Viinarannasta (Imunify360 bot protection on its host) sometimes shows GitHub's servers a "One moment, please..." page.
  The script sends one honest request (own User-Agent with repo link), waits 20 minutes and tries once more if challenged,
  and never runs or answers the challenge. On a blocked day the last prices stay and the run does not fail.

## Stores and how they are read
| Store | Used for | Source | Loyalty / notes |
|---|---|---|---|
| Selver | all | catalog JSON API `.../vue_storefront_catalog_et/product/_search?q=` | Partnerkaart = `product_group_price` or customer group 1; EAN `product_main_ean` |
| Rimi | all | search page HTML, `data-gtm-eec-product` JSON | campaign vs "Tavahind"; no EAN |
| Barbora | all | `barbora.ee/api/eshop/v1/search?query=` | AITÄH: `promotion.loyaltyCardRequired`, `oldPrice`; no EAN |
| Bauhof | Zewa | toilet paper category page HTML (in-stock items only) | "Meistriklubi hind" club price, shown without logging in (`club-information`, since Nov 2026; older `tier-price` still read) |
| Coop (Haapsalu e-shop) | all | WooCommerce Store API `coophaapsalu.ee/wp-json/wc/store/v1/products?search=` | own shelf prices; SKU = EAN; names use "tk" for rolls |
| Coop kliendileht | Zewa, Huggies | coop.ee/kliendileht links (+ Hoiame soodsana); iPaper page JSON "enrichments" have name + price | weekly leaflet = Säästukaart until end date; undated lists = regular |
| Coop Lasnamäe (Wolt) | all | Wolt consumer assortment API, category paged (50 per page) | delivery price; `barcode_gtin` |
| Lapseriided.com | Huggies | WooCommerce Store API | sale price |
| DEPO | Huggies | `online.depo.ee/graphql` `products(searchString)` | Tallinn Veskiposti stock; 2+ pack price not used |
| Juku | Huggies | product sitemap `jukukeskus.ee/sitemap/products_1.xml` filtered by `juku_slug`/`juku_skip`, then hidden Nosto tags on product pages | campaign vs `list_price` |
| Põhjala e-shop | beers | WooCommerce Store API `shop.pohjalabeer.com`, `category=olu` | 24-can cases; no can size in names (taken from other stores) |
| Kaupmees | beers | `kaupmees.ee/et/alkohol-ja-tubakas/olled?brand=PÕHJALA` cards | prices shown without VAT ("+KM"): 24% added; "Soodushind -X%" |
| Viinarannasta | beers | `viinarannasta.ee/shop?search=põhjala` cards | see Safeguards |

Checked and not used: K-Rauta, 1a.ee, Hansapost, Kaup24 (block GitHub's servers); Apotheka, Benu (products loaded in the
browser); Lidl (no grocery data, only leaflets with own brands); Bolt Coop Tartu (browser only); Liviko, Charlot (no
usable Põhjala listing); Taig (removed on request); odavkorv.ee and pood.bebo.ee (aggregators of stores already read).
Viinarannasta has no public product feed; a request for an allowlist or feed was drafted.

## Adding a product or store
- Same kind of product (one item, many pack sizes): add an entry to `PRODUCTS` (search term, `match`, `near`, `count`,
  stores, `good_price`, `info`), copy `docs/index.html` to `docs/<name>/index.html`, add it to the "Trackers" nav on all pages.
- New store: write an adapter returning `offer(...)` records, add it to `ALL_STORES` (or `STORES` in `beers.py`),
  add a cut-off check, test a few requests from a home computer first, then from a GitHub run.
- Keep request counts low (one search per store per day) and respect bot protection; never work around it.
