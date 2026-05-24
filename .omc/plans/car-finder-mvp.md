# Car Finder MVP — West LA Used Car Aggregator

**Plan status:** REVISED (iter 2) — addressing Architect+Critic feedback
**Created:** 2026-05-21
**Project dir:** `/Users/sylvain/Projects/Cars/`

---

## Changes from iter 1

1. **Added M0.5 CarMax Feasibility Spike** (BLOCKING before M2) with decision tree: httpx XHR, alternative source pivot, Playwright fallback, or CL-only MVP. Options updated for `api.carmax.com` NXDOMAIN reality. (C1)
2. **Classified Open Questions as BLOCKING vs. CONFIRM-LATER.** Gate before M3. (C2)
3. **Replaced KBB `score_price_value` with median-of-cohort** — no external API. (C3)
4. **Split M3 into M3a (scorer + stub tables + confidence) and M3b (populate real tables).** Lookup data in `data/*.yaml`. MPG prep moved to M0. (M1, M2, M13)
5. **Scoring confidence indicator:** `~` prefix when factors use defaults. (M3)
6. **Cross-source dedup:** VIN-first, fuzzy fallback `(year, make, model, price+-5%, mileage+-2000)`, flagged not silently merged. (M4)
7. **Added M4.5 `carfinder watch`** — diff against last run, print new listings above threshold. (M9)
8. **Pydantic v2 as single schema source** with `to_row()`/`from_row()` for SQLite. (M7)
9. **Fixed acceptance criteria:** mileage scoped to CL pages with odometer; RAV4/BMW use fixture files; e2e = exit 0 + 5+ scored listings in markdown. (M10)
10. **Realistic time:** 10-14h weekend effort, not 6.5h. (N4)

---

## Problem Framing

Sylvain is a new driver in Santa Monica (90405) needing a car for weekend windsurf trips and errands. Currently rents at ~$200-280/weekend — works but adds friction (booking, no roof rack, can't leave gear loaded). Used-car listings are scattered across CL, CarMax, FB Marketplace, and dealers with no unified way to score against his specific needs (new driver, gear hauling, West LA parking, weekend duty cycle). This tool aggregates, normalizes, scores, and ranks listings so the search is data-driven.

## Goals

1. **Aggregate** listings within configurable radius of 90405 into local SQLite.
2. **Normalize** to Pydantic v2 schema with scoring confidence indicators.
3. **Score** against windsurf-new-driver rubric. Surface confidence when lookup data is missing.
4. **Export** shortlist as rich terminal table + Markdown (with photo thumbnails) to Obsidian vault.
5. **Ship MVP in one weekend** — CL + scorer + CLI + export minimum; CarMax if spike passes.

## Non-Goals

Bidding/messaging sellers, image-based damage detection, web UI, Carfax automation, FB Marketplace in MVP, KBB/third-party pricing API.

---

## RALPLAN-DR Summary

### Principles

1. **Local-first, single-user.** CLI + SQLite + YAML config. No server/accounts.
2. **Honest source feasibility.** CarMax feasibility is unproven — requires spike. FB deferred (ToS, fragility).
3. **Scoring tuned to user profile.** Rubric encodes specific constraints. Show confidence honestly when data is missing.
4. **Pluggable async fetchers.** `asyncio.gather` with 60s per-fetcher timeout. Failed sources don't block pipeline.
5. **No scope creep.** `carfinder watch` provides minimal diff detection; user manages cron.

### Decision Drivers

1. **Source obtainability.** CL is proven. CarMax `api.carmax.com` NXDOMAIN, `www.carmax.com` behind Akamai — UNPROVEN.
2. **Scoring fidelity** to windsurf-new-driver use case (the novel value prop).
3. **Ship in one weekend** with at least one guaranteed source.

### Options — Source Strategy (REVISED)

**Option A: CL-only MVP + CarMax via spike (RECOMMENDED)**
Ship with CL guaranteed. M0.5 spike determines CarMax. Pros: ships regardless. Cons: CL-only misses dealer inventory if spike fails.

**Option B: CL + alternative dealer source (Cars.com/CarGurus)**
VIABLE as CarMax fallback — requires sub-spike. Not pre-committed.

**Option C: CL + CarMax via Playwright**
VIABLE but expensive (heavyweight dependency, may still be fingerprinted). Only if user explicitly wants CarMax.

**Options D/E: FB Marketplace / Apify**
INVALIDATED. ToS violation, fragility, cost.

---

## Architecture

### Project Structure

```
Cars/
├── pyproject.toml              # uv, Python 3.12+
├── config.yaml
├── data/
│   ├── reliability_tiers.yaml  # make → score
│   ├── vehicle_dimensions.yaml # (make,model) → length_inches
│   ├── insurance_risk.yaml     # (make,model,year_range) → tier
│   ├── roof_rack.yaml          # (make,model) → status
│   └── mpg_lookup.csv          # fueleconomy.gov 2014-2022
├── src/carfinder/
│   ├── cli.py, config.py, db.py, models.py, scorer.py, render.py
│   └── fetchers/ (base.py, craigslist.py, carmax.py, facebook.py stub)
├── tests/
│   ├── fixtures/{craigslist/, carmax/, scorer/rav4_2014_xle.json, scorer/bmw_328i_2014_salvage.json}
│   └── test_*.py
```

### Data Flow

```
carfinder search → config.yaml → asyncio.gather(fetchers) → db.py upsert+dedup → scorer.py → render.py
                                                              ↑ VIN-first dedup       ↑ loads data/*.yaml
                                                              ↑ fuzzy fallback         ↑ confidence indicator
```

### Dependencies

`click` (CLI), `httpx` (async HTTP), `selectolax` (HTML parsing), `rich` (terminal), `pydantic` v2 (schema), `pyyaml` (config+data), `sqlite3` (stdlib). Dev: `pytest`, `pytest-asyncio`, `pytest-httpx`, `ruff`.

### Config (`config.yaml`)

```yaml
zip: "90405"
radius_miles: 25
budget: {min: 5000, max: 12000}   # OQ #1 resolved: <$12k preferred
mileage: {max: 140000, sweet_spot: [50000, 110000]}
transmission: {exclude_manual: true}  # OQ #3 resolved: exclude manuals
sources: {craigslist: true, carmax: false, facebook: false}
carmax_include_transfer: true
carmax_max_transfer_miles: 200
# Weights rebalanced for: dedicated street parking (OQ #6), AWD low priority (OQ #2)
weights:
  reliability: 0.22, price_value: 0.20, mileage: 0.16, size_class: 0.12,
  insurance_risk: 0.08, mpg: 0.08, parking_footprint: 0.06, drivetrain: 0.02,
  roof_rack: 0.03, title_status: 0.03
export:
  vault_path: "~/Obsidian/PersonalVault/wiki/cars"
  photo_thumbnails: 3
rate_limit: {min_delay_seconds: 2, max_delay_seconds: 5}
retry: {max_retries: 3, backoff_base: 2, retryable_status: [429, 503]}
```

**Vault path:** `os.environ.get("CARFINDER_VAULT_PATH", config.export.vault_path)` + `os.path.expanduser`.

---

## Scoring Rubric

Score 0-100. Each factor 0-10 * weight. `total = sum(factor * weight) * 10`. Weights sum to 1.0.

### Confidence Indicator

- **Full:** all 10 factors had real data. Display: `87.3`
- **Partial:** 1-2 factors defaulted. Display: `~82.1`
- **Low:** 3+ factors defaulted. Display: `~71.4*`

Per-factor breakdown shows which factors were estimated.

### Factors

| Factor | Wt | 10 (best) | 0 (worst) |
|--------|-----|-----------|-----------|
| Reliability | .20 | Toyota/Lexus/Honda/Mazda | BMW/Audi/VW >5y, Land Rover, Chrysler |
| Price value | .18 | At/below cohort median | >20% above median |
| Mileage | .15 | 50k-80k | >140k or <20k |
| Size class | .12 | Compact SUV/wagon | Full-size truck or 2-door coupe |
| Parking | .10 | <180" length | >190" |
| MPG | .08 | >30 combined | <22 combined |
| Drivetrain | .05 | AWD | RWD |
| Insurance | .05 | Low-theft (CX-5, Forester) | High-theft (Kia/Hyundai pre-2022, Prius cat theft) |
| Roof rack | .04 | OEM rails standard | No viable rack option |
| Title | .03 | Clean | Salvage/flood/lemon (hard reject, score 0) |

### Price Value — Median-of-Cohort (replaces KBB)

1. Group listings by `(year, make, model)`. Compute median price.
2. At/below median = 10, within 10% above = 7, within 20% = 4, >20% = 1.
3. Cohort <3 listings: fallback heuristic `expected = msrp_estimate * (1-0.12)^age - mileage*0.04` where `msrp_estimate` comes from a static `data/msrp_by_make_model.yaml` (top 20 vehicles). Mark low-confidence.

---

## Source Details

### Craigslist (M1)

Feasibility HIGH. `losangeles.craigslist.org/search/cta` with params: `min_price`, `max_price`, `auto_transmission=1`, `postal=90405`, `search_distance=25`. Parse with selectolax. Detail pages for mileage/VIN/photos. Pagination at 120. Rate-limit 2-5s. Distance: rely on CL server-side `search_distance`; store `distance_miles=None`.

### CarMax (M2, conditional on M0.5)

Feasibility UNPROVEN. `api.carmax.com` NXDOMAIN; `www.carmax.com` behind Akamai 403. Spike required. If working: out-of-radius listings tagged `transfer_fee="transfer ~$X"` per config. If blocked: sub-spike Cars.com/CarGurus or ship CL-only.

---

## Schema (Pydantic v2 — single source of truth)

`Listing` model with: identity (id, source, source_id, url), vehicle (year, make, model, trim, body_type, drivetrain, transmission, fuel_type, mpg_combined, vin), condition (mileage, title_status, condition), pricing (asking_price, seller_type), location (location, distance_miles, transfer_fee), metadata (photos, description, posted_date, days_listed), internal (first_seen, last_seen, score, score_breakdown, score_confidence), enrichment (length_inches, roof_rack_compatible, insurance_risk_tier).

`to_row()` serializes for SQLite (JSON-encodes list/dict fields). `from_row()` deserializes. SQLite DDL derived from model. Indexes on score DESC, asking_price, source.

### Dedup: VIN-first merge; fuzzy fallback `(year, make, model, price+-5%, mileage+-2000)` flagged as "possible duplicate."

---

## CLI Commands

```bash
carfinder search [--sources X] [--zip X] [--radius X] [--verbose]
carfinder rank [--top 20] [--min-score 60] [--format table|markdown|json]
carfinder export [--top 15] [--path ...]
carfinder show <listing-id>
carfinder stats
carfinder prune [--days 30]
carfinder watch [--min-score 70]         # diff vs. last run
carfinder dev refresh-fixtures           # save dated live fixtures
```

`--verbose` sets logging to INFO (default WARNING). Logging via stdlib `logging`.

---

## Milestones

**Total realistic effort: 10-14 hours** (weekend = 5-7h/day).

### M0: Scaffold + Data Prep (1-1.5h)

**Tasks:** uv init, directory structure, `pyproject.toml`, `config.yaml`, `config.py` (YAML loader + `CARFINDER_VAULT_PATH` env override), `cli.py` (click group, all commands as stubs, `--verbose` flag), `models.py` (Pydantic v2 `Listing`), `db.py` (schema creation, upsert, dedup, prune). Download fueleconomy.gov `vehicles.csv.zip` (`https://www.fueleconomy.gov/feg/epadata/vehicles.csv.zip`), filter 2014-2022, dedup most common trim per year/make/model, output `data/mpg_lookup.csv` (~500 rows, pin download date in header). Create stub `data/*.yaml` (5-10 entries each). Create `tests/fixtures/scorer/rav4_2014_xle.json` and `bmw_328i_2014_salvage.json`.

**Acceptance:**
- `uv run carfinder --help` exits 0 with all subcommands.
- `uv run pytest` passes (config, DB schema, Pydantic validation).
- `data/mpg_lookup.csv` >200 rows. `data/reliability_tiers.yaml` has 5+ makes.

### M0.5: CarMax Feasibility Spike (30-45 min, BLOCKING before M2)

**Decision tree:**
1. Browser inspect carmax.com search near 90405 for XHR endpoints.
2. Replicate with httpx + captured headers. Works? -> PROCEED (document recipe).
3. Fails? -> 15-min sub-spike on Cars.com/CarGurus. Tractable? -> PIVOT M2.
4. All blocked? -> Ship CL-only. Dealer source deferred to Phase 2.

**Acceptance:** `spike-results.md` with endpoints tested, response codes, go/no-go, working snippet if go.

### M1: Craigslist Fetcher (2-3h)

**Tasks:** `CraigslistFetcher(BaseFetcher)` async with httpx. Search URL from config. Parse search HTML + detail pages with selectolax. Regex year/make/model from titles. Pagination at 120. Rate-limit 2-5s. Retry 429/503/timeout: exponential backoff (2s/4s/8s), max 3, then skip with WARNING. Save fixtures. Write `test_craigslist_parser.py`.

**Acceptance:**
- `carfinder search --sources craigslist` stores >5 listings in SQLite.
- Mileage populated for >80% of listings *where CL detail page has odometer field*.
- Rate limiting visible in `--verbose` output.
- `pytest tests/test_craigslist_parser.py` passes against fixtures.

### M2: Dealer Source Fetcher (1-2h, conditional on M0.5)

**Skipped if M0.5 = CL-only.** Implement fetcher per spike findings. CarMax: tag transfer listings per config. Run concurrently with CL via `asyncio.gather` (60s timeout). Save fixture, write parser test.

**Acceptance:**
- `carfinder search` uses enabled sources concurrently.
- Dealer listings have trim/MPG/VIN populated.
- Dedup works: VIN merges, fuzzy flags.

### GATE: Resolve BLOCKING Open Questions

Before M3: confirm budget range (#1), AWD filter-vs-weight (#2), manual exclude-vs-flag (#3), parking situation (#6). If unresolved, proceed with defaults documented in Open Questions file.

### M3a: Scorer — Core + Stub Tables (2-3h)

**Tasks:** `score_listing()` pure function. Per-factor scoring functions. Load `data/*.yaml` + `data/mpg_lookup.csv`. Default 5/10 for unknowns, count defaults for confidence. Median-of-cohort price scoring (fallback heuristic for <3 cohort). Return breakdown dict with `{score, weight, weighted, confidence}` per factor.

**Acceptance:**
- RAV4 2014 XLE fixture (110k mi, $11.5k, clean, AWD, auto) scores >75. BMW 328i 2014 salvage fixture scores <30.
- Manual transmission flagged in breakdown.
- Config weights respected. Confidence indicator correct.
- `pytest tests/test_scorer.py` passes with >15 test cases.

### M3b: Populate Real Lookup Tables (1-2h)

**Tasks:** Fill `data/*.yaml` for top 30 West LA vehicles. `reliability_tiers.yaml` (all major makes, ~30 entries). `vehicle_dimensions.yaml` (top 30 models -> length_inches). `insurance_risk.yaml` (Kia/Hyundai cutoffs, Civic/Accord/Prius cat theft). `roof_rack.yaml` (top 20 models). Verify `mpg_lookup.csv` coverage.

**Acceptance:** Each YAML >20 entries. RAV4 scores with full confidence. Test suite passes.

### M4: Render + Export (1.5-2h)

**Tasks:** `render_table()` with rich (score with confidence prefix). `render_markdown()` with YAML frontmatter, summary table, per-vehicle breakdown, first 2-3 photos as `![](url)`. `export_to_vault()` with env var / config path resolution. Wire `rank`, `export`, `show`, `stats`, `prune` commands.

**Acceptance:**
- `carfinder rank --top 10` prints formatted rich table.
- `carfinder export` creates vault markdown with frontmatter, table, `![](photo_url)` embeds.
- `carfinder prune --days 30` removes old listings, reports count.
- **End-to-end:** `carfinder search && carfinder rank --top 10 && carfinder export` exits 0, markdown has 5+ scored listings.

### M4.5: Watch Command (30 min)

Persist listing IDs + scores to `last_run` table on each search. `carfinder watch --min-score 70`: search, diff, print only new listings above threshold.

**Acceptance:** First run = all new. Second run = only delta. `--min-score` filter works.

### M4.6: Dev Tooling (15 min)

`carfinder dev refresh-fixtures`: fetch one live search + one detail page per source, save with datestamp to `tests/fixtures/`.

---

## Error Handling

- **Retry:** 429/503/timeout -> exponential backoff (2s, 4s, 8s), max 3 retries, then skip with WARNING.
- **Per-fetcher timeout:** 60s via asyncio. Cancelled fetcher doesn't block others.
- **Logging:** stdlib `logging`. Default WARNING, `--verbose` -> INFO.

---

## Open Questions

### BLOCKING — RESOLVED 2026-05-22

| # | Question | Resolution |
|---|----------|------------|
| 1 | Budget? | **$5k-$12k** (target under $12k) |
| 2 | AWD: filter or weight? | **Weight, low priority** (drivetrain weight reduced to 0.02) |
| 3 | Manual: exclude or flag? | **Exclude** (CL `auto_transmission=1`, scorer drops manuals) |
| 6 | Parking? | **Dedicated street spot** (parking_footprint weight reduced to 0.06; insurance_risk raised to 0.08 — street parking still implies theft exposure) |

### CONFIRM-LATER

| # | Question | Default |
|---|----------|---------|
| 4 | Hybrid preference? | No preference |
| 5 | Buy vs. rent TCO module? | Buy assumed, no TCO |
| 7 | Color preference? | Not scored |

---

## ADR: Source Aggregation Strategy

**Decision:** Option A — CL-only MVP + CarMax via M0.5 spike.

**Drivers:** CarMax `api.carmax.com` NXDOMAIN (iter 1 assumption wrong); need one guaranteed source; CL covers primary market (private sellers).

**Alternatives:** B (alternative dealer source) viable as fallback; C (Playwright) viable but expensive; D/E (FB/Apify) invalidated (ToS, cost).

**Why chosen:** Only strategy guaranteeing a shippable MVP regardless of external factors. Spike is time-boxed with clear decision tree.

**Consequences:** MVP may be CL-only (private sellers only). Price-value cohort scoring less meaningful with small dataset. Fetcher abstraction supports future sources.

**Follow-ups:** If spike passes, add dealer fetcher. If all fail, evaluate Playwright for Phase 2. Consider Cars.com RSS as low-effort dealer source.

---

## Risks

| Risk | Mitigation |
|------|-----------|
| CarMax fully blocked | M0.5 spike + decision tree. CL-only still useful. |
| CL HTML changes | Defensive parsing, fixture regression tests, `refresh-fixtures` cmd. |
| CL IP blocks | Rate-limit 2-5s, realistic UA, max once/day. |
| Lookup tables incomplete | Confidence indicator. Stubs ship working; M3b fills real data. |
| Weekend time overrun | Milestones ordered by value. M0+M1+M3a+M4 = minimum viable. |
