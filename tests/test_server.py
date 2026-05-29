"""Tests for server.py — local dashboard HTTP API (GET / import / delete)."""
from __future__ import annotations

import threading
import types
from pathlib import Path

import httpx
import pytest

from carfinder.config import Config
from carfinder.db import init_db, upsert_listing
from carfinder.models import Listing
from carfinder.server import _make_handler, run_server


# ---------------------------------------------------------------------------
# Integration: a real loopback server on an ephemeral port
# ---------------------------------------------------------------------------

@pytest.fixture
def server(tmp_path):
    db_path = tmp_path / "listings.db"
    srv, _ = run_server(Config(), db_path, port=0)
    port = srv.server_port
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield types.SimpleNamespace(
            base=f"http://localhost:{port}", port=port, db_path=db_path
        )
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def test_get_index_returns_html(server):
    r = httpx.get(server.base + "/", timeout=5)
    assert r.status_code == 200
    assert "<!DOCTYPE html>" in r.text


def test_get_unknown_path_404(server):
    r = httpx.get(server.base + "/does-not-exist", timeout=5)
    assert r.status_code == 404


def test_import_valid_creates_manual_listing(server):
    r = httpx.post(
        server.base + "/api/import",
        json={"make": "Toyota", "model": "RAV4", "year": 2018, "price": "9500"},
        timeout=5,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["id"]


def test_import_missing_fields_returns_400(server):
    r = httpx.post(server.base + "/api/import", json={"make": "Toyota"}, timeout=5)
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_import_bad_year_returns_400(server):
    r = httpx.post(
        server.base + "/api/import",
        json={"make": "Toyota", "model": "RAV4", "year": "nope"},
        timeout=5,
    )
    assert r.status_code == 400


def test_import_non_http_url_rejected(server):
    r = httpx.post(
        server.base + "/api/import",
        json={"make": "T", "model": "R", "year": 2018, "url": "javascript:alert(1)"},
        timeout=5,
    )
    assert r.status_code == 400


def test_cross_origin_post_refused(server):
    r = httpx.post(
        server.base + "/api/import",
        headers={"Origin": "http://evil.com"},
        json={"make": "Toyota", "model": "RAV4", "year": 2018},
        timeout=5,
    )
    assert r.status_code == 403


def test_same_origin_post_allowed(server):
    r = httpx.post(
        server.base + "/api/import",
        headers={"Origin": f"http://localhost:{server.port}"},
        json={"make": "Toyota", "model": "Camry", "year": 2019},
        timeout=5,
    )
    assert r.status_code == 200


def test_delete_manual_round_trip(server):
    imp = httpx.post(
        server.base + "/api/import",
        json={"make": "Honda", "model": "Civic", "year": 2017},
        timeout=5,
    ).json()
    r = httpx.post(server.base + "/api/delete/" + imp["id"], timeout=5)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_delete_nonexistent_returns_404(server):
    r = httpx.post(server.base + "/api/delete/nope-xyz", timeout=5)
    assert r.status_code == 404


def test_delete_scraped_listing_refused(server):
    # A scraped (non-manual) row must not be deletable via the API.
    conn = init_db(server.db_path)
    upsert_listing(
        conn,
        Listing(id="craigslist:1", source="craigslist", source_id="1",
                make="Toyota", model="RAV4", year=2018),
    )
    conn.close()
    r = httpx.post(server.base + "/api/delete/craigslist:1", timeout=5)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Unit tests for the security guards (no socket needed)
# ---------------------------------------------------------------------------

def _bare_handler(port: int = 8765):
    Handler = _make_handler(Config(), Path("/tmp/unused.db"))
    h = Handler.__new__(Handler)  # bypass __init__ (needs a live socket)
    h.server = types.SimpleNamespace(server_port=port)
    return h


@pytest.mark.parametrize(
    "origin,expected",
    [
        (None, True),                              # no Origin (curl) → allowed
        ("http://localhost:8765", True),
        ("http://127.0.0.1:8765", True),
        ("http://localhost:8765/dashboard", True),  # Referer with a path
        ("http://evil.com", False),
        ("http://localhost:8765.evil.com", False),  # the startswith() bypass
        ("https://localhost:8765", False),          # wrong scheme
        ("http://localhost:9999", False),           # wrong port
    ],
)
def test_origin_ok(origin, expected):
    h = _bare_handler(8765)
    h.headers = {"Origin": origin} if origin is not None else {}
    assert h._origin_ok() is expected


def test_read_body_rejects_oversized_content_length():
    h = _bare_handler()
    h.headers = {"Content-Length": str(2_000_000)}
    with pytest.raises(ValueError):
        h._read_body()


def test_read_body_empty_returns_empty_dict():
    h = _bare_handler()
    h.headers = {}
    assert h._read_body() == {}


def test_read_body_malformed_length_returns_empty_dict():
    h = _bare_handler()
    h.headers = {"Content-Length": "garbage"}
    assert h._read_body() == {}
