"""Tests for db.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from carfinder.db import (
    find_fuzzy_duplicate,
    get_listings,
    init_db,
    prune_old,
    upsert_listing,
)
from carfinder.models import Listing


@pytest.fixture
def db(tmp_path):
    """Return an in-memory-equivalent temp-file DB connection."""
    conn = init_db(tmp_path / "test.db")
    yield conn
    conn.close()


def make_listing(**kwargs) -> Listing:
    defaults = dict(
        source="craigslist",
        source_id="cl-001",
        year=2014,
        make="Toyota",
        model="RAV4",
        mileage=80000,
        asking_price=10000.0,
        title_status="clean",
    )
    defaults.update(kwargs)
    return Listing(**defaults)


# --- Schema tests ---

def test_init_db_creates_listings_table(db):
    cur = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='listings'"
    )
    assert cur.fetchone() is not None


def test_init_db_creates_indexes(db):
    cur = db.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )
    names = {row[0] for row in cur.fetchall()}
    assert "idx_listings_score" in names
    assert "idx_listings_price" in names
    assert "idx_listings_source" in names


def test_init_db_idempotent(tmp_path):
    """Calling init_db twice on same path should not raise."""
    path = tmp_path / "test.db"
    conn1 = init_db(path)
    conn1.close()
    conn2 = init_db(path)
    conn2.close()


# --- Upsert tests ---

def test_upsert_inserts_new_listing(db):
    listing = make_listing()
    lid = upsert_listing(db, listing)
    assert lid is not None
    rows = db.execute("SELECT * FROM listings WHERE source_id='cl-001'").fetchall()
    assert len(rows) == 1


def test_upsert_updates_on_conflict(db):
    listing = make_listing(asking_price=10000.0)
    upsert_listing(db, listing)
    # Same source+source_id, different price
    updated = make_listing(asking_price=9500.0)
    upsert_listing(db, updated)

    rows = db.execute("SELECT * FROM listings WHERE source_id='cl-001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["asking_price"] == 9500.0


def test_upsert_returns_listing_id(db):
    listing = make_listing()
    lid = upsert_listing(db, listing)
    assert isinstance(lid, str)
    assert len(lid) > 0


def test_upsert_assigns_first_seen_and_last_seen(db):
    listing = make_listing()
    upsert_listing(db, listing)
    row = db.execute("SELECT first_seen, last_seen FROM listings LIMIT 1").fetchone()
    assert row["first_seen"] is not None
    assert row["last_seen"] is not None


# --- Fuzzy duplicate tests ---

def test_find_fuzzy_duplicate_finds_match(db):
    """find_fuzzy_duplicate should find a listing with same year/make/model within ±5% price."""
    existing = make_listing(source_id="cl-existing", asking_price=10000.0, mileage=80000)
    upsert_listing(db, existing)

    candidate = make_listing(
        source="carmax",
        source_id="cm-new",
        asking_price=10300.0,  # within 5%
        mileage=81500,         # within 2000
        vin=None,
    )
    dup = find_fuzzy_duplicate(db, candidate)
    assert dup is not None
    assert dup.source_id == "cl-existing"


def test_find_fuzzy_duplicate_no_match_price_too_different(db):
    existing = make_listing(source_id="cl-existing", asking_price=10000.0, mileage=80000)
    upsert_listing(db, existing)

    candidate = make_listing(
        source="carmax",
        source_id="cm-new",
        asking_price=11500.0,  # > 5% different
        mileage=80000,
        vin=None,
    )
    dup = find_fuzzy_duplicate(db, candidate)
    assert dup is None


def test_find_fuzzy_duplicate_no_match_mileage_too_different(db):
    existing = make_listing(source_id="cl-existing", asking_price=10000.0, mileage=80000)
    upsert_listing(db, existing)

    candidate = make_listing(
        source="carmax",
        source_id="cm-new",
        asking_price=10000.0,
        mileage=83000,  # > 2000 miles away
        vin=None,
    )
    dup = find_fuzzy_duplicate(db, candidate)
    assert dup is None


# --- get_listings tests ---

def test_get_listings_empty(db):
    result = get_listings(db)
    assert result == []


def test_get_listings_ordered_by_score(db):
    for score, sid in [(70.0, "cl-a"), (90.0, "cl-b"), (50.0, "cl-c")]:
        listing = make_listing(source_id=sid, score=score)
        upsert_listing(db, listing)

    results = get_listings(db)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_get_listings_min_score_filter(db):
    for score, sid in [(70.0, "cl-a"), (90.0, "cl-b"), (50.0, "cl-c")]:
        listing = make_listing(source_id=sid, score=score)
        upsert_listing(db, listing)

    results = get_listings(db, min_score=65.0)
    assert all(r.score >= 65.0 for r in results)
    assert len(results) == 2


def test_get_listings_limit(db):
    for i in range(5):
        listing = make_listing(source_id=f"cl-{i}", score=float(i * 10))
        upsert_listing(db, listing)

    results = get_listings(db, limit=3)
    assert len(results) == 3


# --- prune_old tests ---

def test_prune_old_removes_stale_listings(db):
    # Insert a listing with old last_seen
    old_listing = make_listing(source_id="cl-old")
    lid = upsert_listing(db, old_listing)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    db.execute("UPDATE listings SET last_seen = ? WHERE id = ?", (old_ts, lid))
    db.commit()

    # Insert a fresh listing
    fresh_listing = make_listing(source_id="cl-fresh")
    upsert_listing(db, fresh_listing)

    removed = prune_old(db, days=30)
    assert removed == 1
    remaining = get_listings(db)
    assert len(remaining) == 1
    assert remaining[0].source_id == "cl-fresh"


def test_prune_old_returns_count(db):
    listing = make_listing(source_id="cl-one")
    lid = upsert_listing(db, listing)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    db.execute("UPDATE listings SET last_seen = ? WHERE id = ?", (old_ts, lid))
    db.commit()

    count = prune_old(db, days=30)
    assert count == 1


def test_prune_old_keeps_fresh(db):
    listing = make_listing(source_id="cl-fresh")
    upsert_listing(db, listing)

    removed = prune_old(db, days=30)
    assert removed == 0
    assert len(get_listings(db)) == 1
