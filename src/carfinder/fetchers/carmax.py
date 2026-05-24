"""CarMax async fetcher.

Pagination trade-off: CarMax SSR bakes 24 listings per page with no server-side
?page=N parameter. Each httpx call returns the first 24 results for the given
filter combination. To cover more inventory we run a second wider query when
config.carmax_include_transfer is true and the first query signals >24 total.
We cap at 5 queries per run (~120 listings max) — sufficient for a personal MVP.
If CarMax ever adds a pagination parameter this cap can be removed.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from carfinder.config import Config
from carfinder.fetchers.base import BaseFetcher
from carfinder.models import Listing

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browser-like headers required to pass Akamai bot check.
# Minimal UA-only headers return 403. Full Sec-Fetch-* + sec-ch-ua headers
# are required. No cookies needed for SSR response. See spike-results.md.
# ---------------------------------------------------------------------------
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

# Rough transfer fee estimate: $1500 base + $5/mile beyond local radius.
_TRANSFER_BASE = 1500
_TRANSFER_PER_MILE = 5

MAX_QUERIES = 5  # defensive cap — see module docstring


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _extract_cars(html: str) -> list[dict]:
    """Extract the `const cars = [...]` array from CarMax SSR HTML.

    Uses bracket-matching to handle nested arrays/objects robustly.
    Returns an empty list if the block is not found.
    """
    for block in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        if "const cars = [" not in block:
            continue
        start = block.index("const cars = [") + len("const cars = ")
        depth, i = 0, start
        while i < len(block):
            ch = block[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(block[start : i + 1])
                    except json.JSONDecodeError:
                        logger.warning("Failed to JSON-parse cars block")
                        return []
            i += 1
    return []


def _parse_total_results(html: str) -> int | None:
    """Parse total result count from CarMax SSR HTML.

    Tries JSON-embedded totalCount first (most reliable), then text patterns.
    Returns None if not found.
    """
    # JSON-embedded: "totalCount":1558
    m = re.search(r'"totalCount"\s*:\s*(\d+)', html)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    # Text fallback: "1,558 cars" style
    m = re.search(r"([\d,]+)\s+(?:cars?|vehicles?)\b", html, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Vehicle → Listing mapping
# ---------------------------------------------------------------------------

def _estimate_transfer_fee(distance: float, local_radius: int) -> str:
    """Compute a rough transfer fee string for vehicles beyond local radius."""
    extra_miles = max(0.0, distance - local_radius)
    estimate = _TRANSFER_BASE + int(extra_miles * _TRANSFER_PER_MILE)
    return f"transfer ~${estimate:,}"


# CarMax returns body types like "4D Sedan", "4D Crew Cab", "4D Pass Ext Van".
# The scorer expects normalized strings: "SUV", "Sedan", "Wagon", "Hatchback",
# "Coupe", "Truck", "Van", "Convertible". Map the common CarMax variants.
_BODY_TYPE_MAP = {
    "sedan": "Sedan",
    "hatchback": "Hatchback",
    "wagon": "Wagon",
    "coupe": "Coupe",
    "convertible": "Convertible",
    "sport utility": "SUV",
    "suv": "SUV",
    "crossover": "SUV",
    "crew cab": "Truck",
    "extended cab": "Truck",
    "regular cab": "Truck",
    "pickup": "Truck",
    "truck": "Truck",
    "pass van": "Van",
    "pass ext van": "Van",
    "cargo van": "Van",
    "minivan": "Van",
    "van": "Van",
}


def _normalize_body_type(raw: str | None) -> str | None:
    if not raw:
        return None
    lowered = raw.lower()
    # CarMax prefixes like "4D " or "2D " — strip and try each suffix substring.
    for key, normalized in _BODY_TYPE_MAP.items():
        if key in lowered:
            return normalized
    return raw  # leave unchanged if no match — scorer will mark estimated


def _vehicle_to_listing(vehicle: dict, config: Config) -> Listing:
    """Map a CarMax vehicle dict (71 fields) to a Listing."""
    stock = str(vehicle.get("stockNumber", ""))
    now = datetime.now(timezone.utc)

    distance = vehicle.get("distance")  # miles from search zip

    # Transfer fee: set if vehicle is beyond local radius
    transfer_fee: str | None = None
    if (
        config.carmax_include_transfer
        and distance is not None
        and distance > config.radius_miles
    ):
        transfer_fee = _estimate_transfer_fee(float(distance), config.radius_miles)

    # Photos: heroImageUrl first, then up to 4 more (CarMax SSR only has hero)
    photos: list[str] = []
    hero = vehicle.get("heroImageUrl")
    if hero:
        photos.append(hero)

    # MPG: CarMax provides city/highway; compute combined as harmonic mean if both present
    mpg_city = vehicle.get("mpgCity")
    mpg_hwy = vehicle.get("mpgHighway")
    mpg_combined: float | None = None
    if mpg_city and mpg_hwy:
        mpg_combined = round(2 * mpg_city * mpg_hwy / (mpg_city + mpg_hwy), 1)

    # Location: prefer storeCity, fallback storeName
    location = vehicle.get("storeCity") or vehicle.get("storeName")
    if vehicle.get("stateAbbreviation"):
        location = f"{location}, {vehicle['stateAbbreviation']}" if location else vehicle["stateAbbreviation"]

    # Transmission: normalize to lowercase
    trans_raw = vehicle.get("transmission", "")
    transmission = trans_raw.lower() if trans_raw else None

    # Body type / fuel
    body_type = _normalize_body_type(vehicle.get("body"))
    fuel_type = vehicle.get("fuelType") or vehicle.get("engineType")
    if fuel_type:
        fuel_type = fuel_type.lower()

    return Listing(
        id=f"carmax:{stock}",
        source="carmax",
        source_id=stock,
        url=f"https://www.carmax.com/car/{stock}",
        year=vehicle.get("year"),
        make=vehicle.get("make"),
        model=vehicle.get("model"),
        trim=vehicle.get("trim"),
        body_type=body_type,
        drivetrain=vehicle.get("driveTrain"),
        transmission=transmission,
        fuel_type=fuel_type,
        mpg_combined=mpg_combined,
        vin=vehicle.get("vin"),
        mileage=vehicle.get("mileage"),
        title_status="clean",  # CarMax certifies all inventory
        asking_price=vehicle.get("basePrice"),
        seller_type="dealer",
        location=location,
        distance_miles=distance,
        transfer_fee=transfer_fee,
        photos=photos[:5],
        first_seen=now,
        last_seen=now,
    )


# ---------------------------------------------------------------------------
# CarMaxFetcher
# ---------------------------------------------------------------------------

class CarMaxFetcher(BaseFetcher):
    """Async fetcher for CarMax listings via SSR HTML parsing."""

    BASE_URL = "https://www.carmax.com/cars/all"

    async def fetch_listings(self, config: Config) -> AsyncIterator[Listing]:
        """Yield Listing objects from CarMax search results.

        Runs the primary local query first. If carmax_include_transfer is enabled
        and the primary response signals >24 total results, also runs a wider
        transfer query to surface additional inventory.
        """
        async with httpx.AsyncClient(
            http2=True,
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            seen_stock: set[str] = set()
            query_count = 0

            # --- Primary local query ---
            local_params = self._build_params(config, distance=config.radius_miles)
            logger.info("CarMax local query: %s", local_params)

            try:
                response = await self._retry_request(client, "GET", self.BASE_URL, params=local_params)
            except Exception as exc:
                logger.warning("CarMax local query failed: %s", exc)
                return

            if response.status_code != 200:
                logger.warning("CarMax returned HTTP %d for local query", response.status_code)
                return

            query_count += 1
            vehicles = _extract_cars(response.text)
            logger.info("CarMax local query: %d vehicles parsed", len(vehicles))

            for vehicle in vehicles:
                stock = str(vehicle.get("stockNumber", ""))
                if stock and stock in seen_stock:
                    continue
                seen_stock.add(stock)
                yield _vehicle_to_listing(vehicle, config)

            # --- Transfer query (wider radius) ---
            if not config.carmax_include_transfer:
                return

            total = _parse_total_results(response.text)
            logger.info("CarMax total results signal: %s", total)

            if total is None or total <= 24:
                return  # no additional inventory to surface

            if query_count >= MAX_QUERIES:
                logger.info("CarMax: MAX_QUERIES (%d) reached, stopping", MAX_QUERIES)
                return

            await self._rate_limit_sleep()

            transfer_params = self._build_params(config, distance=config.carmax_max_transfer_miles)
            logger.info("CarMax transfer query: distance=%d", config.carmax_max_transfer_miles)

            try:
                response2 = await self._retry_request(
                    client, "GET", self.BASE_URL, params=transfer_params
                )
            except Exception as exc:
                logger.warning("CarMax transfer query failed: %s", exc)
                return

            if response2.status_code != 200:
                logger.warning("CarMax returned HTTP %d for transfer query", response2.status_code)
                return

            query_count += 1
            vehicles2 = _extract_cars(response2.text)
            logger.info("CarMax transfer query: %d vehicles parsed", len(vehicles2))

            for vehicle in vehicles2:
                stock = str(vehicle.get("stockNumber", ""))
                if stock and stock in seen_stock:
                    continue
                seen_stock.add(stock)
                yield _vehicle_to_listing(vehicle, config)

    def _build_params(self, config: Config, distance: int) -> dict[str, str]:
        """Build CarMax query params from config.

        CarMax URL params (verified 2026-05-23):
        - `price` is the single max-price filter (NOT `priceMax`).
        - There is no min-price URL filter — applied client-side after fetch.
        - `transmission=Automatic` filters at the source.
        """
        params: dict[str, str] = {
            "zip": config.zip,
            "distance": str(distance),
            "price": str(int(config.budget.max)),
        }
        if config.transmission.exclude_manual:
            params["transmission"] = "Automatic"
        return params
