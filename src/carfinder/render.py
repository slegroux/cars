"""Render — rich tables, Markdown export, and vault writer."""
from __future__ import annotations

import datetime
import os
import sqlite3
import statistics
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from carfinder.config import Config
    from carfinder.models import Listing
    from carfinder.scorer import ScoredListing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_cell(scored: "ScoredListing") -> str:
    """Score string with confidence prefix."""
    return scored.display_score()


def _confidence_badge(confidence: str) -> str:
    if confidence == "full":
        return "[full]"
    if confidence == "partial":
        return "[~partial]"
    return "[~low*]"


def _days_on_market(listing: "Listing") -> str:
    if listing.first_seen:
        delta = datetime.datetime.now(datetime.timezone.utc) - listing.first_seen
        return str(delta.days)
    if listing.days_listed is not None:
        return str(listing.days_listed)
    return "—"


# ---------------------------------------------------------------------------
# render_table
# ---------------------------------------------------------------------------

def render_table(
    scored: list["ScoredListing"],
    top_n: int | None = None,
    min_score: float | None = None,
):
    """Return a rich Table of scored listings."""
    from rich.table import Table

    items = list(scored)
    if min_score is not None:
        items = [s for s in items if s.score >= min_score]
    if top_n is not None:
        items = items[:top_n]

    table = Table(title=f"Top {len(items)} Listings", show_lines=False)
    table.add_column("#", justify="right", width=4)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Year", justify="center", width=6)
    table.add_column("Make", width=10)
    table.add_column("Model", width=12)
    table.add_column("Trim", width=10)
    table.add_column("Miles", justify="right", width=9)
    table.add_column("Price", justify="right", width=9)
    table.add_column("Source", width=10)
    table.add_column("Location", width=16)
    table.add_column("Days", justify="right", width=5)

    for rank, s in enumerate(items, 1):
        from rich.text import Text

        l = s.listing
        raw_score = _score_cell(s)
        # Color by score value using Text objects (not markup strings)
        if s.score >= 80:
            score_cell = Text(raw_score, style="green")
        elif s.score >= 60:
            score_cell = Text(raw_score, style="yellow")
        else:
            score_cell = Text(raw_score, style="dim white")

        mileage_str = f"{l.mileage:,}" if l.mileage is not None else "—"
        price_str = f"${l.asking_price:,.0f}" if l.asking_price is not None else "—"

        table.add_row(
            str(rank),
            score_cell,
            str(l.year or "—"),
            l.make or "—",
            l.model or "—",
            l.trim or "—",
            mileage_str,
            price_str,
            l.source or "—",
            l.location or "—",
            _days_on_market(l),
        )

    return table


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

def render_markdown(
    scored: list["ScoredListing"],
    top_n: int,
    photo_thumbnails: int = 3,
) -> str:
    """Return a Markdown string for vault export."""
    today = datetime.date.today()
    iso_date = today.isoformat()

    items = scored[:top_n]

    # Count confidences
    full_count = sum(1 for s in items if s.confidence == "full")
    partial_count = sum(1 for s in items if s.confidence == "partial")
    low_count = sum(1 for s in items if s.confidence == "low")

    # Count by source
    source_counts: dict[str, int] = {}
    for s in items:
        src = s.listing.source or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1
    sources_str = ", ".join(f"{src} ({cnt})" for src, cnt in source_counts.items())

    # YAML frontmatter
    lines: list[str] = [
        "---",
        f'title: "Car Finder Shortlist — {today}"',
        "type: shortlist",
        "domain: cars",
        f"updated: {iso_date}",
        "sources: [craigslist, carmax]",
        "budget: [5000, 12000]",
        "---",
        "",
    ]

    # Section 1: prose summary
    lines += [
        f"Top {len(items)} listings ranked by personal-profile scorer. "
        f"Confidence: {full_count} full / {partial_count} partial / {low_count} low. "
        f"Sources: {sources_str}.",
        "",
    ]

    # Section 2: summary table
    header_cols = ["#", "Score", "Year", "Make", "Model", "Trim", "Miles", "Price", "Source", "Location", "Days"]
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("| " + " | ".join("---" for _ in header_cols) + " |")

    for rank, s in enumerate(items, 1):
        l = s.listing
        mileage_str = f"{l.mileage:,}" if l.mileage is not None else "—"
        price_str = f"${l.asking_price:,.0f}" if l.asking_price is not None else "—"
        row = [
            str(rank),
            _score_cell(s),
            str(l.year or "—"),
            l.make or "—",
            l.model or "—",
            l.trim or "—",
            mileage_str,
            price_str,
            l.source or "—",
            l.location or "—",
            _days_on_market(l),
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # Section 3: per-vehicle breakdown
    for rank, s in enumerate(items, 1):
        l = s.listing
        name_parts = [str(l.year or ""), l.make or "", l.model or ""]
        if l.trim:
            name_parts.append(l.trim)
        vehicle_name = " ".join(p for p in name_parts if p)
        badge = _confidence_badge(s.confidence)

        lines.append(f"### {rank}. {vehicle_name} — {_score_cell(s)} {badge}")
        lines.append("")

        # One-line meta
        price_str = f"${l.asking_price:,.0f}" if l.asking_price is not None else "—"
        mileage_str = f"{l.mileage:,}" if l.mileage is not None else "—"
        vin_str = l.vin or "—"
        lines.append(
            f"**Price:** {price_str} · **Miles:** {mileage_str} · "
            f"**Source:** {l.source or '—'} · **Location:** {l.location or '—'} · "
            f"**VIN:** {vin_str}"
        )
        lines.append("")

        # Link
        if l.url:
            lines.append(f"[View listing]({l.url})")
            lines.append("")

        # Photos
        photos = l.photos or []
        for photo_url in photos[:photo_thumbnails]:
            lines.append(f"![{vehicle_name}]({photo_url})")
        if photos:
            lines.append("")

        # Score breakdown table
        if s.score_breakdown:
            lines.append("| Factor | Raw | Weight | Weighted | Reason |")
            lines.append("| --- | --- | --- | --- | --- |")
            for factor_name, fs in s.score_breakdown.items():
                lines.append(
                    f"| {factor_name} | {fs.raw:.1f} | {fs.weight:.2f} | {fs.weighted:.2f} | {fs.reason} |"
                )
            lines.append("")

        # Rationale from top 3 strongest factors
        if s.score_breakdown:
            sorted_factors = sorted(
                s.score_breakdown.items(),
                key=lambda kv: kv[1].weighted,
                reverse=True,
            )
            top_factors = sorted_factors[:3]
            rationale_parts = []
            for fname, fs in top_factors:
                rationale_parts.append(f"{fname} scores {fs.raw:.0f}/10 ({fs.reason})")
            lines.append("> " + "; ".join(rationale_parts) + ".")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# render_show
# ---------------------------------------------------------------------------

def render_show(scored: "ScoredListing"):
    """Return a rich renderable for a single listing detail view."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    l = scored.listing

    # Basic info text
    info_lines = [
        f"[bold]Score:[/bold] {_score_cell(scored)}  [bold]Confidence:[/bold] {scored.confidence}",
        f"[bold]Year:[/bold] {l.year or '—'}  [bold]Make:[/bold] {l.make or '—'}  "
        f"[bold]Model:[/bold] {l.model or '—'}  [bold]Trim:[/bold] {l.trim or '—'}",
        f"[bold]Price:[/bold] {'$' + f'{l.asking_price:,.0f}' if l.asking_price else '—'}  "
        f"[bold]Mileage:[/bold] {f'{l.mileage:,}' if l.mileage else '—'}",
        f"[bold]Body:[/bold] {l.body_type or '—'}  [bold]Drivetrain:[/bold] {l.drivetrain or '—'}  "
        f"[bold]Transmission:[/bold] {l.transmission or '—'}",
        f"[bold]Fuel:[/bold] {l.fuel_type or '—'}  [bold]MPG:[/bold] {l.mpg_combined or '—'}",
        f"[bold]Title:[/bold] {l.title_status or '—'}  [bold]Condition:[/bold] {l.condition or '—'}",
        f"[bold]VIN:[/bold] {l.vin or '—'}",
        f"[bold]Location:[/bold] {l.location or '—'}  [bold]Distance:[/bold] {l.distance_miles or '—'} mi",
        f"[bold]Source:[/bold] {l.source or '—'}  [bold]Source ID:[/bold] {l.source_id or '—'}",
        f"[bold]URL:[/bold] {l.url or '—'}",
        f"[bold]Posted:[/bold] {l.posted_date or '—'}  [bold]Days listed:[/bold] {l.days_listed or '—'}",
    ]

    # Description (truncated)
    if l.description:
        desc = l.description[:500]
        if len(l.description) > 500:
            desc += "…"
        info_lines += ["", f"[bold]Description:[/bold]", desc]

    info_text = Text.from_markup("\n".join(info_lines))

    # Score breakdown table
    breakdown_table = Table(title="Score Breakdown", show_lines=True)
    breakdown_table.add_column("Factor", width=20)
    breakdown_table.add_column("Raw", justify="right", width=6)
    breakdown_table.add_column("Weight", justify="right", width=8)
    breakdown_table.add_column("Weighted", justify="right", width=10)
    breakdown_table.add_column("Conf", width=10)
    breakdown_table.add_column("Reason")

    for factor_name, fs in scored.score_breakdown.items():
        breakdown_table.add_row(
            factor_name,
            f"{fs.raw:.1f}",
            f"{fs.weight:.2f}",
            f"{fs.weighted:.2f}",
            fs.confidence,
            fs.reason,
        )

    name_parts = [str(l.year or ""), l.make or "", l.model or ""]
    if l.trim:
        name_parts.append(l.trim)
    title = " ".join(p for p in name_parts if p) or l.id or "Listing"

    return Panel(
        Group(info_text, breakdown_table),
        title=title,
        border_style="cyan",
    )


# ---------------------------------------------------------------------------
# render_stats
# ---------------------------------------------------------------------------

def render_stats(listings: list["Listing"], conn: sqlite3.Connection):
    """Return a rich renderable dashboard of database statistics."""
    from rich.console import Group
    from rich.table import Table
    from rich.text import Text

    # --- Basic counts ---
    total = len(listings)

    source_counts: dict[str, int] = {}
    body_counts: dict[str, int] = {}
    make_counts: dict[str, int] = {}
    prices: list[float] = []

    for l in listings:
        src = l.source or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1
        bt = l.body_type or "unknown"
        body_counts[bt] = body_counts.get(bt, 0) + 1
        mk = l.make or "unknown"
        make_counts[mk] = make_counts.get(mk, 0) + 1
        if l.asking_price is not None:
            prices.append(l.asking_price)

    # Price stats
    price_min = min(prices) if prices else None
    price_max = max(prices) if prices else None
    price_med = statistics.median(prices) if prices else None

    # Last run timestamp
    try:
        row = conn.execute("SELECT MAX(last_seen) FROM listings").fetchone()
        last_seen = row[0] if row and row[0] else "—"
    except Exception:
        last_seen = "—"

    # --- Summary table ---
    summary_table = Table(title=f"Database Summary — {total} total listings", show_lines=False)
    summary_table.add_column("Metric", width=20)
    summary_table.add_column("Value", width=30)

    summary_table.add_row("Total listings", str(total))
    summary_table.add_row("Last seen", str(last_seen))
    if prices:
        summary_table.add_row("Price min", f"${price_min:,.0f}")
        summary_table.add_row("Price median", f"${price_med:,.0f}")
        summary_table.add_row("Price max", f"${price_max:,.0f}")
    else:
        summary_table.add_row("Price data", "none")

    # --- By-source table ---
    src_table = Table(title="By Source", show_lines=False)
    src_table.add_column("Source", width=15)
    src_table.add_column("Count", justify="right", width=8)
    for src, cnt in sorted(source_counts.items(), key=lambda kv: kv[1], reverse=True):
        src_table.add_row(src, str(cnt))

    # --- By body type ---
    body_table = Table(title="By Body Type", show_lines=False)
    body_table.add_column("Body Type", width=15)
    body_table.add_column("Count", justify="right", width=8)
    for bt, cnt in sorted(body_counts.items(), key=lambda kv: kv[1], reverse=True):
        body_table.add_row(bt, str(cnt))

    # --- Top 10 makes ---
    make_table = Table(title="Top Makes", show_lines=False)
    make_table.add_column("Make", width=15)
    make_table.add_column("Count", justify="right", width=8)
    top_makes = sorted(make_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    for mk, cnt in top_makes:
        make_table.add_row(mk, str(cnt))

    # --- Score histogram ---
    scores = [l.score for l in listings if l.score is not None]
    bins = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]
    bin_counts = [
        sum(1 for s in scores if lo <= s < hi) for (lo, hi) in bins
    ]
    # Include 100 in last bin
    bin_counts[-1] += sum(1 for s in scores if s == 100)

    max_bin = max(bin_counts) if bin_counts else 1
    bar_width = 30

    hist_lines = ["[bold]Score Distribution[/bold]"]
    for (lo, hi), cnt in zip(bins, bin_counts):
        bar_len = int(bar_width * cnt / max_bin) if max_bin > 0 else 0
        bar = "█" * bar_len
        hist_lines.append(f"  {lo:>3}-{hi:<3}  {bar:<{bar_width}}  {cnt}")
    hist_text = Text.from_markup("\n".join(hist_lines))

    return Group(summary_table, src_table, body_table, make_table, hist_text)


# ---------------------------------------------------------------------------
# export_to_vault
# ---------------------------------------------------------------------------

def export_to_vault(markdown: str, config: "Config") -> Path:
    """Write markdown to vault directory. Returns the written path."""
    return export_markdown_to_vault(markdown, config)


def export_markdown_to_vault(markdown: str, config: "Config") -> Path:
    """Write markdown to vault directory. Returns the written path."""
    from carfinder.config import resolved_vault_path

    vault_dir = resolved_vault_path(config)
    vault_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today().isoformat()
    out_path = vault_dir / f"shortlist-{today}.md"
    out_path.write_text(markdown, encoding="utf-8")
    return out_path


def export_html_to_vault(html: str, config: "Config") -> Path:
    """Write HTML dashboard to vault directory. Returns the written path."""
    from carfinder.config import resolved_vault_path

    vault_dir = resolved_vault_path(config)
    vault_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today().isoformat()
    out_path = vault_dir / f"shortlist-{today}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
