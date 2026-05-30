"""KBB valuation fetcher — Fair Market Price per (make, model, year).

Distinct from ``kbb.py`` (which scrapes cars-for-sale *listings*). This hits
KBB's year/make/model value page, e.g. https://www.kbb.com/toyota/rav4/2016/,
and extracts the Fair Market Price KBB publishes per trim. The scorer uses this
as a real valuation reference instead of a heuristic cohort estimate.

The value page is a Next.js app; trim prices live in the embedded
``<script id="__NEXT_DATA__">`` JSON under ``...generatedReview/trimsData[]``
(``fairMarketPriceLow``/``High``) with a top-level ``pricingData.fairMarketPrice``
(``ymmtAverage``) fallback.

Results are slow/fragile to fetch (one page per vehicle, bot-detection risk), so
they are scraped once into ``data/kbb_values.json`` by the ``kbb-values`` CLI
command and read from that cache at score time — the scorer never goes online.
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

import httpx

from carfinder.lookups import _norm

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_KBB_BASE = "https://www.kbb.com"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def cache_key(make: str, model: str, year: int) -> str:
    """Stable cache key for one (make, model, year) — normalised, '|'-joined."""
    return f"{_norm(make)}|{_norm(model)}|{year}"


def _slug_variants(make: str, model: str) -> list[str]:
    """Candidate KBB URL slugs for a make/model.

    KBB slugs are mostly lowercase-hyphenated, but model punctuation is
    inconsistent ("cr-v" vs "crv"), so try a few forms and use the first that
    resolves to a 200.
    """
    mk = make.strip().lower().replace(" ", "-")
    raw = model.strip().lower()
    models = []
    for cand in (raw.replace(" ", "-"), raw.replace(" ", "").replace("-", ""), raw.replace("-", " ").strip().replace(" ", "-")):
        if cand and cand not in models:
            models.append(cand)
    return [f"{mk}/{mo}" for mo in models]


def parse_fair_values(html: str, expected_year: int | None = None) -> dict | None:
    """Extract Fair Market Prices from a KBB value page.

    Returns ``{"default": <median trim price>, "trims": {<norm trim>: price}}``
    or None if no valuation data is present.

    When ``expected_year`` is given, the page is rejected unless its canonical
    URL contains ``/<year>/``. KBB serves the *latest* model-year landing page
    (canonical ``…/make/model/``, no year) when a year-specific page doesn't
    exist, so without this guard a 2015 car could be priced off 2026 data.
    """
    if expected_year is not None:
        cm = re.search(r'<link rel="canonical" href="([^"]*)"', html)
        canonical = cm.group(1) if cm else ""
        if f"/{expected_year}/" not in canonical:
            logger.debug("KBB page canonical %r lacks year %d — rejecting", canonical, expected_year)
            return None

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    trims: dict[str, float] = {}
    averages: list[float] = []

    def walk(o: object) -> None:
        if isinstance(o, dict):
            name = o.get("trimName") or o.get("name")
            lo, hi = o.get("fairMarketPriceLow"), o.get("fairMarketPriceHigh")
            if name:
                vals = [float(v) for v in (lo, hi) if isinstance(v, (int, float)) and v > 0]
                if vals:
                    trims[_norm(str(name))] = sum(vals) / len(vals)
            fmp = o.get("fairMarketPrice")
            if isinstance(fmp, dict):
                a = fmp.get("ymmtAverage") or fmp.get("ymmtLow")
                if isinstance(a, (int, float)) and a > 0:
                    averages.append(float(a))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)

    if not trims and not averages:
        return None
    if trims:
        mids = sorted(trims.values())
        default = mids[len(mids) // 2]  # median trim price
    else:
        default = averages[0]

    # Studio model image (EVOX) — exact model+year because the page already
    # passed the year guard. Used as a photo fallback for listings without one.
    img_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    image = img_m.group(1) if img_m and "evox" in img_m.group(1).lower() else None

    return {
        "default": round(default),
        "trims": {k: round(v) for k, v in trims.items()},
        "image": image,
    }


async def fetch_fair_values(client: httpx.AsyncClient, make: str, model: str, year: int) -> dict | None:
    """Fetch the KBB Fair Market Price for one vehicle, trying slug variants."""
    for slug in _slug_variants(make, model):
        url = f"{_KBB_BASE}/{slug}/{year}/"
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.debug("KBB value request failed for %s: %s", url, exc)
            continue
        if resp.status_code == 200:
            vals = parse_fair_values(resp.text, expected_year=year)
            if vals:
                return vals
        logger.debug("KBB value page %s -> %d (no usable data)", url, resp.status_code)
    return None
