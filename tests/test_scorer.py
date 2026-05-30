"""Tests for scorer.py — M3a acceptance criteria."""
from __future__ import annotations

import json
from pathlib import Path


from carfinder.config import Config, WeightsConfig
from carfinder.lookups import Lookups, load_lookups
from carfinder.models import Listing
from carfinder.scorer import (
    score_drivetrain,
    score_listing,
    score_mileage,
    score_mpg,
    score_parking_footprint,
    score_price_value,
    score_reliability,
    score_roof_rack,
    score_size_class,
    score_title_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "scorer"


def _cfg() -> Config:
    return Config()


def _lk() -> Lookups:
    return load_lookups(DATA_DIR)


def _listing(**kwargs) -> Listing:
    defaults: dict = {
        "id": "test-1",
        "source": "test",
        "source_id": "test-1",
        "year": 2016,
        "make": "Toyota",
        "model": "RAV4",
        "body_type": "SUV",
        "drivetrain": "AWD",
        "transmission": "automatic",
        "mileage": 70_000,
        "title_status": "clean",
        "asking_price": 12_000,
    }
    defaults.update(kwargs)
    return Listing(**defaults)


def _cohort_around(median_price: float, n: int = 5, **kwargs) -> list[Listing]:
    """Build n listings around a median price for cohort testing."""
    prices = [median_price * (1 - 0.05 * i) for i in range(n)]
    listings = []
    for i, price in enumerate(prices):
        base = dict(
            id=f"cohort-{i}",
            source="test",
            source_id=f"cohort-{i}",
            year=2016,
            make="Toyota",
            model="RAV4",
            body_type="SUV",
            drivetrain="AWD",
            transmission="automatic",
            mileage=70_000,
            title_status="clean",
            asking_price=price,
        )
        base.update(kwargs)
        listings.append(Listing(**base))
    return listings


# ---------------------------------------------------------------------------
# 1. RAV4 2014 XLE fixture scores > 75
# ---------------------------------------------------------------------------

def test_rav4_2014_xle_fixture_scores_above_75():
    raw = json.loads((FIXTURE_DIR / "rav4_2014_xle.json").read_text())
    listing = Listing(**raw)
    # Build cohort of 5 synthetic 2014 RAV4 XLE around $11k-13k median (~$12k)
    cohort = []
    for i, price in enumerate([11_000, 11_500, 12_000, 12_500, 13_000]):
        cohort.append(Listing(
            id=f"c{i}", source="test", source_id=f"c{i}",
            year=2014, make="Toyota", model="RAV4",
            asking_price=price, mileage=100_000,
            transmission="automatic", title_status="clean",
        ))
    result = score_listing(listing, cohort, _cfg(), _lk())
    assert result.score > 75, f"RAV4 XLE expected >75, got {result.score}"


# ---------------------------------------------------------------------------
# 2. BMW 328i 2014 salvage scores < 30 with HARD REJECT in title breakdown
# ---------------------------------------------------------------------------

def test_bmw_salvage_fixture_scores_below_30():
    raw = json.loads((FIXTURE_DIR / "bmw_328i_2014_salvage.json").read_text())
    listing = Listing(**raw)
    result = score_listing(listing, [], _cfg(), _lk())
    assert result.score < 30, f"BMW salvage expected <30, got {result.score}"
    assert "HARD REJECT" in result.score_breakdown["title_status"].reason


# ---------------------------------------------------------------------------
# 3. Manual transmission → score == 0
# ---------------------------------------------------------------------------

def test_manual_transmission_returns_zero():
    listing = _listing(transmission="manual")
    result = score_listing(listing, [], _cfg(), _lk())
    assert result.score == 0.0


# ---------------------------------------------------------------------------
# 4. Price at/below cohort median → raw == 10
# ---------------------------------------------------------------------------

def test_price_below_cohort_median_scores_10():
    cohort = []
    for i, price in enumerate([11_000, 12_000, 13_000, 14_000, 15_000]):
        cohort.append(Listing(
            id=f"c{i}", source="test", source_id=f"c{i}",
            year=2016, make="Toyota", model="RAV4",
            asking_price=price, mileage=70_000,
            transmission="automatic", title_status="clean",
        ))
    # median = 13000; asking 10000 < median
    listing = _listing(asking_price=10_000)
    w = _cfg().weights.price_value
    fs = score_price_value(listing, cohort, _lk(), _cfg(), w)
    assert fs.raw == 10.0


# ---------------------------------------------------------------------------
# 5. Price far above cohort median → raw == 1
# ---------------------------------------------------------------------------

def test_price_far_above_median_scores_1():
    cohort = []
    for i, price in enumerate([9_000, 10_000, 11_000, 12_000, 13_000]):
        cohort.append(Listing(
            id=f"c{i}", source="test", source_id=f"c{i}",
            year=2016, make="Toyota", model="RAV4",
            asking_price=price, mileage=70_000,
            transmission="automatic", title_status="clean",
        ))
    # median = 11000; asking 15000 > 120% of median
    listing = _listing(asking_price=15_000)
    w = _cfg().weights.price_value
    fs = score_price_value(listing, cohort, _lk(), _cfg(), w)
    assert fs.raw == 1.0


# ---------------------------------------------------------------------------
# 6. Price falls back to depreciation when cohort < 3
# ---------------------------------------------------------------------------

def test_price_falls_back_to_depreciation_when_cohort_lt_3():
    # RAV4 has an MSRP lookup entry, so with only 2 same-model comps (below the
    # exact- and model-cohort thresholds) the scorer falls back to an
    # MSRP-depreciation estimate and exposes the reference price.
    listing = _listing(year=2016, make="Toyota", model="RAV4", asking_price=12_000, mileage=80_000)
    cohort = [
        Listing(id="c0", source="test", source_id="c0", year=2016, make="Toyota", model="RAV4",
                asking_price=15_000, mileage=70_000, transmission="automatic", title_status="clean"),
        Listing(id="c1", source="test", source_id="c1", year=2016, make="Toyota", model="RAV4",
                asking_price=14_000, mileage=75_000, transmission="automatic", title_status="clean"),
    ]
    w = _cfg().weights.price_value
    fs = score_price_value(listing, cohort, _lk(), _cfg(), w)
    assert fs.confidence == "estimated"
    assert "depreciation" in fs.reason.lower() or "msrp" in fs.reason.lower()
    assert fs.ref_price is not None


# ---------------------------------------------------------------------------
# 7. Unknown make defaults to 5 / estimated (reliability)
# ---------------------------------------------------------------------------

def test_unknown_make_defaults_to_5_with_estimated_confidence():
    listing = _listing(make="Trabant")
    w = _cfg().weights.reliability
    fs = score_reliability(listing, _lk(), w)
    assert fs.raw == 5.0
    assert fs.confidence == "estimated"


# ---------------------------------------------------------------------------
# 8. Mileage sweet spot (70k) → 10
# ---------------------------------------------------------------------------

def test_mileage_sweet_spot_scores_10():
    listing = _listing(mileage=70_000)
    fs = score_mileage(listing, _cfg().weights.mileage)
    assert fs.raw == 10.0
    assert fs.confidence == "real"


# ---------------------------------------------------------------------------
# 9. Mileage over hard cap → 1
# ---------------------------------------------------------------------------

def test_mileage_over_cap_scores_1():
    listing = _listing(mileage=150_000)
    fs = score_mileage(listing, _cfg().weights.mileage)
    assert fs.raw == 1.0


# ---------------------------------------------------------------------------
# 10. AWD → 10, FWD → 8
# ---------------------------------------------------------------------------

def test_awd_scores_10_fwd_scores_8():
    w = _cfg().weights.drivetrain
    awd = score_drivetrain(_listing(drivetrain="AWD"), w)
    fwd = score_drivetrain(_listing(drivetrain="FWD"), w)
    assert awd.raw == 10.0
    assert fwd.raw == 8.0


# ---------------------------------------------------------------------------
# 11. Size class SUV → 10, Coupe → 4
# ---------------------------------------------------------------------------

def test_size_class_suv_scores_10_coupe_scores_4():
    w = _cfg().weights.size_class
    suv = score_size_class(_listing(body_type="SUV"), w)
    coupe = score_size_class(_listing(body_type="Coupe"), w)
    assert suv.raw == 10.0
    assert coupe.raw == 4.0


# ---------------------------------------------------------------------------
# 12. Roof rack missing but SUV → 8 / estimated
# ---------------------------------------------------------------------------

def test_roof_rack_missing_but_suv_defaults_to_8():
    # Unknown make/model so no lookup hit, but body_type=SUV
    listing = _listing(make="Trabant", model="P601", body_type="SUV",
                       roof_rack_compatible=None)
    w = _cfg().weights.roof_rack
    fs = score_roof_rack(listing, _lk(), w)
    assert fs.raw == 8.0
    assert fs.confidence == "estimated"
    assert "SUV" in fs.reason or "rack" in fs.reason.lower()


# ---------------------------------------------------------------------------
# 13. Confidence "full" when all lookups hit
# ---------------------------------------------------------------------------

def test_confidence_full_when_all_lookups_hit():
    # RAV4 2016 has full lookup coverage in stubs
    listing = Listing(
        id="full-1", source="test", source_id="full-1",
        year=2016, make="Toyota", model="RAV4",
        body_type="SUV", drivetrain="AWD",
        transmission="automatic",
        mileage=70_000, title_status="clean",
        asking_price=12_000,
        mpg_combined=28.0,
        length_inches=180.9,           # explicit — no lookup needed
        roof_rack_compatible="oem_rails",  # explicit
        insurance_risk_tier="low",     # explicit
        seller_type="dealer",          # explicit
    )
    # Build cohort ≥3 so price_value is "real"
    cohort = [
        Listing(id=f"c{i}", source="test", source_id=f"c{i}",
                year=2016, make="Toyota", model="RAV4",
                asking_price=12_000 + i * 500, mileage=70_000,
                transmission="automatic", title_status="clean")
        for i in range(5)
    ]
    result = score_listing(listing, cohort, _cfg(), _lk())
    assert result.confidence == "full", (
        f"Expected full confidence, got {result.confidence}. "
        f"Estimated factors: {[k for k, v in result.score_breakdown.items() if v.confidence == 'estimated']}"
    )


# ---------------------------------------------------------------------------
# 14. Confidence "low" when many lookups miss
# ---------------------------------------------------------------------------

def test_confidence_low_when_many_lookups_miss():
    listing = Listing(
        id="low-1", source="test", source_id="low-1",
        year=2016, make="Trabant", model="P601",
        transmission="automatic",
    )
    result = score_listing(listing, [], _cfg(), _lk())
    assert result.confidence == "low"
    assert result.display_score().startswith("~") and result.display_score().endswith("*")


# ---------------------------------------------------------------------------
# 15. Weights respected — changing reliability weight changes score
# ---------------------------------------------------------------------------

def test_weights_respected():
    listing = _listing(make="Toyota")  # reliability = 10
    cohort = [
        Listing(id=f"c{i}", source="test", source_id=f"c{i}",
                year=2016, make="Toyota", model="RAV4",
                asking_price=12_000, mileage=70_000,
                transmission="automatic", title_status="clean")
        for i in range(5)
    ]
    lk = _lk()

    cfg_default = _cfg()
    result_default = score_listing(listing, cohort, cfg_default, lk)

    # Boost reliability weight significantly, reduce others proportionally
    # Total must still sum to 1.0
    w_new = WeightsConfig(
        reliability=0.50,
        price_value=0.10,
        mileage=0.10,
        size_class=0.08,
        insurance_risk=0.06,
        mpg=0.06,
        parking_footprint=0.04,
        drivetrain=0.02,
        roof_rack=0.02,
        title_status=0.02,
        seller_type=0.00,
    )
    cfg_boosted = Config(weights=w_new)
    result_boosted = score_listing(listing, cohort, cfg_boosted, lk)

    # Toyota reliability = 10 (max), so boosting its weight should increase score
    assert result_boosted.score != result_default.score, "Score should change with different weights"
    assert result_boosted.score_breakdown["reliability"].weight == 0.50


# ---------------------------------------------------------------------------
# 16. Breakdown contains all 11 factors
# ---------------------------------------------------------------------------

def test_score_breakdown_contains_all_11_factors():
    listing = _listing()
    result = score_listing(listing, [], _cfg(), _lk())
    expected = {
        "reliability", "price_value", "mileage", "size_class",
        "parking_footprint", "mpg", "drivetrain", "insurance_risk",
        "roof_rack", "title_status", "seller_type",
    }
    assert set(result.score_breakdown.keys()) == expected


# ---------------------------------------------------------------------------
# Extra: MPG tiers
# ---------------------------------------------------------------------------

def test_mpg_hybrid_scores_10():
    listing = _listing(mpg_combined=40.0)
    fs = score_mpg(listing, _lk(), _cfg().weights.mpg)
    assert fs.raw == 10.0
    assert fs.confidence == "real"


def test_mpg_low_scores_1():
    listing = _listing(mpg_combined=18.0)
    fs = score_mpg(listing, _lk(), _cfg().weights.mpg)
    assert fs.raw == 1.0


# ---------------------------------------------------------------------------
# Extra: title hard reject propagates to low overall
# ---------------------------------------------------------------------------

def test_salvage_title_hard_reject_in_reason():
    listing = _listing(title_status="salvage")
    fs = score_title_status(listing, _cfg().weights.title_status)
    assert fs.raw == 0.0
    assert "HARD REJECT" in fs.reason


def test_parking_footprint_under_180_scores_10():
    listing = _listing(length_inches=175.0)
    fs = score_parking_footprint(listing, _lk(), _cfg().weights.parking_footprint)
    assert fs.raw == 10.0
    assert fs.confidence == "real"
