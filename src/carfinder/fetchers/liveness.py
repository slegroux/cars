"""Detect whether a listing's page indicates the car is gone / sold.

Used by the `check-sold` command to flag listings whose source page has been
removed. Deliberately conservative: it returns True only on clear signals
(404/410 or an explicit "deleted/sold/no-longer-available" marker). Transient
failures — timeouts, 5xx, bot-blocks — must NOT be treated as sold, so the
caller passes those through as "unknown" (status None) and we return False.
"""
from __future__ import annotations

# Source-specific "this listing is gone" markers (lowercased substring match).
_SOURCE_MARKERS: dict[str, list[str]] = {
    "craigslist": [
        "this posting has been deleted",
        "this posting has been flagged",
    ],
    "carmax": [
        "no longer available",
        "this vehicle is no longer",
        "this car is no longer available",
    ],
    "carscom": [
        "no longer available",
        "this listing is no longer",
        "we couldn't find that vehicle",
    ],
}
# Markers that signal "gone" on any source.
_GENERIC_MARKERS = [
    "no longer available",
    "listing not found",
    "this listing has ended",
    "page not found",
]


def detect_sold(status: int | None, text: str, source: str | None) -> bool:
    """Return True only when confident the listing is gone/sold.

    ``status`` is the final HTTP status (after redirects), or None for a
    transient error — both 5xx and None yield False (unknown, leave as-is).
    """
    if status in (404, 410):
        return True
    if status != 200:
        return False
    body = (text or "").lower()
    markers = _SOURCE_MARKERS.get((source or "").lower(), []) + _GENERIC_MARKERS
    return any(m in body for m in markers)
