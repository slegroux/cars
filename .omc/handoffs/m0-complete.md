# M0 Complete

**Date:** 2026-05-23

## Files Created

- `pyproject.toml` — entry point fixed to `carfinder.cli:cli`, pytest/ruff config added
- `config.yaml` — verbatim from plan, weights verified sum to 1.0
- `.gitignore`, `.env.example`
- `src/carfinder/__init__.py`, `cli.py`, `config.py`, `db.py`, `models.py`, `scorer.py` (stub), `render.py` (stub)
- `src/carfinder/fetchers/__init__.py`, `base.py` (BaseFetcher ABC with rate-limit + retry helpers)
- `tests/__init__.py`, `test_config.py`, `test_db.py`, `test_models.py`
- `tests/fixtures/scorer/rav4_2014_xle.json`, `bmw_328i_2014_salvage.json`
- `tests/fixtures/craigslist/.gitkeep`, `tests/fixtures/carmax/.gitkeep`
- `data/reliability_tiers.yaml` (20 makes), `vehicle_dimensions.yaml` (20 entries), `insurance_risk.yaml` (12 entries), `roof_rack.yaml` (15 entries)
- `scripts/build_mpg_lookup.py`
- `data/mpg_lookup.csv` — 11,193 rows (years 2009–2022)

## Dependencies Installed

Runtime: `httpx`, `selectolax`, `pydantic>=2`, `click`, `rich`, `pyyaml`
Dev: `pytest`, `pytest-asyncio`, `pytest-httpx`, `ruff`

## mpg_lookup.csv Row Count

11,193 data rows (+ 2 header lines) — well above 200 threshold.

## Deviations from Plan

- `_get_column_defs()` in `db.py` uses type annotation introspection rather than hand-rolled DDL; fixed Union/Optional unwrapping to correctly map `float→REAL`, `int→INTEGER`.
- Pydantic v2.11 deprecates `model_fields` on instances; updated `config.py` and `test_config.py` to access it on the class.

## Blockers

None. M1 (Craigslist fetcher) can proceed.
