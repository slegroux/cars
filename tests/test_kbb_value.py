"""Tests for the KBB valuation parser (fetchers/kbb_value.py)."""
from __future__ import annotations

import json

from carfinder.fetchers.kbb_value import cache_key, parse_fair_values


def _next_data_html(payload: dict) -> str:
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


def test_parse_fair_values_extracts_trims_and_median_default():
    html = _next_data_html({
        "props": {"pageProps": {"result": {
            "trimsData": [
                {"name": "LE Sport Utility 4D", "fairMarketPriceLow": 14000, "fairMarketPriceHigh": 14000},
                {"name": "XLE Sport Utility 4D", "fairMarketPriceLow": 16000, "fairMarketPriceHigh": 16000},
                {"name": "Limited Sport Utility 4D", "fairMarketPriceLow": 18000, "fairMarketPriceHigh": 18000},
            ],
            "pricingData": {"fairMarketPrice": {"ymmtAverage": 14000}},
        }}}
    })
    vals = parse_fair_values(html)
    assert vals is not None
    assert vals["default"] == 16000  # median of the three trims
    assert "trims" in vals
    # trim names are normalised (lowercased, spaces removed)
    assert any(k.startswith("xle") for k in vals["trims"])


def test_parse_fair_values_falls_back_to_average_without_trims():
    html = _next_data_html({
        "props": {"x": {"pricingData": {"fairMarketPrice": {"ymmtAverage": 12500}}}}
    })
    vals = parse_fair_values(html)
    assert vals is not None
    assert vals["default"] == 12500
    assert vals["trims"] == {}


def test_parse_fair_values_returns_none_when_absent():
    assert parse_fair_values("<html><body>no next data</body></html>") is None
    assert parse_fair_values(_next_data_html({"props": {"unrelated": 1}})) is None


def _with_canonical(href: str, payload: dict) -> str:
    return (
        f'<html><head><link rel="canonical" href="{href}"/></head><body>'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


_PAYLOAD = {"props": {"r": {"trimsData": [
    {"name": "Base", "fairMarketPriceLow": 12000, "fairMarketPriceHigh": 12000},
]}}}


def test_year_guard_rejects_wrong_year_landing_page():
    # KBB served the model landing page (canonical has no /year/) — must reject.
    html = _with_canonical("https://www.kbb.com/hyundai/sonata-hybrid/", _PAYLOAD)
    assert parse_fair_values(html, expected_year=2015) is None
    # No expected_year → no guard, parses fine.
    assert parse_fair_values(html) is not None


def test_year_guard_accepts_matching_year():
    html = _with_canonical("https://www.kbb.com/toyota/rav4/2016/", _PAYLOAD)
    vals = parse_fair_values(html, expected_year=2016)
    assert vals is not None and vals["default"] == 12000


def test_parse_extracts_evox_og_image():
    html = (
        '<html><head>'
        '<link rel="canonical" href="https://www.kbb.com/toyota/rav4/2016/"/>'
        '<meta property="og:image" content="https://file.kelleybluebookimages.com/kbb/base/evox/CP/10921/2016-Toyota-RAV4-front.png"/>'
        '</head><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"r": {"trimsData": [
            {"name": "LE", "fairMarketPriceLow": 14000, "fairMarketPriceHigh": 14000}]}}})
        + "</script></body></html>"
    )
    vals = parse_fair_values(html, expected_year=2016)
    assert vals is not None
    assert vals["image"] and "2016-Toyota-RAV4" in vals["image"]


def test_parse_ignores_non_evox_og_image():
    # A generic social-share image (not an EVOX studio render) is not a car photo.
    html = (
        '<html><head>'
        '<link rel="canonical" href="https://www.kbb.com/toyota/rav4/2016/"/>'
        '<meta property="og:image" content="https://www.kbb.com/assets/social-card.png"/>'
        '</head><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"r": {"trimsData": [
            {"name": "LE", "fairMarketPriceLow": 14000, "fairMarketPriceHigh": 14000}]}}})
        + "</script></body></html>"
    )
    vals = parse_fair_values(html, expected_year=2016)
    assert vals is not None and vals["image"] is None


def test_cache_key_is_normalised():
    assert cache_key("Toyota", "RAV 4", 2016) == "toyota|rav4|2016"
    assert cache_key("toyota", "rav4", 2016) == cache_key("TOYOTA", "RAV4", 2016)
