"""Base fetcher ABC."""
from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

from carfinder.config import Config
from carfinder.models import Listing

logger = logging.getLogger(__name__)


class BaseFetcher(ABC):
    """Abstract base class for all listing fetchers."""

    def __init__(self, config: Config) -> None:
        self.config = config

    @abstractmethod
    async def fetch_listings(self, config: Config) -> AsyncIterator[Listing]:
        """Yield Listing objects from the source."""
        ...

    async def _rate_limit_sleep(self) -> None:
        """Sleep a random interval as configured in rate_limit."""
        delay = random.uniform(
            self.config.rate_limit.min_delay_seconds,
            self.config.rate_limit.max_delay_seconds,
        )
        logger.info("Rate-limit sleep %.1fs", delay)
        await asyncio.sleep(delay)

    async def _retry_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Send an HTTP request with exponential-backoff retry.

        Retries on 429/503/timeout up to config.retry.max_retries times.
        Backoff: 2s, 4s, 8s (base^attempt).
        """
        cfg = self.config.retry
        last_exc: Exception | None = None

        for attempt in range(cfg.max_retries + 1):
            try:
                response = await client.request(method, url, **kwargs)
                if response.status_code in cfg.retryable_status:
                    wait = cfg.backoff_base ** attempt
                    logger.warning(
                        "HTTP %d from %s — retrying in %.0fs (attempt %d/%d)",
                        response.status_code,
                        url,
                        wait,
                        attempt + 1,
                        cfg.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < cfg.max_retries:
                    wait = cfg.backoff_base ** attempt
                    logger.warning(
                        "Request error %s — retrying in %.0fs (attempt %d/%d)",
                        exc,
                        wait,
                        attempt + 1,
                        cfg.max_retries,
                    )
                    await asyncio.sleep(wait)

        msg = f"All {cfg.max_retries} retries exhausted for {url}"
        if last_exc:
            raise last_exc from last_exc
        raise httpx.HTTPStatusError(
            msg,
            request=httpx.Request(method, url),
            response=httpx.Response(503),
        )
