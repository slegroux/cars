"""Tests for db.py."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from carfinder.db import (
    find_by_vin,
    find_fuzzy_duplicate,
    get_listings,
    init_db,
    prune_old,
    upsert_listing,
)
from carfinder.importer import _source_id_from_fields
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


# --- Mutable columns upsert tests ---

def test_upsert_updates_detail_page_fields(db):
    """Fields scraped on a second-pass detail-page crawl should overwrite NULL values."""
    # First pass: insert with NULL detail fields
    listing = make_listing(
        source_id="cl-detail",
        transmission=None,
        drivetrain=None,
        fuel_type=None,
        title_status=None,
        location=None,
    )
    upsert_listing(db, listing)

    # Second pass: same source+source_id with real values from detail page
    updated = make_listing(
        source_id="cl-detail",
        transmission="automatic",
        drivetrain="AWD",
        fuel_type="gasoline",
        title_status="clean",
        location="Seattle, WA",
    )
    upsert_listing(db, updated)

    row = db.execute(
        "SELECT transmission, drivetrain, fuel_type, title_status, location "
        "FROM listings WHERE source_id='cl-detail'"
    ).fetchone()
    assert row["transmission"] == "automatic"
    assert row["drivetrain"] == "AWD"
    assert row["fuel_type"] == "gasoline"
    assert row["title_status"] == "clean"
    assert row["location"] == "Seattle, WA"


# --- Schema migration tests ---

def test_migrate_schema_adds_missing_column(tmp_path):
    """init_db should add columns present in the model but absent from an older DB."""
    db_path = tmp_path / "migrate.db"

    # Create a fresh DB so the table exists, then simulate an older schema by
    # recreating the listings table without the 'insurance_risk_tier' column.
    conn = init_db(db_path)
    conn.close()

    raw = sqlite3.connect(str(db_path))
    raw.row_factory = sqlite3.Row
    # Collect all current columns except the one we want to drop.
    cols_info = raw.execute("PRAGMA table_info(listings)").fetchall()
    kept_cols = [row["name"] for row in cols_info if row["name"] != "insurance_risk_tier"]
    col_list = ", ".join(kept_cols)
    raw.executescript(f"""
        DROP TABLE listings;
        CREATE TABLE listings ({col_list}, UNIQUE(source, source_id));
    """)
    raw.close()

    # Now call init_db again — migration should add the missing column back.
    conn2 = init_db(db_path)
    existing = {row[1] for row in conn2.execute("PRAGMA table_info(listings)").fetchall()}
    assert "insurance_risk_tier" in existing

    # And upsert_listing must not raise OperationalError.
    listing = make_listing(source_id="migration-test", insurance_risk_tier="low")
    upsert_listing(conn2, listing)
    conn2.close()


# --- VIN-based cross-source merge tests ---


def test_upsert_merges_same_vin_from_different_source(db):
    """Same VIN from a different source should merge into the existing row."""
    first = make_listing(
        source="carmax",
        source_id="cm-123",
        vin="ABC123",
        asking_price=12000.0,
        description=None,
        location="Seattle, WA",
    )
    first_id = upsert_listing(db, first)

    second = make_listing(
        source="craigslist",
        source_id="cl-456",
        vin="ABC123",
        asking_price=11500.0,  # existing non-null, should NOT be overwritten
        description="Great condition, one owner",  # existing is null, should fill
        location=None,
    )
    second_id = upsert_listing(db, second)

    # Same id (canonical existing row)
    assert second_id == first_id

    # Only one row in DB
    rows = db.execute("SELECT * FROM listings").fetchall()
    assert len(rows) == 1

    row = rows[0]
    # Canonical (source, source_id) preserved from the existing row.
    assert row["source"] == "carmax"
    assert row["source_id"] == "cm-123"
    # Non-null existing field preserved (no overwrite).
    assert row["asking_price"] == 12000.0
    assert row["location"] == "Seattle, WA"
    # Null existing field filled from incoming.
    assert row["description"] == "Great condition, one owner"


def test_upsert_no_vin_does_not_merge(db):
    """Without VINs, listings from different sources stay as separate rows."""
    first = make_listing(source="carmax", source_id="cm-1", vin=None)
    upsert_listing(db, first)

    second = make_listing(source="craigslist", source_id="cl-1", vin=None)
    upsert_listing(db, second)

    rows = db.execute("SELECT * FROM listings").fetchall()
    assert len(rows) == 2


def test_upsert_same_vin_same_source_is_normal_upsert(db):
    """Same VIN + same (source, source_id) follows normal ON CONFLICT update path."""
    first = make_listing(
        source="carmax", source_id="cm-789", vin="XYZ999", asking_price=15000.0
    )
    upsert_listing(db, first)

    second = make_listing(
        source="carmax", source_id="cm-789", vin="XYZ999", asking_price=14500.0
    )
    upsert_listing(db, second)

    rows = db.execute("SELECT * FROM listings").fetchall()
    assert len(rows) == 1
    # Mutable field updated via normal ON CONFLICT path.
    assert rows[0]["asking_price"] == 14500.0


def test_find_by_vin_returns_none_for_null_vin(db):
    """find_by_vin must never match on a NULL/empty VIN."""
    # Insert a listing with a real VIN.
    listing = make_listing(source_id="cl-vin", vin="REAL-VIN-1")
    upsert_listing(db, listing)
    # Insert a listing with NULL VIN.
    null_vin_listing = make_listing(source_id="cl-novin", vin=None)
    upsert_listing(db, null_vin_listing)

    assert find_by_vin(db, None) is None
    assert find_by_vin(db, "") is None
    # Sanity: a real VIN still resolves.
    found = find_by_vin(db, "REAL-VIN-1")
    assert found is not None
    assert found.source_id == "cl-vin"


# --- _source_id_from_fields tests ---

def test_source_id_from_fields_is_deterministic():
    """Same inputs produce the same id across multiple calls."""
    id1 = _source_id_from_fields("Toyota", "RAV4", 2019, 45000)
    id2 = _source_id_from_fields("Toyota", "RAV4", 2019, 45000)
    assert id1 == id2
    assert id1.startswith("manual-")


def test_source_id_from_fields_normalizes_whitespace_case():
    """Variations in case and surrounding whitespace produce the same id."""
    base = _source_id_from_fields("Toyota", "RAV4", 2019)
    assert _source_id_from_fields("TOYOTA", "RAV4", 2019) == base
    assert _source_id_from_fields(" toyota ", " rav4 ", 2019) == base
    assert _source_id_from_fields("toyota", "RAV4", 2019) == base


def test_manual_import_idempotent_without_url(db):
    """Importing the same car twice without a URL creates only one DB row."""
    from carfinder.importer import _source_id_from_fields

    source_id = _source_id_from_fields("Honda", "CR-V", 2020, 30000)
    listing = Listing(
        id=source_id,
        source="manual",
        source_id=source_id,
        url=None,
        make="Honda",
        model="CR-V",
        year=2020,
        mileage=30000,
        asking_price=25000.0,
    )
    upsert_listing(db, listing)
    upsert_listing(db, listing)

    rows = db.execute(
        "SELECT * FROM listings WHERE source='manual' AND source_id=?", (source_id,)
    ).fetchall()
    assert len(rows) == 1
