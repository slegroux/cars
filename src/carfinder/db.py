"""SQLite database layer."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from carfinder.models import Listing

logger = logging.getLogger(__name__)

# Columns that are mutable and should be updated on conflict
_MUTABLE_COLS: List[str] = [
    "asking_price",
    "last_seen",
    "score",
    "score_breakdown",
    "mileage",
    "photos",
    "description",
    "days_listed",
    "score_confidence",
    "length_inches",
    "roof_rack_compatible",
    "insurance_risk_tier",
    "transmission",
    "drivetrain",
    "fuel_type",
    "title_status",
    "location",
]


def _get_column_defs() -> List[str]:
    """Derive column list from Listing.model_fields.

    We resolve the inner type of each Optional[X] annotation by walking
    __args__ and picking the first non-NoneType argument.
    """
    import types
    import typing

    def _sql_type(annotation: Any) -> str:
        # Unwrap Optional / Union
        origin = getattr(annotation, "__origin__", None)
        if origin is typing.Union or (
            hasattr(types, "UnionType") and isinstance(annotation, types.UnionType)
        ):
            args = [a for a in annotation.__args__ if a is not type(None)]
            annotation = args[0] if args else annotation
            origin = getattr(annotation, "__origin__", None)

        # Check for list/dict generics (e.g. list[str], dict[str, Any])
        if origin is list or annotation is list:
            return "TEXT"  # JSON-encoded
        if origin is dict or annotation is dict:
            return "TEXT"  # JSON-encoded

        name = getattr(annotation, "__name__", "").lower()
        mapping = {
            "str": "TEXT",
            "int": "INTEGER",
            "float": "REAL",
            "bool": "INTEGER",
            "date": "TEXT",
            "datetime": "TEXT",
        }
        return mapping.get(name, "TEXT")

    cols: List[str] = []
    for name, field_info in Listing.model_fields.items():
        sql_type = _sql_type(field_info.annotation)
        cols.append(f"    {name} {sql_type}")
    return cols


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add any columns present in the canonical Listing schema but missing from the DB."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    added = False
    for col_def in _get_column_defs():
        # col_def looks like "    col_name TYPE"
        parts = col_def.split()
        if len(parts) < 2:
            continue
        col_name, col_type = parts[0], parts[1]
        if col_name not in existing:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col_name} {col_type}")
            added = True
    if added:
        # Persist the DDL so the new columns survive even if the caller never
        # commits (init_db does commit, but keep the migration self-contained).
        conn.commit()


def init_db(path: Path) -> sqlite3.Connection:
    """Create the database schema if it doesn't exist, return connection."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    col_defs = _get_column_defs()
    col_sql = ",\n".join(col_defs)

    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS listings (
{col_sql},
            UNIQUE(source, source_id)
        );

        CREATE INDEX IF NOT EXISTS idx_listings_score
            ON listings(score DESC);
        CREATE INDEX IF NOT EXISTS idx_listings_price
            ON listings(asking_price);
        CREATE INDEX IF NOT EXISTS idx_listings_source
            ON listings(source);

        CREATE TABLE IF NOT EXISTS last_run (
            listing_id TEXT PRIMARY KEY,
            score REAL,
            run_at TEXT NOT NULL
        );
    """)

    # Migration: add any new columns to listings that exist in the model but not the DB.
    _migrate_schema(conn)

    # Migration: if last_run was created with old schema (run_ts column), recreate it.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(last_run)").fetchall()}
    if "run_ts" in cols:
        conn.execute("DROP TABLE last_run")
        conn.execute("""
            CREATE TABLE last_run (
                listing_id TEXT PRIMARY KEY,
                score REAL,
                run_at TEXT NOT NULL
            )
        """)

    conn.commit()
    return conn


def find_by_vin(conn: sqlite3.Connection, vin: Optional[str]) -> Optional[Listing]:
    """Return any existing listing with the given VIN, or None.

    Always returns None when ``vin`` is None or empty — we never want to match
    NULL VINs to each other.
    """
    if not vin:
        return None
    row = conn.execute(
        "SELECT * FROM listings WHERE vin IS NOT NULL AND vin = ? LIMIT 1",
        (vin,),
    ).fetchone()
    return Listing.from_row(row) if row else None


def upsert_listing(conn: sqlite3.Connection, listing: Listing) -> str:
    """Insert or update a listing. Returns listing id.

    If the incoming listing has a VIN and there is an existing row with the same
    VIN from a DIFFERENT (source, source_id), merge into the existing row: fill
    NULL fields from the incoming listing but never overwrite non-null values.
    The existing row's (source, source_id) wins as canonical and its id is
    returned. The new source row is NOT inserted.
    """
    import uuid

    if listing.id is None:
        listing = listing.model_copy(update={"id": str(uuid.uuid4())})
    now = datetime.now(timezone.utc)
    if listing.first_seen is None:
        listing = listing.model_copy(update={"first_seen": now})
    listing = listing.model_copy(update={"last_seen": now})

    # VIN-based cross-source merge: only when incoming has a VIN.
    if listing.vin:
        existing = find_by_vin(conn, listing.vin)
        if existing is not None and (
            existing.source != listing.source
            or existing.source_id != listing.source_id
        ):
            return _merge_into_existing(conn, existing, listing)

    row = listing.to_row()
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)

    # Build UPDATE clause for mutable columns
    update_parts = ", ".join(
        f"{c} = excluded.{c}" for c in _MUTABLE_COLS if c in row
    )

    sql = f"""
        INSERT INTO listings ({col_list})
        VALUES ({placeholders})
        ON CONFLICT(source, source_id) DO UPDATE SET
            {update_parts}
    """
    conn.execute(sql, [row[c] for c in cols])
    conn.commit()
    return listing.id  # type: ignore[return-value]


# Columns excluded from the VIN-merge fill (identity / scoring-stability).
_VIN_MERGE_EXCLUDED: set[str] = {"id", "source", "source_id", "first_seen"}


def _merge_into_existing(
    conn: sqlite3.Connection, existing: Listing, incoming: Listing
) -> str:
    """Fill NULL columns on the existing row from the incoming listing.

    Only updates columns where the existing value is NULL/empty and the
    incoming value is non-NULL/non-empty. Always bumps last_seen. The
    existing row's id is returned. Never overwrites non-null existing values.
    """
    existing_row = existing.to_row()
    incoming_row = incoming.to_row()

    updates: Dict[str, Any] = {}
    for col, new_val in incoming_row.items():
        if col in _VIN_MERGE_EXCLUDED:
            continue
        if new_val is None:
            continue
        # JSON-encoded list/dict cols: "[]" / "{}" count as empty.
        if isinstance(new_val, str) and new_val in ("[]", "{}"):
            continue
        old_val = existing_row.get(col)
        if old_val is None or old_val == "" or old_val in ("[]", "{}"):
            updates[col] = new_val

    # Always refresh last_seen so the merged row reflects this observation.
    updates["last_seen"] = incoming_row["last_seen"]

    set_clause = ", ".join(f"{c} = ?" for c in updates)
    params = list(updates.values()) + [existing.id]
    conn.execute(
        f"UPDATE listings SET {set_clause} WHERE id = ?",
        params,
    )
    conn.commit()

    logger.info(
        "VIN merge: incoming %s/%s merged into existing %s/%s (vin=%s, id=%s)",
        incoming.source,
        incoming.source_id,
        existing.source,
        existing.source_id,
        incoming.vin,
        existing.id,
    )
    return existing.id  # type: ignore[return-value]


def find_fuzzy_duplicate(
    conn: sqlite3.Connection, listing: Listing
) -> Optional[Listing]:
    """Find a possible duplicate when VIN is absent.

    Matches on (year, make, model) within ±5% price and ±2000 mileage.
    Returns the candidate listing, or None. Does NOT merge — let caller decide.
    """
    if listing.vin:
        # VIN present — use exact match instead
        row = conn.execute(
            "SELECT * FROM listings WHERE vin = ? AND id != ?",
            (listing.vin, listing.id or ""),
        ).fetchone()
        return Listing.from_row(row) if row else None

    if not all([listing.year, listing.make, listing.model, listing.asking_price, listing.mileage]):
        return None

    price_lo = listing.asking_price * 0.95  # type: ignore[operator]
    price_hi = listing.asking_price * 1.05  # type: ignore[operator]
    mile_lo = (listing.mileage or 0) - 2000
    mile_hi = (listing.mileage or 0) + 2000

    row = conn.execute(
        """
        SELECT * FROM listings
        WHERE year = ?
          AND make = ?
          AND model = ?
          AND asking_price BETWEEN ? AND ?
          AND mileage BETWEEN ? AND ?
          AND (id != ? OR id IS NULL)
        LIMIT 1
        """,
        (
            listing.year,
            listing.make,
            listing.model,
            price_lo,
            price_hi,
            mile_lo,
            mile_hi,
            listing.id or "",
        ),
    ).fetchone()
    return Listing.from_row(row) if row else None


def get_listings(
    conn: sqlite3.Connection,
    min_score: Optional[float] = None,
    limit: Optional[int] = None,
    source: Optional[str] = None,
) -> List[Listing]:
    """Fetch listings ordered by score DESC."""
    clauses: List[str] = []
    params: List[Union[float, int, str]] = []

    if min_score is not None:
        clauses.append("score >= ?")
        params.append(min_score)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # int() guarantees the LIMIT value can never carry injected SQL even if a
    # caller passes a non-int; SQLite does not allow parameterizing LIMIT.
    lim = f"LIMIT {int(limit)}" if limit else ""

    rows = conn.execute(
        f"SELECT * FROM listings {where} ORDER BY score DESC {lim}",
        params,
    ).fetchall()
    return [Listing.from_row(r) for r in rows]


def get_listing_by_id(conn: sqlite3.Connection, listing_id: str) -> Optional[Listing]:
    """Fetch a single listing by its id column. Returns None if not found."""
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return Listing.from_row(row) if row else None


def get_last_run(conn: sqlite3.Connection) -> Dict[str, float]:
    """Return {listing_id: score} from the last_run snapshot table."""
    rows = conn.execute("SELECT listing_id, score FROM last_run").fetchall()
    return {row[0]: row[1] for row in rows}


def update_last_run(conn: sqlite3.Connection, scored_listings: List) -> int:
    """Replace last_run contents with current scored set. Returns count written."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM last_run")
    for s in scored_listings:
        conn.execute(
            "INSERT INTO last_run (listing_id, score, run_at) VALUES (?, ?, ?)",
            (s.listing.id, s.score, now),
        )
    conn.commit()
    return len(scored_listings)


def prune_old(conn: sqlite3.Connection, days: int) -> int:
    """Remove listings not seen in `days` days. Returns count removed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "DELETE FROM listings WHERE last_seen < ?", (cutoff,)
    )
    conn.commit()
    return cur.rowcount
