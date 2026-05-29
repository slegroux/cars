"""Regression tests for fixes applied during the repo audit.

Each test pins a specific bug so it cannot silently regress.
"""
from __future__ import annotations

import pytest
import yaml

from carfinder.config import Config
from carfinder.fetchers.craigslist import (
    _extract_source_id_from_url,
    _parse_price,
    _parse_search_page,
    parse_title,
)
from carfinder.fetchers.kbb import _extract_vehicle_from_eggs, _parse_mileage
from carfinder.lookups import Lookups, load_lookups
from carfinder.models import Listing
from carfinder.scorer import (
    score_insurance_risk,
    score_mpg,
    score_parking_footprint,
    score_price_value,
    score_roof_rack,
)


# ---------------------------------------------------------------------------
# Craigslist price parsing — ranges must not concatenate into giant numbers
# ---------------------------------------------------------------------------

def test_parse_price_single_value():
    assert _parse_price("$7,500") == 7500.0


def test_parse_price_range_takes_first_value():
    # Was "1200015000"; must be the first number, 12000.
    assert _parse_price("$12,000 – $15,000") == 12000.0


def test_parse_price_no_digits_returns_none():
    assert _parse_price("call for price") is None
    assert _parse_price(None) is None


# ---------------------------------------------------------------------------
# Craigslist source_id extraction
# ---------------------------------------------------------------------------

def test_extract_source_id_from_html_url():
    url = "https://losangeles.craigslist.org/wst/cto/d/la-2015-honda/7891234567.html"
    assert _extract_source_id_from_url(url) == "7891234567"


def test_extract_source_id_without_html_extension():
    url = "https://losangeles.craigslist.org/wst/cto/d/some-slug/7891234567"
    assert _extract_source_id_from_url(url) == "7891234567"


def test_extract_source_id_returns_none_not_full_url():
    # Previously returned the whole URL, poisoning dedup.
    assert _extract_source_id_from_url("https://example.com/foo/bar") is None
    assert _extract_source_id_from_url("") is None


# ---------------------------------------------------------------------------
# Craigslist title parsing — price must not leak into the model, but real
# numeric models (Chrysler 300) must survive.
# ---------------------------------------------------------------------------

def test_parse_title_price_does_not_become_model():
    year, make, model = parse_title("2020 Honda – $15,000")
    assert model is None or not model.split()[0].isdigit()


def test_parse_title_model_survives_trailing_price():
    year, make, model = parse_title("2016 Toyota RAV4 XLE - $12,500")
    assert (year, make) == (2016, "Toyota")
    assert model.split()[0] == "RAV4"


def test_parse_title_numeric_model_without_price_survives():
    year, make, model = parse_title("2015 Chrysler 300 Limited")
    assert (year, make) == (2015, "Chrysler")
    assert model.split()[0] == "300"


# ---------------------------------------------------------------------------
# Craigslist location — parenthesized hood, trailing junk stripped
# ---------------------------------------------------------------------------

def test_parse_location_extracts_parenthesized_hood():
    html = (
        '<li class="cl-static-search-result">'
        '<a href="https://x.craigslist.org/d/abc/7891234567.html">'
        '<div class="title">2016 Toyota RAV4</div>'
        '<div class="price">$12,000</div>'
        '<div class="location">(santa monica) - great area</div>'
        "</a></li>"
    )
    cards = _parse_search_page(html)
    assert len(cards) == 1
    assert cards[0]["location"] == "santa monica"


# ---------------------------------------------------------------------------
# KBB mileage parsing — ranges + sanity cap
# ---------------------------------------------------------------------------

def test_kbb_mileage_single():
    assert _parse_mileage("27,800") == 27800


def test_kbb_mileage_range_takes_first():
    assert _parse_mileage("27,800–30,000") == 27800


def test_kbb_mileage_rejects_implausible():
    assert _parse_mileage("2780030000") is None


def test_kbb_mileage_none_inputs():
    assert _parse_mileage(None) is None
    assert _parse_mileage("") is None


# ---------------------------------------------------------------------------
# KBB __eggsState extraction — null/odd-typed fields must not crash
# ---------------------------------------------------------------------------

def test_kbb_extract_handles_explicit_nulls():
    item = {
        "year": 2018, "vin": "X", "make": None, "model": None, "trim": None,
        "pricingDetail": None, "mileage": None, "bodyStyles": None,
        "driveType": None, "fuelType": None, "color": None, "vdpBaseUrl": None,
    }
    v = _extract_vehicle_from_eggs("L1", item)
    assert v is not None  # no AttributeError, no whole-vehicle loss
    assert v["make"] is None and v["model"] is None
    assert v["mileage"] is None and v["price"] is None and v["url"] is None


def test_kbb_extract_bodystyles_string_is_ignored():
    item = {"year": 2018, "make": {"name": "Toyota"}, "model": {"name": "RAV4"},
            "bodyStyles": "Sedan"}
    v = _extract_vehicle_from_eggs("L2", item)
    assert v is not None and v["body_type"] is None


def test_kbb_extract_relative_vdp_without_slash_dropped():
    item = {"year": 2018, "vdpBaseUrl": "cars/foo"}
    assert _extract_vehicle_from_eggs("L3", item)["url"] is None


def test_kbb_extract_absolute_and_rooted_vdp():
    abs_item = {"year": 2018, "vdpBaseUrl": "https://www.kbb.com/x"}
    rooted = {"year": 2018, "vdpBaseUrl": "/cars/foo"}
    assert _extract_vehicle_from_eggs("a", abs_item)["url"] == "https://www.kbb.com/x"
    assert _extract_vehicle_from_eggs("b", rooted)["url"] == "https://www.kbb.com/cars/foo"


# ---------------------------------------------------------------------------
# Scorer MPG confidence — a lookup hit is canonical ("real"), like its siblings
# ---------------------------------------------------------------------------

def test_score_mpg_lookup_hit_is_real():
    lk = Lookups()
    lk.mpg[(2016, "toyota", "rav4")] = 30  # keys are normalized (lowercased)
    listing = Listing(year=2016, make="Toyota", model="RAV4")  # no mpg_combined
    fs = score_mpg(listing, lk, 0.04)
    assert fs.confidence == "real"
    assert fs.raw == 8.0  # 30 mpg → "28+" tier


def test_score_mpg_lookup_miss_is_estimated():
    listing = Listing(year=1999, make="Trabant", model="P601")
    fs = score_mpg(listing, Lookups(), 0.04)
    assert fs.confidence == "estimated"
    assert fs.raw == 5.0


# ---------------------------------------------------------------------------
# Config validation — fail at load time with clear errors, not mid-search
# ---------------------------------------------------------------------------

def test_config_rejects_non_numeric_zip():
    with pytest.raises(ValueError):
        Config(zip="abcde")


def test_config_rejects_short_zip():
    with pytest.raises(ValueError):
        Config(zip="9040")


def test_config_rejects_negative_radius():
    with pytest.raises(ValueError):
        Config(radius_miles=-5)


def test_config_rejects_budget_min_gt_max():
    with pytest.raises(ValueError):
        Config(budget={"min": 20000, "max": 5000})


def test_config_rejects_out_of_range_weight():
    with pytest.raises(ValueError):
        Config(weights={"reliability": -0.1})


def test_config_defaults_are_valid():
    cfg = Config()
    assert cfg.zip == "90405" and cfg.radius_miles == 25


# ---------------------------------------------------------------------------
# Lookup tables are case-insensitive on make AND model — scraped casing
# ("MAZDA"/"ELANTRA"/"camry") must still resolve against canonical table keys.
# ---------------------------------------------------------------------------

def test_mpg_lookup_case_insensitive(tmp_path):
    (tmp_path / "mpg_lookup.csv").write_text(
        "year,make,model,mpg_combined\n2016,Toyota,RAV4,30\n"
    )
    lk = load_lookups(tmp_path)
    fs = score_mpg(Listing(year=2016, make="TOYOTA", model="rav4"), lk, 0.04)
    assert fs.confidence == "real" and fs.raw == 8.0


def test_dimensions_lookup_case_insensitive(tmp_path):
    (tmp_path / "vehicle_dimensions.yaml").write_text(
        yaml.dump([{"make": "Toyota", "model": "RAV4",
                    "year_min": 2015, "year_max": 2018, "length_inches": 179.0}])
    )
    lk = load_lookups(tmp_path)
    fs = score_parking_footprint(Listing(year=2016, make="TOYOTA", model="rav4"), lk, 0.02)
    assert fs.confidence == "real" and fs.raw == 10.0  # < 180"


def test_insurance_lookup_case_insensitive(tmp_path):
    (tmp_path / "insurance_risk.yaml").write_text(
        yaml.dump([{"make": "Toyota", "model": "RAV4",
                    "year_min": 2015, "year_max": 2018, "tier": "low"}])
    )
    lk = load_lookups(tmp_path)
    fs = score_insurance_risk(Listing(year=2016, make="toyota", model="RAV4"), lk, 0.10)
    assert fs.confidence == "real" and fs.raw == 10.0


def test_roof_rack_lookup_case_insensitive(tmp_path):
    (tmp_path / "roof_rack.yaml").write_text(
        yaml.dump([{"make": "Toyota", "model": "RAV4", "status": "oem_rails"}])
    )
    lk = load_lookups(tmp_path)
    fs = score_roof_rack(Listing(make="TOYOTA", model="rav4"), lk, 0.06)
    assert fs.confidence == "real" and fs.raw == 10.0


def test_msrp_lookup_case_insensitive(tmp_path):
    (tmp_path / "msrp_by_make_model.yaml").write_text(
        yaml.dump([{"make": "Mazda", "model": "Mazda3", "msrp": 23000}])
    )
    lk = load_lookups(tmp_path)
    # Empty cohort → MSRP depreciation fallback; the uppercase "MAZDA"/"MAZDA3"
    # scraped casing must still hit the canonical "Mazda"/"Mazda3" entry.
    listing = Listing(year=2018, make="MAZDA", model="MAZDA3",
                      asking_price=12000, mileage=40000)
    fs = score_price_value(listing, [], lk, Config(), 0.18)
    assert "MSRP" in fs.reason or "depreciation" in fs.reason.lower()
