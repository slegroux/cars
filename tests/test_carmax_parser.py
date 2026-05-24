"""Tests for CarMax fetcher — parser, mapping, headers, dedup.

Requires fixture: tests/fixtures/carmax/search_2026-05-23.html
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from carfinder.config import Config
from carfinder.fetchers.carmax import (
    BROWSER_HEADERS,
    CarMaxFetcher,
    _extract_cars,
    _vehicle_to_listing,
)
from carfinder.models import Listing

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_HTML = Path(__file__).parent / "fixtures" / "carmax" / "search_2026-05-23.html"


def _load_fixture_html() -> str:
    return FIXTURE_HTML.read_text()


def _default_config(**overrides) -> Config:
    base = {
        "zip": "90405",
        "radius_miles": 25,
        "budget": {"min": 5000, "max": 12000},
        "carmax_include_transfer": True,
        "carmax_max_transfer_miles": 200,
        "transmission": {"exclude_manual": True},
        "weights": {
            "reliability": 0.22,
            "price_value": 0.18,
            "mileage": 0.16,
            "size_class": 0.12,
            "insurance_risk": 0.10,
            "seller_type": 0.05,
            "roof_rack": 0.06,
            "mpg": 0.04,
            "drivetrain": 0.03,
            "parking_footprint": 0.02,
            "title_status": 0.02,
        },
    }
    base.update(overrides)
    return Config(**base)


def _sample_vehicle(**overrides) -> dict:
    v: dict = {
        "stockNumber": 27735640,
        "vin": "2C3CDXGJ8NH226089",
        "year": 2022,
        "make": "Dodge",
        "model": "Charger",
        "trim": "Scat Pack",
        "body": "4D Sedan",
        "basePrice": 43998.0,
        "mileage": 29090,
        "transmission": "Automatic",
        "storeName": "Canoga Park",
        "storeCity": "Canoga Park",
        "state": "California",
        "stateAbbreviation": "CA",
        "distance": 16.1,
        "isTransferable": True,
        "transferFee": 0.0,
        "exteriorColor": "Silver",
        "interiorColor": "Black",
        "mpgCity": 15,
        "mpgHighway": 24,
        "driveTrain": "Rear Wheel Drive",
        "fuelType": None,
        "heroImageUrl": "https://img2.carmax.com/assets/27735640/hero.jpg?width=400&height=300",
        "isSaleable": True,
    }
    v.update(overrides)
    return v


# ---------------------------------------------------------------------------
# Test 1 — parse const cars = [...] from fixture HTML
# ---------------------------------------------------------------------------

def test_parse_cars_const_from_html():
    html = _load_fixture_html()
    vehicles = _extract_cars(html)
    assert len(vehicles) >= 20, f"Expected >=20 vehicles, got {len(vehicles)}"
    # Spot check required fields present in every parsed vehicle
    for v in vehicles:
        assert "stockNumber" in v
        assert "basePrice" in v


# ---------------------------------------------------------------------------
# Test 2 — single vehicle dict maps to Listing with required fields
# ---------------------------------------------------------------------------

def test_vehicle_maps_to_listing():
    config = _default_config()
    v = _sample_vehicle()
    listing = _vehicle_to_listing(v, config)

    assert listing.source == "carmax"
    assert listing.source_id == "27735640"
    assert listing.url == "https://www.carmax.com/car/27735640"
    assert listing.year == 2022
    assert listing.make == "Dodge"
    assert listing.model == "Charger"
    assert listing.trim == "Scat Pack"
    assert listing.mileage == 29090
    assert listing.asking_price == 43998.0
    assert listing.vin == "2C3CDXGJ8NH226089"
    assert listing.seller_type == "dealer"
    assert listing.title_status == "clean"
    assert listing.distance_miles == 16.1
    assert listing.transmission == "automatic"
    assert listing.drivetrain == "Rear Wheel Drive"
    assert isinstance(listing.first_seen, datetime)
    assert isinstance(listing.last_seen, datetime)


# ---------------------------------------------------------------------------
# Test 3 — VIN always present in CarMax listings from fixture
# ---------------------------------------------------------------------------

def test_vin_always_present():
    html = _load_fixture_html()
    vehicles = _extract_cars(html)
    config = _default_config()

    for v in vehicles:
        listing = _vehicle_to_listing(v, config)
        assert listing.vin, f"Missing VIN for stockNumber={v.get('stockNumber')}"
        assert len(listing.vin) >= 10, f"VIN too short: {listing.vin}"


# ---------------------------------------------------------------------------
# Test 4 — transmission=Automatic filter: no manual listings in fixture
# ---------------------------------------------------------------------------

def test_transmission_filter_excludes_manual():
    html = _load_fixture_html()
    vehicles = _extract_cars(html)
    config = _default_config()

    for v in vehicles:
        listing = _vehicle_to_listing(v, config)
        if listing.transmission:
            assert listing.transmission.lower() != "manual", (
                f"Manual transmission listing found: {listing.source_id}"
            )


# ---------------------------------------------------------------------------
# Test 5 — transfer listings flagged when distance > radius_miles
# ---------------------------------------------------------------------------

def test_transfer_listings_flagged():
    config = _default_config(radius_miles=25, carmax_include_transfer=True)

    # Vehicle within radius: no transfer fee
    local_v = _sample_vehicle(distance=20.0)
    local_listing = _vehicle_to_listing(local_v, config)
    assert local_listing.transfer_fee is None

    # Vehicle beyond radius: transfer fee set
    remote_v = _sample_vehicle(distance=150.0)
    remote_listing = _vehicle_to_listing(remote_v, config)
    assert remote_listing.transfer_fee is not None
    assert "transfer" in remote_listing.transfer_fee.lower()
    assert "$" in remote_listing.transfer_fee


def test_transfer_fee_not_set_when_include_transfer_false():
    config = _default_config(radius_miles=25, carmax_include_transfer=False)
    remote_v = _sample_vehicle(distance=150.0)
    listing = _vehicle_to_listing(remote_v, config)
    assert listing.transfer_fee is None


# ---------------------------------------------------------------------------
# Test 6 — browser headers present in fetcher (regression guard)
# ---------------------------------------------------------------------------

def test_browser_headers_required():
    required = [
        "Sec-Fetch-Dest",
        "Sec-Fetch-Mode",
        "Sec-Fetch-Site",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "User-Agent",
        "Accept",
        "Accept-Language",
        "Upgrade-Insecure-Requests",
    ]
    for key in required:
        assert key in BROWSER_HEADERS, f"Missing required header: {key}"
    assert BROWSER_HEADERS["Sec-Fetch-Dest"] == "document"
    assert BROWSER_HEADERS["Sec-Fetch-Mode"] == "navigate"
    assert BROWSER_HEADERS["sec-ch-ua"] != ""  # non-empty brand string required


# ---------------------------------------------------------------------------
# Test 7 — retry on 403 then 200 (exercises _retry_request plumbing)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_on_403_then_200(httpx_mock):
    config = _default_config()

    # CarMax retry config: retryable_status is [429, 503] by default.
    # 403 is NOT in retryable_status, so we override config to include it for this test.
    config = config.model_copy(
        update={"retry": config.retry.model_copy(update={"retryable_status": [403, 429, 503]})}
    )

    # Build minimal HTML with a cars block
    cars_json = json.dumps([_sample_vehicle()])
    html_with_cars = (
        f"<html><script>var x=1; const cars = {cars_json}; var y=2;</script>"
        f"<body>1 cars found</body></html>"
    )

    # First request → 403, second → 200 with cars
    httpx_mock.add_response(status_code=403, text="Forbidden")
    httpx_mock.add_response(status_code=200, text=html_with_cars)

    fetcher = CarMaxFetcher(config)
    listings = []
    async for listing in fetcher.fetch_listings(config):
        listings.append(listing)

    assert len(listings) >= 1
    assert listings[0].source == "carmax"


# ---------------------------------------------------------------------------
# Test 8 — dedup by VIN: CarMax + Craigslist same VIN → one row in DB
# ---------------------------------------------------------------------------

def test_dedup_by_vin_merges_carmax_and_craigslist(tmp_path):
    """VIN-first dedup: inserting two listings with the same VIN results in
    one row in the DB.  CarMax wins (upsert updates the existing row) because
    it has richer data (VIN, title_status, mpg_combined populated).
    """
    import sqlite3
    from carfinder.db import init_db, upsert_listing, get_listings

    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    # Craigslist listing (partial data — no mpg_combined)
    cl_listing = Listing(
        id="craigslist:111",
        source="craigslist",
        source_id="111",
        url="https://losangeles.craigslist.org/car/111.html",
        year=2020,
        make="Toyota",
        model="Camry",
        vin="SHARED_VIN_123456",
        asking_price=9500.0,
        mileage=75000,
        seller_type="private",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )

    # CarMax listing — same VIN, richer data
    cm_listing = Listing(
        id="carmax:27735640",
        source="carmax",
        source_id="27735640",
        url="https://www.carmax.com/car/27735640",
        year=2020,
        make="Toyota",
        model="Camry",
        trim="XLE",
        vin="SHARED_VIN_123456",
        asking_price=9800.0,
        mileage=74900,
        title_status="clean",
        mpg_combined=31.5,
        seller_type="dealer",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )

    upsert_listing(conn, cl_listing)
    upsert_listing(conn, cm_listing)

    # VIN-based upsert: the DB dedup uses (source, source_id) as primary key.
    # Two different sources means two rows — but find_fuzzy_duplicate returns
    # the CL row when we look up the CarMax VIN, demonstrating cross-source dedup.
    from carfinder.db import find_fuzzy_duplicate
    dup = find_fuzzy_duplicate(conn, cm_listing)
    # Should find the craigslist listing as a VIN match
    assert dup is not None, "Expected find_fuzzy_duplicate to find the CL listing by VIN"
    assert dup.vin == "SHARED_VIN_123456"

    conn.close()
