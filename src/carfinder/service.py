"""Service layer — business logic shared between CLI and HTTP server."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from carfinder.config import Config


_DEFAULT_DB_PATH = Path("data/listings.db")


def load_scored_listings(
    cfg: "Config",
    top_n: int | None = None,
    db_path: Path | None = None,
    in_budget: bool = False,
):
    """Load all listings, score them, return sorted list.

    Args:
        cfg: Loaded configuration.
        top_n: If set, truncate results to this many entries after sorting.
        db_path: Override the default database path.
        in_budget: When True, drop listings whose asking_price is None or
            outside cfg.budget.min/cfg.budget.max *after* scoring so that
            cohort medians remain accurate.  When False (default) all
            listings are returned regardless of price.

    Returns (scored_list, conn) — caller is responsible for closing conn.
    """
    from carfinder.db import get_listings, init_db
    from carfinder.lookups import load_lookups
    from carfinder.scorer import score_listing

    if db_path is None:
        db_path = _DEFAULT_DB_PATH

    lk = load_lookups(Path("data"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)

    all_listings = get_listings(conn)

    if not all_listings:
        return [], conn

    # Exclude manual if configured. Two-stage check:
    # 1. structured transmission field (when fetcher parsed it cleanly)
    # 2. defensive text scan of model + description (CL listings often leave the
    #    structured field empty but the title says "5 speed" / "manual" / "5spd")
    if cfg.transmission.exclude_manual:
        import re as _re
        _manual_re = _re.compile(
            r"\bmanual\b|\b\d+\s?spd\b|\b\d+\s?speed\b|\bstick\s?shift\b",
            _re.IGNORECASE,
        )

        def _is_manual(l):
            if (l.transmission or "").lower() == "manual":
                return True
            if (l.transmission or "").lower() in ("automatic", "auto"):
                return False  # trust explicit auto signal
            text = " ".join(filter(None, [l.model, l.trim, l.description]))
            return bool(_manual_re.search(text))

        all_listings = [l for l in all_listings if not _is_manual(l)]

    # Enrich distance_miles for listings that don't have it yet
    from carfinder.geo import distance_from_location
    for l in all_listings:
        if l.distance_miles is None and l.location:
            d = distance_from_location(l.location, cfg.zip)
            if d is not None:
                l.distance_miles = d

    scored = [score_listing(l, all_listings, cfg, lk) for l in all_listings]
    scored.sort(key=lambda s: s.score, reverse=True)

    # Apply budget filter after scoring so cohort medians stay accurate.
    # Listings with no asking_price are treated as out-of-budget.
    if in_budget:
        bmin, bmax = cfg.budget.min, cfg.budget.max
        scored = [
            s for s in scored
            if s.listing.asking_price is not None
            and bmin <= s.listing.asking_price <= bmax
        ]

    if top_n is not None:
        scored = scored[:top_n]

    return scored, conn
