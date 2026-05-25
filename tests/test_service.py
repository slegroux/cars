"""Smoke tests for carfinder.service.load_scored_listings."""
from __future__ import annotations

from pathlib import Path

import pytest

from carfinder.db import init_db, upsert_listing
from carfinder.models import Listing
from carfinder.service import load_scored_listings


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def _make_listing(**kwargs) -> Listing:
    defaults = dict(
        source="manual",
        source_id="svc-001",
        year=2017,
        make="Toyota",
        model="RAV4",
        mileage=60000,
        asking_price=9500.0,
        title_status="clean",
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def test_load_scored_listings_returns_inserted_listing(tmp_path, monkeypatch):
    """load_scored_listings returns a scored entry for every eligible listing."""
    from carfinder.config import load_config

    # Point lookups at an empty tmp dir so load_lookups skips missing files
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)
    listing = _make_listing()
    upsert_listing(conn, listing)
    conn.close()

    cfg = load_config(CONFIG_PATH)

    scored, conn = load_scored_listings(cfg, db_path=db_path)
    conn.close()

    assert len(scored) == 1
    result = scored[0]
    assert result.listing.make == "Toyota"
    assert result.listing.model == "RAV4"
    assert isinstance(result.score, float)


def test_load_scored_listings_empty_db(tmp_path, monkeypatch):
    """Returns empty list when database has no listings."""
    from carfinder.config import load_config

    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "listings.db"
    init_db(db_path).close()

    cfg = load_config(CONFIG_PATH)

    scored, conn = load_scored_listings(cfg, db_path=db_path)
    conn.close()

    assert scored == []


def test_load_scored_listings_in_budget_filters_out_of_range(tmp_path, monkeypatch):
    """With in_budget=True, listings outside budget range are excluded."""
    from carfinder.config import load_config

    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)
    # Default budget in config.yaml is 5000–12000
    cheap = _make_listing(source_id="cheap", asking_price=1000.0)
    expensive = _make_listing(source_id="expensive", asking_price=99000.0)
    in_range = _make_listing(source_id="ok", asking_price=8000.0)
    for l in (cheap, expensive, in_range):
        upsert_listing(conn, l)
    conn.close()

    cfg = load_config(CONFIG_PATH)

    scored, conn = load_scored_listings(cfg, db_path=db_path, in_budget=True)
    conn.close()

    assert len(scored) == 1
    assert scored[0].listing.source_id == "ok"


def test_load_scored_listings_no_budget_flag_returns_all(tmp_path, monkeypatch):
    """Without in_budget flag, all listings are returned regardless of price."""
    from carfinder.config import load_config

    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)
    # Default budget in config.yaml is 5000–12000
    cheap = _make_listing(source_id="cheap", asking_price=1000.0)
    expensive = _make_listing(source_id="expensive", asking_price=99000.0)
    in_range = _make_listing(source_id="ok", asking_price=8000.0)
    for l in (cheap, expensive, in_range):
        upsert_listing(conn, l)
    conn.close()

    cfg = load_config(CONFIG_PATH)

    scored, conn = load_scored_listings(cfg, db_path=db_path, in_budget=False)
    conn.close()

    assert len(scored) == 3


def test_load_scored_listings_in_budget_drops_none_price(tmp_path, monkeypatch):
    """With in_budget=True, listings with no asking_price are dropped."""
    from carfinder.config import load_config

    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)
    no_price = _make_listing(source_id="no-price", asking_price=None)
    in_range = _make_listing(source_id="ok", asking_price=8000.0)
    for l in (no_price, in_range):
        upsert_listing(conn, l)
    conn.close()

    cfg = load_config(CONFIG_PATH)

    scored, conn = load_scored_listings(cfg, db_path=db_path, in_budget=True)
    conn.close()

    assert len(scored) == 1
    assert scored[0].listing.source_id == "ok"
