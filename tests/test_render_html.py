"""Tests for render_html.py — M5 HTML dashboard."""
from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path

import pytest

from carfinder.models import Listing
from carfinder.scorer import FactorScore, ScoredListing


# ---------------------------------------------------------------------------
# Helpers (mirrors test_render.py helpers)
# ---------------------------------------------------------------------------

def _make_factor(
    raw: float,
    weight: float,
    confidence: str = "real",
    reason: str = "test",
) -> FactorScore:
    return FactorScore(
        raw=raw,
        weight=weight,
        weighted=raw * weight,
        confidence=confidence,
        reason=reason,
    )


_FULL_BREAKDOWN = {
    "reliability":       _make_factor(8.0, 0.22),
    "price_value":       _make_factor(7.0, 0.20),
    "mileage":           _make_factor(9.0, 0.16),
    "size_class":        _make_factor(10.0, 0.12),
    "parking_footprint": _make_factor(7.0, 0.06),
    "mpg":               _make_factor(6.0, 0.08),
    "drivetrain":        _make_factor(10.0, 0.02),
    "insurance_risk":    _make_factor(6.0, 0.08),
    "roof_rack":         _make_factor(8.0, 0.03),
    "title_status":      _make_factor(10.0, 0.03),
}


def _make_scored(
    *,
    listing_id: str = "test-id-1",
    score: float = 78.5,
    confidence: str = "full",
    make: str = "Toyota",
    model: str = "RAV4",
    year: int = 2018,
    asking_price: float = 9500.0,
    mileage: int = 65000,
    source: str = "craigslist",
    photos: list[str] | None = None,
    last_seen: datetime.datetime | None = None,
) -> ScoredListing:
    listing = Listing(
        id=listing_id,
        source=source,
        source_id=listing_id,
        year=year,
        make=make,
        model=model,
        trim="XLE",
        body_type="SUV",
        drivetrain="AWD",
        mileage=mileage,
        asking_price=asking_price,
        location="Santa Monica, CA",
        photos=photos if photos is not None else [],
        url=f"https://example.com/listing/{listing_id}",
        last_seen=last_seen or datetime.datetime(2026, 5, 20, 10, 0, 0, tzinfo=datetime.timezone.utc),
    )
    return ScoredListing(
        listing=listing,
        score=score,
        score_breakdown=_FULL_BREAKDOWN,
        confidence=confidence,
    )


def _make_scored_list(n: int) -> list[ScoredListing]:
    sources = ["craigslist", "carmax"]
    return [
        _make_scored(
            listing_id=f"listing-{i}",
            score=80.0 - i,
            make=f"Make{i}",
            model=f"Model{i}",
            asking_price=8000.0 + i * 200,
            source=sources[i % 2],
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. Output shape
# ---------------------------------------------------------------------------

def test_render_html_returns_str_with_doctype():
    """Output must be a string starting with <!DOCTYPE html> and ending with </html>."""
    from carfinder.render_html import render_html

    items = _make_scored_list(3)
    out = render_html(items)

    assert isinstance(out, str)
    assert out.startswith("<!DOCTYPE html>")
    assert out.strip().endswith("</html>")


# ---------------------------------------------------------------------------
# 2. All listings present
# ---------------------------------------------------------------------------

def test_render_html_contains_all_listings():
    """Every listing id and asking_price must appear in the output JSON blob."""
    from carfinder.render_html import render_html

    n = 5
    items = _make_scored_list(n)
    out = render_html(items)

    for item in items:
        assert item.listing.id in out, f"id {item.listing.id!r} not found in HTML"
        price_str = str(int(item.listing.asking_price))
        assert price_str in out, f"price {price_str} not found in HTML"


# ---------------------------------------------------------------------------
# 3. Chart.js inlined
# ---------------------------------------------------------------------------

def test_render_html_includes_chart_js_inline():
    """Chart.js must be inlined in the output (not loaded from CDN)."""
    from carfinder.render_html import render_html

    out = render_html(_make_scored_list(2))
    # CDN src tag should be gone — Chart.js is now inlined
    assert "cdn.jsdelivr.net/npm/chart.js" not in out
    # The inlined build always starts with a comment containing "Chart.js"
    assert "Chart.js" in out


# ---------------------------------------------------------------------------
# 4. Photo URLs embedded
# ---------------------------------------------------------------------------

def test_render_html_embeds_photos():
    """Listings with photos must have their photo URLs in the JSON data blob."""
    from carfinder.render_html import render_html

    photos = [
        "https://images.craigslist.org/photo1.jpg",
        "https://images.craigslist.org/photo2.jpg",
    ]
    items = [_make_scored(photos=photos)]
    out = render_html(items)

    for url in photos:
        assert url in out, f"photo URL {url!r} not in HTML output"


# ---------------------------------------------------------------------------
# 5. No crash on listings without photos; placeholder rendered
# ---------------------------------------------------------------------------

def test_render_html_handles_listings_without_photos():
    """Listings with empty photo list must not crash and render a placeholder."""
    from carfinder.render_html import render_html

    items = [_make_scored(photos=[])]
    # Must not raise
    out = render_html(items)

    assert "<!DOCTYPE html>" in out
    # placeholder text is in the JS template
    assert "no photo" in out or "photo-placeholder" in out


# ---------------------------------------------------------------------------
# 6. Score breakdown factors in JSON blob
# ---------------------------------------------------------------------------

def test_render_html_embeds_score_breakdown():
    """All 10 factor keys must appear in the JSON-encoded LISTINGS blob."""
    from carfinder.render_html import render_html

    factor_keys = [
        "reliability", "price_value", "mileage", "size_class",
        "parking_footprint", "mpg", "drivetrain", "insurance_risk",
        "roof_rack", "title_status",
    ]

    items = _make_scored_list(2)
    out = render_html(items)

    # Extract the LISTINGS JSON from the script tag
    marker = "var LISTINGS = "
    assert marker in out
    start = out.index(marker) + len(marker)
    end = out.index(";\n", start)
    listings_json = out[start:end]
    data = json.loads(listings_json)

    assert len(data) == 2
    for entry in data:
        factor_names_in_entry = {f["key"] for f in entry["factors"]}
        for key in factor_keys:
            assert key in factor_names_in_entry, (
                f"Factor {key!r} missing from listing {entry['id']!r}"
            )


# ---------------------------------------------------------------------------
# 7. export_html_to_vault writes file
# ---------------------------------------------------------------------------

def test_export_html_to_vault_writes_file():
    """export_html_to_vault must write a shortlist-YYYY-MM-DD.html file."""
    import datetime

    from carfinder.config import load_config
    from carfinder.render import export_html_to_vault
    from carfinder.render_html import render_html

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["CARFINDER_VAULT_PATH"] = tmpdir
        try:
            cfg = load_config()
            items = _make_scored_list(3)
            html = render_html(items, config=cfg)
            out_path = export_html_to_vault(html, cfg)

            assert out_path.exists(), f"Expected {out_path} to exist"
            today = datetime.date.today().isoformat()
            assert out_path.name == f"shortlist-{today}.html"
            content = out_path.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
        finally:
            del os.environ["CARFINDER_VAULT_PATH"]


# ---------------------------------------------------------------------------
# 8. --format both writes both files
# ---------------------------------------------------------------------------

def test_export_both_writes_both_files():
    """export_markdown_to_vault and export_html_to_vault together produce both files."""
    import datetime

    from carfinder.config import load_config
    from carfinder.render import export_html_to_vault, export_markdown_to_vault, render_markdown
    from carfinder.render_html import render_html

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["CARFINDER_VAULT_PATH"] = tmpdir
        try:
            cfg = load_config()
            items = _make_scored_list(3)

            md = render_markdown(items, top_n=len(items))
            md_path = export_markdown_to_vault(md, cfg)

            html = render_html(items, config=cfg)
            html_path = export_html_to_vault(html, cfg)

            today = datetime.date.today().isoformat()
            assert md_path.exists(), "Markdown file not written"
            assert html_path.exists(), "HTML file not written"
            assert md_path.name == f"shortlist-{today}.md"
            assert html_path.name == f"shortlist-{today}.html"
        finally:
            del os.environ["CARFINDER_VAULT_PATH"]


# ---------------------------------------------------------------------------
# Bonus: output size sanity check
# ---------------------------------------------------------------------------

def test_render_html_output_under_600kb():
    """30-listing output should stay under 600 KB (includes ~200 KB inlined Chart.js)."""
    from carfinder.render_html import render_html

    items = _make_scored_list(30)
    out = render_html(items)
    size_kb = len(out.encode("utf-8")) / 1024
    assert size_kb < 600, f"HTML output is {size_kb:.1f} KB, expected < 600 KB"


# ---------------------------------------------------------------------------
# XSS: </script> in listing data must not break out of the script tag
# ---------------------------------------------------------------------------


def test_render_html_escapes_closing_script_tag_in_json():
    """String fields containing </script> must be escaped so they cannot break
    out of the embedded <script> block (XSS regression test).

    The payload is injected into ``url``, which is serialised directly into the
    LISTINGS JSON blob by ``_listing_to_dict``.
    """
    from carfinder.render_html import render_html

    xss_payload = "</script><script>alert(1)</script>"
    # url is included verbatim in the JSON blob via _listing_to_dict
    listing = _make_scored(listing_id="xss-test")
    listing.listing.url = xss_payload

    out = render_html([listing])

    # The raw payload must NOT appear verbatim in the rendered output.
    assert xss_payload not in out, "XSS payload appeared unescaped in rendered HTML"
    # The escaped form must be present, confirming the fix is applied.
    assert "<\\/script>" in out, "Expected escaped form <\\/script> not found in rendered HTML"
