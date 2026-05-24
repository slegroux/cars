"""Local HTTP server — serves the dashboard and handles import/delete via REST API."""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

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
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _html(self, html: str) -> None:
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            return json.loads(raw) if raw else {}

        # ── GET ────────────────────────────────────────────────────────────
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                from carfinder.cli import _load_scored_listings
                from carfinder.render_html import render_html

                scored, conn = _load_scored_listings(config)
                conn.close()
                self._html(render_html(scored, config=config))
            else:
                self.send_response(404)
                self.end_headers()

        # ── POST ───────────────────────────────────────────────────────────
        def do_POST(self) -> None:
            if self.path == "/api/import":
                self._handle_import()
            elif self.path.startswith("/api/delete/"):
                listing_id = self.path.removeprefix("/api/delete/")
                self._handle_delete(listing_id)
            else:
                self.send_response(404)
                self.end_headers()

        # ── OPTIONS (CORS preflight) ────────────────────────────────────────
        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
            from carfinder.importer import _source_id_from_url
            from carfinder.models import Listing

            url = (data.get("url") or "").strip() or None
            source_id = _source_id_from_url(url) if url else None

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
                mileage=_safe_int(data.get("mileage")),
                asking_price=_safe_float(data.get("price")),
                location=(data.get("location") or "").strip() or None,
                seller_type=(data.get("seller_type") or "private").strip(),
                description=(data.get("notes") or "").strip() or None,
            )

            conn = init_db(db_path)
            lid = upsert_listing(conn, listing)
            conn.commit()
            logger.info("Saved and committed listing %s", lid)
            conn.close()
            self._json({"ok": True, "id": lid})

        # ── Delete handler ─────────────────────────────────────────────────
        def _handle_delete(self, listing_id: str) -> None:
            from carfinder.db import init_db

            conn = init_db(db_path)
            cur = conn.execute("DELETE FROM listings WHERE id = ?", [listing_id])
            conn.commit()
            if cur.rowcount:
                logger.info("Deleted and committed listing %s", listing_id)
            conn.close()
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


def run_server(config: "Config", db_path: Path, port: int = 8765) -> tuple[HTTPServer, str]:
    """Create and return the server (not yet started). Caller calls server.serve_forever()."""
    handler = _make_handler(config, db_path)
    server = HTTPServer(("localhost", port), handler)
    return server, f"http://localhost:{port}"
