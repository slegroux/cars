"""HTML dashboard export — produces a self-contained HTML file.

Dependencies:
  - Chart.js v4 is inlined from data/vendor/chart.umd.min.js at render time.
    Charts work fully offline as long as that file exists. To (re)download it:
      curl -L -o data/vendor/chart.umd.min.js \
        https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js
  - External photo URLs (Craigslist / CarMax CDNs) still require network.
  - Everything else (layout, filters, table, radar) works offline.

No Jinja2, no build step. Python stdlib only: json, html, datetime, string.
"""
from __future__ import annotations

import datetime
import html as _html
import json
import statistics
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from carfinder.config import Config
    from carfinder.scorer import ScoredListing

# ---------------------------------------------------------------------------
# Vendored Chart.js (inlined at render time for offline support)
# ---------------------------------------------------------------------------

_CHART_JS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "vendor" / "chart.umd.min.js"


def _chart_js_source() -> str:
    if _CHART_JS_PATH.exists():
        return _CHART_JS_PATH.read_text(encoding="utf-8")
    return ""  # fall back to empty; chart won't render but dashboard still loads


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FACTOR_KEYS = [
    "reliability",
    "price_value",
    "mileage",
    "size_class",
    "parking_footprint",
    "mpg",
    "drivetrain",
    "insurance_risk",
    "roof_rack",
    "title_status",
    "seller_type",
]


def _h(s: object) -> str:
    """HTML-escape a value."""
    return _html.escape(str(s) if s is not None else "")


def _git_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        # git missing, timeout, or not a repo — the hash is cosmetic.
        return ""


def _listing_to_dict(s: "ScoredListing") -> dict:
    """Serialise one ScoredListing into a JSON-safe dict for the dashboard."""
    lst = s.listing
    photos = lst.photos or []

    # Market reference + deal delta from the price_value factor (negative = below market).
    pv = s.score_breakdown.get("price_value")
    ref_price = pv.ref_price if pv else None
    deal = (
        lst.asking_price - ref_price
        if ref_price is not None and lst.asking_price is not None
        else None
    )

    factors = []
    for key in _FACTOR_KEYS:
        fs = s.score_breakdown.get(key)
        if fs:
            factors.append({
                "key": key,
                "raw": fs.raw,
                "weight": fs.weight,
                "weighted": fs.weighted,
                "confidence": fs.confidence,
                "reason": fs.reason,
            })
        else:
            factors.append({
                "key": key,
                "raw": 5.0,
                "weight": 0.0,
                "weighted": 0.0,
                "confidence": "estimated",
                "reason": "—",
            })

    return {
        "id": lst.id or "",
        "url": lst.url or "",
        "source": lst.source or "unknown",
        "year": lst.year,
        "make": lst.make or "",
        "model": lst.model or "",
        "trim": lst.trim or "",
        "body_type": lst.body_type or "",
        "mileage": lst.mileage,
        "asking_price": lst.asking_price,
        "score": s.score,
        "confidence": s.confidence,
        "display_score": s.display_score(),
        "location": lst.location or "",
        "distance_miles": lst.distance_miles,
        "seller_type": lst.seller_type or "",
        "transmission": lst.transmission or "",
        "drivetrain": lst.drivetrain or "",
        "title_status": lst.title_status or "",
        "mpg": lst.mpg_combined,
        "market_value": ref_price,
        "deal": round(deal) if deal is not None else None,
        "description": lst.description or "",
        "photos": photos,
        "first_photo": photos[0] if photos else "",
        "model_image": s.model_image or "",  # exact model+year studio image fallback
        "first_seen": lst.first_seen.isoformat() if lst.first_seen else "",
        "last_seen": lst.last_seen.isoformat() if lst.last_seen else "",
        "factors": factors,
    }


def _compute_stats(scored: list["ScoredListing"]) -> dict:
    scores = [s.score for s in scored]
    prices = [s.listing.asking_price for s in scored if s.listing.asking_price is not None]

    source_counts: dict[str, int] = {}
    for s in scored:
        src = s.listing.source or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1

    last_seen_times = [
        s.listing.last_seen for s in scored if s.listing.last_seen is not None
    ]
    last_fetched = max(last_seen_times).isoformat() if last_seen_times else "—"

    return {
        "total": len(scored),
        "source_counts": source_counts,
        "median_score": round(statistics.median(scores), 1) if scores else 0,
        "median_price": round(statistics.median(prices), 0) if prices else 0,
        "last_fetched": last_fetched,
    }


# ---------------------------------------------------------------------------
# CSS / JS (loaded from static files at import time)
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"


def _load_static(name: str) -> str:
    path = _STATIC_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"Dashboard static asset missing: {path}. "
            f"Reinstall the carfinder package or restore src/carfinder/render_html/static/."
        ) from e


_CSS = _load_static("dashboard.css")
_JS = _load_static("dashboard.js")

# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

def render_html(
    scored: list["ScoredListing"],
    config: "Config | None" = None,
) -> str:
    """Return a self-contained HTML dashboard string.

    Pure function — no I/O. Inline JSON-encodes all listing data and Chart.js
    into the page so it works as a fully offline static file:// document
    (external photo URLs still require network).
    """
    today = datetime.date.today().isoformat()
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    git = _git_hash()
    footer_hash = f"· {git}" if git else ""

    stats = _compute_stats(scored)
    listings_data = [_listing_to_dict(s) for s in scored]

    # JSON-encode into the page — use separators to keep it compact
    listings_json = json.dumps(listings_data, separators=(",", ":"), default=str)
    # Prevent </script> in string values from breaking out of the script block.
    # <\/ is valid JSON (forward slash needs no escaping) and valid JS.
    listings_json = listings_json.replace("</", "<\\/")

    # Default scoring weights — seed the dashboard's live re-rank sliders.
    from carfinder.config import WeightsConfig
    weights = config.weights if config is not None else WeightsConfig()
    weights_json = json.dumps(weights.model_dump(), separators=(",", ":"))

    # Stat chips
    src_parts = ", ".join(
        f"{src} ({cnt})" for src, cnt in stats["source_counts"].items()
    )
    median_price_str = f"${stats['median_price']:,.0f}" if stats["median_price"] else "—"
    last_fetched = _h(stats["last_fetched"])

    # Build HTML
    lines: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Car Finder Shortlist — {_h(today)}</title>",
        f"<script>{_chart_js_source()}</script>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        '<div class="page">',
        "",
        "<!-- ── Header ─────────────────────────────────────────── -->",
        '<div class="header">',
        f'  <span class="header-title">Car Finder Shortlist — {_h(today)}</span>',
        '  <div class="header-meta">',
        f'    <span class="stat-chip"><strong>{stats["total"]}</strong> listings</span>',
        f'    <span class="stat-chip">{_h(src_parts)}</span>',
        f'    <span class="stat-chip">Median score <strong>{stats["median_score"]}</strong></span>',
        f'    <span class="stat-chip">Median price <strong>{_h(median_price_str)}</strong></span>',
        "  </div>",
        f'  <span class="fetched">Last fetched: {last_fetched}</span>',
        '  <button id="importBtn" class="import-btn">+ Add listing</button>',
        "</div>",
        "",
        "<!-- ── Filters ─────────────────────────────────────────── -->",
        '<div class="filters">',
        '  <div class="filter-group">',
        '    <label for="filterSearch">Search</label>',
        '    <input type="search" id="filterSearch" placeholder="make, model, trim, notes…" autocomplete="off" style="width:220px">',
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterSource">Source</label>',
        '    <select id="filterSource">',
        "    </select>",
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterScore">Min score <span id="filterScoreLabel">0</span></label>',
        '    <input type="range" id="filterScore" min="0" max="100" value="0" step="1">',
        "  </div>",
        '  <div class="filter-group">',
        "    <label>Body type</label>",
        '    <div class="checkbox-group">',
    ]

    body_types = ["SUV", "Sedan", "Wagon", "Hatchback", "Coupe", "Truck", "Van", "Unknown"]
    for bt in body_types:
        lines.append(
            f'      <label class="cb-label checked"><input type="checkbox" class="body-cb" '
            f'value="{_h(bt)}" checked>{_h(bt)}</label>'
        )

    lines += [
        "    </div>",
        "  </div>",
        '  <div class="filter-group range-wrap">',
        '    <label>Price <span id="priceLabel">$0 – $20k</span></label>',
        '    <div class="range-wrapper">',
        '      <input type="range" id="priceMin" min="0" max="20000" value="0" step="250">',
        '      <input type="range" id="priceMax" min="0" max="20000" value="20000" step="250">',
        "    </div>",
        "  </div>",
        '  <div class="filter-group range-wrap">',
        '    <label>Mileage <span id="mileLabel">0k – 200k mi</span></label>',
        '    <div class="range-wrapper">',
        '      <input type="range" id="mileMin" min="0" max="200000" value="0" step="5000">',
        '      <input type="range" id="mileMax" min="0" max="200000" value="200000" step="5000">',
        "    </div>",
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterYear">Year min</label>',
        '    <input type="number" id="filterYear" min="1990" max="2030" value="2008" style="width:80px">',
        "  </div>",
        '  <button id="btnReset" class="btn-reset">Reset filters</button>',
        "</div>",
        "",
        "<!-- ── Secondary filters (make/model facets + spec filters) ── -->",
        '<div class="filters filters-secondary">',
        '  <div class="filter-group facet-group">',
        '    <label>Make</label>',
        '    <div class="facet" id="makeFacet"></div>',
        "  </div>",
        '  <div class="filter-group facet-group">',
        '    <label>Model</label>',
        '    <div class="facet" id="modelFacet"></div>',
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterDrivetrain">Drivetrain</label>',
        '    <select id="filterDrivetrain">',
        '      <option value="all">Any</option><option value="AWD">AWD</option>',
        '      <option value="4WD">4WD</option><option value="FWD">FWD</option><option value="RWD">RWD</option>',
        "    </select>",
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterTransmission">Transmission</label>',
        '    <select id="filterTransmission">',
        '      <option value="all">Any</option><option value="automatic">Automatic</option><option value="manual">Manual</option>',
        "    </select>",
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterTitle">Title</label>',
        '    <select id="filterTitle">',
        '      <option value="all">Any</option><option value="clean">Clean</option>',
        '      <option value="rebuilt">Rebuilt</option><option value="salvage">Salvage</option>',
        "    </select>",
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterSeller">Seller</label>',
        '    <select id="filterSeller">',
        '      <option value="all">Any</option><option value="dealer">Dealer</option>',
        '      <option value="private">Private</option><option value="certified">Certified</option>',
        "    </select>",
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterDist">Max distance <span id="filterDistLabel">any</span></label>',
        '    <input type="range" id="filterDist" min="0" max="300" value="300" step="10">',
        "  </div>",
        '  <div class="filter-group">',
        '    <label for="filterMpg">Min MPG <span id="filterMpgLabel">0</span></label>',
        '    <input type="range" id="filterMpg" min="0" max="60" value="0" step="1">',
        "  </div>",
        '  <div class="filter-group">',
        "    <label>Confidence</label>",
        '    <div class="checkbox-group" id="confGroup">',
        '      <label class="cb-label checked"><input type="checkbox" class="conf-cb" value="full" checked>Full</label>',
        '      <label class="cb-label checked"><input type="checkbox" class="conf-cb" value="partial" checked>Partial</label>',
        '      <label class="cb-label checked"><input type="checkbox" class="conf-cb" value="low" checked>Low</label>',
        "    </div>",
        "  </div>",
        '  <div class="filter-group">',
        "    <label>Freshness</label>",
        '    <label class="cb-label"><input type="checkbox" id="filterNew">New only</label>',
        "  </div>",
        "</div>",
        "",
        "<!-- ── Live re-rank weights ────────────────────────────── -->",
        '<div class="weights-panel">',
        '  <button type="button" class="weights-toggle" id="weightsToggle">⚖ Re-rank weights</button>',
        '  <div class="weights-body" id="weightsBody" hidden>',
        '    <div class="weights-grid" id="weightsGrid"></div>',
        '    <button type="button" class="btn-reset" id="weightsReset">Reset weights</button>',
        "  </div>",
        "</div>",
        "",
        "<!-- ── Saved targets ───────────────────────────────────── -->",
        '<div class="targets-bar" id="targetsBar">',
        '  <span class="targets-label">★ Targets</span>',
        '  <span class="targets-chips" id="targetsChips"></span>',
        '  <button type="button" class="target-save" id="saveTargetBtn">+ Save current filters</button>',
        "</div>",
        "",
        "<!-- ── Scatter chart ───────────────────────────────────── -->",
        '<div class="chart-section">',
        '  <div class="section-title">Price vs Score</div>',
        '  <div class="chart-wrap">',
        '    <canvas id="scatterCanvas"></canvas>',
        "  </div>",
        "</div>",
        "",
        "<!-- ── Listings table ──────────────────────────────────── -->",
        '<div class="table-section">',
        '  <div class="table-meta">',
        '    <span class="section-title" style="margin:0">Listings</span>',
        '    <span class="table-count" id="tableCount"></span>',
        "  </div>",
        '  <table class="listings">',
        "    <thead>",
        "      <tr>",
    ]

    col_def = [
        ("photo", "Photo", False),
        ("year", "Year", True),
        ("make", "Make", True),
        ("model", "Model", True),
        ("trim", "Trim", False),
        ("body_type", "Body", False),
        ("mileage", "Miles", True),
        ("asking_price", "Price", True),
        ("deal", "Deal", True),
        ("score", "Score", True),
        ("source", "Src", True),
        ("distance_miles", "Dist", False),
        ("url", "View", False),
    ]
    for col, label, sortable in col_def:
        arrow = '<span class="sort-arrow"></span>' if sortable else ""
        lines.append(
            f'        <th data-col="{col}">{_h(label)}{arrow}</th>'
        )
    lines.append('        <th class="col-actions"></th>')

    lines += [
        "      </tr>",
        "    </thead>",
        '    <tbody id="listingsTbody">',
        "    </tbody>",
        "  </table>",
        '  <div id="pagination" class="pagination"></div>',
        "</div>",
        "",
        "<!-- ── Lightbox ────────────────────────────────────────── -->",
        '<div id="lightbox" class="lightbox">',
        '  <img id="lbImg" src="" alt="listing photo">',
        '  <div class="lightbox-counter" id="lbCounter"></div>',
        '  <div class="lightbox-nav">',
        '    <button class="lightbox-btn" id="lbPrev">← Prev</button>',
        '    <button class="lightbox-btn" id="lbClose">Close</button>',
        '    <button class="lightbox-btn" id="lbNext">Next →</button>',
        "  </div>",
        "</div>",
        "",
        "<!-- ── Import modal ────────────────────────────────────── -->",
        '<div id="importModal" class="modal-backdrop">',
        '  <div class="modal-box">',
        '    <div class="modal-title">Add listing manually</div>',
        '    <div class="form-group paste-section">',
        '      <label>Paste listing text to auto-fill (Facebook Marketplace, Craigslist, etc.)</label>',
        '      <div class="paste-row">',
        '        <textarea id="f-paste" placeholder="Copy all text from the listing page and paste here — the parser will extract make, model, year, price, mileage, and location automatically."></textarea>',
        '        <button class="btn-parse" id="parseBtn" type="button">Parse &#x2192;</button>',
        '      </div>',
        '      <div class="parse-result" id="parseResult"></div>',
        '    </div>',
        '    <hr class="modal-divider">',
        '    <div class="form-grid">',
        '      <div class="form-group full"><label>URL (optional)</label><input id="f-url" type="url" placeholder="https://www.facebook.com/marketplace/item/..."></div>',
        '      <div class="form-group"><label>Make *</label><input id="f-make" type="text" placeholder="Toyota" required></div>',
        '      <div class="form-group"><label>Model *</label><input id="f-model" type="text" placeholder="RAV4" required></div>',
        '      <div class="form-group"><label>Year *</label><input id="f-year" type="number" placeholder="2018" min="1990" max="2030" required></div>',
        '      <div class="form-group"><label>Trim</label><input id="f-trim" type="text" placeholder="SE"></div>',
        '      <div class="form-group"><label>Body type</label><select id="f-body-type"><option value="">—</option><option>SUV</option><option>Sedan</option><option>Wagon</option><option>Hatchback</option><option>Coupe</option><option>Truck</option><option>Van</option></select></div>',
        '      <div class="form-group"><label>Seller type</label><select id="f-seller-type"><option value="private">Private</option><option value="dealer">Dealer</option><option value="certified">Certified</option></select></div>',
        '      <div class="form-group"><label>Mileage</label><input id="f-mileage" type="number" placeholder="75000" min="0"></div>',
        '      <div class="form-group"><label>Price ($)</label><input id="f-price" type="number" placeholder="9500" min="0"></div>',
        '      <div class="form-group"><label>Location</label><input id="f-location" type="text" placeholder="Santa Monica, CA"></div>',
        '      <div class="form-group full"><label>Notes</label><textarea id="f-notes" placeholder="Clean title, one owner, no accidents…"></textarea></div>',
        '    </div>',
        '    <div class="modal-footer">',
        '      <span class="form-msg" id="formMsg"></span>',
        '      <button class="btn-cancel" id="importCancel">Cancel</button>',
        '      <button class="btn-primary" id="importSubmit">Save listing</button>',
        '    </div>',
        '  </div>',
        '</div>',
        "",
        "<!-- ── Notes modal (manual listings) ──────────────────── -->",
        '<div id="notesModal" class="modal-backdrop">',
        '  <div class="modal-box">',
        '    <div class="modal-title" id="notesTitle">Listing notes</div>',
        '    <pre id="notesBody" class="notes-body"></pre>',
        '    <div class="modal-footer">',
        '      <button class="btn-cancel" id="notesClose">Close</button>',
        '    </div>',
        '  </div>',
        '</div>',
        "",
        "<!-- ── Footer ──────────────────────────────────────────── -->",
        '<div class="footer">',
        f'  <span>Generated by carfinder · {_h(now_ts)} {_h(footer_hash)}</span>',
        "  <span>Shortlist file: shortlist.md (Obsidian vault export)</span>",
        "</div>",
        "",
        "</div><!-- /page -->",
        "",
        "<!-- Listing data embedded as JSON -->",
        "<script>",
        f"/* global LISTINGS, WEIGHTS */",  # noqa
        f"var LISTINGS = {listings_json};",  # noqa: S608
        f"var WEIGHTS = {weights_json};",  # noqa: S608
        "</script>",
        "<script>",
        _JS,
        "</script>",
        "</body>",
        "</html>",
    ]

    return "\n".join(lines)
