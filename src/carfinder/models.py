"""Pydantic v2 Listing model — single schema source of truth."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Listing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Identity
    id: str | None = None
    source: str | None = None
    source_id: str | None = None
    url: str | None = None

    # Vehicle
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    body_type: str | None = None
    drivetrain: str | None = None
    transmission: str | None = None
    fuel_type: str | None = None
    mpg_combined: float | None = None
    vin: str | None = None

    # Condition
    mileage: int | None = None
    title_status: str | None = None
    condition: str | None = None

    # Pricing
    asking_price: float | None = None
    seller_type: str | None = None

    # Location
    location: str | None = None
    distance_miles: float | None = None
    transfer_fee: str | None = None

    # Metadata
    photos: list[str] = []
    description: str | None = None
    posted_date: date | None = None
    days_listed: int | None = None

    # Internal / scoring
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    score: float | None = None
    score_breakdown: dict[str, Any] = {}
    score_confidence: str | None = None

    # Enrichment (populated by scorer from lookup tables)
    length_inches: float | None = None
    roof_rack_compatible: str | None = None
    insurance_risk_tier: str | None = None

    def to_row(self) -> dict[str, Any]:
        """Serialize to a dict suitable for SQLite insertion.

        list/dict fields are JSON-encoded as strings.
        """
        data = self.model_dump()
        data["photos"] = json.dumps(data["photos"])
        data["score_breakdown"] = json.dumps(data["score_breakdown"])
        # Convert date/datetime to ISO strings
        if isinstance(data.get("posted_date"), date):
            data["posted_date"] = data["posted_date"].isoformat()
        if isinstance(data.get("first_seen"), datetime):
            data["first_seen"] = data["first_seen"].isoformat()
        if isinstance(data.get("last_seen"), datetime):
            data["last_seen"] = data["last_seen"].isoformat()
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict) -> "Listing":
        """Deserialize from a SQLite row or plain dict."""
        data = dict(row)
        if isinstance(data.get("photos"), str):
            data["photos"] = json.loads(data["photos"])
        if isinstance(data.get("score_breakdown"), str):
            data["score_breakdown"] = json.loads(data["score_breakdown"])
        return cls(**data)
