"""Tests for make/model normalization (normalize.py)."""
from __future__ import annotations

import pytest

from carfinder.normalize import clean_model, normalize_make, normalize_make_model


@pytest.mark.parametrize("raw, expected", [
    ("Forester 2 5x manual transmission AWD", "Forester"),
    ("Tacoma 4X4 SR5 4 cylinder 5 speed manual", "Tacoma"),
    ("Accord two-door hatchback 76 000 miles", "Accord"),
    ("350z roadster 6psd manual", "350z"),
    ("GENESIS 107k 6 Speed TOP MODEL Gran Touring 3 8L POWERFUL", "GENESIS"),
    ("500 Pop Pop 2dr Hatchback NO JOB OR CREDIT NEEDED", "500"),
    ("FOCUS ST 4 DOOR HATCHBACK", "FOCUS"),
    ("V70 T5", "V70"),
    ("CR-V", "CR-V"),          # clean single-token model is untouched
    ("Tacoma", "Tacoma"),
    # multi-word models keep their second token even though it looks numeric
    ("model 3 Long Range AWD", "model 3"),
    ("Model Y", "Model Y"),
    ("RS 7", "RS 7"),
    ("Range Rover Evoque", "Range Rover"),
    ("Grand Cherokee Laredo 4x4", "Grand Cherokee"),
])
def test_clean_model_reduces_to_leading_token(raw, expected):
    assert clean_model(raw) == expected


def test_clean_model_handles_none_and_empty():
    assert clean_model(None) is None
    assert clean_model("") == ""


@pytest.mark.parametrize("raw, expected", [
    ("Chevy", "Chevrolet"),
    ("Vw", "Volkswagen"),
    ("Volkswgen", "Volkswagen"),
    ("Volkwagen", "Volkswagen"),
    ("Mercedes", "Mercedes-Benz"),
    ("Toyota", "Toyota"),       # already canonical, unchanged
])
def test_normalize_make_aliases(raw, expected):
    assert normalize_make(raw) == expected


def test_make_that_is_actually_a_model():
    # make="Mustang" model="GT" -> Ford Mustang (the trim is discarded)
    assert normalize_make_model("Mustang", "GT") == ("Ford", "Mustang")
    assert normalize_make_model("Tj", "Jeep") == ("Jeep", "Wrangler")


def test_normalize_make_model_combined():
    assert normalize_make_model("Subaru", "Forester 2 5x manual transmission AWD") == ("Subaru", "Forester")
    assert normalize_make_model("Chevy", "Avalanche") == ("Chevrolet", "Avalanche")


@pytest.mark.parametrize("make, model, expected_model", [
    ("BMW", "528i", "5 Series"),
    ("BMW", "330i", "3 Series"),
    ("BMW", "228i", "2 Series"),
    ("BMW", "325xi", "3 Series"),
    ("BMW", "2002", "2002"),   # classic, not a trim code — untouched
    ("BMW", "M3", "M3"),       # untouched
    ("BMW", "X5", "X5"),       # untouched
    ("MAZDA", "MAZDASPEED3", "Mazda3"),
    ("Mazda", "Mazdaspeed6", "Mazda6"),
])
def test_trim_code_model_aliases(make, model, expected_model):
    assert normalize_make_model(make, model)[1] == expected_model
