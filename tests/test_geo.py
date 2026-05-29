"""Tests for geo.py — haversine distance + offline zip/city resolution."""
from __future__ import annotations

from carfinder.geo import (
    _SANTA_MONICA,
    distance_from_location,
    haversine_miles,
    home_coords,
)


# ---------------------------------------------------------------------------
# haversine_miles
# ---------------------------------------------------------------------------

def test_haversine_zero_distance_to_self():
    assert haversine_miles(34.0, -118.0, 34.0, -118.0) == 0.0


def test_haversine_known_distance_sm_to_downtown():
    # Santa Monica (90405) → Downtown LA (90012) is roughly 13–15 miles.
    sm = (34.0025, -118.4751)
    dt = (34.0561, -118.2390)
    d = haversine_miles(*sm, *dt)
    assert 12.0 < d < 16.0, f"expected ~14 mi, got {d}"


def test_haversine_is_symmetric():
    a = (34.0, -118.4)
    b = (33.8, -118.1)
    assert abs(haversine_miles(*a, *b) - haversine_miles(*b, *a)) < 1e-6


# ---------------------------------------------------------------------------
# home_coords
# ---------------------------------------------------------------------------

def test_home_coords_known_zip():
    assert home_coords("90405") == (34.0025, -118.4751)


def test_home_coords_unknown_zip_defaults_to_santa_monica():
    assert home_coords("00000") == _SANTA_MONICA


def test_home_coords_strips_whitespace():
    assert home_coords("  90405 ") == (34.0025, -118.4751)


# ---------------------------------------------------------------------------
# distance_from_location
# ---------------------------------------------------------------------------

def test_distance_none_for_empty_input():
    assert distance_from_location(None, "90405") is None
    assert distance_from_location("", "90405") is None


def test_distance_from_zip_code():
    d = distance_from_location("90012", "90405")  # downtown from SM
    assert d is not None and 12.0 < d < 16.0


def test_distance_from_zip_to_itself_is_zero():
    assert distance_from_location("90405", "90405") == 0.0


def test_distance_unknown_zip_returns_none():
    assert distance_from_location("00000", "90405") is None


def test_distance_from_city_name_case_insensitive():
    lower = distance_from_location("santa monica", "90405")
    upper = distance_from_location("SANTA MONICA", "90405")
    assert lower is not None
    assert lower == upper


def test_distance_strips_state_suffix():
    a = distance_from_location("Culver City", "90405")
    b = distance_from_location("Culver City, CA", "90405")
    c = distance_from_location("Culver City, California", "90405")
    assert a is not None
    assert a == b == c


def test_distance_unknown_city_returns_none():
    assert distance_from_location("Atlantis", "90405") is None
