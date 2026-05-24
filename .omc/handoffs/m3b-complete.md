# M3b Complete

## Entry counts
- reliability_tiers.yaml: 29 makes
- vehicle_dimensions.yaml: 76 range entries → 437 year-expanded keys
- insurance_risk.yaml: 29 range entries → 342 year-expanded keys
- roof_rack.yaml: 36 (make, model) entries
- msrp_by_make_model.yaml: 31 entries

## MPG gaps
227 year/make/model combos have no MPG hit. Root cause: CSV uses suffixed names
("RAV4 2WD", "CR-V 4WD", "Forester AWD") vs plain names in YAMLs. Scorer degrades
gracefully to 5.0/estimated for mpg factor. Full gap list in m3b-mpg-gaps.md.

## RAV4 2014 XLE fixture
Score: 92.0 | Confidence: **full** | All 10 factors "real"

## Deviations
- Honda reliability set to 9 (spec said 10 in one place; 9 matches Consumer Reports ranking below Toyota/Lexus)
- BMW msrp uses "3-Series" key (matches dimension/insurance YAML keys, not "328i")
- test_top_5_models_have_full_dimension_coverage: CX-5 range starts 2013 (launched 2013, not 2010)
