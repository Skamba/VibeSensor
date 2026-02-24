# Car Variant Data Sources

This file documents the sources used to populate variant data in
`car_library.json`. Each entry maps a car model to the variants added
and the confidence level of the data.

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
- Final drive ratios for variant-specific gearbox overrides were sourced
  from manufacturer technical data where available. Where exact ratios
  could not be confirmed, base-model ratios are inherited (no override).
- Tire specifications are shared across variants within a model generation
  and are not overridden at variant level (same factory options).

---

## BMW

### 1 Series (F20, 2011-2019)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 118i | B38 1.5L I3 Turbo | RWD | BMW press release | High |
| 120i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| M140i | B58 3.0L I6 Turbo | RWD | BMW press release | High |

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
| M240i | B58 3.0L I6 Turbo | RWD | BMW press release | High |

### 2 Series Coupe (G42, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 220i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 230i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| M240i xDrive | B58 3.0L I6 Turbo | AWD | BMW press release | High |

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
| 330i xDrive | B48 2.0L I4 Turbo | AWD | 8-speed automatic (ZF 8HP) FD 3.077 | BMW press release / technical data | Medium |
| M340i | B58 3.0L I6 Turbo | RWD | – | BMW press release / technical data | High |
| M340i xDrive | B58 3.0L I6 Turbo | AWD | 8-speed automatic (ZF 8HP) FD 3.077 | BMW press release / technical data | Medium |

### 4 Series (F32, 2014-2020)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 420i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 430i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 440i | B58 3.0L I6 Turbo | RWD | BMW press release | High |

### 4 Series (G22, 2021-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 420i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 430i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| M440i xDrive | B58 3.0L I6 Turbo | AWD | BMW press release | High |

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
| M550i xDrive | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### 5 Series (G60, 2024-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 520i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| 530i xDrive | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| 540i xDrive | B58 3.0L I6 Turbo | AWD | BMW press release | High |
| i5 eDrive40 | Electric Single Motor | RWD | BMW press release | High |
| i5 M60 xDrive | Electric Dual Motor | AWD | BMW press release | High |

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
| 740i | B58 3.0L I6 Turbo | RWD | BMW press release | High |
| 760i xDrive | N63 4.4L V8 Turbo | AWD | BMW press release | High |
| i7 eDrive50 | Electric Single Motor | RWD | BMW press release | High |
| i7 M70 xDrive | Electric Dual Motor | AWD | BMW press release | High |

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
| iX1 xDrive30 | Electric Dual Motor | AWD | BMW press release | High |

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
| iX2 xDrive30 | Electric Dual Motor | AWD | BMW press release | High |

### X3 (F25, 2011-2017)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive20i | N20 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive28i | N20 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive35i | N55 3.0L I6 Turbo | AWD | BMW press release | High |

### X3 (G01, 2018-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| sDrive20i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| xDrive20i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive30i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| M40i | B58 3.0L I6 Turbo | AWD | BMW press release | High |

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

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive40i | B58 3.0L I6 Turbo | AWD | BMW press release | High |
| xDrive45e | B58 3.0L I6 Turbo PHEV | AWD | BMW press release | High |
| M50i | N63 4.4L V8 Turbo | AWD | BMW press release | High |

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

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive40i | B58 3.0L I6 Turbo | AWD | BMW press release | High |
| xDrive40d | B57 3.0L I6 Diesel | AWD | BMW press release | High |
| M60i xDrive | S68 4.4L V8 Turbo | AWD | BMW press release | High |

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
| M3 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8-speed automatic (ZF 8HP) FD 3.154 | BMW press release / technical data | Medium |

### M4 (F82, 2014-2020)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| M4 | S55 3.0L I6 Turbo | RWD | BMW press release | High |
| M4 Competition | S55 3.0L I6 Turbo | RWD | BMW press release | High |

### M4 (G82, 2021-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| M4 | S58 3.0L I6 Turbo | RWD | 6-speed manual FD 3.846, 8-speed automatic (ZF 8HP) FD 3.154 | BMW press release / technical data | Medium |
| M4 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8-speed automatic (ZF 8HP) FD 3.154 | BMW press release / technical data | Medium |

### M5 (F90, 2018-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| M5 | S63 4.4L V8 Turbo | AWD | BMW press release | High |
| M5 Competition | S63 4.4L V8 Turbo | AWD | BMW press release | High |

### iX (I20, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive40 | Electric Dual Motor | AWD | BMW press release | High |
| xDrive50 | Electric Dual Motor | AWD | BMW press release | High |
| M60 | Electric Dual Motor (Performance) | AWD | BMW press release | High |

### i4 (G26, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| eDrive40 | Electric Single Motor | RWD | BMW press release | High |
| M50 | Electric Dual Motor | AWD | BMW press release | High |

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

### A3 (8Y, 2021-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 30 TFSI | 1.0L I3 TFSI Turbo | FWD | Audi press release | High |
| 35 TFSI | 1.5L I4 TFSI Turbo | FWD | Audi press release | High |
| 40 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |

### A4 (B8, 2011-2016)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 1.8 TFSI | 1.8L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 3.0 TFSI quattro | 3.0L V6 Supercharged | AWD | Audi press release | High |

### A4 (B9, 2016-2024)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 35 TFSI | 2.0L I4 TFSI Turbo | FWD | 7-speed S tronic FD 4.769 | Audi press release / technical data | Medium |
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | 7-speed S tronic FD 4.769 | Audi press release / technical data | Medium |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | 7-speed S tronic FD 3.76 | Audi press release / technical data | Medium |

### A5 (B8, 2012-2016)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi press release | High |

### A5 (B9, 2017-2024)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |

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

### Q3 (F3, 2019-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 35 TFSI | 1.5L I4 TFSI Turbo | FWD | Audi press release | High |
| 40 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 45 TFSI e | 1.4L I4 TFSI Turbo PHEV | FWD | Audi press release | High |

### Q5 (8R, 2011-2017)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi press release | High |

### Q5 (FY, 2017-2026)

| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | – | Audi press release / technical data | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | 7-speed S tronic FD 4.27 | Audi press release / technical data | Medium |
| 55 TFSI e quattro | 2.0L I4 TFSI Turbo PHEV | AWD | – | Audi press release / technical data | High |

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
| e-tron GT quattro | Electric Dual Motor | AWD | Audi press release | High |
| RS e-tron GT | Electric Dual Motor (Performance) | AWD | Audi press release | High |

### Q4 e-tron (FZ, 2022-2026)

| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 40 e-tron | Electric Single Motor | RWD | Audi press release | High |
| 50 e-tron quattro | Electric Dual Motor | AWD | Audi press release | High |

---

## TODOs

- [ ] Verify xDrive final drive ratio overrides for BMW G20 variants against
  official BMW technical documentation
- [ ] Cross-check S tronic final drive ratios for Audi B9/FY platforms
- [ ] Add diesel (TDI) variants for European-market Audi models where relevant
- [ ] Research and verify electric vehicle motor specifications
