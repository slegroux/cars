"""HTML dashboard export — produces a self-contained HTML file.

Dependencies:
  - Chart.js loaded from CDN (https://cdn.jsdelivr.net/npm/chart.js@4).
    The file will NOT render charts when opened offline without network.
  - External photo URLs (Craigslist / CarMax CDNs) also require network.
  - Everything else (layout, filters, table, radar) works offline.

No Jinja2, no build step. Python stdlib only: json, html, datetime, string.
"""
from __future__ import annotations

import datetime
import html as _html
import json
import statistics
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from carfinder.config import Config
    from carfinder.scorer import ScoredListing

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
    except Exception:
        return ""


def _listing_to_dict(s: "ScoredListing") -> dict:
    """Serialise one ScoredListing into a JSON-safe dict for the dashboard."""
    l = s.listing
    photos = l.photos or []

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
        "id": l.id or "",
        "url": l.url or "",
        "source": l.source or "unknown",
        "year": l.year,
        "make": l.make or "",
        "model": l.model or "",
        "trim": l.trim or "",
        "body_type": l.body_type or "",
        "mileage": l.mileage,
        "asking_price": l.asking_price,
        "score": s.score,
        "confidence": s.confidence,
        "display_score": s.display_score(),
        "location": l.location or "",
        "distance_miles": l.distance_miles,
        "photos": photos,
        "first_photo": photos[0] if photos else "",
        "last_seen": l.last_seen.isoformat() if l.last_seen else "",
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
# CSS
# ---------------------------------------------------------------------------

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #fafaf9;
  --surface: #ffffff;
  --border: #e5e3df;
  --border-light: #f0eee9;
  --text: #1a1917;
  --text-muted: #6b6861;
  --text-faint: #9c9890;
  --accent: #d97706;
  --accent-dim: #fef3c7;
  --blue: #2563eb;
  --blue-dim: #dbeafe;
  --green: #16a34a;
  --green-dim: #dcfce7;
  --yellow: #ca8a04;
  --yellow-dim: #fef9c3;
  --orange: #ea580c;
  --orange-dim: #ffedd5;
  --red: #dc2626;
  --red-dim: #fee2e2;
  --font: "Berkeley Mono", "Fira Mono", "JetBrains Mono", "Courier New", monospace;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  --radius: 3px;
  --row-highlight: #fff8e7;
}

html { font-size: 13px; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  line-height: 1.5;
  padding: 0;
}

/* ── layout ── */
.page { max-width: 1440px; margin: 0 auto; padding: 0 24px 48px; }

/* ── header ── */
.header {
  border-bottom: 1px solid var(--border);
  padding: 20px 0 16px;
  margin-bottom: 20px;
  display: flex;
  align-items: baseline;
  gap: 32px;
  flex-wrap: wrap;
}
.header-title {
  font-family: var(--font);
  font-size: 1.15rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text);
}
.header-meta {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  align-items: center;
}
.stat-chip {
  font-size: 0.85rem;
  color: var(--text-muted);
}
.stat-chip strong {
  color: var(--text);
  font-weight: 600;
}
.fetched {
  font-size: 0.78rem;
  color: var(--text-faint);
  font-family: var(--font);
  margin-left: auto;
}

/* ── filters ── */
.filters {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: flex-end;
}
.filter-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 120px;
}
.filter-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.filter-group select,
.filter-group input[type=number] {
  font-family: var(--font-sans);
  font-size: 0.875rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  background: var(--bg);
  color: var(--text);
  height: 30px;
}
.filter-group select:focus,
.filter-group input:focus {
  outline: 2px solid var(--accent);
  outline-offset: -1px;
}

/* checkboxes */
.checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}
.cb-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.8rem;
  cursor: pointer;
  padding: 3px 7px;
  border: 1px solid var(--border);
  border-radius: 2px;
  background: var(--bg);
  user-select: none;
  transition: background 0.1s, border-color 0.1s;
}
.cb-label input[type=checkbox] { display: none; }
.cb-label.checked {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--text);
}

/* range slider */
.range-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 200px;
}
.range-track {
  position: relative;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  margin: 6px 0;
}
.range-fill {
  position: absolute;
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
}
.range-inputs {
  display: flex;
  gap: 8px;
  align-items: center;
}
.range-inputs input[type=range] {
  -webkit-appearance: none;
  appearance: none;
  flex: 1;
  height: 4px;
  background: transparent;
  cursor: pointer;
  position: absolute;
  pointer-events: none;
  width: 100%;
  left: 0;
  top: 0;
}
.range-inputs input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid white;
  box-shadow: 0 0 0 1px var(--accent);
  pointer-events: all;
  cursor: grab;
}
.range-inputs input[type=range]::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid white;
  pointer-events: all;
  cursor: grab;
}
.range-label {
  font-size: 0.78rem;
  color: var(--text-muted);
  font-family: var(--font);
  white-space: nowrap;
}
.range-wrapper {
  position: relative;
  height: 16px;
  margin: 4px 0;
}
.range-wrapper input[type=range]:first-child { z-index: 2; }
.range-wrapper input[type=range]:last-child  { z-index: 3; }

.btn-reset {
  font-family: var(--font-sans);
  font-size: 0.8rem;
  padding: 5px 12px;
  height: 30px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  color: var(--text-muted);
  transition: border-color 0.1s, color 0.1s;
  align-self: flex-end;
}
.btn-reset:hover { border-color: var(--text-muted); color: var(--text); }

/* ── chart section ── */
.chart-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 20px;
}
.section-title {
  font-family: var(--font);
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 12px;
}
.chart-wrap { position: relative; height: 320px; }

/* ── table section ── */
.table-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.table-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-light);
}
.table-count {
  font-size: 0.8rem;
  color: var(--text-muted);
}
table.listings {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
table.listings thead th {
  text-align: left;
  padding: 8px 10px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  background: var(--bg);
  position: sticky;
  top: 0;
  z-index: 2;
}
table.listings thead th:hover { color: var(--text); }
table.listings thead th .sort-arrow {
  display: inline-block;
  width: 12px;
  color: var(--text-faint);
}
table.listings thead th.sort-asc .sort-arrow::after { content: " ↑"; }
table.listings thead th.sort-desc .sort-arrow::after { content: " ↓"; }

table.listings tbody tr.data-row {
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background 0.08s;
}
table.listings tbody tr.data-row:hover { background: var(--border-light); }
table.listings tbody tr.data-row.highlighted {
  background: var(--row-highlight);
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

table.listings td {
  padding: 7px 10px;
  vertical-align: middle;
  color: var(--text);
}
table.listings td.col-photo {
  width: 90px;
  padding: 4px 6px;
}
table.listings td.col-photo img {
  width: 80px;
  height: 60px;
  object-fit: cover;
  border-radius: 2px;
  display: block;
  background: var(--border-light);
}
.photo-placeholder {
  width: 80px;
  height: 60px;
  background: var(--border-light);
  border-radius: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  color: var(--text-faint);
  font-family: var(--font);
}
.score-cell {
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.85rem;
  padding: 2px 6px;
  border-radius: 2px;
  display: inline-block;
}
.score-green  { background: var(--green-dim);  color: var(--green); }
.score-yellow { background: var(--yellow-dim); color: var(--yellow); }
.score-orange { background: var(--orange-dim); color: var(--orange); }
.score-red    { background: var(--red-dim);    color: var(--red); }

.source-chip {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 2px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.source-craigslist { background: var(--blue-dim);    color: var(--blue); }
.source-carmax     { background: var(--orange-dim);  color: var(--orange); }
.source-carscom    { background: var(--green-dim);   color: var(--green); }
.source-other      { background: var(--border-light); color: var(--text-muted); }

.ext-link {
  color: var(--text-muted);
  font-size: 0.9rem;
  text-decoration: none;
  padding: 2px 4px;
}
.ext-link:hover { color: var(--accent); }

/* ── expand row ── */
tr.expand-row { display: none; }
tr.expand-row.open { display: table-row; }
tr.expand-row td {
  background: var(--surface);
  padding: 0;
  border-bottom: 1px solid var(--border);
}
.expand-inner {
  padding: 16px;
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 24px;
}
.radar-wrap { position: relative; height: 280px; width: 280px; }
.breakdown-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
  font-family: var(--font);
}
.breakdown-table th {
  text-align: left;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
}
.breakdown-table td {
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-light);
  vertical-align: middle;
}
.breakdown-table tr:last-child td { border-bottom: none; }
.breakdown-table td:nth-child(2),
.breakdown-table td:nth-child(3),
.breakdown-table td:nth-child(4) {
  text-align: right;
  color: var(--text-muted);
}
.expand-subtitle {
  margin-top: 10px;
  font-size: 0.78rem;
  color: var(--text-muted);
  font-family: var(--font);
}

/* ── lightbox ── */
.lightbox {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 1000;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
}
.lightbox.open { display: flex; }
.lightbox img {
  max-width: 90vw;
  max-height: 80vh;
  object-fit: contain;
  border-radius: 2px;
}
.lightbox-nav {
  display: flex;
  gap: 12px;
}
.lightbox-btn {
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.3);
  color: white;
  padding: 6px 16px;
  border-radius: 2px;
  cursor: pointer;
  font-size: 0.85rem;
  font-family: var(--font-sans);
}
.lightbox-btn:hover { background: rgba(255,255,255,0.25); }
.lightbox-counter {
  font-size: 0.8rem;
  color: rgba(255,255,255,0.5);
  font-family: var(--font);
}

/* ── import modal ── */
.import-btn {
  display: none;
  font-family: var(--font-sans);
  font-size: 0.8rem;
  padding: 5px 12px;
  height: 30px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-weight: 600;
  margin-left: auto;
}
.import-btn:hover { background: #b45309; }
.modal-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.45);
  z-index: 500;
  align-items: flex-start;
  justify-content: center;
  padding-top: 60px;
}
.modal-backdrop.open { display: flex; }
.modal-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  width: 560px;
  max-width: 95vw;
  max-height: 80vh;
  overflow-y: auto;
}
.modal-title {
  font-family: var(--font);
  font-size: 0.9rem;
  font-weight: 700;
  margin-bottom: 16px;
  color: var(--text);
}
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }
.form-group { display: flex; flex-direction: column; gap: 3px; }
.form-group.full { grid-column: 1 / -1; }
.form-group label {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.form-group input,
.form-group select,
.form-group textarea {
  font-family: var(--font-sans);
  font-size: 0.875rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  background: var(--bg);
  color: var(--text);
}
.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.form-group textarea { resize: vertical; min-height: 60px; }
.modal-footer { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; align-items: center; }
.form-msg { font-size: 0.78rem; color: var(--red); flex: 1; }
.btn-primary {
  font-family: var(--font-sans);
  font-size: 0.85rem;
  padding: 6px 16px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-weight: 600;
}
.btn-primary:hover { background: #b45309; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }
.btn-cancel {
  font-family: var(--font-sans);
  font-size: 0.85rem;
  padding: 6px 16px;
  background: var(--bg);
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
}
.btn-cancel:hover { border-color: var(--text-muted); color: var(--text); }
.col-actions { display: none; width: 36px; text-align: center; }
.del-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-faint);
  font-size: 1rem;
  padding: 2px 5px;
  border-radius: 2px;
  line-height: 1;
}
.del-btn:hover { color: var(--red); background: var(--red-dim); }

/* ── pagination ── */
.pagination {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-top: 1px solid var(--border-light);
  font-size: 0.8rem;
  flex-wrap: wrap;
}
.page-size-sel {
  font-family: var(--font-sans);
  font-size: 0.8rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 3px 6px;
  background: var(--bg);
  color: var(--text-muted);
  height: 26px;
  margin-right: auto;
}
.page-btn {
  font-family: var(--font-sans);
  font-size: 0.8rem;
  padding: 3px 10px;
  height: 26px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  color: var(--text-muted);
  transition: border-color 0.1s, color 0.1s;
}
.page-btn:disabled { opacity: 0.35; cursor: default; }
.page-btn:not(:disabled):hover { border-color: var(--text-muted); color: var(--text); }
.page-info {
  font-family: var(--font);
  color: var(--text-muted);
  min-width: 90px;
  text-align: center;
  font-size: 0.78rem;
}

/* ── footer ── */
.footer {
  padding: 20px 0 8px;
  border-top: 1px solid var(--border);
  margin-top: 24px;
  font-size: 0.75rem;
  color: var(--text-faint);
  font-family: var(--font);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
"""

# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

_JS = r"""
(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────────
  var SERVER_MODE = window.location.protocol !== 'file:' && window.location.hostname === 'localhost';

  window.dashboardState = {
    source: 'all',
    minScore: 0,
    bodyTypes: new Set(['SUV','Sedan','Wagon','Hatchback','Coupe','Truck','Van','Unknown']),
    mileMin: 0,
    mileMax: 200000,
    yearMin: 2008,
    sortCol: 'score',
    sortDir: 'desc',
    page: 1,
    pageSize: 25,
    priceMin: 0,
    priceMax: 20000,
  };

  var S = window.dashboardState;
  var scatterChart = null;
  var openRadarChart = null;
  var openRowId = null;

  // ── Filtering ──────────────────────────────────────────────────────────────
  function matchesFilter(d) {
    if (S.source !== 'all' && d.source !== S.source) return false;
    if (d.score < S.minScore) return false;
    var bt = d.body_type || 'Unknown';
    if (!S.bodyTypes.has(bt) && !S.bodyTypes.has('Unknown')) return false;
    if (S.bodyTypes.size > 0 && !S.bodyTypes.has(bt === '' ? 'Unknown' : bt)) return false;
    var pr = d.asking_price != null ? d.asking_price : 0;
    if (pr < S.priceMin || pr > S.priceMax) return false;
    var mi = d.mileage != null ? d.mileage : 0;
    if (mi < S.mileMin || mi > S.mileMax) return false;
    var yr = d.year != null ? d.year : 0;
    if (yr < S.yearMin) return false;
    return true;
  }

  function filteredListings() {
    return LISTINGS.filter(matchesFilter);
  }

  // ── Score colour ───────────────────────────────────────────────────────────
  function scoreClass(score) {
    if (score >= 75) return 'score-green';
    if (score >= 60) return 'score-yellow';
    if (score >= 45) return 'score-orange';
    return 'score-red';
  }

  function sourceChipClass(src) {
    if (src === 'craigslist') return 'source-craigslist';
    if (src === 'carmax')     return 'source-carmax';
    if (src === 'carscom')    return 'source-carscom';
    return 'source-other';
  }

  // ── Format helpers ─────────────────────────────────────────────────────────
  function fmtPrice(p) { return p != null ? '$' + Math.round(p).toLocaleString() : '—'; }
  function fmtMiles(m) { return m != null ? m.toLocaleString() + ' mi' : '—'; }
  function fmtDist(d)  { return d != null ? d.toFixed(0) + ' mi' : '—'; }

  // ── OLS value line ─────────────────────────────────────────────────────────
  function olsLine(pts) {
    var n = pts.length;
    if (n < 2) return null;
    var sumX = 0, sumY = 0, sumXX = 0, sumXY = 0;
    for (var i = 0; i < n; i++) {
      sumX  += pts[i].x; sumY  += pts[i].y;
      sumXX += pts[i].x * pts[i].x;
      sumXY += pts[i].x * pts[i].y;
    }
    var denom = n * sumXX - sumX * sumX;
    if (Math.abs(denom) < 1e-9) return null;
    var m = (n * sumXY - sumX * sumY) / denom;
    var b = (sumY - m * sumX) / n;
    var xs = pts.map(function(p){ return p.x; });
    var xMin = Math.min.apply(null, xs);
    var xMax = Math.max.apply(null, xs);
    return [{ x: xMin, y: m * xMin + b }, { x: xMax, y: m * xMax + b }];
  }

  // Mileage → point size (inverse: low mileage = bigger)
  function mileageSize(mi) {
    if (mi == null) return 7;
    if (mi < 30000)  return 13;
    if (mi < 60000)  return 11;
    if (mi < 90000)  return 9;
    if (mi < 120000) return 7;
    return 5;
  }

  // ── Scatter chart ──────────────────────────────────────────────────────────
  function buildScatter() {
    var fl = filteredListings();
    var pts = fl.map(function(d, idx) {
      return {
        x: d.asking_price,
        y: d.score,
        r: mileageSize(d.mileage),
        dataIdx: idx,
        id: d.id,
      };
    });

    var clPts  = pts.filter(function(p){ return fl[p.dataIdx].source === 'craigslist'; });
    var cmPts  = pts.filter(function(p){ return fl[p.dataIdx].source === 'carmax'; });
    var othPts = pts.filter(function(p){ return fl[p.dataIdx].source !== 'craigslist' && fl[p.dataIdx].source !== 'carmax'; });

    var allXY = fl.filter(function(d){ return d.asking_price != null; }).map(function(d){ return { x: d.asking_price, y: d.score }; });
    var ols = olsLine(allXY);

    var datasets = [
      {
        label: 'Craigslist',
        data: clPts,
        backgroundColor: 'rgba(37,99,235,0.65)',
        borderColor: 'rgba(37,99,235,0.9)',
        borderWidth: 1,
      },
      {
        label: 'CarMax',
        data: cmPts,
        backgroundColor: 'rgba(234,88,12,0.65)',
        borderColor: 'rgba(234,88,12,0.9)',
        borderWidth: 1,
      },
    ];
    if (othPts.length) {
      datasets.push({
        label: 'Other',
        data: othPts,
        backgroundColor: 'rgba(100,100,100,0.55)',
        borderColor: 'rgba(100,100,100,0.8)',
        borderWidth: 1,
      });
    }
    if (ols) {
      datasets.push({
        label: 'Value line',
        type: 'line',
        data: ols,
        borderColor: 'rgba(180,160,120,0.4)',
        borderWidth: 1.5,
        borderDash: [4, 4],
        pointRadius: 0,
        fill: false,
        tension: 0,
        order: -1,
      });
    }

    var ctx = document.getElementById('scatterCanvas').getContext('2d');
    if (scatterChart) { scatterChart.destroy(); scatterChart = null; }

    scatterChart = new Chart(ctx, {
      type: 'bubble',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 120 },
        plugins: {
          legend: {
            labels: { font: { size: 11 }, color: '#6b6861', usePointStyle: true, pointStyleWidth: 8 }
          },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var raw = ctx.raw;
                var d = fl[raw.dataIdx];
                if (!d) return '';
                var yr  = d.year || '?';
                var mk  = d.make || '';
                var mo  = d.model || '';
                var sc  = d.display_score;
                var pr  = fmtPrice(d.asking_price);
                var mi  = fmtMiles(d.mileage);
                var src = d.source;
                var conf = d.confidence;
                return [yr + ' ' + mk + ' ' + mo, 'Score: ' + sc + '  (' + conf + ')', 'Price: ' + pr, 'Miles: ' + mi, 'Source: ' + src];
              },
            },
            backgroundColor: 'rgba(26,25,23,0.92)',
            titleFont: { size: 11 },
            bodyFont: { size: 11 },
            padding: 10,
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Asking price ($)', font: { size: 11 }, color: '#6b6861' },
            ticks: { font: { size: 10 }, color: '#9c9890', callback: function(v){ return '$' + (v/1000).toFixed(0) + 'k'; } },
            grid: { color: '#e5e3df' },
          },
          y: {
            title: { display: true, text: 'Score', font: { size: 11 }, color: '#6b6861' },
            min: 0, max: 100,
            ticks: { font: { size: 10 }, color: '#9c9890' },
            grid: { color: '#e5e3df' },
          },
        },
        onClick: function(event, elements) {
          if (!elements.length) return;
          var el = elements[0];
          var raw = scatterChart.data.datasets[el.datasetIndex].data[el.index];
          if (raw && raw.id) {
            scrollToRow(raw.id);
          }
        },
      },
    });
  }

  // ── Table rendering ────────────────────────────────────────────────────────
  var COLS = ['photo','year','make','model','trim','body_type','mileage','asking_price','score','source','distance_miles','url'];
  var COL_LABELS = { photo:'Photo', year:'Year', make:'Make', model:'Model', trim:'Trim', body_type:'Body',
                     mileage:'Miles', asking_price:'Price', score:'Score', source:'Src', distance_miles:'Dist', url:'View' };
  var SORTABLE = new Set(['year','make','model','mileage','asking_price','score','source']);

  function renderTable() {
    var fl = filteredListings();

    // Sort
    fl.sort(function(a, b) {
      var av = a[S.sortCol], bv = b[S.sortCol];
      if (av == null) av = S.sortDir === 'asc' ? Infinity : -Infinity;
      if (bv == null) bv = S.sortDir === 'asc' ? Infinity : -Infinity;
      if (typeof av === 'string') av = av.toLowerCase();
      if (typeof bv === 'string') bv = bv.toLowerCase();
      if (av < bv) return S.sortDir === 'asc' ? -1 : 1;
      if (av > bv) return S.sortDir === 'asc' ? 1 : -1;
      return 0;
    });

    var total = fl.length;
    var start = S.pageSize > 0 ? (S.page - 1) * S.pageSize : 0;
    var end   = S.pageSize > 0 ? start + S.pageSize : total;
    var paginated = fl.slice(start, end);

    var tbody = document.getElementById('listingsTbody');
    tbody.innerHTML = '';

    var countEl = document.getElementById('tableCount');
    if (countEl) countEl.textContent = fl.length + ' listing' + (fl.length !== 1 ? 's' : '');

    // Update sort arrow classes on headers
    document.querySelectorAll('table.listings thead th').forEach(function(th) {
      var col = th.dataset.col;
      th.classList.remove('sort-asc', 'sort-desc');
      if (col === S.sortCol) th.classList.add(S.sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
    });

    paginated.forEach(function(d, i) {
      // Data row
      var tr = document.createElement('tr');
      tr.className = 'data-row';
      tr.dataset.id = d.id;

      // Photo
      var tdPhoto = document.createElement('td');
      tdPhoto.className = 'col-photo';
      if (d.first_photo) {
        var img = document.createElement('img');
        img.src = d.first_photo;
        img.loading = 'lazy';
        img.alt = (d.year || '') + ' ' + (d.make || '') + ' ' + (d.model || '');
        img.addEventListener('click', function(e) {
          e.stopPropagation();
          openLightbox(d.photos, 0);
        });
        tdPhoto.appendChild(img);
      } else {
        var ph = document.createElement('div');
        ph.className = 'photo-placeholder';
        ph.textContent = 'no photo';
        tdPhoto.appendChild(ph);
      }
      tr.appendChild(tdPhoto);

      // Year
      tr.appendChild(_td(d.year || '—'));
      // Make
      tr.appendChild(_td(d.make || '—'));
      // Model
      tr.appendChild(_td(d.model || '—'));
      // Trim
      tr.appendChild(_td(d.trim || '—'));
      // Body
      tr.appendChild(_td(d.body_type || '—'));
      // Miles
      tr.appendChild(_td(fmtMiles(d.mileage)));
      // Price
      tr.appendChild(_td(fmtPrice(d.asking_price)));

      // Score
      var tdScore = document.createElement('td');
      var scoreSpan = document.createElement('span');
      scoreSpan.className = 'score-cell ' + scoreClass(d.score);
      scoreSpan.textContent = d.display_score;
      tdScore.appendChild(scoreSpan);
      tr.appendChild(tdScore);

      // Source
      var tdSrc = document.createElement('td');
      var srcSpan = document.createElement('span');
      srcSpan.className = 'source-chip ' + sourceChipClass(d.source);
      srcSpan.textContent = d.source === 'craigslist' ? 'CL' : d.source === 'carmax' ? 'CMax' : d.source === 'carscom' ? 'Cars' : d.source;
      tdSrc.appendChild(srcSpan);
      tr.appendChild(tdSrc);

      // Distance
      tr.appendChild(_td(fmtDist(d.distance_miles)));

      // View link
      var tdView = document.createElement('td');
      if (d.url) {
        var a = document.createElement('a');
        a.href = d.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'ext-link';
        a.title = 'Open listing';
        a.textContent = '↗';
        a.addEventListener('click', function(e){ e.stopPropagation(); });
        tdView.appendChild(a);
      } else {
        tdView.textContent = '—';
      }
      tr.appendChild(tdView);

      // Delete (col hidden until server mode enables it)
      var tdDel = document.createElement('td');
      tdDel.className = 'col-actions';
      var delBtn = document.createElement('button');
      delBtn.className = 'del-btn';
      delBtn.title = 'Remove listing';
      delBtn.textContent = '×';
      delBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        deleteRow(d.id, tr, expandRow);
      });
      tdDel.appendChild(delBtn);
      tr.appendChild(tdDel);

      // Row click → expand radar
      tr.addEventListener('click', function() { toggleExpand(d, tr, expandRow); });

      tbody.appendChild(tr);

      // Expand row (hidden by default)
      var expandRow = document.createElement('tr');
      expandRow.className = 'expand-row';
      expandRow.dataset.parentId = d.id;
      var expandTd = document.createElement('td');
      expandTd.colSpan = 12;
      expandRow.appendChild(expandTd);
      tbody.appendChild(expandRow);
    });

    renderPagination(total);
  }

  function _td(text) {
    var td = document.createElement('td');
    td.textContent = text;
    return td;
  }

  // ── Pagination ─────────────────────────────────────────────────────────────
  function renderPagination(total) {
    var el = document.getElementById('pagination');
    if (!el) return;
    el.innerHTML = '';

    var totalPages = S.pageSize > 0 ? Math.ceil(total / S.pageSize) : 1;
    if (S.page > totalPages) S.page = Math.max(1, totalPages);

    // Per-page selector (right side via margin-left:auto on first element)
    var sel = document.createElement('select');
    sel.className = 'page-size-sel';
    [10, 25, 50, 100].forEach(function(n) {
      var opt = document.createElement('option');
      opt.value = n; opt.textContent = n + ' per page';
      if (n === S.pageSize) opt.selected = true;
      sel.appendChild(opt);
    });
    var optAll = document.createElement('option');
    optAll.value = 0; optAll.textContent = 'All';
    if (S.pageSize === 0) optAll.selected = true;
    sel.appendChild(optAll);
    sel.addEventListener('change', function() {
      S.pageSize = +this.value; S.page = 1;
      renderTable();
    });
    el.appendChild(sel);

    if (S.pageSize <= 0 || total <= S.pageSize) return;

    var prev = document.createElement('button');
    prev.className = 'page-btn';
    prev.textContent = '← Prev';
    prev.disabled = S.page <= 1;
    prev.addEventListener('click', function() {
      if (S.page > 1) { S.page--; renderTable(); window.scrollTo({top: document.getElementById('listingsTbody').getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth'}); }
    });
    el.appendChild(prev);

    var info = document.createElement('span');
    info.className = 'page-info';
    var from = (S.page - 1) * S.pageSize + 1;
    var to   = Math.min(S.page * S.pageSize, total);
    info.textContent = from + '–' + to + ' of ' + total;
    el.appendChild(info);

    var next = document.createElement('button');
    next.className = 'page-btn';
    next.textContent = 'Next →';
    next.disabled = S.page >= totalPages;
    next.addEventListener('click', function() {
      if (S.page < totalPages) { S.page++; renderTable(); window.scrollTo({top: document.getElementById('listingsTbody').getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth'}); }
    });
    el.appendChild(next);
  }

  // ── Expand / radar ─────────────────────────────────────────────────────────
  function toggleExpand(d, dataRow, expandRow) {
    var isOpen = expandRow.classList.contains('open');

    // Close any open row first
    document.querySelectorAll('tr.expand-row.open').forEach(function(r) {
      r.classList.remove('open');
      r.querySelector('td').innerHTML = '';
    });
    document.querySelectorAll('tr.data-row').forEach(function(r) {
      r.classList.remove('highlighted');
    });
    if (openRadarChart) { openRadarChart.destroy(); openRadarChart = null; }
    openRowId = null;

    if (isOpen) return; // was open → just close

    expandRow.classList.add('open');
    dataRow.classList.add('highlighted');
    openRowId = d.id;

    var td = expandRow.querySelector('td');
    var inner = document.createElement('div');
    inner.className = 'expand-inner';

    // Radar chart
    var radarWrap = document.createElement('div');
    radarWrap.className = 'radar-wrap';
    var canvas = document.createElement('canvas');
    canvas.id = 'radarCanvas-' + d.id.replace(/[^a-z0-9]/gi,'_');
    radarWrap.appendChild(canvas);

    var subtitle = document.createElement('div');
    subtitle.className = 'expand-subtitle';
    subtitle.textContent = 'Weighted total: ' + d.display_score + '  ·  Confidence: ' + d.confidence;
    radarWrap.appendChild(subtitle);
    inner.appendChild(radarWrap);

    // Factor breakdown
    var right = document.createElement('div');
    var table = document.createElement('table');
    table.className = 'breakdown-table';
    var thead = table.createTHead();
    var hrow = thead.insertRow();
    ['Factor','Raw','Weight','Weighted','Reason'].forEach(function(h) {
      var th = document.createElement('th');
      th.textContent = h;
      hrow.appendChild(th);
    });
    var tbody2 = table.createTBody();
    d.factors.forEach(function(f) {
      var row = tbody2.insertRow();
      [f.key, f.raw.toFixed(1), f.weight.toFixed(2), f.weighted.toFixed(2), f.reason].forEach(function(v, i) {
        var cell = row.insertCell();
        cell.textContent = v;
      });
    });
    right.appendChild(table);
    inner.appendChild(right);
    td.appendChild(inner);

    // Draw radar
    var labels = d.factors.map(function(f){ return f.key.replace(/_/g,' '); });
    var values = d.factors.map(function(f){ return f.raw; });
    openRadarChart = new Chart(canvas.getContext('2d'), {
      type: 'radar',
      data: {
        labels: labels,
        datasets: [{
          label: (d.year || '') + ' ' + (d.make || '') + ' ' + (d.model || ''),
          data: values,
          backgroundColor: 'rgba(217,119,6,0.12)',
          borderColor: 'rgba(217,119,6,0.75)',
          borderWidth: 1.5,
          pointBackgroundColor: 'rgba(217,119,6,0.8)',
          pointRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        animation: { duration: 180 },
        plugins: {
          legend: { display: false },
        },
        scales: {
          r: {
            min: 0, max: 10,
            ticks: { stepSize: 2, font: { size: 9 }, color: '#9c9890', backdropColor: 'transparent' },
            grid: { color: '#e5e3df' },
            angleLines: { color: '#e5e3df' },
            pointLabels: { font: { size: 9 }, color: '#6b6861' },
          },
        },
      },
    });
  }

  // ── Scroll + highlight ─────────────────────────────────────────────────────
  function scrollToRow(id) {
    if (S.pageSize > 0) {
      var sorted = filteredListings();
      sorted.sort(function(a, b) {
        var av = a[S.sortCol], bv = b[S.sortCol];
        if (av == null) av = S.sortDir === 'asc' ? Infinity : -Infinity;
        if (bv == null) bv = S.sortDir === 'asc' ? Infinity : -Infinity;
        if (typeof av === 'string') av = av.toLowerCase();
        if (typeof bv === 'string') bv = bv.toLowerCase();
        if (av < bv) return S.sortDir === 'asc' ? -1 : 1;
        if (av > bv) return S.sortDir === 'asc' ? 1 : -1;
        return 0;
      });
      var idx = -1;
      for (var i = 0; i < sorted.length; i++) {
        if (sorted[i].id === id) { idx = i; break; }
      }
      if (idx >= 0) {
        var targetPage = Math.floor(idx / S.pageSize) + 1;
        if (targetPage !== S.page) { S.page = targetPage; renderTable(); }
      }
    }
    var row = document.querySelector('tr.data-row[data-id="' + CSS.escape(id) + '"]');
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('highlighted');
    setTimeout(function(){ if (openRowId !== id) row.classList.remove('highlighted'); }, 2500);
  }

  // ── Lightbox ───────────────────────────────────────────────────────────────
  var lbPhotos = [], lbIdx = 0;
  function openLightbox(photos, idx) {
    if (!photos || !photos.length) return;
    lbPhotos = photos; lbIdx = idx;
    updateLightbox();
    document.getElementById('lightbox').classList.add('open');
  }
  function updateLightbox() {
    document.getElementById('lbImg').src = lbPhotos[lbIdx];
    document.getElementById('lbCounter').textContent = (lbIdx + 1) + ' / ' + lbPhotos.length;
  }

  // ── Apply all filters ──────────────────────────────────────────────────────
  function applyFilters() {
    S.page = 1;
    renderTable();
    buildScatter();
  }

  // ── Header sort ───────────────────────────────────────────────────────────
  function attachSortHandlers() {
    document.querySelectorAll('table.listings thead th[data-col]').forEach(function(th) {
      var col = th.dataset.col;
      if (!SORTABLE.has(col)) return;
      th.addEventListener('click', function() {
        if (S.sortCol === col) {
          S.sortDir = S.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          S.sortCol = col;
          S.sortDir = col === 'score' ? 'desc' : 'asc';
        }
        renderTable();
      });
    });
  }

  // ── Filter controls wiring ─────────────────────────────────────────────────
  function initFilters() {
    // Source dropdown
    var selSrc = document.getElementById('filterSource');
    selSrc.addEventListener('change', function() {
      S.source = this.value;
      applyFilters();
    });

    // Score slider
    var scoreSlider = document.getElementById('filterScore');
    var scoreLabel  = document.getElementById('filterScoreLabel');
    scoreSlider.addEventListener('input', function() {
      S.minScore = +this.value;
      scoreLabel.textContent = this.value;
      applyFilters();
    });

    // Body checkboxes
    document.querySelectorAll('.body-cb').forEach(function(cb) {
      cb.parentElement.classList.add('checked'); // all checked initially
      cb.addEventListener('change', function() {
        if (this.checked) {
          S.bodyTypes.add(this.value);
          this.parentElement.classList.add('checked');
        } else {
          S.bodyTypes.delete(this.value);
          this.parentElement.classList.remove('checked');
        }
        applyFilters();
      });
    });

    // Year min
    var yearInput = document.getElementById('filterYear');
    yearInput.addEventListener('change', function() {
      S.yearMin = +this.value || 2008;
      applyFilters();
    });

    // Price range double slider
    var priceMinEl = document.getElementById('priceMin');
    var priceMaxEl = document.getElementById('priceMax');
    var priceLabel = document.getElementById('priceLabel');
    function updatePrice() {
      var lo = +priceMinEl.value, hi = +priceMaxEl.value;
      if (lo > hi) { var t = lo; lo = hi; hi = t; }
      S.priceMin = lo; S.priceMax = hi;
      priceLabel.textContent = '$' + (lo/1000).toFixed(0) + 'k – $' + (hi/1000).toFixed(lo >= 1000 ? 1 : 0) + 'k';
      applyFilters();
    }
    priceMinEl.addEventListener('input', updatePrice);
    priceMaxEl.addEventListener('input', updatePrice);

    // Mileage range double slider
    var mileMin = document.getElementById('mileMin');
    var mileMax = document.getElementById('mileMax');
    var mileLabel = document.getElementById('mileLabel');
    function updateMileage() {
      var lo = +mileMin.value, hi = +mileMax.value;
      if (lo > hi) { var t = lo; lo = hi; hi = t; }
      S.mileMin = lo; S.mileMax = hi;
      mileLabel.textContent = (lo/1000).toFixed(0) + 'k – ' + (hi/1000).toFixed(0) + 'k mi';
      applyFilters();
    }
    mileMin.addEventListener('input', updateMileage);
    mileMax.addEventListener('input', updateMileage);

    // Reset
    document.getElementById('btnReset').addEventListener('click', function() {
      S.source = 'all'; S.minScore = 0;
      S.bodyTypes = new Set(['SUV','Sedan','Wagon','Hatchback','Coupe','Truck','Van','Unknown']);
      S.priceMin = 0; S.priceMax = 20000;
      S.mileMin = 0; S.mileMax = 200000; S.yearMin = 2008;
      selSrc.value = 'all';
      scoreSlider.value = 0; scoreLabel.textContent = '0';
      document.querySelectorAll('.body-cb').forEach(function(cb){
        cb.checked = true; cb.parentElement.classList.add('checked');
      });
      yearInput.value = 2008;
      priceMinEl.value = 0; priceMaxEl.value = 20000;
      priceLabel.textContent = '$0k – $20k';
      mileMin.value = 0; mileMax.value = 200000;
      mileLabel.textContent = '0k – 200k mi';
      applyFilters();
    });
  }

  // ── Lightbox wiring ────────────────────────────────────────────────────────
  function initLightbox() {
    document.getElementById('lightbox').addEventListener('click', function(e) {
      if (e.target === this) this.classList.remove('open');
    });
    document.getElementById('lbClose').addEventListener('click', function() {
      document.getElementById('lightbox').classList.remove('open');
    });
    document.getElementById('lbPrev').addEventListener('click', function() {
      lbIdx = (lbIdx - 1 + lbPhotos.length) % lbPhotos.length;
      updateLightbox();
    });
    document.getElementById('lbNext').addEventListener('click', function() {
      lbIdx = (lbIdx + 1) % lbPhotos.length;
      updateLightbox();
    });
    document.addEventListener('keydown', function(e) {
      var lb = document.getElementById('lightbox');
      if (!lb.classList.contains('open')) return;
      if (e.key === 'Escape') lb.classList.remove('open');
      if (e.key === 'ArrowLeft')  { lbIdx = (lbIdx - 1 + lbPhotos.length) % lbPhotos.length; updateLightbox(); }
      if (e.key === 'ArrowRight') { lbIdx = (lbIdx + 1) % lbPhotos.length; updateLightbox(); }
    });
  }

  // ── Import modal ───────────────────────────────────────────────────────────
  function openImportModal() {
    document.getElementById('importModal').classList.add('open');
    document.getElementById('f-make').focus();
  }
  function closeImportModal() {
    document.getElementById('importModal').classList.remove('open');
    document.getElementById('formMsg').textContent = '';
  }
  function submitImport() {
    var make = document.getElementById('f-make').value.trim();
    var model = document.getElementById('f-model').value.trim();
    var year = document.getElementById('f-year').value.trim();
    var msgEl = document.getElementById('formMsg');
    if (!make || !model || !year) { msgEl.textContent = 'Make, model, and year are required.'; return; }
    var btn = document.getElementById('importSubmit');
    btn.disabled = true; btn.textContent = 'Saving…';
    fetch('/api/import', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        url:         document.getElementById('f-url').value.trim() || null,
        make:        make,
        model:       model,
        year:        +year,
        trim:        document.getElementById('f-trim').value.trim() || null,
        body_type:   document.getElementById('f-body-type').value || null,
        mileage:     document.getElementById('f-mileage').value || null,
        price:       document.getElementById('f-price').value || null,
        location:    document.getElementById('f-location').value.trim() || null,
        seller_type: document.getElementById('f-seller-type').value,
        notes:       document.getElementById('f-notes').value.trim() || null,
      }),
    })
    .then(function(r){ return r.json(); })
    .then(function(data) {
      if (data.ok) { window.location.reload(); }
      else { msgEl.textContent = data.error || 'Error saving listing.'; btn.disabled = false; btn.textContent = 'Save listing'; }
    })
    .catch(function(err) {
      msgEl.textContent = 'Network error: ' + err.message;
      btn.disabled = false; btn.textContent = 'Save listing';
    });
  }
  function deleteRow(listingId, dataRow, expandRow) {
    if (!confirm('Remove this listing from the database?')) return;
    fetch('/api/delete/' + encodeURIComponent(listingId), { method: 'POST' })
    .then(function(r){ return r.json(); })
    .then(function(d) {
      if (!d.ok) return;
      if (expandRow) expandRow.remove();
      dataRow.remove();
      var tbody = document.getElementById('listingsTbody');
      var n = tbody ? tbody.querySelectorAll('tr.data-row').length : 0;
      var countEl = document.getElementById('tableCount');
      if (countEl) countEl.textContent = n + ' listing' + (n !== 1 ? 's' : '');
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    initFilters();
    initLightbox();
    attachSortHandlers();
    renderTable();
    buildScatter();

    if (SERVER_MODE) {
      var importBtn = document.getElementById('importBtn');
      if (importBtn) importBtn.style.display = 'block';
      document.querySelectorAll('.col-actions').forEach(function(el){ el.style.display = ''; });
      importBtn.addEventListener('click', openImportModal);
      document.getElementById('importCancel').addEventListener('click', closeImportModal);
      document.getElementById('importSubmit').addEventListener('click', submitImport);
      document.getElementById('importModal').addEventListener('click', function(e){ if (e.target === this) closeImportModal(); });
      document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeImportModal(); });
    }
  });

}());
"""

# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

def render_html(
    scored: list["ScoredListing"],
    config: "Config | None" = None,
) -> str:
    """Return a self-contained HTML dashboard string.

    Pure function — no I/O. Inline JSON-encodes all listing data into the
    page so it works as a static file:// document (except Chart.js CDN
    and external photo URLs which require network).
    """
    today = datetime.date.today().isoformat()
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    git = _git_hash()
    footer_hash = f"· {git}" if git else ""

    stats = _compute_stats(scored)
    listings_data = [_listing_to_dict(s) for s in scored]

    # JSON-encode into the page — use separators to keep it compact
    listings_json = json.dumps(listings_data, separators=(",", ":"), default=str)

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
        "<!-- Chart.js from CDN — requires network for charts to render -->",
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>',
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
        '    <label for="filterSource">Source</label>',
        '    <select id="filterSource">',
        '      <option value="all">All sources</option>',
        '      <option value="craigslist">Craigslist</option>',
        '      <option value="carmax">CarMax</option>',
        '      <option value="carscom">Cars.com</option>',
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
        f"/* global LISTINGS */",  # noqa
        f"var LISTINGS = {listings_json};",  # noqa: S608
        "</script>",
        "<script>",
        _JS,
        "</script>",
        "</body>",
        "</html>",
    ]

    return "\n".join(lines)
