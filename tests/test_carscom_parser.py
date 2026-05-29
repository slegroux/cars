"""Tests for the Cars.com fetcher parser."""
from __future__ import annotations

from pathlib import Path


from carfinder.config import Config
from carfinder.fetchers.carscom import _map_vehicle, _parse_search_page

FIXTURE = Path(__file__).parent / "fixtures" / "carscom" / "search_sample.html"


def _cfg(**overrides) -> Config:
    base = {
        "zip": "90405",
        "radius_miles": 25,
        "budget": {"min": 5000, "max": 12000},
        "mileage": {"max": 100000},
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


def _html() -> str:
    return FIXTURE.read_text()


# ---------------------------------------------------------------------------
# 1. In-budget listings are returned
# ---------------------------------------------------------------------------

def test_in_budget_listings_are_returned():
    listings = _parse_search_page(_html(), _cfg())
    ids = {lst.source_id for lst in listings}
    assert "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa" in ids  # RAV4 $11,500
    assert "bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb" in ids  # CR-V $10,800
    assert "cccccccc-0003-0003-0003-cccccccccccc" in ids  # Forester $8,500


# ---------------------------------------------------------------------------
# 2. Over-budget listing is filtered out
# ---------------------------------------------------------------------------

def test_over_budget_listing_excluded():
    listings = _parse_search_page(_html(), _cfg())
    ids = {lst.source_id for lst in listings}
    assert "dddddddd-0004-0004-0004-dddddddddddd" not in ids  # BMW $42,000


# ---------------------------------------------------------------------------
# 3. Over-mileage listing is filtered out
# ---------------------------------------------------------------------------

def test_over_mileage_listing_excluded():
    listings = _parse_search_page(_html(), _cfg())
    ids = {lst.source_id for lst in listings}
    assert "eeeeeeee-0005-0005-0005-eeeeeeeeeeee" not in ids  # Camry 130k mi


# ---------------------------------------------------------------------------
# 4. CPO indicator maps to seller_type="certified"
# ---------------------------------------------------------------------------

def test_cpo_maps_to_certified():
    listings = _parse_search_page(_html(), _cfg())
    forester = next(lst for lst in listings if lst.source_id =="cccccccc-0003-0003-0003-cccccccccccc")
    assert forester.seller_type == "certified"


# ---------------------------------------------------------------------------
# 5. Non-CPO dealer listing maps to seller_type="dealer"
# ---------------------------------------------------------------------------

def test_non_cpo_maps_to_dealer():
    listings = _parse_search_page(_html(), _cfg())
    rav4 = next(lst for lst in listings if lst.source_id =="aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa")
    assert rav4.seller_type == "dealer"


# ---------------------------------------------------------------------------
# 6. Core fields parsed correctly
# ---------------------------------------------------------------------------

def test_core_fields_parsed():
    listings = _parse_search_page(_html(), _cfg())
    rav4 = next(lst for lst in listings if lst.source_id =="aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa")
    assert rav4.make == "Toyota"
    assert rav4.model == "RAV4"
    assert rav4.year == 2019
    assert rav4.trim == "XLE"
    assert rav4.mileage == 75000
    assert rav4.asking_price == 11500.0
    assert rav4.body_type == "SUV"
    assert rav4.fuel_type == "Gasoline"
    assert rav4.source == "carscom"
    assert rav4.url == "https://www.cars.com/vehicledetail/aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa/"
    assert rav4.photos == ["https://example.com/rav4.jpg"]


# ---------------------------------------------------------------------------
# 7. Ad placeholders (no data-vehicle-details) are silently skipped
# ---------------------------------------------------------------------------

def test_ad_placeholders_skipped():
    listings = _parse_search_page(_html(), _cfg())
    assert len(listings) == 3  # RAV4 + CR-V + Forester; BMW and Camry filtered


# ---------------------------------------------------------------------------
# 8. Empty page returns empty list
# ---------------------------------------------------------------------------

def test_empty_page_returns_empty():
    listings = _parse_search_page("<html><body></body></html>", _cfg())
    assert listings == []


# ---------------------------------------------------------------------------
# 9. Missing listingId returns None from _map_vehicle
# ---------------------------------------------------------------------------

def test_map_vehicle_missing_id_returns_none():
    assert _map_vehicle({}) is None
    assert _map_vehicle({"make": "Toyota"}) is None


# ---------------------------------------------------------------------------
# 10. None price passes through without filtering (price=None → not filtered)
# ---------------------------------------------------------------------------

def test_none_price_not_filtered():
    html = """<html><body>
    <div data-listing-id="ff000000-0001-0001-0001-ff0000000000"
         data-vehicle-details='{"listingId":"ff000000-0001-0001-0001-ff0000000000","make":"Mazda","model":"CX-5","year":"2019","mileage":"50000","price":null,"bodyStyle":"SUV","cpoIndicator":false}'>
    </div></body></html>"""
    listings = _parse_search_page(html, _cfg())
    assert len(listings) == 1
    assert listings[0].asking_price is None
