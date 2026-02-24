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
| 118i | B38 1.5L I3 Turbo | RWD | BMW press release, official spec sheets | High |
| 120i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| M140i | B58 3.0L I6 Turbo | RWD | BMW press release | High |

### 1 Series (F40, 2019-2025)
| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 118i | B38 1.5L I3 Turbo | FWD | BMW press release | High |
| 120i | B48 2.0L I4 Turbo | FWD | BMW press release | High |
| M135i xDrive | B48 2.0L I4 Turbo | AWD | BMW press release | High |

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
| 320i | B48 2.0L I4 Turbo | RWD | – | BMW press release | High |
| 330i | B48 2.0L I4 Turbo | RWD | – | BMW press release | High |
| 330i xDrive | B48 2.0L I4 Turbo | AWD | FD 3.077 | BMW technical data | Medium |
| M340i | B58 3.0L I6 Turbo | RWD | – | BMW press release | High |
| M340i xDrive | B58 3.0L I6 Turbo | AWD | FD 3.077 | BMW technical data | Medium |

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

### X3 (G01, 2018-2024)
| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| sDrive20i | B48 2.0L I4 Turbo | RWD | BMW press release | High |
| xDrive20i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| xDrive30i | B48 2.0L I4 Turbo | AWD | BMW press release | High |
| M40i | B58 3.0L I6 Turbo | AWD | BMW press release | High |

### X5 (G05, 2019-2026)
| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| xDrive40i | B58 3.0L I6 Turbo | AWD | BMW press release | High |
| xDrive45e | B58 3.0L I6 Turbo PHEV | AWD | BMW press release | High |
| M50i | N63 4.4L V8 Turbo | AWD | BMW press release | High |

### M3 (G80, 2021-2026)
| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| M3 | S58 3.0L I6 Turbo | RWD | 6MT FD 3.846 / 8AT FD 3.154 | BMW M technical data | Medium |
| M3 Competition | S58 3.0L I6 Turbo | RWD | 8AT FD 3.154 | BMW M technical data | Medium |
| M3 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8AT FD 3.154 | BMW M technical data | Medium |

### M4 (G82, 2021-2026)
| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| M4 | S58 3.0L I6 Turbo | RWD | 6MT FD 3.846 / 8AT FD 3.154 | BMW M technical data | Medium |
| M4 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8AT FD 3.154 | BMW M technical data | Medium |

---

## Audi

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
| 35 TFSI | 2.0L I4 TFSI Turbo | FWD | S tronic FD 4.769 | Audi technical data | Medium |
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | S tronic FD 4.769 | Audi technical data | Medium |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | S tronic FD 3.760 | Audi technical data | Medium |

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

### Q5 (8R, 2011-2017)
| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 2.0 TFSI | 2.0L I4 TFSI Turbo | FWD | Audi press release | High |
| 2.0 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 3.0 TDI quattro | 3.0L V6 TDI Diesel | AWD | Audi press release | High |

### Q5 (FY, 2017-2026)
| Variant | Engine | Drivetrain | Gearbox Override | Source | Confidence |
|---------|--------|------------|------------------|--------|------------|
| 40 TFSI | 2.0L I4 TFSI Turbo | FWD | – | Audi press release | High |
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | S tronic FD 4.270 | Audi technical data | Medium |
| 55 TFSI e quattro | 2.0L I4 TFSI Turbo PHEV | AWD | – | Audi press release | High |

### Q7 (4M, 2016-2026)
| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | Audi press release | High |
| 55 TFSI quattro | 3.0L V6 TFSI Turbo | AWD | Audi press release | High |
| 55 TFSI e quattro | 3.0L V6 TFSI Turbo PHEV | AWD | Audi press release | High |

### RS 3 (8V/8Y, 2017-2026)
| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| RS 3 | 2.5L I5 TFSI Turbo | AWD | Audi Sport press release | High |

### e-tron GT (J1, 2022-2026)
| Variant | Engine | Drivetrain | Source | Confidence |
|---------|--------|------------|--------|------------|
| e-tron GT quattro | Electric Dual Motor | AWD | Audi press release | High |
| RS e-tron GT | Electric Dual Motor (Performance) | AWD | Audi press release | High |

---

## TODOs

- [ ] Verify xDrive final drive ratio overrides for BMW G20 variants against
  official BMW technical documentation
- [ ] Add variants for remaining models without variant data (currently 51
  models have no variants; they inherit base specs)
- [ ] Cross-check S tronic final drive ratios for Audi B9/FY platforms
- [ ] Add diesel (TDI) variants for European-market Audi models where relevant
