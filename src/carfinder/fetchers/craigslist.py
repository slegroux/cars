"""Craigslist async fetcher."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import httpx
import yaml
from selectolax.parser import HTMLParser

from carfinder.config import Config
from carfinder.fetchers.base import BaseFetcher
from carfinder.models import Listing

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"

# Canonical makes loaded from reliability_tiers.yaml keys
_KNOWN_MAKES: list[str] = []


def _load_known_makes() -> list[str]:
    """Load make names from reliability_tiers.yaml."""
    path = _DATA_DIR / "reliability_tiers.yaml"
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        # Keys like "MercedesBenz" → "Mercedes Benz"; preserve as-is for lookup
        return list(data.keys())
    except Exception:
        return []


def _get_known_makes() -> list[str]:
    global _KNOWN_MAKES
    if not _KNOWN_MAKES:
        _KNOWN_MAKES = _load_known_makes()
    return _KNOWN_MAKES


# ---------------------------------------------------------------------------
# Title parsing helpers
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"(\d{4})\s+([A-Za-z][A-Za-z\-]*)\s+(.+)")


def parse_title(title: str) -> tuple[int | None, str | None, str | None]:
    """Extract (year, make, model) from a CL title string.

    Tries regex match, then normalizes make against known makes list.
    Returns (None, None, None) if no year found.
    """
    # Strip emoji and extra punctuation
    clean = re.sub(r"[^\w\s\-/]", " ", title).strip()
    clean = re.sub(r"\s+", " ", clean)

    m = _TITLE_RE.search(clean)
    if not m:
        return None, None, None

    year_str, raw_make, rest = m.group(1), m.group(2), m.group(3)

    try:
        year = int(year_str)
        if year < 1900 or year > 2100:
            return None, None, None
    except ValueError:
        return None, None, None

    # Normalize make
    make = _normalize_make(raw_make)

    # model is first word of rest; store full rest as model (includes trim)
    # Strip trailing price/noise like "- $7500" or "clean title"
    rest_clean = re.sub(r"\s*[-–]\s*\$?\d[\d,]*.*$", "", rest).strip()
    rest_clean = re.sub(r"\s+", " ", rest_clean)
    model = rest_clean if rest_clean else rest.split()[0] if rest.split() else None

    return year, make, model


def _split_model_trim(model: str) -> tuple[str, str | None]:
    """Split 'RAV4 XLE' into ('RAV4', 'XLE'). Returns ('RAV4', None) when no trim."""
    if not model:
        return model, None
    parts = model.strip().split(None, 1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1] or None


def _normalize_make(raw: str) -> str:
    """Normalize raw make string to title case, matching known makes if possible."""
    raw_lower = raw.lower().replace("-", "").replace(" ", "")
    known = _get_known_makes()

    for known_make in known:
        if known_make.lower().replace(" ", "") == raw_lower:
            # Insert space before capitals for display (e.g. MercedesBenz → Mercedes Benz)
            spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", known_make)
            return spaced

    # Fallback: title case
    return raw.title()


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else None


def _extract_source_id_from_url(url: str) -> str:
    """Extract the numeric post ID from a CL URL slug."""
    m = re.search(r"/(\d+)\.html", url)
    return m.group(1) if m else url


def _parse_search_page(html: str) -> list[dict]:
    """Parse a CL search results page. Returns list of card dicts.

    Handles three known CL layouts:
    1. Current (2025+): li.cl-static-search-result > a > div.title + div.price + div.location
    2. Mid (2020s): li.cl-static-search-result with data-pid + a.titlestring + span.result-price
    3. Old: li.result-row with a.result-title + span.result-price + span.result-hood
    """
    tree = HTMLParser(html)
    cards = []

    # Try new layout first, then old
    items = tree.css("li.cl-static-search-result")
    layout = "new"
    if not items:
        items = tree.css("li.result-row")
        layout = "old"

    for item in items:
        # Skip the "see also" hub-links entry
        if "hub-links" in (item.attributes.get("class") or ""):
            continue

        card: dict = {}

        # --- URL and title ---
        # Layout 1 (current): plain <a> wrapping the card
        link = item.css_first("a")
        if not link:
            continue

        url = link.attributes.get("href", "")
        card["url"] = url

        # Title: try div.title first (current layout), then a.titlestring text,
        # then a.result-title text, then title attribute on li
        title_node = item.css_first("div.title")
        if title_node:
            card["title"] = title_node.text(strip=True)
        elif item.css_first("a.titlestring"):
            card["title"] = item.css_first("a.titlestring").text(strip=True)
        elif item.css_first("a.result-title"):
            card["title"] = item.css_first("a.result-title").text(strip=True)
        else:
            # Fallback: title attribute on li, or link text
            card["title"] = item.attributes.get("title") or link.text(strip=True)

        if not card.get("title"):
            continue

        # source_id: prefer data-pid, then extract from URL
        source_id = item.attributes.get("data-pid", "")
        if not source_id:
            source_id = _extract_source_id_from_url(url)
        card["source_id"] = source_id

        # Price: div.price (current) or span.result-price (old)
        price_node = item.css_first("div.price") or item.css_first("span.result-price")
        card["asking_price"] = _parse_price(price_node.text(strip=True) if price_node else None)

        # Location: div.location (current) or span.result-hood (old)
        loc_node = item.css_first("div.location") or item.css_first("span.result-hood")
        card["location"] = loc_node.text(strip=True).strip("() ") if loc_node else None

        # Posting datetime (older layouts only)
        time_node = item.css_first("time")
        card["posted_dt"] = time_node.attributes.get("datetime", "") if time_node else None

        # Thumbnail
        img = item.css_first("img")
        card["thumbnail"] = img.attributes.get("src", "") if img else None

        cards.append(card)

    return cards


def _parse_detail_page(html: str) -> dict:
    """Parse a CL detail page. Returns dict of extracted fields."""
    tree = HTMLParser(html)
    result: dict = {}

    # --- Attribute groups: scan all span.labl/span.valu pairs ---
    # Build a mapping label → value from attrgroup sections
    attr_map: dict[str, str] = {}
    for section in tree.css("section.attrgroup"):
        labels = section.css("span.labl")
        values = section.css("span.valu")
        for lbl, val in zip(labels, values):
            lbl_text = lbl.text(strip=True).lower().rstrip(":")
            val_text = val.text(strip=True)
            attr_map[lbl_text] = val_text

    # Odometer / mileage
    if "odometer" in attr_map:
        try:
            result["mileage"] = int(re.sub(r"[^\d]", "", attr_map["odometer"]))
        except (ValueError, TypeError):
            pass

    # VIN
    if "vin" in attr_map:
        result["vin"] = attr_map["vin"]

    # Title status
    if "title status" in attr_map:
        result["title_status"] = attr_map["title status"].lower()

    # Condition
    if "condition" in attr_map:
        result["condition"] = attr_map["condition"].lower()

    # Transmission
    if "transmission" in attr_map:
        trans_raw = attr_map["transmission"].lower()
        if "manual" in trans_raw or "5-speed" in trans_raw or "6-speed" in trans_raw:
            result["transmission"] = "manual"
        else:
            result["transmission"] = "automatic"

    # Drive / drivetrain
    if "drive" in attr_map:
        result["drivetrain"] = attr_map["drive"].lower()

    # Fuel
    if "fuel" in attr_map:
        result["fuel_type"] = attr_map["fuel"].lower()

    # Body type
    if "type" in attr_map:
        result["body_type"] = attr_map["type"].lower()

    # Paint color (not stored in Listing but ignore)

    # Description — strip "QR Code" prefix boilerplate
    body = tree.css_first("#postingbody")
    if body:
        desc_text = body.text(strip=True)
        # Remove the standard QR code prefix line
        desc_text = re.sub(
            r"^QR\s+Code\s+Link\s+to\s+This\s+Post\s*", "", desc_text, flags=re.IGNORECASE
        ).strip()
        result["description"] = desc_text

    # Photos — collect craigslist image URLs
    photos = []
    for img in tree.css("img"):
        src = img.attributes.get("src", "")
        if "images.craigslist.org" in src:
            photos.append(src)
    result["photos"] = photos

    # Posted date from time element
    time_node = tree.css_first("time.date.timeago")
    if time_node:
        dt_str = time_node.attributes.get("datetime", "")
        result["posted_dt"] = dt_str

    return result


# ---------------------------------------------------------------------------
# CraigslistFetcher
# ---------------------------------------------------------------------------

class CraigslistFetcher(BaseFetcher):
    """Async fetcher for Craigslist Los Angeles cars+trucks."""

    BASE_URL = "https://losangeles.craigslist.org/search/cta"
    MAX_PAGES = 5
    PAGE_SIZE = 120

    async def fetch_listings(self, config: Config) -> AsyncIterator[Listing]:
        """Yield Listing objects from Craigslist search results."""
        headers = {"User-Agent": _USER_AGENT}

        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            async for listing in self._paginate(client, config):
                yield listing

    async def _paginate(
        self, client: httpx.AsyncClient, config: Config
    ) -> AsyncIterator[Listing]:
        """Paginate through search results, yielding Listings."""
        offset = 0

        for page_num in range(self.MAX_PAGES):
            url = self._build_search_url(config, offset)
            logger.info("Fetching search page %d: %s", page_num + 1, url)

            try:
                response = await self._retry_request(client, "GET", url)
            except Exception as exc:
                logger.warning("Failed to fetch search page %d: %s", page_num + 1, exc)
                break

            if response.status_code != 200:
                logger.warning("Non-200 status %d on page %d", response.status_code, page_num + 1)
                break

            cards = _parse_search_page(response.text)
            logger.info("Page %d: found %d cards", page_num + 1, len(cards))

            if not cards:
                logger.info("No results on page %d — stopping pagination", page_num + 1)
                break

            sem = asyncio.Semaphore(4)

            async def _bounded_fetch(card: dict, _sem: asyncio.Semaphore = sem) -> Listing | None:
                async with _sem:
                    await self._rate_limit_sleep()
                    return await self._fetch_and_build_listing(client, card, config)

            tasks = [asyncio.ensure_future(_bounded_fetch(card)) for card in cards]
            for coro in asyncio.as_completed(tasks):
                listing = await coro
                if listing is not None:
                    yield listing

            offset += self.PAGE_SIZE

    def _build_search_url(self, config: Config, offset: int = 0) -> str:
        parts = [
            f"postal={config.zip}",
            f"search_distance={config.radius_miles}",
        ]
        if config.transmission.exclude_manual:
            parts.append("auto_transmission=1")
        parts += [
            f"min_price={int(config.budget.min)}",
            f"max_price={int(config.budget.max)}",
        ]
        if offset > 0:
            parts.append(f"s={offset}")
        return f"{self.BASE_URL}?{'&'.join(parts)}"

    async def _fetch_and_build_listing(
        self,
        client: httpx.AsyncClient,
        card: dict,
        config: Config,
    ) -> Listing | None:
        """Fetch detail page for a card and build a Listing."""
        detail_url = card.get("url", "")
        if not detail_url:
            logger.warning("Card missing URL, skipping: %s", card.get("source_id"))
            return None

        try:
            response = await self._retry_request(client, "GET", detail_url)
        except Exception as exc:
            logger.warning("Failed to fetch detail page %s: %s", detail_url, exc)
            return None

        if response.status_code != 200:
            logger.warning(
                "Non-200 status %d for detail page %s", response.status_code, detail_url
            )
            return None

        detail = _parse_detail_page(response.text)
        return self._build_listing(card, detail, config)

    def _build_listing(self, card: dict, detail: dict, config: Config) -> Listing | None:
        """Merge card + detail dicts into a Listing."""
        source_id = card.get("source_id", "")
        if not source_id:
            # Try to extract from URL slug
            url = card.get("url", "")
            m = re.search(r"/(\d+)\.html", url)
            source_id = m.group(1) if m else url

        if not source_id:
            logger.warning("Cannot determine source_id for card %s", card)
            return None

        title = card.get("title", "")
        year, make, parsed_model = parse_title(title)
        model, trim = _split_model_trim(parsed_model or "")
        if not model:
            model = None

        now = datetime.now(timezone.utc)

        # Parse posted date
        posted_date = None
        posted_dt_str = detail.get("posted_dt") or card.get("posted_dt")
        if posted_dt_str:
            try:
                dt = datetime.fromisoformat(posted_dt_str.replace("Z", "+00:00"))
                posted_date = dt.date()
            except (ValueError, TypeError):
                pass

        listing = Listing(
            id=f"craigslist:{source_id}",
            source="craigslist",
            source_id=source_id,
            url=card.get("url"),
            year=year,
            make=make,
            model=model,
            trim=trim or None,
            title_status=detail.get("title_status"),
            condition=detail.get("condition"),
            transmission=detail.get("transmission"),
            drivetrain=detail.get("drivetrain"),
            fuel_type=detail.get("fuel_type"),
            body_type=detail.get("body_type"),
            vin=detail.get("vin"),
            mileage=detail.get("mileage"),
            asking_price=card.get("asking_price"),
            seller_type="private",
            location=card.get("location"),
            distance_miles=None,
            photos=(
                [p for p in ([card.get("thumbnail")] + detail.get("photos", [])) if p]
                if card.get("thumbnail")
                else detail.get("photos", [])
            ),
            description=detail.get("description"),
            posted_date=posted_date,
            first_seen=now,
            last_seen=now,
        )
        return listing
