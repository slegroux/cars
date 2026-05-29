"""Render — rich tables, Markdown export, and vault writer."""
from __future__ import annotations

import datetime
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


def _md_alt(text: str) -> str:
    """Escape characters that would break a Markdown image/link alt-text.

    Scraped make/model strings can contain ``[`` / ``]`` that would otherwise
    corrupt ``![alt](url)`` syntax in the exported vault file.
    """
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _safe_md_url(url: str | None) -> str | None:
    """Return ``url`` only when it is an http(s) URL, else None.

    Prevents a scraped ``javascript:`` / ``data:`` URL from being emitted as a
    clickable Markdown link in the exported vault note.
    """
    if not url:
        return None
    return url if url.lower().startswith(("http://", "https://")) else None


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

        lst = s.listing
        raw_score = _score_cell(s)
        # Color by score value using Text objects (not markup strings)
        if s.score >= 80:
            score_cell = Text(raw_score, style="green")
        elif s.score >= 60:
            score_cell = Text(raw_score, style="yellow")
        else:
            score_cell = Text(raw_score, style="dim white")

        mileage_str = f"{lst.mileage:,}" if lst.mileage is not None else "—"
        price_str = f"${lst.asking_price:,.0f}" if lst.asking_price is not None else "—"

        table.add_row(
            str(rank),
            score_cell,
            str(lst.year or "—"),
            lst.make or "—",
            lst.model or "—",
            lst.trim or "—",
            mileage_str,
            price_str,
            lst.source or "—",
            lst.location or "—",
            _days_on_market(lst),
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
        lst = s.listing
        mileage_str = f"{lst.mileage:,}" if lst.mileage is not None else "—"
        price_str = f"${lst.asking_price:,.0f}" if lst.asking_price is not None else "—"
        row = [
            str(rank),
            _score_cell(s),
            str(lst.year or "—"),
            lst.make or "—",
            lst.model or "—",
            lst.trim or "—",
            mileage_str,
            price_str,
            lst.source or "—",
            lst.location or "—",
            _days_on_market(lst),
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # Section 3: per-vehicle breakdown
    for rank, s in enumerate(items, 1):
        lst = s.listing
        name_parts = [str(lst.year or ""), lst.make or "", lst.model or ""]
        if lst.trim:
            name_parts.append(lst.trim)
        vehicle_name = " ".join(p for p in name_parts if p)
        badge = _confidence_badge(s.confidence)

        lines.append(f"### {rank}. {vehicle_name} — {_score_cell(s)} {badge}")
        lines.append("")

        # One-line meta
        price_str = f"${lst.asking_price:,.0f}" if lst.asking_price is not None else "—"
        mileage_str = f"{lst.mileage:,}" if lst.mileage is not None else "—"
        vin_str = lst.vin or "—"
        lines.append(
            f"**Price:** {price_str} · **Miles:** {mileage_str} · "
            f"**Source:** {lst.source or '—'} · **Location:** {lst.location or '—'} · "
            f"**VIN:** {vin_str}"
        )
        lines.append("")

        # Link — only emit validated http(s) URLs
        safe_url = _safe_md_url(lst.url)
        if safe_url:
            lines.append(f"[View listing]({safe_url})")
            lines.append("")

        # Photos — skip non-http(s) URLs and escape the alt text
        photos = lst.photos or []
        embedded = 0
        for photo_url in photos[:photo_thumbnails]:
            safe_photo = _safe_md_url(photo_url)
            if safe_photo:
                lines.append(f"![{_md_alt(vehicle_name)}]({safe_photo})")
                embedded += 1
        if embedded:
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

    lst = scored.listing

    # Basic info text
    info_lines = [
        f"[bold]Score:[/bold] {_score_cell(scored)}  [bold]Confidence:[/bold] {scored.confidence}",
        f"[bold]Year:[/bold] {lst.year or '—'}  [bold]Make:[/bold] {lst.make or '—'}  "
        f"[bold]Model:[/bold] {lst.model or '—'}  [bold]Trim:[/bold] {lst.trim or '—'}",
        f"[bold]Price:[/bold] {'$' + f'{lst.asking_price:,.0f}' if lst.asking_price else '—'}  "
        f"[bold]Mileage:[/bold] {f'{lst.mileage:,}' if lst.mileage else '—'}",
        f"[bold]Body:[/bold] {lst.body_type or '—'}  [bold]Drivetrain:[/bold] {lst.drivetrain or '—'}  "
        f"[bold]Transmission:[/bold] {lst.transmission or '—'}",
        f"[bold]Fuel:[/bold] {lst.fuel_type or '—'}  [bold]MPG:[/bold] {lst.mpg_combined or '—'}",
        f"[bold]Title:[/bold] {lst.title_status or '—'}  [bold]Condition:[/bold] {lst.condition or '—'}",
        f"[bold]VIN:[/bold] {lst.vin or '—'}",
        f"[bold]Location:[/bold] {lst.location or '—'}  [bold]Distance:[/bold] {lst.distance_miles or '—'} mi",
        f"[bold]Source:[/bold] {lst.source or '—'}  [bold]Source ID:[/bold] {lst.source_id or '—'}",
        f"[bold]URL:[/bold] {lst.url or '—'}",
        f"[bold]Posted:[/bold] {lst.posted_date or '—'}  [bold]Days listed:[/bold] {lst.days_listed or '—'}",
    ]

    # Description (truncated)
    if lst.description:
        desc = lst.description[:500]
        if len(lst.description) > 500:
            desc += "…"
        info_lines += ["", "[bold]Description:[/bold]", desc]

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

    name_parts = [str(lst.year or ""), lst.make or "", lst.model or ""]
    if lst.trim:
        name_parts.append(lst.trim)
    title = " ".join(p for p in name_parts if p) or lst.id or "Listing"

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

    for lst in listings:
        src = lst.source or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1
        bt = lst.body_type or "unknown"
        body_counts[bt] = body_counts.get(bt, 0) + 1
        mk = lst.make or "unknown"
        make_counts[mk] = make_counts.get(mk, 0) + 1
        if lst.asking_price is not None:
            prices.append(lst.asking_price)

    # Price stats
    price_min = min(prices) if prices else None
    price_max = max(prices) if prices else None
    price_med = statistics.median(prices) if prices else None

    # Last run timestamp
    try:
        row = conn.execute("SELECT MAX(last_seen) FROM listings").fetchone()
        last_seen = row[0] if row and row[0] else "—"
    except sqlite3.Error:
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
    scores = [lst.score for lst in listings if lst.score is not None]
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
