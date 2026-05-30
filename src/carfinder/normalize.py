"""Normalize scraped make/model strings to canonical names.

Craigslist titles in particular leave make/model polluted with trim,
transmission, body style and marketing text — e.g. make="Subaru",
model="Forester 2 5x manual transmission AWD". This recovers a clean
(make, model) so the listing resolves against KBB and the lookup tables.

Deliberately conservative: the model is reduced to its leading token only, and
when a value is ambiguous it's left as-is. A model we can't confidently clean
yields *no* KBB match (an honest placeholder) rather than a wrong-car match.
"""
from __future__ import annotations

import re

# Canonical make for common aliases / typos.
_MAKE_ALIASES = {
    "chevy": "Chevrolet", "chev": "Chevrolet",
    "vw": "Volkswagen", "volkswgen": "Volkswagen", "volkwagen": "Volkswagen", "volkswagon": "Volkswagen",
    "mercedes": "Mercedes-Benz", "mercedes benz": "Mercedes-Benz", "benz": "Mercedes-Benz",
    "alfa": "Alfa Romeo",
}

# A make value that is really a model — map to the true (make, model). The raw
# model field in these rows is a trim ("GT", "Cobra") and is discarded.
_MAKE_IS_MODEL = {
    "mustang": ("Ford", "Mustang"),
    "tj": ("Jeep", "Wrangler"),
}

# Tokens that are never the start of a model name.
_NOISE_TOKENS = {
    "manual", "automatic", "auto", "awd", "fwd", "rwd", "4wd", "2wd", "4x4",
    "hatchback", "sedan", "coupe", "convertible", "wagon", "suv", "truck",
    "pickup", "roadster", "cabriolet", "hardtop", "van", "minivan",
    "door", "doors", "dr", "two-door", "four-door",
    "cylinder", "cyl", "speed", "spd", "transmission", "trans",
    "turbo", "diesel", "hybrid", "miles", "mile", "mi",
}
_MILES_K = re.compile(r"^\d+k$", re.IGNORECASE)        # 107k
_DISPLACEMENT = re.compile(r"^\d(\.\d)?l?$", re.IGNORECASE)  # 2, 2.5, 2.0l, 3l


def normalize_make(make: str | None) -> str | None:
    if not make:
        return make
    return _MAKE_ALIASES.get(make.strip().lower(), make.strip()) or None


def _is_noise(tok: str) -> bool:
    t = tok.lower().strip(".,/")
    if not t:
        return True
    return t in _NOISE_TOKENS or bool(_MILES_K.match(t)) or bool(_DISPLACEMENT.match(t))


def clean_model(model: str | None) -> str | None:
    """Reduce a polluted model string to its leading model token.

    Most model names are a single token (Forester, Tacoma, 350Z, CR-V); the
    trailing tokens are trim/transmission/body noise. Taking the first
    non-noise token is conservative and high-accuracy for this data.
    """
    if not model:
        return model
    for tok in re.split(r"\s+", model.strip()):
        if not _is_noise(tok):
            return tok
    return model.strip() or None


def normalize_make_model(make: str | None, model: str | None) -> tuple[str | None, str | None]:
    """Return a canonical (make, model). See module docstring for the contract."""
    key = (make or "").strip().lower()
    if key in _MAKE_IS_MODEL:
        return _MAKE_IS_MODEL[key]
    return normalize_make(make), clean_model(model)
