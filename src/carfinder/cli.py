"""CLI entry point using Click."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click

from carfinder.service import load_scored_listings as _load_scored_listings

if TYPE_CHECKING:
    pass


@click.group()
@click.option("--verbose", is_flag=True, default=False, help="Enable INFO logging.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Car Finder — aggregate and score used-car listings."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Fetcher registry — add new source classes here
# ---------------------------------------------------------------------------
def _get_fetcher_registry():
    from carfinder.fetchers.carmax import CarMaxFetcher
    from carfinder.fetchers.carscom import CarsDotComFetcher
    from carfinder.fetchers.craigslist import CraigslistFetcher
    from carfinder.fetchers.kbb import KBBFetcher
    return {
        "craigslist": CraigslistFetcher,
        "carmax": CarMaxFetcher,
        "carscom": CarsDotComFetcher,
        "kbb": KBBFetcher,
    }


async def _run_search(config, enabled_sources: list[str]) -> None:
    """Run all enabled fetchers concurrently, upsert results."""
    from carfinder.db import find_fuzzy_duplicate, init_db, upsert_listing

    logger = logging.getLogger(__name__)
    registry = _get_fetcher_registry()

    db_path = Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    fetchers = []
    for source in enabled_sources:
        cls = registry.get(source)
        if cls is None:
            logger.warning("Unknown source %r — skipping", source)
            continue
        fetchers.append((source, cls(config)))

    if not fetchers:
        # Open the DB connection only after this guard so the early return
        # can't leak a connection.
        click.echo("No valid sources configured.")
        return

    conn = init_db(db_path)
    counters = {"fetched": 0, "new": 0, "updated": 0, "fuzzy": 0, "skipped": 0}

    async def run_fetcher(source: str, fetcher) -> None:
        try:
            async for listing in fetcher.fetch_listings(config):
                counters["fetched"] += 1

                # Drop manuals if configured
                if (
                    config.transmission.exclude_manual
                    and listing.transmission == "manual"
                ):
                    logger.info(
                        "Skipping manual transmission listing %s", listing.id
                    )
                    counters["skipped"] += 1
                    continue

                # VIN-first dedup / fuzzy fallback
                dup = find_fuzzy_duplicate(conn, listing)
                if dup is not None and not listing.vin:
                    logger.info(
                        "Fuzzy duplicate flagged: %s ~ %s", listing.id, dup.id
                    )
                    counters["fuzzy"] += 1

                # Check if already exists (to distinguish new vs updated)
                existing = conn.execute(
                    "SELECT id FROM listings WHERE source=? AND source_id=?",
                    (listing.source, listing.source_id),
                ).fetchone()

                upsert_listing(conn, listing)

                if existing:
                    counters["updated"] += 1
                else:
                    counters["new"] += 1

                # M3a score post-upsert hook — uncomment when wiring scorer into search:
                # try:
                #     from carfinder.scorer import score_listing
                #     from carfinder.lookups import load_lookups
                #     lk = load_lookups(Path("data"))
                #     all_listings = get_listings(conn)
                #     scored = score_listing(listing, all_listings, config, lk)
                #     updated = scored.listing.model_copy(update={
                #         "score": scored.score,
                #         "score_breakdown": {k: v.model_dump() for k, v in scored.score_breakdown.items()},
                #         "score_confidence": scored.confidence,
                #     })
                #     upsert_listing(conn, updated)
                # except ImportError:
                #     pass

        except asyncio.CancelledError:
            logger.error("Fetcher %r timed out after 300s", source)
        except Exception as exc:
            logger.error("Fetcher %r failed: %s", source, exc)

    tasks = [
        asyncio.wait_for(run_fetcher(src, f), timeout=300.0)
        for src, f in fetchers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for (src, _), result in zip(fetchers, results):
        if isinstance(result, Exception):
            logger.error("Fetcher %r raised: %s", src, result)

    conn.close()

    click.echo(
        f"Fetched {counters['fetched']} listings, "
        f"{counters['new']} new, "
        f"{counters['updated']} updated, "
        f"{counters['fuzzy']} flagged as possible duplicates."
    )
    if counters["skipped"]:
        click.echo(f"Skipped {counters['skipped']} manual-transmission listings.")


@cli.command()
@click.option("--sources", default=None, help="Comma-separated sources to search.")
@click.option("--zip", "zip_code", default=None, help="ZIP code override.")
@click.option("--radius", default=None, type=int, help="Search radius in miles.")
@click.pass_context
def search(
    ctx: click.Context,
    sources: str | None,
    zip_code: str | None,
    radius: int | None,
) -> None:
    """Search configured sources and store listings."""
    from carfinder.config import load_config

    config = load_config()

    # Apply CLI overrides
    if zip_code:
        config = config.model_copy(update={"zip": zip_code})
    if radius is not None:
        config = config.model_copy(update={"radius_miles": radius})

    # Determine enabled sources
    if sources:
        enabled = [s.strip() for s in sources.split(",") if s.strip()]
    else:
        src = config.sources
        enabled = [s for s, on in src.model_dump().items() if on]

    if not enabled:
        click.echo("No sources enabled. Pass --sources or set sources in config.yaml.")
        return

    click.echo(f"Searching sources: {', '.join(enabled)}")
    asyncio.run(_run_search(config, enabled))


@cli.command()
@click.option("--top", default=20, show_default=True, help="Number of listings to show.")
@click.option("--min-score", default=0.0, show_default=True, type=float)
@click.option(
    "--format",
    "fmt",
    default="table",
    show_default=True,
    type=click.Choice(["table", "markdown", "json"]),
)
@click.option(
    "--body-type",
    "body_types",
    default=None,
    help="Filter by body type (comma-separated, e.g. SUV,Wagon). Case-insensitive substring match.",
)
@click.option(
    "--in-budget",
    "in_budget",
    is_flag=True,
    default=False,
    help="Filter out listings outside config.budget.min/max.",
)
def rank(top: int, min_score: float, fmt: str, body_types: str | None, in_budget: bool) -> None:
    """Rank and display stored listings by score."""
    import json as _json

    from carfinder.config import load_config
    from carfinder.render import render_markdown, render_table

    cfg = load_config()
    scored, conn = _load_scored_listings(cfg, in_budget=in_budget)
    conn.close()

    if not scored:
        click.echo("No listings in database. Run `carfinder search` first.")
        return

    # Apply body-type filter
    if body_types:
        bt_filters = [bt.strip().lower() for bt in body_types.split(",")]
        scored = [
            s for s in scored
            if s.listing.body_type and any(f in s.listing.body_type.lower() for f in bt_filters)
        ]

    # Apply min-score filter then top-N
    if min_score > 0:
        scored = [s for s in scored if s.score >= min_score]
    scored = scored[:top]

    if not scored:
        click.echo(f"No listings above min-score {min_score}.")
        return

    if fmt == "table":
        from rich.console import Console
        console = Console()
        console.print(render_table(scored))
    elif fmt == "markdown":
        click.echo(render_markdown(scored, top_n=len(scored)))
    elif fmt == "json":
        click.echo(_json.dumps([s.model_dump() for s in scored], default=str))


@cli.command()
@click.option("--top", default=None, type=int, help="Limit number of listings exported (default: all).")
@click.option("--path", default=None, help="Override export path.")
@click.option(
    "--format",
    "fmt",
    default="markdown",
    show_default=True,
    type=click.Choice(["markdown", "html", "both"]),
    help="Output format: markdown, html, or both.",
)
@click.option(
    "--in-budget",
    "in_budget",
    is_flag=True,
    default=False,
    help="Filter out listings outside config.budget.min/max.",
)
def export(top: int, path: str | None, fmt: str, in_budget: bool) -> None:
    """Export shortlist to Obsidian vault."""
    import os

    from carfinder.config import load_config
    from carfinder.render import export_html_to_vault, export_markdown_to_vault, render_markdown
    from carfinder.render_html import render_html

    cfg = load_config()

    # Allow --path to override vault path via env var mechanism
    if path:
        os.environ["CARFINDER_VAULT_PATH"] = path

    scored, conn = _load_scored_listings(cfg, top_n=top, in_budget=in_budget)
    conn.close()

    if not scored:
        click.echo("No listings in database. Run `carfinder search` first.")
        return

    if fmt in ("markdown", "both"):
        md = render_markdown(scored, top_n=len(scored))
        md_path = export_markdown_to_vault(md, cfg)
        click.echo(f"Markdown exported to {md_path} ({len(scored)} listings)")

    if fmt in ("html", "both"):
        html = render_html(scored, config=cfg)
        html_path = export_html_to_vault(html, cfg)
        click.echo(f"HTML dashboard exported to {html_path} ({len(scored)} listings)")


@cli.command("import")
@click.argument("url_or_file", required=False, metavar="[URL|CSV_FILE]")
@click.option("--template", is_flag=True, help="Print CSV template headers and exit.")
def import_listings(url_or_file: str | None, template: bool) -> None:
    """Manually import listings (Facebook Marketplace, CSV, etc.).

    \b
    Examples:
      carfinder import                          # interactive form
      carfinder import https://fb.com/...       # pre-fill URL, prompt the rest
      carfinder import listings.csv             # batch import from CSV
      carfinder import --template               # print CSV column headers
    """
    from pathlib import Path as _Path

    from carfinder.db import init_db
    from carfinder.importer import CSV_TEMPLATE, import_csv, import_one

    if template:
        click.echo(CSV_TEMPLATE)
        return

    db_path = _Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)

    # Detect if argument is a CSV file
    if url_or_file and url_or_file.endswith(".csv") and _Path(url_or_file).exists():
        saved, skipped = import_csv(_Path(url_or_file), conn)
        click.echo(f"\nImported {saved} listing(s), skipped {skipped}.")
        if saved:
            conn.commit()
            click.echo("Run 'carfinder export --format html --path ./output' to update the dashboard.")
        conn.close()
        return

    # URL or no-arg → interactive
    url = url_or_file if url_or_file and url_or_file.startswith("http") else None
    if url_or_file and not url:
        raise click.UsageError(f"'{url_or_file}' is not a URL or existing CSV file.")

    ok = import_one(url, conn)
    if ok:
        conn.commit()
        click.echo("Run 'carfinder export --format html --path ./output' to update the dashboard.")
    conn.close()


@cli.command()
@click.argument("listing_id")
def show(listing_id: str) -> None:
    """Show details for a single listing."""
    from carfinder.config import load_config
    from carfinder.db import get_listing_by_id, get_listings, init_db
    from carfinder.lookups import load_lookups
    from carfinder.render import render_show
    from carfinder.scorer import score_listing

    cfg = load_config()
    lk = load_lookups(Path("data"))
    db_path = Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)

    listing = get_listing_by_id(conn, listing_id)
    if listing is None:
        conn.close()
        click.echo(f"Listing {listing_id!r} not found in database.")
        return

    # Build cohort of same year/make/model for scoring context
    cohort = get_listings(conn)
    conn.close()

    scored = score_listing(listing, cohort, cfg, lk)

    from rich.console import Console
    Console().print(render_show(scored))


@cli.command()
def stats() -> None:
    """Show database statistics."""
    from carfinder.db import get_listings, init_db
    from carfinder.render import render_stats

    db_path = Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)
    listings = get_listings(conn)

    from rich.console import Console
    Console().print(render_stats(listings, conn))
    conn.close()


@cli.command()
@click.option("--port", default=8765, show_default=True, help="Port to listen on.")
def serve(port: int) -> None:
    """Start a local web server with live import and delete UI.

    Opens the dashboard at http://localhost:PORT with an Import button
    and per-row delete controls. Changes are persisted to the database
    immediately; reload the page to see updated scores.
    """
    import webbrowser

    from carfinder.config import load_config
    from carfinder.server import run_server

    cfg = load_config()
    db_path = Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    server, url = run_server(cfg, db_path, port=port)
    click.echo(f"Serving carfinder dashboard at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")


@cli.command()
@click.option("--days", default=30, show_default=True)
def prune(days: int) -> None:
    """Remove listings older than N days."""
    from carfinder.db import init_db, prune_old

    db_path = Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)
    removed = prune_old(conn, days)
    conn.close()
    click.echo(f"Removed {removed} listings older than {days} days.")


@cli.command()
@click.option("--min-score", default=70, show_default=True, type=float)
def watch(min_score: float) -> None:
    """Show new listings since last run above min-score."""
    import datetime

    from carfinder.config import load_config
    from carfinder.db import get_last_run, init_db, update_last_run

    cfg = load_config()

    db_path = Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)

    # 1. Snapshot previous last_run
    previous = get_last_run(conn)
    conn.close()

    # 2. Run search (fetch + upsert from all enabled sources)
    src = cfg.sources
    enabled = [s for s, on in src.model_dump().items() if on]
    if enabled:
        asyncio.run(_run_search(cfg, enabled))
    else:
        click.echo("No sources enabled — scoring existing DB contents.")

    # 3. Score all listings
    all_scored, conn = _load_scored_listings(cfg)

    if not all_scored:
        conn.close()
        click.echo("No listings in database. Run `carfinder search` first.")
        return

    # 4. Compute delta
    new_listings = []
    changed_listings = []  # (scored, old_score)

    for s in all_scored:
        lid = s.listing.id
        if lid not in previous:
            if s.score >= min_score:
                new_listings.append(s)
        else:
            old_score = previous[lid]
            if abs(s.score - old_score) >= 5 and s.score >= min_score:
                changed_listings.append((s, old_score))

    # 5. Print summary
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    click.echo(f"Watch run at {now_iso}")
    click.echo(f"{len(new_listings)} new listings above threshold {min_score}")
    click.echo(f"{len(changed_listings)} listings with score changes >=5")

    if new_listings or changed_listings:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text

        table = Table(title=f"Watch Delta (min-score={min_score})", show_lines=False)
        table.add_column("Type", width=6)
        table.add_column("#", justify="right", width=4)
        table.add_column("Score", justify="right", width=12)
        table.add_column("Year", justify="center", width=6)
        table.add_column("Make", width=10)
        table.add_column("Model", width=12)
        table.add_column("Trim", width=10)
        table.add_column("Miles", justify="right", width=9)
        table.add_column("Price", justify="right", width=9)
        table.add_column("Source", width=10)
        table.add_column("Location", width=16)

        rank = 0
        for s in new_listings:
            rank += 1
            lst = s.listing
            score_str = s.display_score()
            mileage_str = f"{lst.mileage:,}" if lst.mileage is not None else "—"
            price_str = f"${lst.asking_price:,.0f}" if lst.asking_price is not None else "—"
            table.add_row(
                Text("NEW", style="green bold"),
                str(rank),
                Text(score_str, style="green" if s.score >= 80 else "yellow"),
                str(lst.year or "—"),
                lst.make or "—",
                lst.model or "—",
                lst.trim or "—",
                mileage_str,
                price_str,
                lst.source or "—",
                lst.location or "—",
            )

        for s, old_score in changed_listings:
            rank += 1
            lst = s.listing
            score_str = f"{old_score:.1f} → {s.display_score()}"
            mileage_str = f"{lst.mileage:,}" if lst.mileage is not None else "—"
            price_str = f"${lst.asking_price:,.0f}" if lst.asking_price is not None else "—"
            table.add_row(
                Text("Δ", style="yellow bold"),
                str(rank),
                Text(score_str, style="yellow"),
                str(lst.year or "—"),
                lst.make or "—",
                lst.model or "—",
                lst.trim or "—",
                mileage_str,
                price_str,
                lst.source or "—",
                lst.location or "—",
            )

        Console().print(table)

    # 6. Persist current snapshot
    update_last_run(conn, all_scored)
    conn.close()


@cli.group()
def dev() -> None:
    """Developer utilities."""


@dev.command("refresh-fixtures")
def refresh_fixtures() -> None:
    """Fetch live pages and save as dated test fixtures."""
    import datetime

    from carfinder.config import load_config

    cfg = load_config()
    today = datetime.date.today().isoformat()

    src = cfg.sources
    enabled_sources = [s for s, on in src.model_dump().items() if on]

    if not enabled_sources:
        click.echo("No sources enabled in config.")
        return

    asyncio.run(_refresh_fixtures_async(cfg, enabled_sources, today))


async def _refresh_fixtures_async(cfg, enabled_sources: list[str], today: str) -> None:
    """Fetch raw pages for each enabled source and save as dated fixtures."""
    import httpx

    from carfinder.fetchers.craigslist import (
        _USER_AGENT as CL_UA,
        CraigslistFetcher,
    )
    from carfinder.fetchers.carmax import BROWSER_HEADERS as CM_HEADERS

    fixtures_root = Path("tests/fixtures")
    results: list[str] = []
    warnings: list[str] = []

    for source in enabled_sources:
        out_dir = fixtures_root / source
        out_dir.mkdir(parents=True, exist_ok=True)

        if source == "craigslist":
            fetcher = CraigslistFetcher(cfg)
            search_url = fetcher._build_search_url(cfg, offset=0)
            headers = {"User-Agent": CL_UA}

            # Fetch search page
            try:
                async with httpx.AsyncClient(
                    headers=headers, follow_redirects=True, timeout=30.0
                ) as client:
                    resp = await fetcher._retry_request(client, "GET", search_url)
                    if resp.status_code == 200:
                        search_path = out_dir / f"search_{today}.html"
                        search_path.write_bytes(resp.content)
                        results.append(f"tests/fixtures/craigslist/search_{today}.html ({len(resp.content)} bytes)")

                        # Fetch first detail page
                        from carfinder.fetchers.craigslist import _parse_search_page
                        cards = _parse_search_page(resp.text)
                        if cards:
                            detail_url = cards[0].get("url", "")
                            if detail_url:
                                await fetcher._rate_limit_sleep()
                                dresp = await fetcher._retry_request(client, "GET", detail_url)
                                if dresp.status_code == 200:
                                    detail_path = out_dir / f"detail_{today}.html"
                                    detail_path.write_bytes(dresp.content)
                                    results.append(f"tests/fixtures/craigslist/detail_{today}.html ({len(dresp.content)} bytes)")
                    else:
                        warnings.append(f"craigslist: HTTP {resp.status_code} on search page")
            except Exception as exc:
                warnings.append(f"craigslist: fetch failed — {exc}")

        elif source == "carmax":
            from carfinder.fetchers.carmax import CarMaxFetcher
            fetcher = CarMaxFetcher(cfg)
            params = fetcher._build_params(cfg, distance=cfg.radius_miles)

            try:
                async with httpx.AsyncClient(
                    http2=True,
                    headers=CM_HEADERS,
                    follow_redirects=True,
                    timeout=30.0,
                ) as client:
                    resp = await fetcher._retry_request(
                        client, "GET", fetcher.BASE_URL, params=params
                    )
                    if resp.status_code == 200:
                        search_path = out_dir / f"search_{today}.html"
                        search_path.write_bytes(resp.content)
                        results.append(f"tests/fixtures/carmax/search_{today}.html ({len(resp.content)} bytes)")
                    else:
                        warnings.append(f"carmax: HTTP {resp.status_code} on search page")
            except Exception as exc:
                warnings.append(f"carmax: fetch failed — {exc}")

        elif source == "kbb":
            from carfinder.fetchers.kbb import KBBFetcher, BROWSER_HEADERS
            fetcher = KBBFetcher(cfg)
            params = fetcher._build_params(cfg)

            try:
                async with httpx.AsyncClient(
                    http2=True,
                    headers=BROWSER_HEADERS,
                    follow_redirects=True,
                    timeout=30.0,
                ) as client:
                    resp = await fetcher._retry_request(
                        client, "GET", fetcher.SEARCH_URL, params=params
                    )
                    if resp.status_code == 200:
                        search_path = out_dir / f"search_{today}.html"
                        search_path.write_bytes(resp.content)
                        results.append(f"tests/fixtures/kbb/search_{today}.html ({len(resp.content)} bytes)")
                    else:
                        warnings.append(f"kbb: HTTP {resp.status_code} on search page")
            except Exception as exc:
                warnings.append(f"kbb: fetch failed — {exc}")

        else:
            warnings.append(f"refresh-fixtures: no raw-fetch implementation for source {source!r}")

    if results:
        click.echo("Refreshed fixtures:")
        for r in results:
            click.echo(f"  {r}")
    else:
        click.echo("No fixtures written.")

    for w in warnings:
        click.echo(f"WARNING: {w}")


@cli.command("kbb-values")
@click.option("--limit", default=None, type=int, help="Cap how many vehicles to fetch this run.")
@click.option("--refresh", is_flag=True, help="Re-fetch even vehicles already cached.")
def kbb_values(limit: int | None, refresh: bool) -> None:
    """Populate data/kbb_values.json with KBB Fair Market Prices.

    Scrapes the KBB value page once per unique (make, model, year) in the
    database and caches the result so the scorer can use a real valuation as
    its price reference. Re-run periodically to refresh.
    """
    import json as _json
    import random

    import httpx

    from carfinder.config import load_config
    from carfinder.db import get_listings, init_db
    from carfinder.fetchers.kbb_value import BROWSER_HEADERS, cache_key, fetch_fair_values

    cfg = load_config()
    cache_path = Path("data/kbb_values.json")
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = _json.loads(cache_path.read_text())
        except _json.JSONDecodeError:
            click.echo(f"WARNING: {cache_path} is corrupt — starting fresh.")

    db_path = Path("data/listings.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)
    listings = get_listings(conn)
    conn.close()

    unique: dict[str, tuple[str, str, int]] = {}
    for lst in listings:
        if lst.make and lst.model and lst.year:
            unique.setdefault(cache_key(lst.make, lst.model, lst.year), (lst.make, lst.model, lst.year))

    todo = [(k, v) for k, v in unique.items() if refresh or k not in cache]
    if limit is not None:
        todo = todo[:limit]
    click.echo(f"{len(unique)} unique vehicles · {len(cache)} cached · {len(todo)} to fetch")
    if not todo:
        return

    async def _run() -> None:
        async with httpx.AsyncClient(
            http2=True, headers=BROWSER_HEADERS, follow_redirects=True, timeout=30.0
        ) as client:
            for i, (key, (mk, mo, yr)) in enumerate(todo, 1):
                vals = await fetch_fair_values(client, mk, mo, yr)
                if vals:
                    cache[key] = vals
                    click.echo(f"  [{i}/{len(todo)}] {yr} {mk} {mo}: ${vals['default']:,} ({len(vals['trims'])} trims)")
                else:
                    # Negative cache so re-runs skip models KBB can't resolve
                    # (e.g. Craigslist free-text model strings). Use --refresh to retry.
                    cache[key] = {"default": None, "miss": True}
                    click.echo(f"  [{i}/{len(todo)}] {yr} {mk} {mo}: no value found")
                # Flush periodically so progress survives a crash and the
                # dashboard can pick up new values mid-run.
                if i % 10 == 0:
                    cache_path.write_text(_json.dumps(cache, indent=2, sort_keys=True))
                await asyncio.sleep(random.uniform(cfg.rate_limit.min_delay_seconds, cfg.rate_limit.max_delay_seconds))

    try:
        asyncio.run(_run())
    finally:
        cache_path.write_text(_json.dumps(cache, indent=2, sort_keys=True))
        click.echo(f"Wrote {len(cache)} entries to {cache_path}")
