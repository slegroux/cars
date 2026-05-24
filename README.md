# carfinder

Local-first CLI that aggregates used-car listings from Craigslist and CarMax in the West LA area, scores each against a personal-profile rubric (new driver, weekend windsurf trips, dedicated street parking), and exports a ranked Markdown shortlist to an Obsidian vault.

Single-user, no server, no accounts, no ongoing cost. Pure-function scorer with median-of-cohort price comparison and a confidence indicator (`~` partial, `~*` low) so the output is honest when lookup data is missing.

## Quick start

```bash
cd /Users/sylvain/Projects/Cars
uv sync
uv run carfinder --help
uv run carfinder search                    # fetch + store
uv run carfinder rank --top 10             # ranked terminal table
uv run carfinder export --top 15           # write shortlist-YYYY-MM-DD.md to vault
```

## Commands

| Command | Purpose |
|---|---|
| `carfinder search [--sources X[,Y]] [--zip Z] [--radius N] [--verbose]` | Fetch listings from enabled sources, dedupe, upsert into SQLite |
| `carfinder rank [--top N] [--min-score F] [--format table\|markdown\|json]` | Score cached listings and display ranked output |
| `carfinder export [--top N] [--path P]` | Export Markdown shortlist with photo embeds to vault |
| `carfinder show <listing-id>` | Full detail for one listing with score breakdown |
| `carfinder stats` | Database summary: counts, price range, score histogram |
| `carfinder prune [--days N]` | Remove listings whose `last_seen` is older than N days |
| `carfinder watch [--min-score F]` | Run search, diff against last run, show only new or score-changed listings |
| `carfinder dev refresh-fixtures` | Save dated live HTML/JSON samples into `tests/fixtures/` |

## Config

`config.yaml` at the repo root. Key knobs:

- `zip` / `radius_miles` — geo filter (default `90405` / `25`)
- `budget.min` / `budget.max` — price filter (default `5000` / `12000`)
- `transmission.exclude_manual` — drops manuals server-side and in the scorer
- `sources.{craigslist,carmax,facebook}` — per-source enable flags (`facebook` is permanently stubbed)
- `weights` — 10 scoring factors; must sum to 1.0 (validated at load)
- `export.vault_path` — default `~/Obsidian/PersonalVault/wiki/cars`
- `export.photo_thumbnails` — first N photos embedded per listing in Markdown export
- `rate_limit` / `retry` — request pacing and resilience

## Environment variables

- `CARFINDER_VAULT_PATH` — overrides `export.vault_path`. Useful for testing or sharing the tool across machines.

## Data files (`data/`)

| File | Purpose |
|---|---|
| `mpg_lookup.csv` | EPA fueleconomy.gov dataset, filtered to model years 2009-2022 (~11k rows). Used when a listing doesn't expose MPG directly. |
| `reliability_tiers.yaml` | Make → score (0-10). Toyota/Honda/Mazda top, German marques penalized. |
| `vehicle_dimensions.yaml` | `(make, model, year_range)` → length in inches. Drives parking footprint score. |
| `insurance_risk.yaml` | `(make, model, year_range)` → low/medium/high. Encodes LA-specific theft trends (pre-2022 Kia/Hyundai, Prius cat theft). |
| `roof_rack.yaml` | `(make, model)` → `oem_rails`/`aftermarket`/`none`. |
| `msrp_by_make_model.yaml` | Used by the price scorer's depreciation fallback when there are fewer than 3 same-model listings in the cohort. |

Unknown vehicles get partial/low confidence scores (`~` or `~*` prefix), never crashes.

## Architecture

```
src/carfinder/
├── cli.py            # click entrypoint, command wiring, _load_scored_listings helper
├── config.py         # Pydantic v2 Config with vault_path env override + weight-sum validation
├── models.py         # Pydantic v2 Listing (single source of truth — SQL DDL derived from it)
├── db.py             # SQLite schema, upsert, VIN-first dedup + fuzzy fallback, last_run table
├── fetchers/
│   ├── base.py       # BaseFetcher ABC with rate-limit + retry helpers
│   ├── craigslist.py # async httpx + selectolax, paginated, robust detail-page parsing
│   └── carmax.py     # SSR HTML parse of `const cars = [...]`, HTTP/2 + Sec-Fetch headers
├── scorer.py         # pure score_listing(listing, cohort, config, lookups) -> ScoredListing
├── lookups.py        # loads + expands all data/*.yaml into O(1) lookup maps
└── render.py         # rich terminal table, Markdown export with frontmatter + photo embeds
```

## Known limitations

- **CarMax inventory in $5-12k is sparse.** Live smoke returned **0** local listings at this budget; the 24 stored CarMax listings come from the wider transfer query (radius=200mi, $14k-$56k). CarMax is effectively a "what if budget flexes up" source at the user's current target.
- **CarMax body_type strings are not normalized.** CarMax returns `"4D Hatchback"`, `"4D Sedan"`, `"4D Crew Cab"` etc. The scorer expects `"SUV"`/`"Sedan"`/`"Wagon"`. Until a body_type normalizer ships, CarMax listings get the size_class default of 5/10 (estimated). Easy follow-up.
- **Rank doesn't filter by budget.** `rank`/`export` score everything in the DB regardless of `budget.max`. Out-of-budget CarMax transfer listings appear at the top because they have richer data than CL listings. A `--in-budget` flag on rank (or a budget filter in `_load_scored_listings`) would fix this in ~5 lines.
- **Craigslist 60s per-fetcher timeout.** A full crawl can return ~140 cards but only ~16 are processed before the timeout — fine for a per-weekend personal tool; bump `_run_search`'s `wait_for` if needed.
- **Facebook Marketplace is not included.** ToS violation, anti-bot fragility, and cookie maintenance burden ruled it out. See `.omc/plans/car-finder-mvp.md` ADR.
- **Lookup tables cover ~30 target vehicles.** Unknown vehicles get `~` partial confidence; the breakdown shows exactly which factors were estimated.
- **MPG CSV uses suffixed model names** (e.g., `"RAV4 2WD"` vs plain `"RAV4"`). Documented in `.omc/handoffs/m3b-mpg-gaps.md`. Scorer falls back to estimated 5/10 for unmatched models.
- **Score post-upsert not wired.** Scores are computed at rank/export time, not stored on the listing. DB rows have `score=NULL`; the `rank` command computes scores in memory.

## Project status

- Plan: `.omc/plans/car-finder-mvp.md` (ralplan consensus, iter-2 APPROVE)
- Spike: `.omc/plans/spike-results.md` (CarMax feasibility, GO)
- Milestones: M0, M0.5, M1, M2, M3a, M3b, M4, M4.5, M4.6 — all complete
- Tests: **111 passing**
- Code: ~2.7k LOC src, ~2.3k LOC tests
- Handoffs: `.omc/handoffs/m{0,1,2,3a,3b,4}-complete.md`

## License

Personal project, no license. Don't redistribute.
