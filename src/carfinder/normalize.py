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

# Trim-code models that KBB pages under a different name. BMW sells "528i",
# "330i", "228i" etc. but KBB's value page is "/bmw/5-series/"; Mazdaspeed3 is a
# trim of the Mazda3. Map these so they resolve to a value page + image.
_BMW_TRIM = re.compile(r"^[1-8]\d\d[a-z]{1,3}$", re.IGNORECASE)   # 528i, 330i, 325xi, 750i
_MAZDASPEED = re.compile(r"^mazdaspeed[\s-]?(\d)$", re.IGNORECASE)


def _model_alias(make: str | None, model: str | None) -> str | None:
    if not model:
        return model
    m = model.strip()
    mk = (make or "").strip().lower()
    if mk == "bmw" and _BMW_TRIM.match(m):
        return f"{m[0]} Series"
    if mk == "mazda":
        ms = _MAZDASPEED.match(m)
        if ms:
            return f"Mazda{ms.group(1)}"
    return m


# Leading tokens of genuine multi-word models — keep the following token too
# (e.g. Tesla "Model 3"/"Model Y", "Range Rover", "Grand Cherokee", Audi "RS 7",
# "Land Cruiser", "Santa Fe"). The 2nd token is kept even when it looks like a
# bare number/letter, which would otherwise be treated as noise.
_MULTIWORD_LEAD = {"model", "range", "grand", "land", "santa", "crown", "rs"}


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
    toks = [t for t in re.split(r"\s+", model.strip()) if t]
    if not toks:
        return model.strip() or None
    first = toks[0]
    # Genuine multi-word model: keep the following token even if it looks numeric.
    if first.lower().strip(".,") in _MULTIWORD_LEAD and len(toks) >= 2:
        return f"{first} {toks[1]}"
    if _is_noise(first):
        # Leading token is itself noise — can't confidently clean; leave as-is.
        return model.strip()
    return first


def normalize_make_model(make: str | None, model: str | None) -> tuple[str | None, str | None]:
    """Return a canonical (make, model). See module docstring for the contract."""
    key = (make or "").strip().lower()
    if key in _MAKE_IS_MODEL:
        return _MAKE_IS_MODEL[key]
    make_norm = normalize_make(make)
    return make_norm, _model_alias(make_norm, clean_model(model))
