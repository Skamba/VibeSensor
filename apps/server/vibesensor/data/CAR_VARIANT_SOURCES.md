# Car Variant Data Sources

This file documents the sources used to populate variant data in
`car_library.json`. Each entry maps a car model to the documented variant
summary and the confidence level of the data.

Row-level verification state now lives in
`car_library_ratio_sources.json`, where every model row must be classified
as `verification_backlog`, `verified`, `corrected`, or
`intentionally_unsupported`.

## Source Priority (per project rules)

1. **Official** – Manufacturer documentation, press releases, brochures
2. **Reputable** – Trusted automotive spec databases (e.g. auto-data.net,
   cars-data.com, carfolio.com)
3. **Community** – Enthusiast forums, wikis (lower confidence)

## General Notes

- Engine family/code names and cylinder configurations are well-documented
  across official BMW and Audi press materials.
- Drivetrain layout (FWD/RWD/AWD) is a fundamental spec published by
  every manufacturer.
- Authoritative ratio verification status is tracked per row in
  `car_library_ratio_sources.json`.
- `verification_backlog` means authoritative verification work is still
  open for the row; entries in that state must keep explicit `unresolved`
  items and are not treated as closed verification debt.
- Terminal states (`verified`, `corrected`, `intentionally_unsupported`)
  must not keep `unresolved` items. Any closed product/schema constraints
  belong under row-level `known_limits` instead.
- Variant-specific gearbox overrides use manufacturer technical data where
  available. If a row cannot be safely verified at the represented
  granularity, that limitation is recorded in the ratio-source ledger
  instead of relying on broad fallback notes here.
- Tire specifications are shared across variants within a model generation
  and are not overridden at variant level (same factory options).

---

## BMW

### 1 Series (F20, 2011-2019)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 118i | B38 1.5L I3 Turbo | RWD | BMW press release | High |
| 120i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 114i | 1.6L | RWD | BMW press release | High |

### 1 Series (F40, 2019-2025)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 118i | B38 1.5L I3 Turbo | FWD | BMW press release | High |
| 120i | B48 2.0L I4 Turbo | FWD | BMW press release | High |
| M135i xDrive | B48 2.0L I4 Turbo | AWD | BMW press release | High |

### 2 Series Coupe (F22, 2014-2021)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 220i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 230i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| M2 | B58B30O0 3.0L I6 Turbo | RWD | BMW press release | High |

### 2 Series Coupe (G42, 2022-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 220i | B48 2.0L I4 Turbo | RWD | 8-speed Steptronic transmission FD 2.813 TG 0.640 | BMW PressClub technical data / DE price lists | High |
| 230i | B48 2.0L I4 Turbo | RWD | – | BMW press release | High |
| 230i xDrive | B48 2.0L I4 Turbo | AWD | – | BMW press release | High |

### 2 Series Active Tourer (F45, 2014-2021)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 218i | B38 1.5L I3 Turbo | FWD | BMW press release | High |
| 220i | B48 2.0L I4 Turbo | FWD | BMW press release | High |
| 225xe | B38 1.5L I3 Turbo PHEV | AWD | BMW press release | High |

### 3 Series (F30, 2012-2019)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 320i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 330i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 330i xDrive | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| 340i | B58 3.0L I6 Turbo | RWD | BMW press release | High |

### 3 Series (G20, 2019-2025)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 320i | B48 2.0L I4 Turbo | RWD | – | BMW press release / technical data | High |
| 330i | B48 2.0L I4 Turbo | RWD | – | BMW press release / technical data | High |
| 330i xDrive | B48 2.0L I4 Turbo | AWD | 8-speed automatic (ZF 8HP) FD 2.813 TG 0.640 | BMW PressClub technical data (03/2021, 07/2022) | High |
| 320e | 1.6L I4 Turbo | RWD | – | BMW press release / technical data | High |
| 330e | 2.0L I4 Turbo | RWD | – | BMW press release / technical data | High |

### 4 Series (F32, 2014-2020)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 420i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 430i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 440i | B58 3.0L I6 Turbo | RWD | BMW press release | High |

### 4 Series (G22, 2021-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 420i | B48 2.0L I4 Turbo | RWD | BMW DE technical data | High |
| 430i xDrive | B48 2.0L I4 Turbo | AWD | BMW DE technical data | High |
| M440i xDrive | B58 3.0L I6 Turbo | AWD | BMW DE technical data | High |

### 5 Series (F10, 2011-2017)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 520i | N20 2.0L I4 Turbo | RWD | BMW press release | High |
| 530i | N20 2.0L I4 Turbo | RWD | BMW press release | High |
| 535i | N55 3.0L I6 Turbo | RWD | BMW press release | High |
| 550i | N63 4.4L V8 Turbo | RWD | BMW press release | High |

### 5 Series (G30, 2017-2023)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 520i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 530i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 530i xDrive | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| 540i | B58 3.0L I6 Turbo | RWD | BMW press release | High |
| 540i xDrive | B58 3.0L I6 Turbo | AWD | BMW press release | High |
| 545e xDrive | 3.0L I6 Turbo | AWD | BMW press release | High |

### 5 Series (G60, 2024-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 520i | B48 2.0L I4 Turbo | RWD | BMW press release / technical data | High |
| i5 eDrive40 | Electric Single Motor | RWD | BMW technical data | High |
| i5 M60 xDrive | Electric Dual Motor | AWD | BMW technical data / BMW M model page | High |

### 6 Series Gran Coupe (F06, 2013-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 640i | N55 3.0L I6 Turbo | RWD | BMW press release | High |
| 640i xDrive | N55 3.0L I6 Turbo | AWD | BMW press release | High |
| 650i | N63 4.4L V8 Turbo | RWD | BMW press release | High |

### 6 Series Gran Turismo (G32, 2018-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 630i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 640i xDrive | B58 3.0L I6 Turbo | AWD | BMW press release | High |

### 7 Series (F01, 2011-2015)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 740i | N55 3.0L I6 Turbo | RWD | BMW press release | High |
| 750i | N63 4.4L V8 Turbo | RWD | BMW press release | High |
| 750i xDrive | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### 7 Series (G11, 2016-2022)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 740i | B58 3.0L I6 Turbo | RWD | BMW press release | High |
| 750i xDrive | N63 4.4L V8 Turbo | AWD | BMW press release | High |
| 745e | B58 3.0L I6 Turbo PHEV | RWD | BMW press release | High |

### 7 Series (G70, 2023-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 740d xDrive | B57 3.0L I6 Diesel | AWD | BMW press release | High |
| 750e xDrive | B58 3.0L I6 Turbo PHEV | AWD | BMW press release | High |
| M760e xDrive | B58 3.0L I6 Turbo PHEV | AWD | BMW press release / BMW M press material | High |
| i7 eDrive50 | Electric Single Motor | RWD | BMW technical data | High |
| i7 M70 xDrive | Electric Dual Motor | AWD | BMW technical data / BMW M model page | High |

### 8 Series Coupe (G15, 2019-2025)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 840i | B58 3.0L I6 Turbo | RWD | BMW press release | High |
| M850i xDrive | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### 8 Series Convertible (G14, 2019-2025)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 840i | B58 3.0L I6 Turbo | RWD | BMW press release | High |
| M850i xDrive | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### 8 Series Gran Coupe (G16, 2020-2025)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 840i | B58 3.0L I6 Turbo | RWD | BMW press release | High |
| M850i xDrive | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### X1 (F48, 2016-2022)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| sDrive18i | B38 1.5L I3 Turbo | FWD | BMW press release | High |
| xDrive20i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive25i | B48 2.0L I4 Turbo | AWD | BMW press release | High |

### X1 (U11, 2023-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| sDrive18i | B38 1.5L I3 Turbo | FWD | BMW press release | High |
| xDrive23i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| iX1 xDrive30 | Electric Dual Motor | AWD | BMW PressClub / model overview | High |

### X2 (F39, 2018-2023)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| sDrive18i | B38 1.5L I3 Turbo | FWD | BMW press release | High |
| xDrive20i | B48 2.0L I4 Turbo | AWD | BMW press release | High |

### X2 (U10, 2024-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| sDrive20i | B48 2.0L I4 Turbo | FWD | BMW press release | High |
| xDrive25e | B48 2.0L I4 Turbo PHEV | AWD | BMW press release | High |
| iX2 xDrive30 | Electric Dual Motor | AWD | BMW technical data / model overview | High |

### X3 (F25, 2011-2017)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive20i | N20 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive28i | N20 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive35i | N55 3.0L I6 Turbo | AWD | BMW press release | High |

### X3 (G01, 2018-2024)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| sDrive20i | B48 2.0L I4 Turbo | RWD | – | BMW press release | High |
| xDrive20i | B48 2.0L I4 Turbo | AWD | – | BMW press release | High |
| xDrive30i | B48 2.0L I4 Turbo | AWD | 8-speed Steptronic FD 3.385 TG 0.640 | BMW PressClub technical data / DE price list | High |
| M40i | B58 3.0L I6 Turbo | AWD | – | BMW press release | High |

### X3 (G45, 2025-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive20 | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive30 | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| M50 xDrive | S58 3.0L I6 Turbo | AWD | BMW press release | High |

### X4 (F26, 2015-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive20i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive28i | N20 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive35i | N55 3.0L I6 Turbo | AWD | BMW press release | High |

### X4 (G02, 2019-2025)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive20i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive30i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| M40i | B58 3.0L I6 Turbo | AWD | BMW press release | High |

### X5 (F15, 2014-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive35i | N55 3.0L I6 Turbo | AWD | BMW press release | High |
| xDrive50i | N63 4.4L V8 Turbo | AWD | BMW press release | High |
| xDrive40e | N20 2.0L I4 Turbo PHEV | AWD | BMW press release | High |

### X5 (G05, 2019-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| xDrive40i | B58 3.0L I6 Turbo | AWD | 8-speed Steptronic FD 3.636 TG 0.640 | BMW PressClub technical data | High |
| xDrive45e | B58 3.0L I6 Turbo PHEV | AWD | 8-speed Steptronic FD 3.636 | BMW DE technical data | High |
| M50i | N63 4.4L V8 Turbo | AWD | – | BMW press release | High |

### X6 (F16, 2015-2019)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive35i | N55 3.0L I6 Turbo | AWD | BMW press release | High |
| xDrive50i | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### X6 (G06, 2020-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive40i | B58 3.0L I6 Turbo | AWD | BMW press release | High |
| M50i | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### X7 (G07, 2019-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| xDrive40i | B58 3.0L I6 Turbo | AWD | – | BMW press release | High |
| xDrive40d | B57 3.0L I6 Diesel | AWD | – | BMW press release | High |
| M60i xDrive | S68 4.4L V8 Turbo | AWD | 8-speed Steptronic FD 3.385 TG 0.640 | BMW PressClub technical data | High |

### Z4 (G29, 2019-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| sDrive20i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| sDrive30i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| M40i | B58 3.0L I6 Turbo | RWD | BMW press release | High |

### M3 (F80, 2014-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| M3 | S55 3.0L I6 Turbo | RWD | BMW press release | High |
| M3 Competition | S55 3.0L I6 Turbo | RWD | BMW press release | High |

### M3 (G80, 2021-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| M3 | S58 3.0L I6 Turbo | RWD | 6-speed manual FD 3.846, 8-speed automatic (ZF 8HP) FD 3.154 | BMW press release / technical data | Medium |
| M3 Competition | S58 3.0L I6 Turbo | RWD | 8-speed automatic (ZF 8HP) FD 3.154 | BMW press release / technical data | Medium |
| M3 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8-speed M Steptronic FD 3.154 TG 0.640 | BMW PressClub technical data | High |

### M4 (F82, 2014-2020)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| M4 | S55 3.0L I6 Turbo | RWD | BMW press release | High |
| M4 Competition | S55 3.0L I6 Turbo | RWD | BMW press release | High |

### M4 (G82, 2021-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| M4 | S58 3.0L I6 Turbo | RWD | 6-speed manual FD 3.846, 8-speed automatic (ZF 8HP) FD 3.154 | BMW press release / technical data | Medium |
| M4 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8-speed M Steptronic FD 3.154 TG 0.640 | BMW PressClub technical data | High |

### M5 (F90, 2018-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| M5 | S63 4.4L V8 Turbo | AWD | BMW press release | High |
| M5 Competition | S63 4.4L V8 Turbo | AWD | BMW press release | High |

### iX (I20, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive40 | Electric Dual Motor | AWD | BMW technical data | High |
| xDrive50 | Electric Dual Motor | AWD | BMW technical data | High |
| M60 | Electric Dual Motor (Performance) | AWD | BMW technical data | High |

### i4 (G26, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| eDrive40 | Electric Single Motor | RWD | BMW technical data | High |
| M50 | Electric Dual Motor | AWD | BMW technical data | High |

## Audi

### A1 (8X, 2011-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 1.0 TFSI | 1.0L I3 TFSI Turbo | FWD | Audi press release | High |
| 1.4 TFSI | 1.4L I4 TFSI Turbo | FWD | Audi press release | High |

### A1 (GB, 2019-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 25 TFSI | 1.0L I3 TFSI Turbo | FWD | Audi press release | High |
| 30 TFSI | 1.0L I3 TFSI Turbo | FWD | Audi press release | High |
| 35 TFSI | 1.5L I4 TFSI Turbo | FWD | Audi press release | High |

### A3 (8V, 2013-2020)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 30 TFSI | 1.0L I3 TFSI Turbo | FWD | Audi press release | High |
| 35 TFSI | 1.5L I4 TFSI Turbo | FWD | Audi press release | High |
| 40 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 1.6 TDI | 1.6L I4 TDI Diesel | FWD | Audi owner manual / brochure archive | Medium |
| 2.0 TDI | 2.0L I4 TDI Diesel | FWD | Audi owner manual / brochure archive / ETKA Europe | Medium |
| 2.0 TDI quattro | 2.0L I4 TDI Diesel | AWD | Audi owner manual / brochure archive / ETKA Europe | Medium |

### A3 (8Y, 2021-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 30 TFSI | 1.0L I3 TFSI Turbo | FWD | Audi press release | High |
| 35 TFSI | 1.5L I4 TFSI Turbo | FWD | Audi press release | High |
| 40 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 30 TDI | 2.0L I4 TDI Diesel | FWD | Audi owner manual / ETKA Europe | Medium |
| 35 TDI | 2.0L I4 TDI Diesel | FWD | Audi owner manual / ETKA Europe | Medium |

### A4 (B8, 2008-2016)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 1.8 TFSI | 1.8L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 3.0 TFSI quattro | 3.0L V6 Supercharged | AWD | Audi press release | High |
| 2.0 TDI | 2.0L I4 TDI Diesel | FWD | Audi owner manual / brochure archive / ETKA Europe | Medium |
| 2.0 TDI quattro | 2.0L I4 TDI Diesel | AWD | Audi owner manual / brochure archive / ETKA Europe | Medium |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi owner manual / brochure archive / ETKA Europe | Medium |

### A4 (B9, 2016-2025)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 35 TFSI | 2.0L I4 TFSI Turbo | FWD | 7-speed S tronic FD 4.234 | Audi MediaCenter eTD technical data | High |
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | 7-speed S tronic FD 4.234 | Audi MediaCenter eTD / Audi UK technical data | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | 7-speed S tronic FD 4.410 | Audi MediaCenter eTD technical data | High |
| 30 TDI | 2.0L I4 TDI Diesel | FWD | – | Audi owner manual / ETKA Europe | Medium |
| 35 TDI | 2.0L I4 TDI Diesel | FWD | – | Audi owner manual / ETKA Europe | Medium |

### A5 (B8, 2007-2016)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi press release | High |

### A5 (B9, 2017-2024)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | 7-speed S tronic FD 4.234 | Audi UK technical data / MediaCenter eTD | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | 7-speed S tronic FD 4.410 | Audi MediaCenter eTD technical data | High |

### A6 (C7, 2011-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 3.0 TFSI quattro | 3.0L V6 Supercharged | AWD | Audi press release | High |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi press release | High |

### A6 (C8, 2019-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 55 TFSI quattro | 3.0L V6 TFSI Turbo | AWD | Audi press release | High |

### A7 Sportback (C7, 2011-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 3.0 TFSI quattro | 3.0L V6 Supercharged | AWD | Audi press release | High |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi press release | High |

### A7 Sportback (C8, 2019-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 55 TFSI quattro | 3.0L V6 TFSI Turbo | AWD | Audi press release | High |

### A8 (D4, 2011-2017)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 3.0 TFSI quattro | 3.0L V6 Supercharged | AWD | Audi press release | High |
| 4.0 TFSI quattro | 4.0L V8 Turbo | AWD | Audi press release | High |

### A8 (D5, 2018-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 50 TFSI quattro | 3.0L V6 TFSI Turbo | AWD | Audi press release | High |
| 55 TFSI quattro | 3.0L V6 TFSI Turbo | AWD | Audi press release | High |
| 60 TFSI e quattro | 3.0L V6 TFSI Turbo PHEV | AWD | Audi press release | High |

### Q2 (GA, 2017-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 30 TFSI | 1.0L I3 TFSI Turbo | FWD | Audi press release | High |
| 35 TFSI | 1.5L I4 TFSI Turbo | FWD | Audi press release | High |

### Q3 (8U, 2012-2018)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 1.4 TFSI | 1.4L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 2.0 TDI | 2.0L I4 TDI Diesel | FWD | Audi owner manual / brochure archive / ETKA Europe | Medium |
| 2.0 TDI quattro | 2.0L I4 TDI Diesel | AWD | Audi owner manual / brochure archive / ETKA Europe | Medium |

### Q3 (F3, 2019-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 35 TFSI | 1.5L I4 TFSI Turbo | FWD | Audi press release | High |
| 40 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 45 TFSI e | 1.4L I4 TFSI Turbo PHEV | FWD | Audi press release | High |
| 35 TDI | 2.0L I4 TDI Diesel | FWD | Audi owner manual / ETKA Europe | Medium |
| 40 TDI quattro | 2.0L I4 TDI Diesel | AWD | Audi owner manual / ETKA Europe | Medium |

### Q5 (8R, 2011-2017)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi press release | High |

### Q5 (FY, 2017-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | 7-speed S tronic FD 5.302 | Audi MediaCenter eTD technical data | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | 7-speed S tronic FD 5.302 TG 0.433 | Audi MediaCenter eTD technical data (2019, 2024) | High |
| 55 TFSI e quattro | 2.0L I4 TFSI Turbo PHEV | AWD | 7-speed S tronic FD 5.302 | Audi MediaCenter / technical data PDF | High |
| 35 TDI quattro | 2.0L I4 TDI Diesel | AWD | – | Audi owner manual / technical data | Medium |
| 40 TDI quattro | 2.0L I4 TDI Diesel | AWD | – | Audi owner manual / technical data | Medium |

### Q7 (4M, 2016-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 55 TFSI quattro | 3.0L V6 TFSI Turbo | AWD | Audi press release | High |
| 55 TFSI e quattro | 3.0L V6 TFSI Turbo PHEV | AWD | Audi press release | High |

### Q8 (4M8, 2019-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 55 TFSI quattro | 3.0L V6 TFSI Turbo | AWD | Audi press release | High |
| 60 TFSI e quattro | 3.0L V6 TFSI Turbo PHEV | AWD | Audi press release | High |

### TT (8J, 2011-2014)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |

### TT (8S, 2015-2023)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |

### R8 (4S, 2015-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| V10 RWD | 5.2L V10 NA | RWD | Audi press release | High |
| V10 quattro | 5.2L V10 NA | AWD | Audi press release | High |

### RS 3 (8V/8Y, 2017-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| RS 3 | 2.5L I5 TFSI Turbo | AWD | Audi press release | High |

### RS 4 Avant (B9, 2018-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| RS 4 | 2.9L V6 TFSI Turbo | AWD | Audi press release | High |

### RS 5 (B9, 2018-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| RS 5 | 2.9L V6 TFSI Turbo | AWD | Audi press release | High |

### RS 6 Avant (C8, 2020-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| RS 6 | 4.0L V8 TFSI Turbo | AWD | Audi press release | High |

### RS 7 Sportback (C8, 2020-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| RS 7 | 4.0L V8 TFSI Turbo | AWD | Audi press release | High |

### e-tron GT (J1, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| e-tron GT quattro | Electric Dual Motor | AWD | Audi MediaCenter technical data | High |
| RS e-tron GT | Electric Dual Motor (Performance) | AWD | Audi MediaCenter technical data | High |

### Q4 e-tron (FZ, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 40 e-tron | Electric Single Motor | RWD | Audi Technology Portal / MediaCenter | High |
| 50 e-tron quattro | Electric Dual Motor | AWD | Audi Technology Portal / MediaCenter | High |
