"""Lookup table loader — loads data/*.yaml and data/mpg_lookup.csv into O(1) dicts."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _norm(s: str | None) -> str:
    """Normalize a make string: strip whitespace, remove internal spaces, lowercase."""
    return (s or "").strip().replace(" ", "").lower()


@dataclass
class Lookups:
    reliability: dict[str, float] = field(default_factory=dict)
    # (make, model, year) -> length_inches
    dimensions: dict[tuple[str, str, int], float] = field(default_factory=dict)
    # (make, model, year) -> tier "low"|"medium"|"high"
    insurance: dict[tuple[str, str, int], str] = field(default_factory=dict)
    # (make, model) -> "oem_rails"|"aftermarket"|"none"
    roof_rack: dict[tuple[str, str], str] = field(default_factory=dict)
    # (year, make, model) -> mpg_combined
    mpg: dict[tuple[int, str, str], int] = field(default_factory=dict)
    # (make, model) -> approximate base MSRP (USD)
    msrp: dict[tuple[str, str], int] = field(default_factory=dict)


def load_lookups(data_dir: Path = Path("data")) -> Lookups:
    """Load all lookup tables from data_dir. Returns a Lookups instance."""
    lk = Lookups()

    # --- reliability_tiers.yaml: make -> score ---
    rel_path = data_dir / "reliability_tiers.yaml"
    if rel_path.exists():
        raw = yaml.safe_load(rel_path.read_text()) or {}
        lk.reliability = {_norm(k): float(v) for k, v in raw.items()}

    # --- vehicle_dimensions.yaml: expand year ranges -> (make, model, year) ---
    dim_path = data_dir / "vehicle_dimensions.yaml"
    if dim_path.exists():
        entries = yaml.safe_load(dim_path.read_text()) or []
        for entry in entries:
            make = _norm(entry["make"])
            model = entry["model"]
            year_min = int(entry["year_min"])
            year_max = int(entry["year_max"])
            length = float(entry["length_inches"])
            for year in range(year_min, year_max + 1):
                lk.dimensions[(make, model, year)] = length

    # --- insurance_risk.yaml: expand year ranges -> (make, model, year) ---
    ins_path = data_dir / "insurance_risk.yaml"
    if ins_path.exists():
        entries = yaml.safe_load(ins_path.read_text()) or []
        for entry in entries:
            make = _norm(entry["make"])
            model = entry["model"]
            year_min = int(entry["year_min"])
            year_max = int(entry["year_max"])
            tier = entry["tier"]
            for year in range(year_min, year_max + 1):
                lk.insurance[(make, model, year)] = tier

    # --- roof_rack.yaml: (make, model) -> status ---
    rack_path = data_dir / "roof_rack.yaml"
    if rack_path.exists():
        entries = yaml.safe_load(rack_path.read_text()) or []
        for entry in entries:
            lk.roof_rack[(_norm(entry["make"]), entry["model"])] = entry["status"]

    # --- mpg_lookup.csv: (year, make, model) -> mpg_combined ---
    mpg_path = data_dir / "mpg_lookup.csv"
    if mpg_path.exists():
        with open(mpg_path, newline="") as f:
            reader = csv.DictReader(row for row in f if not row.startswith("#"))
            for row in reader:
                try:
                    year = int(row["year"])
                    make = row["make"].strip()
                    model = row["model"].strip()
                    mpg = round(float(row["mpg_combined"]))
                    # Keep first entry per (year, make, model) — CSV is pre-deduped
                    key = (year, make, model)
                    if key not in lk.mpg:
                        lk.mpg[key] = mpg
                except (ValueError, KeyError):
                    continue

    # --- msrp_by_make_model.yaml: (make, model) -> msrp ---
    msrp_path = data_dir / "msrp_by_make_model.yaml"
    if msrp_path.exists():
        entries = yaml.safe_load(msrp_path.read_text()) or []
        for entry in entries:
            lk.msrp[(entry["make"], entry["model"])] = int(entry["msrp"])

    return lk
