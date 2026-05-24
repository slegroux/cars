# M1 Complete — Craigslist Fetcher

## Files Added
- `src/carfinder/fetchers/craigslist.py` — CraigslistFetcher with async pagination, dual-layout HTML parser (current div.title + old span.result-price), detail page parser (odometer/VIN/transmission/photos), title regex, retry/rate-limiting
- `tests/test_craigslist_parser.py` — 23 tests
- `tests/fixtures/craigslist/search_page_1.html` — 7-card current-layout fixture
- `tests/fixtures/craigslist/search_page_2.html` — 2-card old-layout fixture
- `tests/fixtures/craigslist/detail_rav4_2014.html` — full detail (odometer, VIN, photos)
- `tests/fixtures/craigslist/detail_civic_2012.html` — detail with odometer, no VIN
- `tests/fixtures/craigslist/detail_escape_no_odometer.html` — detail missing odometer field

## Files Modified
- `src/carfinder/cli.py` — wired `search` command with FETCHER_REGISTRY, asyncio.gather + 60s timeout, manual exclusion, dedup, counters

## Test Count
- `pytest tests/test_craigslist_parser.py`: 23/23 passed
- `pytest -q` (full suite): 74/74 passed

## Live Smoke Result
`carfinder --verbose search --sources craigslist` fetched 16 listings (60s timeout hit — 139 cards × 2-5s rate limit exceeds timeout by design). `sqlite3 data/listings.db "SELECT COUNT(*) FROM listings WHERE source='craigslist';"` → 16.

## Deviations
- CL live HTML uses `div.title`/`div.price`/`div.location` (not `data-pid` or `a.titlestring`). Parser updated to handle all three layouts defensively.
- 60s timeout is intentional per plan; full crawl requires raising timeout or reducing rate limit.
