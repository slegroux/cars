"""Manual listing import — interactive prompts and CSV batch import."""
from __future__ import annotations

import csv
import hashlib
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from carfinder.models import Listing

if TYPE_CHECKING:
    pass

# Columns accepted in CSV (order doesn't matter)
CSV_COLUMNS = [
    "url", "make", "model", "year", "trim", "body_type",
    "mileage", "price", "location", "seller_type", "notes",
]

CSV_TEMPLATE = ",".join(CSV_COLUMNS)

_BODY_TYPES = ["SUV", "Sedan", "Wagon", "Hatchback", "Coupe", "Truck", "Van", ""]
_SELLER_TYPES = ["private", "dealer", "certified", ""]


def _source_id_from_url(url: str) -> str:
    return "manual-" + hashlib.sha256(url.encode()).hexdigest()[:12]


def _source_id_from_fields(make: str, model: str, year: int, mileage: int | None = None) -> str:
    """Stable digest used as source_id for manual imports without a URL.

    Same make/model/year/mileage always produces the same id, so a
    repeat manual entry of the same car updates the existing row
    instead of inserting a duplicate.
    """
    parts = [make.strip().lower(), model.strip().lower(), str(year), str(mileage or "")]
    digest = hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
    return f"manual-{digest}"


def _prompt_listing(url: str | None = None) -> Listing | None:
    """Interactively prompt the user for listing details. Returns None if aborted."""
    click.echo()
    click.echo("── Enter listing details (Enter to skip optional fields) ──")
    click.echo()

    # URL
    if url:
        click.echo(f"  URL: {url}")
    else:
        url = click.prompt("  URL (optional)", default="", show_default=False).strip() or None

    # Required fields
    make = click.prompt("  Make (e.g. Toyota)").strip()
    if not make:
        click.echo("Make is required.", err=True)
        return None
    model = click.prompt("  Model (e.g. RAV4)").strip()
    if not model:
        click.echo("Model is required.", err=True)
        return None

    year_str = click.prompt("  Year").strip()
    try:
        year = int(year_str)
    except ValueError:
        click.echo("Invalid year.", err=True)
        return None

    # Optional fields
    trim = click.prompt("  Trim (optional)", default="", show_default=False).strip() or None

    body_type_input = click.prompt(
        "  Body type [SUV/Sedan/Wagon/Hatchback/Coupe/Truck/Van]",
        default="", show_default=False,
    ).strip() or None

    mileage_str = click.prompt("  Mileage (optional)", default="", show_default=False).strip()
    mileage: int | None = None
    if mileage_str:
        try:
            mileage = int(mileage_str.replace(",", "").replace("k", "000").rstrip("mi").strip())
        except ValueError:
            click.echo("  (Could not parse mileage — leaving blank)", err=True)

    price_str = click.prompt("  Price $ (optional)", default="", show_default=False).strip()
    price: float | None = None
    if price_str:
        try:
            price = float(price_str.replace(",", "").lstrip("$").strip())
        except ValueError:
            click.echo("  (Could not parse price — leaving blank)", err=True)

    location = click.prompt("  Location (optional)", default="", show_default=False).strip() or None

    seller_type = click.prompt(
        "  Seller type [private/dealer/certified]",
        default="private", show_default=True,
    ).strip().lower() or "private"

    notes = click.prompt("  Notes / description (optional)", default="", show_default=False).strip() or None

    source_id = _source_id_from_url(url) if url else _source_id_from_fields(make, model, year, mileage)

    return Listing(
        id=source_id,
        source="manual",
        source_id=source_id,
        url=url,
        make=make,
        model=model,
        year=year,
        trim=trim,
        body_type=body_type_input,
        mileage=mileage,
        asking_price=price,
        location=location,
        seller_type=seller_type,
        description=notes,
    )


def import_one(url: str | None, conn: sqlite3.Connection) -> bool:
    """Interactively import one listing. Returns True on success."""
    from carfinder.db import upsert_listing

    listing = _prompt_listing(url)
    if listing is None:
        return False

    upsert_listing(conn, listing)
    click.echo()
    click.echo(f"  Saved: {listing.year} {listing.make} {listing.model} [{listing.source_id}]")
    return True


def import_csv(path: Path, conn: sqlite3.Connection) -> tuple[int, int]:
    """Batch import from CSV file. Returns (saved, skipped) counts."""
    from carfinder.db import upsert_listing

    saved = skipped = 0
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise click.ClickException(f"Empty or unreadable CSV: {path}")

        headers = {h.strip().lower() for h in reader.fieldnames}
        missing = {"make", "model", "year"} - headers
        if missing:
            raise click.ClickException(
                f"CSV is missing required columns: {', '.join(sorted(missing))}\n"
                f"Run 'carfinder import --template' to see the expected format."
            )

        for i, row in enumerate(reader, start=2):
            # Normalise keys
            row = {k.strip().lower(): v.strip() for k, v in row.items()}

            make = row.get("make", "")
            model = row.get("model", "")
            year_str = row.get("year", "")
            if not make or not model or not year_str:
                click.echo(f"  Row {i}: skipping — make/model/year required", err=True)
                skipped += 1
                continue

            try:
                year = int(year_str)
            except ValueError:
                click.echo(f"  Row {i}: skipping — invalid year '{year_str}'", err=True)
                skipped += 1
                continue

            def _int(v: str) -> int | None:
                try:
                    return int(v.replace(",", "").replace("k", "000").rstrip("mi").strip()) if v else None
                except ValueError:
                    return None

            def _float(v: str) -> float | None:
                try:
                    return float(v.replace(",", "").lstrip("$").strip()) if v else None
                except ValueError:
                    return None

            url = row.get("url") or None
            mileage_for_id = _int(row.get("mileage", ""))
            source_id = _source_id_from_url(url) if url else _source_id_from_fields(make, model, year, mileage_for_id)

            listing = Listing(
                id=source_id,
                source="manual",
                source_id=source_id,
                url=url,
                make=make,
                model=model,
                year=year,
                trim=row.get("trim") or None,
                body_type=row.get("body_type") or None,
                mileage=_int(row.get("mileage", "")),
                asking_price=_float(row.get("price", "")),
                location=row.get("location") or None,
                seller_type=row.get("seller_type") or "private",
                description=row.get("notes") or None,
            )
            upsert_listing(conn, listing)
            click.echo(f"  [{i}] {listing.year} {listing.make} {listing.model} — ${listing.asking_price or '?'}")
            saved += 1

    return saved, skipped
