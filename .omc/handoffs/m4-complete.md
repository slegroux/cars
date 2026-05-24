# M4 Complete

## Files added/modified
- `src/carfinder/render.py` — new: render_table, render_markdown, render_show, render_stats, export_to_vault
- `src/carfinder/cli.py` — replaced rank stub + wired export, show, stats, prune; added _load_scored_listings helper
- `src/carfinder/db.py` — added get_listing_by_id (4-line helper)
- `tests/test_render.py` — new: 12 tests

## Test count
100 total (83 pre-existing + 12 render + 5 from other M4 additions passing). All pass.

## End-to-end smoke
- `carfinder rank --top 10` → table (10 rows, exits 0)
- `carfinder rank --top 10 --format markdown` → YAML frontmatter + table + per-vehicle sections
- `carfinder rank --top 10 --format json` → valid JSON array
- `CARFINDER_VAULT_PATH=/tmp/carfinder-test carfinder export --top 10` → exported to `/tmp/carfinder-test/shortlist-2026-05-23.md` (10 listings)
- File has YAML frontmatter, 10 photo embeds (`grep -c '^!\[' = 10`)
- `carfinder stats` → summary + histogram (exits 0)
- `carfinder prune --days 30` → "Removed 0 listings…" (exits 0)
- `carfinder show <id>` → rich Panel with score breakdown (exits 0)

## Deviations
None. All deliverables implemented as specified.
