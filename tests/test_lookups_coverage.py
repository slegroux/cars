"""M3b — lookup data coverage tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from carfinder.lookups import load_lookups

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def lk():
    return load_lookups(DATA_DIR)


# ---------------------------------------------------------------------------
# 1. All YAMLs load without error
# ---------------------------------------------------------------------------

def test_all_yamls_load_without_error():
    lk = load_lookups(DATA_DIR)
    assert lk.reliability
    assert lk.dimensions
    assert lk.insurance
    assert lk.roof_rack
    assert lk.msrp


# ---------------------------------------------------------------------------
# 2. Target makes have reliability scores
# ---------------------------------------------------------------------------

def test_target_vehicles_have_reliability_score(lk):
    for make in ("Toyota", "Honda", "Mazda", "Subaru", "Hyundai", "Kia", "BMW"):
        assert make in lk.reliability, f"{make} missing from reliability_tiers"


# ---------------------------------------------------------------------------
# 3. Top 5 models have dimension coverage across 2010-2018
# ---------------------------------------------------------------------------

def test_top_5_models_have_full_dimension_coverage(lk):
    # (make, model, year_start, year_end) — bounded to actual production years
    targets = [
        ("Toyota", "RAV4", 2010, 2018),
        ("Honda", "CR-V", 2010, 2018),
        ("Mazda", "CX-5", 2013, 2018),   # CX-5 launched 2013
        ("Subaru", "Forester", 2010, 2018),
        ("Subaru", "Outback", 2010, 2018),
    ]
    for make, model, y_start, y_end in targets:
        for year in range(y_start, y_end + 1):
            key = (make, model, year)
            assert key in lk.dimensions, f"No dimension entry for {make} {model} {year}"


# ---------------------------------------------------------------------------
# 4. Kia/Hyundai pre-2022 marked high risk
# ---------------------------------------------------------------------------

def test_kia_hyundai_pre_2022_marked_high_risk(lk):
    samples = [
        ("Kia", "Forte", 2015),
        ("Kia", "Optima", 2014),
        ("Kia", "Soul", 2018),
        ("Hyundai", "Elantra", 2017),
        ("Hyundai", "Sonata", 2013),
    ]
    for make, model, year in samples:
        tier = lk.insurance.get((make, model, year))
        assert tier == "high", (
            f"Expected high risk for {make} {model} {year}, got {tier!r}"
        )


# ---------------------------------------------------------------------------
# 5. Subaru low risk
# ---------------------------------------------------------------------------

def test_subaru_low_risk(lk):
    for make, model, year in [
        ("Subaru", "Forester", 2014),
        ("Subaru", "Outback", 2014),
    ]:
        tier = lk.insurance.get((make, model, year))
        assert tier == "low", (
            f"Expected low risk for {make} {model} {year}, got {tier!r}"
        )
