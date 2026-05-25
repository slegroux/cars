"""KBB (Kelley Blue Book) fetcher — scrape vehicle listings from KBB.com.

Extraction strategy (as of 2026-05):
  KBB is a Next.js app.  The search results page at /cars-for-sale/used/ embeds
  all listing data server-side inside a <script id="__NEXT_DATA__"> JSON blob.

  Path to listings:
    data["props"]["pageProps"]["__eggsState"]["inventory"]
      → dict keyed by listing-ID string, each value is a full listing object.

  Key fields per listing:
    year, vin, make.name, model.name, trim.name,
    pricingDetail.salePrice, mileage.value (string "27,800"),
    driveType.name, fuelType.name, bodyStyles[0].name,
    color.exteriorColor, color.interiorColor,
    vdpBaseUrl (relative URL), listingType ("USED"/"CERTIFIED"/"NEW")

  Fallback: if __eggsState.inventory is absent or empty the function returns []
  and the fetcher logs a warning (likely bot-detection or page structure change).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING, AsyncIterator

import httpx
from bs4 import BeautifulSoup

from carfinder.fetchers.base import BaseFetcher
from carfinder.models import Listing

if TYPE_CHECKING:
    from carfinder.config import Config

logger = logging.getLogger(__name__)

# Browser-like headers to pass bot detection
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_KBB_BASE = "https://www.kbb.com"


def _parse_search_results(html: str, config: Config) -> list[dict]:
    """Parse KBB search results page and extract vehicle data.

    KBB uses Next.js SSR — all listing data is embedded in a
    <script id="__NEXT_DATA__" type="application/json"> tag.

    The listings live at:
      props.pageProps.__eggsState.inventory
        → dict keyed by listing-ID, each value is a listing object.

    Falls back to an empty list (with a warning) if the expected path is
    missing — this signals either a page-structure change or bot-detection.
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Primary path: __NEXT_DATA__ JSON ---
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            data = json.loads(next_data_tag.string)
            inventory: dict = (
                data
                .get("props", {})
                .get("pageProps", {})
                .get("__eggsState", {})
                .get("inventory", {})
            )
            if inventory:
                vehicles = []
                for listing_id, item in inventory.items():
                    vehicle = _extract_vehicle_from_eggs(listing_id, item)
                    if vehicle:
                        vehicles.append(vehicle)
                logger.debug("Extracted %d vehicles from __NEXT_DATA__", len(vehicles))
                return vehicles
            else:
                logger.warning(
                    "KBB __NEXT_DATA__ found but inventory is empty — "
                    "possible bot-detection or page-structure change"
                )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to parse KBB __NEXT_DATA__: %s", exc)

    # --- Fallback: HTML card parse ---
    logger.debug("Falling back to KBB HTML card parse")
    vehicles = []
    vehicle_cards = soup.find_all(
        ["div", "article"], attrs={"data-listing-id": True}
    )
    if not vehicle_cards:
        vehicle_cards = soup.find_all(
            ["div", "article"], class_=re.compile(r"vehicle|card|listing", re.I)
        )
    for card in vehicle_cards:
        try:
            vehicle = _parse_vehicle_card(card)
            if vehicle:
                vehicles.append(vehicle)
        except Exception as exc:
            logger.debug("Error parsing vehicle card: %s", exc)

    if not vehicles:
        logger.warning(
            "KBB parser returned 0 vehicles — the page may require JavaScript "
            "rendering (bot-detection). Consider Playwright integration."
        )
    return vehicles


def _extract_vehicle_from_eggs(listing_id: str, item: dict) -> dict | None:
    """Map a single __eggsState.inventory entry to a normalized vehicle dict."""
    try:
        price_raw = item.get("pricingDetail", {}).get("salePrice")
        price = int(price_raw) if price_raw is not None else None

        mileage_str = item.get("mileage", {}).get("value", "")
        mileage_digits = re.sub(r"[^0-9]", "", mileage_str)
        mileage = int(mileage_digits) if mileage_digits else None

        body_styles = item.get("bodyStyles", [])
        body_type = body_styles[0].get("name") if body_styles else None

        vdp = item.get("vdpBaseUrl", "")
        url = f"{_KBB_BASE}{vdp}" if vdp and vdp.startswith("/") else vdp or None

        return {
            "listing_id": listing_id,
            "year": item.get("year"),
            "make": item.get("make", {}).get("name"),
            "model": item.get("model", {}).get("name"),
            "trim": item.get("trim", {}).get("name"),
            "mileage": mileage,
            "price": price,
            "url": url,
            "vin": item.get("vin"),
            "body_type": body_type,
            "drivetrain": item.get("driveType", {}).get("name"),
            "fuel_type": item.get("fuelType", {}).get("name"),
            "exterior_color": item.get("color", {}).get("exteriorColor"),
            "interior_color": item.get("color", {}).get("interiorColor"),
            "listing_type": item.get("listingType"),
        }
    except Exception as exc:
        logger.debug("Error extracting vehicle %s: %s", listing_id, exc)
        return None


def _parse_vehicle_card(card) -> dict | None:
    """Parse individual vehicle card from HTML (fallback path)."""
    try:
        # listing ID from data attribute
        listing_id = card.get("data-listing-id")

        title_elem = card.find(["h2", "h3", "h4", "div"], class_=re.compile(r"title|heading", re.I))
        title = title_elem.get_text(strip=True) if title_elem else ""

        year_match = re.search(r"\b(19|20)\d{2}\b", title)
        year = int(year_match.group()) if year_match else None

        price_elem = card.find(["span", "div"], class_=re.compile(r"price", re.I))
        price_text = price_elem.get_text(strip=True) if price_elem else ""
        price_match = re.search(r"\$([0-9,]+)", price_text)
        price = int(price_match.group(1).replace(",", "")) if price_match else None

        mileage_elem = card.find(["span", "div"], class_=re.compile(r"mile|odo", re.I))
        mileage_text = mileage_elem.get_text(strip=True) if mileage_elem else ""
        mileage_match = re.search(r"([0-9,]+)\s*(miles?|mi)", mileage_text, re.I)
        mileage = int(mileage_match.group(1).replace(",", "")) if mileage_match else None

        link_elem = card.find("a", href=True)
        url = link_elem["href"] if link_elem else None

        return {
            "listing_id": listing_id,
            "year": year,
            "make": None,
            "model": None,
            "price": price,
            "mileage": mileage,
            "url": url,
        }
    except Exception:
        return None


def _vehicle_to_listing(vehicle: dict, config: Config) -> Listing | None:
    """Convert KBB vehicle data to Listing model."""
    try:
        year = vehicle.get("year")
        make = vehicle.get("make")
        model = vehicle.get("model")
        trim = vehicle.get("trim")
        mileage = vehicle.get("mileage")
        price = vehicle.get("price")
        url = vehicle.get("url")
        vin = vehicle.get("vin")
        body_type = vehicle.get("body_type")
        drivetrain = vehicle.get("drivetrain")
        fuel_type = vehicle.get("fuel_type")

        # Stable source_id: prefer VIN, then listing_id, then hash of vehicle data
        listing_id = vehicle.get("listing_id")
        source_id = (
            vin
            or (f"kbb-{listing_id}" if listing_id else None)
            or f"kbb-{hashlib.sha1(repr(sorted(vehicle.items())).encode()).hexdigest()[:16]}"
        )

        return Listing(
            source="kbb",
            source_id=source_id,
            url=url,
            year=year,
            make=make,
            model=model,
            trim=trim,
            body_type=body_type,
            drivetrain=drivetrain,
            fuel_type=fuel_type,
            mileage=mileage,
            asking_price=float(price) if price is not None else None,
            vin=vin,
            seller_type="dealer",
        )
    except Exception as exc:
        logger.error("Error converting KBB vehicle to listing: %s", exc)
        return None


class KBBFetcher(BaseFetcher):
    """Async fetcher for KBB listings.

    Fetches from /cars-for-sale/used/ which redirects to a city-specific URL
    and embeds all listing data server-side in __NEXT_DATA__ JSON.
    """

    BASE_URL = "https://www.kbb.com"
    SEARCH_URL = f"{BASE_URL}/cars-for-sale/used/"

    async def fetch_listings(self, config: Config) -> AsyncIterator[Listing]:
        """Fetch used-car listings from KBB."""
        logger.info("Fetching KBB listings")

        params = self._build_params(config)

        async with httpx.AsyncClient(
            http2=True,
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            try:
                logger.debug("Fetching KBB search: %s params=%s", self.SEARCH_URL, params)
                response = await self._retry_request(
                    client, "GET", self.SEARCH_URL, params=params
                )

                if response.status_code != 200:
                    logger.error("KBB search failed with status %d", response.status_code)
                    return

                vehicles = _parse_search_results(response.text, config)
                logger.info("Parsed %d vehicles from KBB", len(vehicles))

                for vehicle in vehicles:
                    listing = _vehicle_to_listing(vehicle, config)
                    if listing:
                        yield listing
                    await asyncio.sleep(0.1)

            except Exception as exc:
                logger.error("Error fetching KBB listings: %s", exc)
                return

    def _build_params(self, config: Config) -> dict:
        """Build search parameters for KBB request."""
        params: dict = {}

        if config.zip:
            params["zip"] = config.zip

        params["radius"] = config.radius_miles

        if config.budget.min:
            params["priceMin"] = int(config.budget.min)
        if config.budget.max:
            params["priceMax"] = int(config.budget.max)

        if config.mileage.max:
            params["mileageMax"] = config.mileage.max

        return params
