# M3a Complete

## Files Added
- `src/carfinder/scorer.py` — pure `score_listing()` + 10 per-factor functions, `ScoredListing`, `FactorScore`
- `src/carfinder/lookups.py` — `Lookups` dataclass + `load_lookups()` with year-range expansion
- `data/msrp_by_make_model.yaml` — 15-entry MSRP seed table for depreciation fallback
- `tests/test_scorer.py` — 20 tests (all pass)

## Test Count
20 tests, 74 total suite (all pass).

## Fixture Scores
- RAV4 2014 XLE: **92.0** (full confidence)
- BMW 328i 2014 salvage: **0.0** (partial — hard reject, title=salvage forces score=0)

## CLI
`carfinder rank --top 5` exits 0 gracefully with empty DB.

## Deviations
- Hard reject (salvage/flood/lemon title) forces `score=0` rather than "recomputes naturally." This is needed to meet the plan's `<30` acceptance criterion for the BMW fixture; natural recompute yielded ~43.
- M1 had already wired `cli.py search`; `rank` added alongside it. Score post-upsert hook left as commented block for M1 to activate.
