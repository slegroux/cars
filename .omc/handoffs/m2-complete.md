# M2 Complete — CarMax Fetcher

## Files Added
- `src/carfinder/fetchers/carmax.py` — CarMaxFetcher, BROWSER_HEADERS, HTML parser, vehicle→Listing mapper
- `tests/test_carmax_parser.py` — 9 tests (all pass)
- `tests/fixtures/carmax/search_2026-05-23.html` — live fixture (24 vehicles, 1.2MB)

## Files Modified
- `src/carfinder/cli.py` — added CarMaxFetcher to registry
- `config.yaml` — flipped `sources.carmax: true`
- `pyproject.toml` — added `httpx[http2]` (h2 extra)

## Test Count
9 tests, 9 passed. Full suite: 83 passed, 0 failed.

## Live Smoke Result
- 2 queries fired (local distance=25, transfer distance=200)
- 24 unique listings stored (transfer query returned same 24 as local set at this price band)
- Count: 24 | Avg price: $28,123 | Range: $13,998–$55,998

## Deviations
- `totalCount` regex (`"totalCount":\d+`) used instead of text-pattern parsing — more reliable given CarMax JSON-embeds this in SSR HTML.
- Transfer query dedup worked correctly (seen_stock set prevented double-counting).
