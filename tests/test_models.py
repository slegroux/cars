"""Tests for models.py."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from carfinder.models import Listing


def test_listing_defaults_to_none():
    """Missing optional fields should default to None."""
    listing = Listing()
    assert listing.id is None
    assert listing.year is None
    assert listing.make is None
    assert listing.score is None


def test_listing_photos_defaults_to_empty_list():
    listing = Listing()
    assert listing.photos == []


def test_listing_score_breakdown_defaults_to_empty_dict():
    listing = Listing()
    assert listing.score_breakdown == {}


def test_to_row_json_encodes_photos():
    listing = Listing(
        source="craigslist",
        source_id="abc123",
        photos=["http://a.jpg", "http://b.jpg"],
    )
    row = listing.to_row()
    assert isinstance(row["photos"], str)
    assert json.loads(row["photos"]) == ["http://a.jpg", "http://b.jpg"]


def test_to_row_json_encodes_score_breakdown():
    listing = Listing(
        source="craigslist",
        source_id="abc123",
        score_breakdown={"reliability": {"score": 10, "weight": 0.22}},
    )
    row = listing.to_row()
    assert isinstance(row["score_breakdown"], str)
    assert json.loads(row["score_breakdown"])["reliability"]["score"] == 10


def test_to_row_serializes_dates():
    listing = Listing(
        posted_date=date(2026, 5, 18),
        first_seen=datetime(2026, 5, 18, 10, 0, 0, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 23, 8, 0, 0, tzinfo=timezone.utc),
    )
    row = listing.to_row()
    assert row["posted_date"] == "2026-05-18"
    assert "2026-05-18" in row["first_seen"]


def test_from_row_round_trip():
    """A Listing should survive to_row() -> from_row() unchanged."""
    original = Listing(
        id="test-id-001",
        source="craigslist",
        source_id="abc123",
        year=2014,
        make="Toyota",
        model="RAV4",
        trim="XLE",
        body_type="SUV",
        drivetrain="AWD",
        transmission="automatic",
        mileage=110000,
        asking_price=11500.0,
        title_status="clean",
        photos=["http://a.jpg", "http://b.jpg"],
        score=82.5,
        score_breakdown={"reliability": {"score": 10}},
    )
    row = original.to_row()
    restored = Listing.from_row(row)

    assert restored.id == original.id
    assert restored.make == original.make
    assert restored.mileage == original.mileage
    assert restored.photos == original.photos
    assert restored.score_breakdown == original.score_breakdown
    assert restored.score == original.score


def test_from_row_extra_fields_ignored():
    """from_row should ignore unknown columns (ConfigDict extra=ignore)."""
    row = {
        "id": "x",
        "make": "Honda",
        "unknown_future_column": "some_value",
        "photos": "[]",
        "score_breakdown": "{}",
    }
    listing = Listing.from_row(row)
    assert listing.make == "Honda"


def test_listing_extra_fields_ignored():
    """Listing construction ignores unknown fields."""
    listing = Listing(make="Mazda", nonexistent_field="blah")
    assert listing.make == "Mazda"
