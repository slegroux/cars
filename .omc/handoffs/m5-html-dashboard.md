# M5 HTML Dashboard — Handoff

## Files added / modified

- `src/carfinder/render_html.py` — new. `render_html(scored, config) -> str`. Pure function, no deps beyond stdlib (`json`, `html`, `datetime`, `statistics`, `subprocess`). Inlines CSS + vanilla JS. Chart.js loaded from CDN only.
- `src/carfinder/render.py` — added `export_markdown_to_vault`, `export_html_to_vault`; `export_to_vault` delegates to `export_markdown_to_vault` (no signature change).
- `src/carfinder/cli.py` — `export` command gains `--format markdown|html|both` (default `markdown`).
- `tests/test_render_html.py` — 9 new tests (all pass).

## Test count

120 total (111 pre-existing + 9 new). 0 failures.

## Smoke result

```
CARFINDER_VAULT_PATH=/tmp/carfinder-html uv run carfinder export --format html --top 30
# → /tmp/carfinder-html/shortlist-2026-05-23.html  (89 KB, 30 listings)
--format both → also writes shortlist-2026-05-23.md
```

Dashboard opened in browser. Chart.js renders on CDN load.
