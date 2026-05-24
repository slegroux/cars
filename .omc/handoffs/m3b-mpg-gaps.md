# M3b MPG Gap Log

The MPG CSV uses EPA-style suffixed model names (e.g. "RAV4 2WD", "CR-V 4WD", "CX-5 4WD") while
our YAML files use plain model names ("RAV4", "CR-V", "CX-5"). The scorer's `lookups.mpg` key is
`(year, make, model)` so these never match — the scorer falls back to `estimated` for mpg on all
gap years unless the listing has `mpg_combined` set directly.

## Gap summary (227 total year/make/model combos)

| Make/Model | Gap years | Notes |
|---|---|---|
| Toyota RAV4 | 2006-2024 (10 yrs in range) | CSV has "RAV4 2WD" / "RAV4 4WD" |
| Toyota Camry | 2007-2010, 2018-2024 | CSV has "Camry" but only 2011+ matched |
| Toyota Corolla | 2023-2024 | Out of CSV range (stops 2022) |
| Toyota Matrix | 2014 | Last year; CSV may stop 2013 |
| Honda CR-V | 2007-2022 (16 yrs) | CSV has "CR-V 2WD" / "CR-V 4WD" |
| Honda Civic | 2006-2021 (9 yrs) | CSV has "Civic" but year range differs |
| Honda Accord | 2008 | CSV gap for first year |
| Honda Fit | 2014 | Single year gap |
| Mazda CX-5 | 2013-2024 (12 yrs) | CSV has "CX-5 2WD" / "CX-5 4WD" |
| Mazda Mazda3 | 2010-2024 (15 yrs) | Plain name not in CSV |
| Mazda Mazda6 | 2009-2021 (13 yrs) | Plain name not in CSV |
| Subaru Forester | 2009-2024 (16 yrs) | CSV has "Forester AWD" |
| Subaru Outback | 2010-2024 (15 yrs) | CSV has "Outback Wagon AWD" |
| Subaru Impreza | 2012-2024 (13 yrs) | CSV has "Impreza AWD" |
| Hyundai Tucson | 2010-2024 (15 yrs) | CSV has "Tucson 2WD" / "Tucson 4WD" |
| Hyundai Sonata | 2023-2024 | Out of CSV range |
| Hyundai Elantra | 2023-2024 | Out of CSV range |
| Kia Sportage | 2011-2022 (11 yrs) | CSV has "Sportage 2WD" / "Sportage 4WD" |
| Kia Soul | 2023-2024 | Out of CSV range |
| Kia Forte | 2023-2024 | Out of CSV range |
| Nissan Rogue | 2008-2024 (17 yrs) | CSV has "Rogue AWD" / "Rogue FWD" |
| Nissan Sentra | 2023-2024 | Out of CSV range |
| Nissan Altima | 2023-2024 | Out of CSV range |
| BMW 3-Series | 2007-2024 (18 yrs) | CSV has "328i", "335i" etc — not "3-Series" |
| Audi A4 | 2018-2024 (5 yrs) | CSV stops 2017 for plain "A4" |
| Lexus IS | 2006-2024 (19 yrs) | CSV has "IS 250", "IS 300" — not plain "IS" |
| Volkswagen Jetta | 2023-2024 | Out of CSV range |

## Impact
Scorer uses `estimated` confidence for mpg factor on these. Since the RAV4 fixture sets
`mpg_combined: 24` directly on the listing, mpg is "real" for that fixture.
The scorer's default for unknown mpg is 5.0 / estimated — no crash, graceful degradation.

## Recommended fix (M4+)
Add a model name normalization step in `load_lookups()` that maps plain model names to
their CSV equivalents, or add deduplicated plain-name rows to mpg_lookup.csv.
