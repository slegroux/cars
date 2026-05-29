"""Local HTTP server — serves the dashboard and handles import/delete via REST API."""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from carfinder.config import Config

logger = logging.getLogger(__name__)


def _make_handler(config: "Config", db_path: Path):
    """Return a request-handler class bound to config and db_path."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # silence default access log
            logger.debug(fmt, *args)

        # ── Helpers ────────────────────────────────────────────────────────
        def _json(self, data: object, status: int = 200) -> None:
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _origin_ok(self) -> bool:
            """Reject cross-origin state-changing requests (CSRF guard).

            The dashboard is served same-origin, so legitimate POSTs carry an
            Origin/Referer pointing back at this loopback server. Anything else
            (a malicious site the user happens to be visiting) is refused.
            """
            origin = self.headers.get("Origin") or self.headers.get("Referer")
            if not origin:
                return True  # non-browser client (curl); not a CSRF vector
            # Parse the URL and compare host + port exactly. A naive
            # startswith() check would accept e.g. "http://localhost:8765.evil.com".
            # Accessing .port can itself raise ValueError for a malformed
            # authority (e.g. that same payload), so guard the whole read.
            try:
                parsed = urlparse(origin)
                port = parsed.port
            except ValueError:
                return False
            return (
                parsed.scheme == "http"
                and parsed.hostname in ("localhost", "127.0.0.1")
                and port == self.server.server_port
            )

        def _html(self, html: str) -> None:
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # Cap request bodies so a malicious/huge Content-Length can't exhaust
        # memory. 1 MB is far more than any single manual listing needs.
        _MAX_BODY_BYTES = 1_000_000

        def _read_body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                length = 0
            if length <= 0:
                return {}
            if length > self._MAX_BODY_BYTES:
                raise ValueError("request body exceeds maximum allowed size")
            raw = self.rfile.read(length)
            return json.loads(raw) if raw else {}

        # ── GET ────────────────────────────────────────────────────────────
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                from carfinder.service import load_scored_listings
                from carfinder.render_html import render_html

                scored, conn = load_scored_listings(config)
                conn.close()
                self._html(render_html(scored, config=config))
            else:
                self.send_response(404)
                self.end_headers()

        # ── POST ───────────────────────────────────────────────────────────
        def do_POST(self) -> None:
            if not self._origin_ok():
                self._json({"ok": False, "error": "cross-origin request refused"}, 403)
                return
            if self.path == "/api/import":
                self._handle_import()
            elif self.path.startswith("/api/delete/"):
                listing_id = self.path.removeprefix("/api/delete/")
                self._handle_delete(listing_id)
            else:
                self.send_response(404)
                self.end_headers()

        # ── Import handler ─────────────────────────────────────────────────
        def _handle_import(self) -> None:
            try:
                data = self._read_body()
            except (json.JSONDecodeError, ValueError):
                self._json({"ok": False, "error": "Invalid JSON"}, 400)
                return

            make = (data.get("make") or "").strip()
            model = (data.get("model") or "").strip()
            year_raw = data.get("year")

            if not make or not model or not year_raw:
                self._json({"ok": False, "error": "make, model, year are required"}, 400)
                return

            try:
                year = int(str(year_raw).strip())
            except ValueError:
                self._json({"ok": False, "error": "year must be a number"}, 400)
                return

            from carfinder.db import init_db, upsert_listing
            from carfinder.importer import _source_id_from_fields, _source_id_from_url
            from carfinder.models import Listing

            url = (data.get("url") or "").strip() or None
            if url and not url.lower().startswith(("http://", "https://")):
                self._json({"ok": False, "error": "url must be http(s)"}, 400)
                return
            mileage = _safe_int(data.get("mileage"))
            source_id = _source_id_from_url(url) if url else _source_id_from_fields(make, model, year, mileage)

            listing = Listing(
                id=source_id,
                source="manual",
                source_id=source_id,
                url=url,
                make=make,
                model=model,
                year=year,
                trim=(data.get("trim") or "").strip() or None,
                body_type=(data.get("body_type") or "").strip() or None,
                mileage=mileage,
                asking_price=_safe_float(data.get("price")),
                location=(data.get("location") or "").strip() or None,
                seller_type=(data.get("seller_type") or "private").strip(),
                description=(data.get("notes") or "").strip() or None,
            )

            import sqlite3
            from contextlib import closing

            try:
                with closing(init_db(db_path)) as conn:
                    lid = upsert_listing(conn, listing)
                    conn.commit()
                    logger.info("Saved and committed listing %s", lid)
            except sqlite3.Error:
                logger.exception("Import failed for %s", source_id)
                self._json({"ok": False, "error": "database error"}, 500)
                return
            self._json({"ok": True, "id": lid})

        # ── Delete handler ─────────────────────────────────────────────────
        def _handle_delete(self, listing_id: str) -> None:
            import sqlite3
            from contextlib import closing

            from carfinder.db import init_db

            try:
                with closing(init_db(db_path)) as conn:
                    # Only manual entries are deletable; scraped rows can be
                    # re-fetched and must not be removable via the API.
                    cur = conn.execute(
                        "DELETE FROM listings WHERE id = ? AND source = 'manual'",
                        [listing_id],
                    )
                    conn.commit()
            except sqlite3.Error:
                logger.exception("Delete failed for %s", listing_id)
                self._json({"ok": False, "error": "database error"}, 500)
                return
            if not cur.rowcount:
                self._json({"ok": False, "error": "not found or not deletable"}, 404)
                return
            logger.info("Deleted and committed listing %s", listing_id)
            self._json({"ok": True})

    return _Handler


def _safe_int(v: object) -> int | None:
    try:
        return int(str(v).replace(",", "").replace("k", "000").rstrip("mi ").strip()) if v else None
    except (ValueError, TypeError):
        return None


def _safe_float(v: object) -> float | None:
    try:
        return float(str(v).replace(",", "").lstrip("$").strip()) if v else None
    except (ValueError, TypeError):
        return None


def run_server(config: "Config", db_path: Path, port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    """Create and return the server (not yet started). Caller calls server.serve_forever()."""
    handler = _make_handler(config, db_path)
    server = ThreadingHTTPServer(("localhost", port), handler)
    return server, f"http://localhost:{port}"
