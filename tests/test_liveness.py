"""Tests for sold/gone detection (fetchers/liveness.py)."""
from __future__ import annotations

import pytest

from carfinder.fetchers.liveness import detect_sold


@pytest.mark.parametrize("status", [404, 410])
def test_gone_status_codes_are_sold(status):
    assert detect_sold(status, "", "craigslist") is True


def test_craigslist_deleted_marker():
    html = "<html><body>This posting has been deleted by its author.</body></html>"
    assert detect_sold(200, html, "craigslist") is True


def test_craigslist_flagged_marker():
    assert detect_sold(200, "This posting has been flagged for removal", "craigslist") is True


def test_carmax_no_longer_available():
    assert detect_sold(200, "Sorry, this car is no longer available.", "carmax") is True


def test_live_page_is_not_sold():
    html = "<html><body>2016 Toyota RAV4 XLE — $15,998. Schedule a test drive.</body></html>"
    assert detect_sold(200, html, "carmax") is False


def test_transient_errors_are_not_sold():
    # 5xx / blocked / unknown must never be treated as sold.
    assert detect_sold(500, "Internal Server Error", "craigslist") is False
    assert detect_sold(403, "Forbidden", "carmax") is False
    assert detect_sold(None, "", "craigslist") is False
