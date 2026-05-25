"""Cars.com fetcher — parses data-vehicle-details JSON from SSR listing cards.

Cars.com renders listing data in data-vehicle-details attributes on each card.
Price/mileage filters are client-side only so we post-filter after parsing.
All Cars.com listings are dealer inventory; CPO listings get seller_type="certified".
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx
from selectolax.parser import HTMLParser

from carfinder.config import Config
from carfinder.fetchers.base import BaseFetcher
from carfinder.models import Listing

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cars.com/shopping/results/"
MAX_PAGES = 10

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="120", "Google Chrome";v="120", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Referer": "https://www.cars.com/",
    "Origin": "https://www.cars.com",
}


class CarsDotComFetcher(BaseFetcher):
    """Fetch used-car listings from Cars.com via SSR HTML parsing."""

    async def fetch_listings(self, config: Config) -> AsyncIterator[Listing]:
        async with httpx.AsyncClient(
            http2=True,
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            for page in range(1, MAX_PAGES + 1):
                params = {
                    "stock_type": "used",
                    "zip": config.zip,
                    "maximum_distance": config.radius_miles,
                    "sort": "best_match_desc",
                    "page_number": page,
                }
                try:
                    resp = await self._retry_request(client, "GET", BASE_URL, params=params)
                except Exception as exc:
                    logger.error("cars.com page %d failed: %s", page, exc)
                    break

                if resp.status_code != 200:
                    logger.warning("cars.com HTTP %d on page %d", resp.status_code, page)
                    break

                page_listings = _parse_search_page(resp.text, config)
                if not page_listings:
                    logger.info("cars.com page %d: no listings, stopping", page)
                    break

                for listing in page_listings:
                    yield listing

                await self._rate_limit_sleep()


def _parse_search_page(html: str, config: Config) -> list[Listing]:
    """Parse a Cars.com results page and return budget/mileage-filtered listings."""
    tree = HTMLParser(html)
    listings: list[Listing] = []

    for node in tree.css("[data-listing-id]"):
        raw = node.attributes.get("data-vehicle-details")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        listing = _map_vehicle(data)
        if listing is None:
            continue

        # Post-filter: price and mileage (Cars.com strips these from URL params)
        if listing.asking_price is not None:
            if listing.asking_price < config.budget.min or listing.asking_price > config.budget.max:
                continue
        if listing.mileage is not None and listing.mileage > config.mileage.max:
            continue

        listings.append(listing)

    return listings


def _map_vehicle(data: dict) -> Listing | None:
    listing_id = data.get("listingId") or ""
    if not listing_id:
        return None

    thumb = data.get("primaryThumbnail")
    seller_type = "certified" if data.get("cpoIndicator") else "dealer"

    dealer_zip = _clean(data.get("zip"))
    dealer_city = _clean(data.get("city"))
    dealer_state = _clean(data.get("state"))
    if dealer_city and dealer_state:
        location = f"{dealer_city}, {dealer_state}"
    elif dealer_city:
        location = dealer_city
    else:
        location = dealer_zip  # fall back to zip for haversine lookup

    return Listing(
        id=f"carscom-{listing_id}",
        source="carscom",
        source_id=listing_id,
        url=f"https://www.cars.com/vehicledetail/{listing_id}/",
        year=_safe_int(data.get("year")),
        make=_clean(data.get("make")),
        model=_clean(data.get("model")),
        trim=_clean(data.get("trim")),
        body_type=_clean(data.get("bodyStyle")),
        fuel_type=_clean(data.get("fuelType")),
        mileage=_safe_int(data.get("mileage")),
        asking_price=_safe_float(data.get("price")),
        seller_type=seller_type,
        photos=[thumb] if thumb else [],
        location=location,
    )


def _safe_float(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clean(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
