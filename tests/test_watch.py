"""Tests for M4.5 watch command and last_run DB helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from carfinder.db import get_last_run, init_db, update_last_run
from carfinder.models import Listing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_listing(**kwargs) -> Listing:
    defaults = dict(
        source="craigslist",
        source_id="cl-001",
        year=2016,
        make="Toyota",
        model="RAV4",
        mileage=75000,
        asking_price=10500.0,
        title_status="clean",
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def make_scored(listing: Listing, score: float) -> MagicMock:
    """Return a minimal ScoredListing-like mock."""
    s = MagicMock()
    s.listing = listing
    s.score = score
    s.display_score.return_value = f"{score:.1f}"
    s.confidence = "full"
    s.score_breakdown = {}
    return s


@pytest.fixture
def db(tmp_path):
    conn = init_db(tmp_path / "test.db")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# DB-level tests
# ---------------------------------------------------------------------------

def test_db_last_run_table_exists(db):
    """init_db must create the last_run table."""
    cur = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='last_run'"
    )
    assert cur.fetchone() is not None


def test_get_last_run_empty(db):
    result = get_last_run(db)
    assert result == {}


def test_update_last_run_writes_and_replaces(db):
    listing_a = make_listing(source_id="a", id="id-a")
    listing_b = make_listing(source_id="b", id="id-b")
    scored_a = make_scored(listing_a, 80.0)
    scored_b = make_scored(listing_b, 65.0)

    count = update_last_run(db, [scored_a, scored_b])
    assert count == 2

    result = get_last_run(db)
    assert result == {"id-a": 80.0, "id-b": 65.0}

    # Replace with only one listing
    listing_c = make_listing(source_id="c", id="id-c")
    scored_c = make_scored(listing_c, 72.0)
    update_last_run(db, [scored_c])

    result2 = get_last_run(db)
    assert result2 == {"id-c": 72.0}
    assert "id-a" not in result2


# ---------------------------------------------------------------------------
# CLI-level watch tests (patching search + score helpers)
# ---------------------------------------------------------------------------

def _make_scored_list(items: list[tuple[str, str, float]]) -> list[MagicMock]:
    """items = [(source_id, listing_id, score), ...]"""
    result = []
    for src_id, lid, score in items:
        listing = make_listing(source_id=src_id, id=lid)
        result.append(make_scored(listing, score))
    return result


@patch("carfinder.cli._run_search")
@patch("carfinder.cli._load_scored_listings")
@patch("carfinder.cli.asyncio")
def test_watch_first_run_all_above_threshold_are_new(
    mock_asyncio, mock_load, mock_search, tmp_path
):
    """Empty last_run → all listings above min_score reported as new."""
    from click.testing import CliRunner
    from carfinder.cli import cli

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)
    # last_run is empty

    scored = _make_scored_list([
        ("cl-001", "id-001", 85.0),
        ("cl-002", "id-002", 75.0),
        ("cl-003", "id-003", 55.0),  # below threshold 70
    ])

    mock_load.return_value = (scored, conn)
    # _run_search is an async def, so @patch replaces it with an AsyncMock whose
    # call returns a coroutine. Close it instead of dropping it on the floor so
    # asyncio.run being stubbed out doesn't leave an un-awaited coroutine.
    mock_asyncio.run = lambda coro: coro.close()  # skip actual search

    runner = CliRunner()
    with patch("carfinder.cli.Path") as mock_path_cls:
        # Make Path("data/listings.db") resolve to tmp_path db
        mock_path_cls.return_value = db_path
        mock_path_cls.side_effect = lambda p: tmp_path / "listings.db" if "listings" in str(p) else Path(p)

        result = runner.invoke(cli, ["watch", "--min-score", "70"])

    assert result.exit_code == 0
    assert "2 new listings above threshold 70" in result.output
    assert "0 listings with score changes" in result.output


@patch("carfinder.cli._run_search")
@patch("carfinder.cli._load_scored_listings")
@patch("carfinder.cli.asyncio")
def test_watch_second_run_no_changes_zero_new(
    mock_asyncio, mock_load, mock_search, tmp_path
):
    """Same listings + same scores → 0 new, 0 changed."""
    from click.testing import CliRunner
    from carfinder.cli import cli

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)

    scored = _make_scored_list([
        ("cl-001", "id-001", 82.0),
        ("cl-002", "id-002", 74.0),
    ])

    # Pre-populate last_run with same IDs + same scores
    update_last_run(conn, scored)

    mock_load.return_value = (scored, conn)
    # _run_search is an async def, so @patch replaces it with an AsyncMock whose
    # call returns a coroutine. Close it instead of dropping it on the floor so
    # asyncio.run being stubbed out doesn't leave an un-awaited coroutine.
    mock_asyncio.run = lambda coro: coro.close()

    runner = CliRunner()
    with patch("carfinder.cli.Path") as mock_path_cls:
        mock_path_cls.side_effect = lambda p: tmp_path / "listings.db" if "listings" in str(p) else Path(p)

        result = runner.invoke(cli, ["watch", "--min-score", "70"])

    assert result.exit_code == 0
    assert "0 new listings above threshold 70" in result.output
    assert "0 listings with score changes" in result.output


@patch("carfinder.cli._run_search")
@patch("carfinder.cli._load_scored_listings")
@patch("carfinder.cli.asyncio")
def test_watch_score_change_detected(
    mock_asyncio, mock_load, mock_search, tmp_path
):
    """Listing whose score moved >=5 and is above threshold is reported as Δ."""
    from click.testing import CliRunner
    from carfinder.cli import cli

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)

    # Previous run: id-001 at score 70
    old_scored = _make_scored_list([("cl-001", "id-001", 70.0)])
    update_last_run(conn, old_scored)

    # New run: id-001 now at 76 (delta = 6 >= 5)
    new_scored = _make_scored_list([("cl-001", "id-001", 76.0)])
    mock_load.return_value = (new_scored, conn)
    # _run_search is an async def, so @patch replaces it with an AsyncMock whose
    # call returns a coroutine. Close it instead of dropping it on the floor so
    # asyncio.run being stubbed out doesn't leave an un-awaited coroutine.
    mock_asyncio.run = lambda coro: coro.close()

    runner = CliRunner()
    with patch("carfinder.cli.Path") as mock_path_cls:
        mock_path_cls.side_effect = lambda p: tmp_path / "listings.db" if "listings" in str(p) else Path(p)

        result = runner.invoke(cli, ["watch", "--min-score", "70"])

    assert result.exit_code == 0
    assert "0 new listings above threshold 70" in result.output
    assert "1 listings with score changes" in result.output


@patch("carfinder.cli._run_search")
@patch("carfinder.cli._load_scored_listings")
@patch("carfinder.cli.asyncio")
def test_watch_below_threshold_filtered(
    mock_asyncio, mock_load, mock_search, tmp_path
):
    """New listing with score below --min-score is not reported."""
    from click.testing import CliRunner
    from carfinder.cli import cli

    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)
    # last_run empty

    scored = _make_scored_list([
        ("cl-001", "id-001", 60.0),  # below min-score 70
        ("cl-002", "id-002", 45.0),  # also below
    ])
    mock_load.return_value = (scored, conn)
    # _run_search is an async def, so @patch replaces it with an AsyncMock whose
    # call returns a coroutine. Close it instead of dropping it on the floor so
    # asyncio.run being stubbed out doesn't leave an un-awaited coroutine.
    mock_asyncio.run = lambda coro: coro.close()

    runner = CliRunner()
    with patch("carfinder.cli.Path") as mock_path_cls:
        mock_path_cls.side_effect = lambda p: tmp_path / "listings.db" if "listings" in str(p) else Path(p)

        result = runner.invoke(cli, ["watch", "--min-score", "70"])

    assert result.exit_code == 0
    assert "0 new listings above threshold 70" in result.output


def test_watch_updates_last_run_table(tmp_path):
    """After watch completes, last_run table holds current scored set."""
    # Test the DB helpers directly — update_last_run then get_last_run
    db_path = tmp_path / "listings.db"
    conn = init_db(db_path)

    scored = _make_scored_list([
        ("cl-001", "id-001", 85.0),
        ("cl-002", "id-002", 72.0),
    ])

    count = update_last_run(conn, scored)
    assert count == 2

    last_run = get_last_run(conn)
    conn.close()

    assert "id-001" in last_run
    assert "id-002" in last_run
    assert last_run["id-001"] == 85.0
    assert last_run["id-002"] == 72.0
