"""Tests for KBB fetcher — __NEXT_DATA__ parser, mapping, field extraction.

Fixture: tests/fixtures/kbb/search_2026-05.html
  10 listings extracted from a live KBB search response (2026-05).
  URL: /cars-for-sale/used/?zip=90405&radius=25&priceMin=5000&priceMax=12000&mileageMax=100000
"""
from __future__ import annotations

from pathlib import Path

import pytest

from carfinder.config import Config
from carfinder.fetchers.kbb import (
    _extract_vehicle_from_eggs,
    _parse_search_results,
    _vehicle_to_listing,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_HTML = Path(__file__).parent / "fixtures" / "kbb" / "search_2026-05.html"


def _load_fixture_html() -> str:
    return FIXTURE_HTML.read_text()


def _default_config(**overrides) -> Config:
    base = {
        "zip": "90405",
        "radius_miles": 25,
        "budget": {"min": 5000, "max": 12000},
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


# ---------------------------------------------------------------------------
# Test 1 — parse __NEXT_DATA__ fixture → >= 5 vehicles
# ---------------------------------------------------------------------------

def test_parse_returns_vehicles_from_fixture():
    html = _load_fixture_html()
    config = _default_config()
    vehicles = _parse_search_results(html, config)
    assert len(vehicles) >= 5, f"Expected >=5 vehicles, got {len(vehicles)}"


# ---------------------------------------------------------------------------
# Test 2 — required fields present on every parsed vehicle
# ---------------------------------------------------------------------------

def test_required_fields_present():
    html = _load_fixture_html()
    config = _default_config()
    vehicles = _parse_search_results(html, config)
    assert vehicles, "No vehicles parsed from fixture"

    for v in vehicles:
        assert v.get("year") is not None, f"Missing year: {v}"
        assert v.get("make"), f"Missing make: {v}"
        assert v.get("model"), f"Missing model: {v}"
        assert v.get("price") is not None, f"Missing price: {v}"


# ---------------------------------------------------------------------------
# Test 3 — at least one vehicle has a VIN
# ---------------------------------------------------------------------------

def test_at_least_one_vin():
    html = _load_fixture_html()
    config = _default_config()
    vehicles = _parse_search_results(html, config)
    vins = [v.get("vin") for v in vehicles if v.get("vin")]
    assert vins, "No VINs found in any parsed vehicle"
    # VINs should be 17 chars
    for vin in vins:
        assert len(vin) == 17, f"Unexpected VIN length: {vin!r}"


# ---------------------------------------------------------------------------
# Test 4 — vehicle dicts map to valid Listing objects
# ---------------------------------------------------------------------------

def test_vehicle_maps_to_listing():
    html = _load_fixture_html()
    config = _default_config()
    vehicles = _parse_search_results(html, config)
    assert vehicles

    for v in vehicles:
        listing = _vehicle_to_listing(v, config)
        assert listing is not None, f"_vehicle_to_listing returned None for {v}"
        assert listing.source == "kbb"
        assert listing.source_id, "source_id must be non-empty"
        assert listing.year is not None
        assert listing.make
        assert listing.model
        assert listing.asking_price is not None
        assert isinstance(listing.asking_price, float)


# ---------------------------------------------------------------------------
# Test 5 — mileage is parsed from comma-formatted string
# ---------------------------------------------------------------------------

def test_mileage_parsed_from_string():
    item = {
        "year": 2018,
        "make": {"name": "BMW"},
        "model": {"name": "M3"},
        "trim": {"name": "Sedan"},
        "mileage": {"label": "Mileage", "value": "27,800"},
        "pricingDetail": {"salePrice": 58900},
        "vin": "WBS8M9C56J5J79614",
        "driveType": {"name": "RWD"},
        "fuelType": {"name": "Gasoline"},
        "bodyStyles": [{"name": "Sedan"}],
        "color": {"exteriorColor": "Yellow", "interiorColor": "Black"},
        "vdpBaseUrl": "/cars-for-sale/vehicle/755985912",
        "listingType": "USED",
    }
    vehicle = _extract_vehicle_from_eggs("755985912", item)
    assert vehicle is not None
    assert vehicle["mileage"] == 27800


# ---------------------------------------------------------------------------
# Test 6 — VIN present in every fixture vehicle (regression guard)
# ---------------------------------------------------------------------------

def test_all_fixture_vehicles_have_vin():
    html = _load_fixture_html()
    config = _default_config()
    vehicles = _parse_search_results(html, config)

    for v in vehicles:
        assert v.get("vin"), f"Expected VIN but got none for vehicle: {v.get('year')} {v.get('make')} {v.get('model')}"


# ---------------------------------------------------------------------------
# Test 7 — vdpBaseUrl becomes full https:// URL
# ---------------------------------------------------------------------------

def test_vdp_url_is_absolute():
    item = {
        "year": 2018,
        "make": {"name": "BMW"},
        "model": {"name": "M3"},
        "trim": {"name": "Sedan"},
        "mileage": {"value": "27,800"},
        "pricingDetail": {"salePrice": 58900},
        "vin": "WBS8M9C56J5J79614",
        "driveType": {"name": "RWD"},
        "fuelType": {"name": "Gasoline"},
        "bodyStyles": [{"name": "Sedan"}],
        "color": {},
        "vdpBaseUrl": "/cars-for-sale/vehicle/755985912?zip=90405",
        "listingType": "USED",
    }
    vehicle = _extract_vehicle_from_eggs("755985912", item)
    assert vehicle is not None
    assert vehicle["url"].startswith("https://www.kbb.com/")


# ---------------------------------------------------------------------------
# Test 8 — empty / malformed HTML returns empty list, no exception
# ---------------------------------------------------------------------------

def test_empty_html_returns_empty_list():
    config = _default_config()
    result = _parse_search_results("<html><body></body></html>", config)
    assert result == []


def test_malformed_next_data_returns_empty_list():
    config = _default_config()
    html = '<html><head><script id="__NEXT_DATA__" type="application/json">{bad json</script></head></html>'
    result = _parse_search_results(html, config)
    assert result == []
