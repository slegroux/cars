"""Scorer — pure scoring core for car listings.

score_listing() is a pure function: no DB writes, no file I/O.
All data is passed in via parameters.
"""
from __future__ import annotations

import datetime
from statistics import median
from typing import Literal

from pydantic import BaseModel

from carfinder.config import Config
from carfinder.lookups import Lookups, _norm
from carfinder.models import Listing

# Current year used for depreciation fallback
_CURRENT_YEAR = datetime.date.today().year


class FactorScore(BaseModel):
    raw: float  # 0-10
    weight: float
    weighted: float
    confidence: Literal["real", "estimated"]
    reason: str


class ScoredListing(BaseModel):
    # All original Listing fields
    listing: Listing
    score: float
    score_breakdown: dict[str, FactorScore]
    confidence: Literal["full", "partial", "low"]

    def display_score(self) -> str:
        """Return score string with confidence prefix."""
        s = f"{self.score:.1f}"
        if self.confidence == "partial":
            return f"~{s}"
        if self.confidence == "low":
            return f"~{s}*"
        return s


# ---------------------------------------------------------------------------
# Per-factor scoring functions
# ---------------------------------------------------------------------------

def _factor(
    raw: float,
    weight: float,
    confidence: Literal["real", "estimated"],
    reason: str,
) -> FactorScore:
    return FactorScore(
        raw=raw,
        weight=weight,
        weighted=raw * weight,
        confidence=confidence,
        reason=reason,
    )


def _default_factor(weight: float) -> FactorScore:
    return _factor(5.0, weight, "estimated", "unknown — defaulted")


def score_reliability(listing: Listing, lookups: Lookups, weight: float) -> FactorScore:
    if listing.make and _norm(listing.make) in lookups.reliability:
        raw = lookups.reliability[_norm(listing.make)]
        return _factor(raw, weight, "real", f"{listing.make} reliability score {raw:.0f}/10")
    return _default_factor(weight)


def score_price_value(
    listing: Listing,
    cohort: list[Listing],
    lookups: Lookups,
    config: Config,
    weight: float,
) -> FactorScore:
    asking = listing.asking_price
    if asking is None:
        return _factor(5.0, weight, "estimated", "no asking price")

    # Filter cohort to same (year, make, model)
    same = [
        c.asking_price
        for c in cohort
        if c.asking_price is not None
        and c.year == listing.year
        and c.make == listing.make
        and c.model == listing.model
        and c.id != listing.id  # exclude self
    ]

    if len(same) >= 3:
        med = median(same)
        raw, reason = _price_bands(asking, med)
        return _factor(raw, weight, "real", f"cohort median ${med:,.0f}, asking ${asking:,.0f} — {reason}")

    # Fallback: depreciation estimate
    make = listing.make or ""
    model = listing.model or ""
    msrp = lookups.msrp.get((make, model))
    if msrp and listing.year:
        age = _CURRENT_YEAR - listing.year
        expected = msrp * (0.88 ** age) - (listing.mileage or 0) * 0.04
        expected = max(expected, 2000.0)
        raw, reason = _price_bands(asking, expected)
        return _factor(
            raw, weight, "estimated",
            f"depreciation estimate ${expected:,.0f} (MSRP ${msrp:,}, age {age}y) — {reason}",
        )

    return _factor(5.0, weight, "estimated", "no cohort or MSRP reference")


def _price_bands(asking: float, reference: float) -> tuple[float, str]:
    """Return (raw_score, reason) relative to a reference price."""
    if asking <= reference:
        return 10.0, "at or below reference"
    if asking <= reference * 1.10:
        return 7.0, "within 10% above reference"
    if asking <= reference * 1.20:
        return 4.0, "within 20% above reference"
    return 1.0, "more than 20% above reference"


def score_mileage(listing: Listing, weight: float) -> FactorScore:
    mileage = listing.mileage
    if mileage is None:
        return _factor(5.0, weight, "estimated", "mileage unknown")

    if 50_000 <= mileage <= 80_000:
        raw, reason = 10.0, "sweet spot 50k-80k"
    elif 30_000 <= mileage < 50_000:
        raw, reason = 8.0, "low miles"
    elif 80_001 <= mileage <= 100_000:
        raw, reason = 7.0, "high side 80k-100k"
    elif 20_000 <= mileage < 30_000:
        raw, reason = 6.0, "moderate low miles 20k-30k"
    elif mileage < 20_000:
        raw, reason = 4.0, "suspiciously low (<20k)"
    else:
        raw, reason = 1.0, f"over 100k cap ({mileage:,} mi)"

    return _factor(raw, weight, "real", reason)


def score_size_class(listing: Listing, weight: float) -> FactorScore:
    bt = (listing.body_type or "").strip()
    mapping: dict[str, tuple[float, str]] = {
        "SUV": (10.0, "compact/mid SUV"),
        "Wagon": (10.0, "wagon"),
        "Hatchback": (9.0, "hatchback"),
        "Sedan": (7.0, "sedan"),
        "Coupe": (4.0, "coupe"),
        "Truck": (3.0, "truck"),
        "Van": (5.0, "van"),
        "Convertible": (5.0, "convertible"),
        "Minivan": (5.0, "minivan"),
        "Pickup": (3.0, "pickup truck"),
    }
    if bt in mapping:
        raw, label = mapping[bt]
        return _factor(raw, weight, "real", label)
    if bt:
        return _factor(5.0, weight, "estimated", f"unknown body type: {bt!r}")
    return _factor(5.0, weight, "estimated", "body type unknown")


def score_parking_footprint(listing: Listing, lookups: Lookups, weight: float) -> FactorScore:
    # Prefer enriched field on listing, then lookup
    length = listing.length_inches
    if length is None and listing.make and listing.model and listing.year:
        length = lookups.dimensions.get((_norm(listing.make), listing.model, listing.year))

    if length is None:
        return _factor(5.0, weight, "estimated", "length unknown")

    if length < 180:
        raw, reason = 10.0, f"{length:.1f}\" — under 180\""
    elif length <= 190:
        raw, reason = 7.0, f"{length:.1f}\" — 180-190\""
    elif length <= 200:
        raw, reason = 4.0, f"{length:.1f}\" — 190-200\""
    else:
        raw, reason = 1.0, f"{length:.1f}\" — over 200\""

    return _factor(raw, weight, "real", reason)


def score_mpg(listing: Listing, lookups: Lookups, weight: float) -> FactorScore:
    mpg = listing.mpg_combined
    if mpg is None and listing.year and listing.make and listing.model:
        looked_up = lookups.mpg.get((listing.year, listing.make, listing.model))
        if looked_up is not None:
            mpg = float(looked_up)
            # A successful lookup is canonical data — treat it as "real" for
            # consistency with reliability/dimensions/insurance/roof_rack, which
            # all report "real" on a lookup hit.
            confidence: Literal["real", "estimated"] = "real"
        else:
            confidence = "estimated"
    else:
        confidence = "real" if mpg is not None else "estimated"

    if mpg is None:
        return _factor(5.0, weight, "estimated", "MPG unknown")

    if mpg >= 35:
        raw, reason = 10.0, f"{mpg:.0f} MPG (hybrid/efficient)"
    elif mpg >= 28:
        raw, reason = 8.0, f"{mpg:.0f} MPG"
    elif mpg >= 25:
        raw, reason = 6.0, f"{mpg:.0f} MPG"
    elif mpg >= 22:
        raw, reason = 4.0, f"{mpg:.0f} MPG"
    else:
        raw, reason = 1.0, f"{mpg:.0f} MPG (below 22)"

    return _factor(raw, weight, confidence, reason)


def score_drivetrain(listing: Listing, weight: float) -> FactorScore:
    dt = (listing.drivetrain or "").upper().strip()
    mapping = {
        "AWD": (10.0, "AWD"),
        "4WD": (9.0, "4WD"),
        "FWD": (8.0, "FWD"),
        "RWD": (4.0, "RWD — slippery conditions risk"),
    }
    if dt in mapping:
        raw, reason = mapping[dt]
        return _factor(raw, weight, "real", reason)
    return _factor(5.0, weight, "estimated", "drivetrain unknown")


def score_insurance_risk(listing: Listing, lookups: Lookups, weight: float) -> FactorScore:
    # Prefer enriched field, then lookup
    tier = listing.insurance_risk_tier
    source = "enriched"
    if tier is None and listing.make and listing.model and listing.year:
        tier = lookups.insurance.get((_norm(listing.make), listing.model, listing.year))
        source = "lookup"

    tier_map = {"low": (10.0, "low insurance risk"), "medium": (6.0, "medium insurance risk"), "high": (2.0, "high insurance risk")}
    if tier and tier in tier_map:
        raw, reason = tier_map[tier]
        return _factor(raw, weight, "real", f"{reason} ({source})")
    return _factor(5.0, weight, "estimated", "insurance risk unknown")


def score_roof_rack(listing: Listing, lookups: Lookups, weight: float) -> FactorScore:
    # Prefer enriched field, then lookup
    status = listing.roof_rack_compatible
    source = "enriched"
    if status is None and listing.make and listing.model:
        status = lookups.roof_rack.get((_norm(listing.make), listing.model))
        source = "lookup"

    status_map = {
        "oem_rails": (10.0, "OEM roof rails standard"),
        "aftermarket": (7.0, "aftermarket rack mount available"),
        "none": (3.0, "no viable rack option"),
    }
    if status and status in status_map:
        raw, reason = status_map[status]
        return _factor(raw, weight, "real", f"{reason} ({source})")

    # Heuristic: SUV/Wagon likely rack-friendly
    bt = (listing.body_type or "").strip()
    if bt in ("SUV", "Wagon"):
        return _factor(8.0, weight, "estimated", "SUV/Wagon likely rack-friendly")
    return _factor(5.0, weight, "estimated", "roof rack compatibility unknown")


def score_seller_type(listing: Listing, weight: float) -> FactorScore:
    st = (listing.seller_type or "").lower().strip()
    if st == "certified":
        return _factor(10.0, weight, "real", "certified pre-owned")
    if st == "dealer":
        return _factor(9.0, weight, "real", "dealer — accountable seller")
    if st == "private":
        return _factor(6.0, weight, "real", "private seller")
    return _factor(5.0, weight, "estimated", "seller type unknown")


def score_title_status(listing: Listing, weight: float) -> FactorScore:
    status = (listing.title_status or "").lower().strip()
    if status == "clean":
        return _factor(10.0, weight, "real", "clean title")
    if status == "rebuilt":
        return _factor(4.0, weight, "real", "rebuilt title — reduced value")
    if status in ("salvage", "flood", "lemon"):
        return _factor(
            0.0, weight, "real",
            f"HARD REJECT — {status} title",
        )
    if status:
        return _factor(5.0, weight, "estimated", f"unknown title status: {status!r}")
    return _factor(5.0, weight, "estimated", "title status unknown")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def score_listing(
    listing: Listing,
    cohort: list[Listing],
    config: Config,
    lookups: Lookups,
) -> ScoredListing:
    """Score a single listing. Pure function — no side effects."""
    w = config.weights

    # Defensive check: manual excluded by config
    if config.transmission.exclude_manual and (listing.transmission or "").lower() == "manual":
        breakdown: dict[str, FactorScore] = {}
        return ScoredListing(
            listing=listing,
            score=0.0,
            score_breakdown=breakdown,
            confidence="low",
        )

    breakdown = {
        "reliability": score_reliability(listing, lookups, w.reliability),
        "price_value": score_price_value(listing, cohort, lookups, config, w.price_value),
        "mileage": score_mileage(listing, w.mileage),
        "size_class": score_size_class(listing, w.size_class),
        "parking_footprint": score_parking_footprint(listing, lookups, w.parking_footprint),
        "mpg": score_mpg(listing, lookups, w.mpg),
        "drivetrain": score_drivetrain(listing, w.drivetrain),
        "insurance_risk": score_insurance_risk(listing, lookups, w.insurance_risk),
        "roof_rack": score_roof_rack(listing, lookups, w.roof_rack),
        "title_status": score_title_status(listing, w.title_status),
        "seller_type": score_seller_type(listing, w.seller_type),
    }

    raw_total = sum(f.weighted for f in breakdown.values()) * 10  # 0-100 scale

    # Hard reject: salvage/flood/lemon title forces score to 0
    title_factor = breakdown.get("title_status")
    hard_rejected = title_factor is not None and title_factor.raw == 0.0 and "HARD REJECT" in title_factor.reason
    total = 0.0 if hard_rejected else raw_total

    estimated_count = sum(1 for f in breakdown.values() if f.confidence == "estimated")
    if estimated_count == 0:
        conf: Literal["full", "partial", "low"] = "full"
    elif estimated_count <= 2:
        conf = "partial"
    else:
        conf = "low"

    return ScoredListing(
        listing=listing,
        score=round(total, 2),
        score_breakdown=breakdown,
        confidence=conf,
    )
