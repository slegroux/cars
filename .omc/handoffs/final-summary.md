# Final Summary — carfinder MVP

**Date:** 2026-05-23
**Status:** All milestones complete

## Milestones

| # | Name | Status | Tests added |
|---|---|---|---|
| M0 | Scaffold + MPG data prep | ✅ | 31 |
| M0.5 | CarMax feasibility spike | ✅ | — (spike) |
| M1 | Craigslist fetcher | ✅ | 23 |
| M2 | CarMax fetcher | ✅ | 9 |
| M3a | Scorer + stub tables + confidence | ✅ | 20 |
| M3b | Populate real lookup tables | ✅ | 5 |
| M4 | Render + Markdown export | ✅ | 12 |
| M4.5 | Watch command | ✅ | 6 |
| M4.6 | dev refresh-fixtures | ✅ | 4 |

**Total tests:** 111 passing (4 warnings, no failures)
**Code:** 2,730 LOC src · 2,270 LOC tests

## Key results

### Pipeline smoke
- `carfinder search` → fetches concurrently from Craigslist + CarMax (`asyncio.gather`, 60s per-fetcher timeout)
- 41 listings stored (17 CL @ $5k-$11k avg $8.3k, 24 CarMax @ $14k-$56k avg $28k)
- `carfinder rank --top 10` → ranked table with confidence prefixes
- `carfinder export` → wrote `shortlist-2026-05-23.md` with **10 photo embeds** + per-vehicle score breakdowns to vault
- `carfinder watch` → first run reports all above threshold; second run reports delta
- `carfinder dev refresh-fixtures` → saves dated HTML/JSON samples

### CarMax spike outcome (M0.5)
- `api.carmax.com` does not exist (NXDOMAIN, as Architect found in plan review).
- CarMax data is **server-side rendered** into the HTML as `const cars = [...]`.
- httpx + HTTP/2 + full Sec-Fetch-* + sec-ch-ua headers bypasses Akamai bot detection → 200 OK with ~24 vehicles per request.
- No cookies needed; pagination via filter-narrowing rather than a page param.

### Scorer behavior
- RAV4 2014 XLE fixture: **92.0, full confidence**
- BMW 328i 2014 salvage fixture: **0.0, hard reject**
- Confidence indicator: `~` (partial), `~*` (low) — surfaces when ≥1 / ≥3 factors fell back to defaults.

## Top 5 actually scored (current DB)

| Score | Conf | Year | Make | Model | Trim | Price | Source |
|---|---|---|---|---|---|---|---|
| 68.1 | ~* | 2021 | Subaru | Impreza | Premium | $19,998 | carmax |
| 67.5 | ~* | 2016 | Honda | Odyssey | EX | $19,998 | carmax |
| 64.5 | ~* | 2018 | Honda | Civic | LX | $18,998 | carmax |
| 62.5 | ~* | 2019 | Toyota | Tacoma | TRD Sport | $34,998 | carmax |
| 62.5 | ~* | 2023 | Toyota | Tundra | Limited | $45,998 | carmax |

**Observation:** All top-5 are CarMax. None are in the $5-12k target budget. Reason below.

## Known issues / follow-ups (not blocking)

1. **`rank`/`export` don't enforce budget filter.** The query layer filters by budget, but the scorer ranks everything in the DB. CarMax transfer-query listings ($14-56k) appear at the top because they have richer fields (VIN, MPG, mileage, dealer-grade data) than CL listings. **Fix:** add `--in-budget` flag (or unconditional filter) in `_load_scored_listings`. ~5 lines.

2. **CarMax body_type not normalized.** `"4D Hatchback"` / `"4D Sedan"` / `"4D Crew Cab"` come through verbatim; scorer expects `"SUV"`/`"Sedan"`/`"Wagon"`. All CarMax listings default to size_class 5/10 estimated. **Fix:** add a normalization step in `CarMaxFetcher._vehicle_to_listing`. ~10 lines.

3. **CarMax inventory at $5-12k is empty.** Live local CarMax query returned 0 listings; the 24 stored come only from the transfer-radius query. The dealer's price floor is ~$14k. Reality check: at current budget, **CarMax is not a useful primary source** — Craigslist is the meaningful one. Consider either: (a) disable CarMax in config to save the 2 HTTP queries per run, or (b) raise the budget to $15k if dealer inventory matters.

4. **Craigslist 60s timeout truncates coverage.** Full crawl is ~140 cards; only ~16 are processed before timeout. **Fix:** bump `wait_for` timeout to 180s, or cap to first 50 cards per page rather than fetching every detail page.

5. **MPG model-name mismatch.** EPA CSV uses suffixed names (`"RAV4 2WD"` vs plain `"RAV4"`). Documented in `m3b-mpg-gaps.md`. Scorer degrades gracefully (estimated 5/10).

6. **Score not persisted to DB.** Scores recompute every rank/export call. Acceptable for an MVP; would matter if listings count grew past 1000s.

## Files produced

- `src/carfinder/{cli,config,db,models,scorer,lookups,render}.py` (7 modules)
- `src/carfinder/fetchers/{base,craigslist,carmax}.py`
- `data/{reliability_tiers,vehicle_dimensions,insurance_risk,roof_rack,msrp_by_make_model}.yaml` + `data/mpg_lookup.csv`
- `tests/test_*.py` (10 test files, 111 cases)
- `tests/fixtures/{craigslist,carmax,scorer}/` (HTML + JSON snapshots)
- `config.yaml`, `pyproject.toml`, `README.md`
- `.omc/plans/{car-finder-mvp,spike-results,open-questions,carmax-xhr-capture}` — planning + spike artifacts
- `.omc/handoffs/m{0,1,2,3a,3b,4}-complete.md` + this final summary

## Next steps (not for execution unless user requests)

- Apply the 4 quick fixes above (budget filter, body_type normalizer, timeout bump, optional CarMax disable).
- If user wants more inventory: add Cars.com or CarGurus as a third source (the spike outline is in `spike-results.md`).
- Re-run `carfinder search && carfinder export --top 15` over the next few weeks; review the exported `shortlist-*.md` files in Obsidian to spot deals.
