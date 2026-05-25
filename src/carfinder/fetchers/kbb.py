"""KBB (Kelley Blue Book) fetcher — scrape vehicle listings from KBB.com."""
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

# Browser-like headers to avoid bot detection
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _parse_search_results(html: str, config: Config) -> list[dict]:
    """Parse KBB search results page and extract vehicle data."""
    soup = BeautifulSoup(html, "html.parser")
    vehicles = []
    
    # KBB uses JavaScript-rendered content, so we need to look for JSON data
    # First, try to find embedded JSON data
    scripts = soup.find_all("script")
    for script in scripts:
        if script.string and "vehicle" in script.string and "price" in script.string:
            # Try to extract JSON data
            try:
                # Look for JSON-like patterns
                json_match = re.search(r'(\{.*"vehicle".*"price".*\})', script.string, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group(1))
                    # Process the structured data
                    vehicle_data = _extract_vehicle_data(data)
                    if vehicle_data:
                        vehicles.append(vehicle_data)
            except (json.JSONDecodeError, KeyError):
                continue
    
    # If no JSON found, try parsing HTML elements
    if not vehicles:
        # Look for vehicle cards in the HTML
        vehicle_cards = soup.find_all(["div", "article"], class_=re.compile(r"vehicle|card|listing", re.I))
        
        for card in vehicle_cards:
            try:
                vehicle_data = _parse_vehicle_card(card)
                if vehicle_data:
                    vehicles.append(vehicle_data)
            except Exception as e:
                logger.debug(f"Error parsing vehicle card: {e}")
                continue
    
    return vehicles


def _extract_vehicle_data(data: dict) -> dict | None:
    """Extract vehicle information from KBB JSON data."""
    try:
        # This is a simplified extraction - actual KBB structure may vary
        vehicle = data.get("vehicle", {})
        price_info = data.get("price", {})
        
        return {
            "year": vehicle.get("year"),
            "make": vehicle.get("make"),
            "model": vehicle.get("model"),
            "trim": vehicle.get("trim"),
            "mileage": vehicle.get("mileage"),
            "price": price_info.get("amount"),
            "url": data.get("url"),
            "vin": vehicle.get("vin"),
            "body_type": vehicle.get("bodyStyle"),
            "drivetrain": vehicle.get("driveTrain"),
            "transmission": vehicle.get("transmission"),
            "fuel_type": vehicle.get("fuelType"),
            "exterior_color": vehicle.get("exteriorColor"),
            "interior_color": vehicle.get("interiorColor"),
        }
    except Exception:
        return None


def _parse_vehicle_card(card) -> dict | None:
    """Parse individual vehicle card from HTML."""
    try:
        # Extract basic information using common HTML patterns
        title_elem = card.find(["h2", "h3", "h4", "div"], class_=re.compile(r"title|heading", re.I))
        title = title_elem.get_text(strip=True) if title_elem else ""
        
        # Try to parse year/make/model from title
        year_match = re.search(r"\b(19|20)\d{2}\b", title)
        year = int(year_match.group()) if year_match else None
        
        # Extract price
        price_elem = card.find(["span", "div"], class_=re.compile(r"price", re.I))
        price_text = price_elem.get_text(strip=True) if price_elem else ""
        price_match = re.search(r"\$([0-9,]+)", price_text)
        price = int(price_match.group(1).replace(",", "")) if price_match else None
        
        # Extract mileage
        mileage_elem = card.find(["span", "div"], class_=re.compile(r"mile|odo", re.I))
        mileage_text = mileage_elem.get_text(strip=True) if mileage_elem else ""
        mileage_match = re.search(r"([0-9,]+)\s*(miles?|mi)", mileage_text, re.I)
        mileage = int(mileage_match.group(1).replace(",", "")) if mileage_match else None
        
        # Extract URL
        link_elem = card.find("a", href=True)
        url = link_elem["href"] if link_elem else None
        
        return {
            "year": year,
            "make": None,  # Would need more sophisticated parsing
            "model": None,  # Would need more sophisticated parsing
            "price": price,
            "mileage": mileage,
            "url": url,
        }
    except Exception:
        return None


def _vehicle_to_listing(vehicle: dict, config: Config) -> Listing | None:
    """Convert KBB vehicle data to Listing model."""
    try:
        # Extract basic information
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
        transmission = vehicle.get("transmission")
        fuel_type = vehicle.get("fuel_type")
        
        # Create listing
        listing = Listing(
            source="kbb",
            source_id=vin or url or f"kbb-{hashlib.sha1(repr(sorted(vehicle.items())).encode()).hexdigest()[:16]}",  # Generate stable ID if no VIN
            url=url,
            year=year,
            make=make,
            model=model,
            trim=trim,
            body_type=body_type,
            drivetrain=drivetrain,
            transmission=transmission,
            fuel_type=fuel_type,
            mileage=mileage,
            asking_price=float(price) if price else None,
            vin=vin,
            seller_type="dealer",  # KBB listings are typically dealer listings
        )
        
        return listing
    except Exception as e:
        logger.error(f"Error converting KBB vehicle to listing: {e}")
        return None


class KBBFetcher(BaseFetcher):
    """Async fetcher for KBB listings."""
    
    BASE_URL = "https://www.kbb.com"
    SEARCH_URL = f"{BASE_URL}/used-cars/"
    
    async def fetch_listings(self, config: Config) -> AsyncIterator[Listing]:
        """Fetch used-car listings from KBB."""
        logger.info("Fetching KBB listings")
        
        # Build search parameters
        params = self._build_params(config)
        
        async with httpx.AsyncClient(
            http2=True,
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            try:
                # Fetch search results page
                logger.debug(f"Fetching KBB search: {self.SEARCH_URL}")
                response = await self._retry_request(
                    client, "GET", self.SEARCH_URL, params=params
                )
                
                if response.status_code != 200:
                    logger.error(f"KBB search failed with status {response.status_code}")
                    return
                
                # Parse search results
                vehicles = _parse_search_results(response.text, config)
                logger.info(f"Parsed {len(vehicles)} vehicles from KBB")
                
                # Convert to listings
                for vehicle in vehicles:
                    listing = _vehicle_to_listing(vehicle, config)
                    if listing:
                        yield listing
                    await asyncio.sleep(0.1)  # Small delay between processing
                    
            except Exception as e:
                logger.error(f"Error fetching KBB listings: {e}")
                return
    
    def _build_params(self, config: Config) -> dict:
        """Build search parameters for KBB request."""
        params = {}
        
        # Add ZIP code for location-based search
        if config.zip:
            params["zip"] = config.zip
            
        # Add radius
        params["radius"] = config.radius_miles
        
        # Add price range
        if config.budget.min:
            params["priceMin"] = int(config.budget.min)
        if config.budget.max:
            params["priceMax"] = int(config.budget.max)
            
        # Add mileage limit
        if config.mileage.max:
            params["mileageMax"] = config.mileage.max
            
        return params
