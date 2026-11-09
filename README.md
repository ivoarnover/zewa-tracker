# Zewa Deluxe price tracker

Finds the cheapest Zewa Deluxe toilet paper per roll in Estonian shops, once a day.
Good price: under 0.35 € per roll.

Page: https://ivoarnover.github.io/zewa-tracker/

## How it works
- `.github/workflows/daily.yml` runs `scraper/scrape.py` every morning on GitHub Actions (free).
- The script makes one request per store, keeps only "Deluxe" toilet paper (not Zewa Everyday), reads the roll count from the name
  and takes the lowest of regular, campaign and loyalty price.
- Results go to `docs/data/latest.json` and `docs/data/history.csv`, which GitHub Pages serves with `docs/index.html`.
- If a store fails, its last good prices stay on the page marked "(old)" and the run goes red, so GitHub emails you.

## Stores and sources
| Store | Source | Loyalty price |
|---|---|---|
| Selver | catalog JSON API, search `zewa` | Partnerkaart (`product_group_price`, customer group 1) |
| Bauhof | toilet paper category page HTML | logged-in customer price (`tier-price`) |
| Rimi | search page HTML (`data-gtm-eec-product`) | campaign vs "Tavahind" |
| Barbora | search JSON API | AITÄH card (`promotion.loyaltyCardRequired`) |

Blocked from GitHub servers (403, bot protection), so not included: K-Rauta, 1a.ee, Hansapost, Kaup24.
Coop Haapsalu timed out.

## Maintenance
- Change the threshold: `GOOD_PRICE` in `scraper/scrape.py`.
- Run now: Actions tab, "daily-prices", Run workflow.
- GitHub pauses scheduled workflows in repos with no activity for 60 days; the daily data commit normally prevents that.
