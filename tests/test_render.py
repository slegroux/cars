"""Tests for render.py — M4."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path


from carfinder.models import Listing
from carfinder.scorer import FactorScore, ScoredListing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_factor(raw: float, weight: float, confidence: str = "real", reason: str = "test") -> FactorScore:
    return FactorScore(raw=raw, weight=weight, weighted=raw * weight, confidence=confidence, reason=reason)


def _make_scored(
    score: float,
    confidence: str = "full",
    mileage: int = 65000,
    price: float = 9000.0,
    year: int = 2018,
    make: str = "Toyota",
    model: str = "RAV4",
    trim: str | None = "XLE",
    photos: list[str] | None = None,
    source: str = "craigslist",
    location: str = "Santa Monica, CA",
) -> ScoredListing:
    listing = Listing(
        id="test-id",
        source=source,
        source_id="src-1",
        year=year,
        make=make,
        model=model,
        trim=trim,
        mileage=mileage,
        asking_price=price,
        location=location,
        photos=photos or [],
        url="https://example.com/listing/1",
    )
    breakdown = {
        "reliability": _make_factor(8.0, 0.22),
        "price_value": _make_factor(7.0, 0.20),
        "mileage": _make_factor(9.0, 0.16),
        "size_class": _make_factor(10.0, 0.12),
        "parking_footprint": _make_factor(7.0, 0.06),
        "mpg": _make_factor(6.0, 0.08),
        "drivetrain": _make_factor(10.0, 0.02),
        "insurance_risk": _make_factor(6.0, 0.08),
        "roof_rack": _make_factor(8.0, 0.03),
        "title_status": _make_factor(10.0, 0.03),
    }
    return ScoredListing(listing=listing, score=score, score_breakdown=breakdown, confidence=confidence)


def _make_scored_list(n: int, base_score: float = 80.0) -> list[ScoredListing]:
    items = []
    for i in range(n):
        items.append(_make_scored(score=base_score - i, make=f"Make{i}", model=f"Model{i}"))
    return items


# ---------------------------------------------------------------------------
# render_table tests
# ---------------------------------------------------------------------------

def test_render_table_filters_top_n():
    from carfinder.render import render_table
    items = _make_scored_list(20)
    table = render_table(items, top_n=5)
    assert table.row_count == 5


def test_render_table_filters_min_score():
    from carfinder.render import render_table
    items = [_make_scored(score=s) for s in [90.0, 75.0, 55.0, 40.0]]
    table = render_table(items, min_score=60.0)
    assert table.row_count == 2


def test_render_table_shows_full_confidence_no_prefix():
    from rich.console import Console
    from io import StringIO
    from carfinder.render import render_table

    items = [_make_scored(score=87.3, confidence="full")]
    console = Console(file=StringIO(), highlight=False, markup=False, width=200)
    console.print(render_table(items))
    output = console.file.getvalue()
    assert "87.3" in output
    # Must NOT have ~ prefix for full confidence
    assert "~87.3" not in output


def test_render_table_shows_partial_confidence_tilde():
    from rich.console import Console
    from io import StringIO
    from carfinder.render import render_table

    items = [_make_scored(score=82.1, confidence="partial")]
    console = Console(file=StringIO(), highlight=False, markup=False, width=200)
    console.print(render_table(items))
    output = console.file.getvalue()
    assert "~82.1" in output


def test_render_table_shows_low_confidence_tilde_star():
    from rich.console import Console
    from io import StringIO
    from carfinder.render import render_table

    items = [_make_scored(score=71.4, confidence="low")]
    console = Console(file=StringIO(), highlight=False, markup=False, width=200)
    console.print(render_table(items))
    output = console.file.getvalue()
    assert "~71.4*" in output


# ---------------------------------------------------------------------------
# render_markdown tests
# ---------------------------------------------------------------------------

def test_render_markdown_has_yaml_frontmatter():
    from carfinder.render import render_markdown
    items = _make_scored_list(3)
    md = render_markdown(items, top_n=3)
    assert md.startswith("---\ntitle:")
    # Must have closing ---
    lines = md.splitlines()
    closing = [line for line in lines[1:] if line.strip() == "---"]
    assert len(closing) >= 1


def test_render_markdown_embeds_first_n_photos():
    from carfinder.render import render_markdown
    photos = [f"https://example.com/photo{i}.jpg" for i in range(5)]
    items = [_make_scored(score=80.0, photos=photos)]
    md = render_markdown(items, top_n=1, photo_thumbnails=3)
    embed_lines = [line for line in md.splitlines() if line.startswith("![")]
    assert len(embed_lines) == 3


def test_render_markdown_includes_score_breakdown_table():
    from carfinder.render import render_markdown
    items = _make_scored_list(2)
    md = render_markdown(items, top_n=2)
    # Each listing has 10 factor rows in its breakdown table
    factor_rows = [line for line in md.splitlines() if line.startswith("| reliability") or
                   line.startswith("| price_value") or line.startswith("| mileage") or
                   line.startswith("| size_class")]
    # 2 listings × at least 4 checked factors = at least 8 rows
    assert len(factor_rows) >= 8


def test_render_markdown_handles_listings_without_photos():
    from carfinder.render import render_markdown
    # photos=None case via empty list default
    item_no_photos = _make_scored(score=75.0, photos=[])
    item_none_photos = _make_scored(score=70.0, photos=None)
    items = [item_no_photos, item_none_photos]
    # Should not raise
    md = render_markdown(items, top_n=2)
    # No photo embeds
    embed_lines = [line for line in md.splitlines() if line.startswith("![")]
    assert len(embed_lines) == 0


# ---------------------------------------------------------------------------
# export_to_vault tests
# ---------------------------------------------------------------------------

def test_export_to_vault_writes_file():
    from carfinder.render import export_to_vault, render_markdown
    from carfinder.config import load_config

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["CARFINDER_VAULT_PATH"] = tmpdir
        try:
            cfg = load_config()
            items = _make_scored_list(3)
            md = render_markdown(items, top_n=3)
            out_path = export_to_vault(md, cfg)
            assert out_path.exists()
            content = out_path.read_text()
            assert content.startswith("---\ntitle:")
        finally:
            del os.environ["CARFINDER_VAULT_PATH"]


def test_export_to_vault_creates_parent_dir():
    from carfinder.render import export_to_vault, render_markdown
    from carfinder.config import load_config

    with tempfile.TemporaryDirectory() as tmpdir:
        nested = os.path.join(tmpdir, "new", "nested", "vault")
        os.environ["CARFINDER_VAULT_PATH"] = nested
        try:
            cfg = load_config()
            items = _make_scored_list(2)
            md = render_markdown(items, top_n=2)
            out_path = export_to_vault(md, cfg)
            assert Path(nested).exists()
            assert out_path.exists()
        finally:
            del os.environ["CARFINDER_VAULT_PATH"]


# ---------------------------------------------------------------------------
# render_stats tests
# ---------------------------------------------------------------------------

def test_stats_handles_empty_db():
    from carfinder.render import render_stats

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Must not raise even with empty listing list and empty db
    result = render_stats([], conn)
    assert result is not None
    conn.close()
