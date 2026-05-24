"""Download fueleconomy.gov vehicles.csv.zip and build data/mpg_lookup.csv.

Usage: uv run python scripts/build_mpg_lookup.py
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from datetime import date
from pathlib import Path
from statistics import median
from urllib.request import urlopen

URL = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv.zip"
YEAR_MIN = 2009
YEAR_MAX = 2022
OUT_PATH = Path(__file__).parent.parent / "data" / "mpg_lookup.csv"


def main() -> None:
    print(f"Downloading {URL} ...", flush=True)
    with urlopen(URL, timeout=120) as resp:
        raw = resp.read()
    print(f"Downloaded {len(raw) // 1024} KB", flush=True)

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        csv_name = next(n for n in names if n.endswith(".csv"))
        print(f"Reading {csv_name} from zip ...", flush=True)
        with zf.open(csv_name) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"))
            rows = list(reader)

    print(f"Total rows: {len(rows)}", flush=True)

    # Filter to year range and required fields
    filtered: list[dict] = []
    for row in rows:
        try:
            yr = int(row.get("year", 0))
        except ValueError:
            continue
        if not (YEAR_MIN <= yr <= YEAR_MAX):
            continue
        try:
            mpg = float(row.get("comb08", 0))
        except ValueError:
            continue
        if mpg <= 0:
            continue
        filtered.append({
            "year": yr,
            "make": (row.get("make") or "").strip(),
            "model": (row.get("model") or "").strip(),
            "mpg": mpg,
            "trany": (row.get("trany") or "").strip(),
            "VClass": (row.get("VClass") or "").strip(),
        })

    print(f"Filtered rows ({YEAR_MIN}-{YEAR_MAX}): {len(filtered)}", flush=True)

    # Group by (year, make, model)
    groups: dict[tuple, list[dict]] = {}
    for r in filtered:
        key = (r["year"], r["make"], r["model"])
        groups.setdefault(key, []).append(r)

    # Dedupe: per group, pick most common transmission, then median mpg
    output_rows: list[dict] = []
    for (yr, make, model), grp in groups.items():
        # Most common transmission
        trany_counts: dict[str, int] = {}
        for r in grp:
            trany_counts[r["trany"]] = trany_counts.get(r["trany"], 0) + 1
        best_trany = max(trany_counts, key=lambda t: trany_counts[t])

        # Median mpg across all rows (not just best trany)
        mpg_med = median(r["mpg"] for r in grp)

        # Body type from most common VClass
        vclass_counts: dict[str, int] = {}
        for r in grp:
            vclass_counts[r["VClass"]] = vclass_counts.get(r["VClass"], 0) + 1
        body_type = max(vclass_counts, key=lambda v: vclass_counts[v])

        output_rows.append({
            "year": yr,
            "make": make,
            "model": model,
            "mpg_combined": round(mpg_med, 1),
            "body_type": body_type,
        })

    output_rows.sort(key=lambda r: (r["year"], r["make"], r["model"]))
    print(f"Deduplicated rows: {len(output_rows)}", flush=True)

    if len(output_rows) < 200:
        print(f"ERROR: only {len(output_rows)} rows, expected >200", file=sys.stderr)
        sys.exit(1)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    with open(OUT_PATH, "w", newline="") as f:
        f.write(f"# fueleconomy.gov vehicles dataset, downloaded {today}, filtered years {YEAR_MIN}-{YEAR_MAX}\n")
        writer = csv.DictWriter(f, fieldnames=["year", "make", "model", "mpg_combined", "body_type"])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {len(output_rows)} rows to {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
